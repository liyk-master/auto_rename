# -*- coding: utf-8 -*-
"""
数据库连接管理器

提供 SQLAlchemy 数据库连接池管理，支持 MySQL/MariaDB
"""

import logging
from contextlib import contextmanager
from typing import Optional, Generator
from sqlalchemy import create_engine, event, pool
from sqlalchemy.orm import sessionmaker, Session, scoped_session
from sqlalchemy.engine import Engine

from .emya_models import Base

logger = logging.getLogger(__name__)


class DatabaseManager:
    """数据库连接管理器"""

    _instance: Optional["DatabaseManager"] = None
    _engine: Optional[Engine] = None
    _session_factory: Optional[sessionmaker] = None
    _scoped_session: Optional[scoped_session] = None

    def __new__(cls, *args, **kwargs):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        database: str = "emya",
        charset: str = "utf8mb4",
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_recycle: int = 3600,
        echo: bool = False,
    ):
        """
        初始化数据库连接

        Args:
            host: 数据库主机地址
            port: 数据库端口
            user: 用户名
            password: 密码
            database: 数据库名
            charset: 字符集
            pool_size: 连接池大小
            max_overflow: 最大溢出连接数
            pool_recycle: 连接回收时间(秒)
            echo: 是否打印SQL语句
        """
        # 如果已经初始化过，直接返回
        if self._engine is not None:
            return

        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.charset = charset

        # 构建连接URL
        self.url = (
            f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
            f"?charset={charset}"
        )

        # 创建引擎
        self._engine = create_engine(
            self.url,
            poolclass=pool.QueuePool,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=pool_recycle,
            pool_pre_ping=True,  # 每次获取连接时检查连接是否有效
            echo=echo,
        )

        # 绑定事件
        self._bind_events()

        # 创建会话工厂
        self._session_factory = sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False,
        )

        # 创建线程安全的 scoped_session
        self._scoped_session = scoped_session(self._session_factory)

        logger.info(f"数据库连接管理器初始化完成: {host}:{port}/{database}")

    def _bind_events(self):
        """绑定数据库事件"""

        @event.listens_for(self._engine, "connect")
        def receive_connect(dbapi_connection, connection_record):
            """连接建立时触发"""
            logger.debug(f"数据库连接建立: {dbapi_connection}")

        @event.listens_for(self._engine, "checkout")
        def receive_checkout(dbapi_connection, connection_record, connection_proxy):
            """从连接池获取连接时触发"""
            logger.debug("从连接池获取连接")

        @event.listens_for(self._engine, "checkin")
        def receive_checkin(dbapi_connection, connection_record):
            """归还连接到连接池时触发"""
            logger.debug("归还连接到连接池")

        @event.listens_for(self._engine, "close")
        def receive_close(dbapi_connection, connection_record):
            """关闭连接时触发"""
            logger.debug("关闭数据库连接")

    @property
    def engine(self) -> Engine:
        """获取数据库引擎"""
        if self._engine is None:
            raise RuntimeError("数据库引擎未初始化，请先调用 init_db()")
        return self._engine

    def get_session(self) -> Session:
        """获取数据库会话"""
        if self._session_factory is None:
            raise RuntimeError("数据库会话工厂未初始化，请先调用 init_db()")
        return self._session_factory()

    def get_scoped_session(self) -> scoped_session:
        """获取线程安全的 scoped_session"""
        if self._scoped_session is None:
            raise RuntimeError("scoped_session 未初始化，请先调用 init_db()")
        return self._scoped_session

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """
        会话上下文管理器

        使用示例:
            with db_manager.session_scope() as session:
                user = session.query(User).first()

        自动处理提交和回滚
        """
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"数据库事务回滚: {e}")
            raise
        finally:
            session.close()

    def create_tables(self):
        """创建所有表（如果不存在）"""
        Base.metadata.create_all(self._engine)
        logger.info("数据库表创建完成")

    def drop_tables(self):
        """删除所有表（危险操作！）"""
        Base.metadata.drop_all(self._engine)
        logger.warning("数据库表已删除")

    def test_connection(self) -> bool:
        """
        测试数据库连接

        Returns:
            bool: 连接成功返回 True，否则返回 False
        """
        try:
            from sqlalchemy import text
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("数据库连接测试成功")
            return True
        except Exception as e:
            logger.error(f"数据库连接测试失败: {e}")
            return False

    def close(self):
        """关闭数据库连接"""
        if self._scoped_session is not None:
            self._scoped_session.remove()
        if self._engine is not None:
            self._engine.dispose()
        logger.info("数据库连接已关闭")

    @classmethod
    def get_instance(cls) -> "DatabaseManager":
        """获取单例实例"""
        if cls._instance is None:
            raise RuntimeError("DatabaseManager 未初始化，请先创建实例")
        return cls._instance

    @classmethod
    def init_from_config(cls, config: dict) -> "DatabaseManager":
        """
        从配置字典初始化

        Args:
            config: 配置字典，包含 host, port, user, password, database 等字段

        Returns:
            DatabaseManager 实例
        """
        return cls(
            host=config.get("host", "localhost"),
            port=config.get("port", 3306),
            user=config.get("user", "root"),
            password=config.get("password", ""),
            database=config.get("database", "emya"),
            charset=config.get("charset", "utf8mb4"),
            pool_size=config.get("pool_size", 5),
            max_overflow=config.get("max_overflow", 10),
            pool_recycle=config.get("pool_recycle", 3600),
            echo=config.get("echo", False),
        )


# 全局数据库管理器实例
db_manager: Optional[DatabaseManager] = None


def init_db(config: dict) -> DatabaseManager:
    """
    初始化数据库连接

    Args:
        config: 配置字典

    Returns:
        DatabaseManager 实例
    """
    global db_manager
    db_manager = DatabaseManager.init_from_config(config)
    return db_manager


def get_db() -> DatabaseManager:
    """获取数据库管理器实例"""
    global db_manager
    if db_manager is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")
    return db_manager


def get_session() -> Session:
    """获取数据库会话"""
    return get_db().get_session()


def session_scope() -> Generator[Session, None, None]:
    """会话上下文管理器"""
    return get_db().session_scope()
