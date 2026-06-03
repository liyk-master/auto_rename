import os
import sys
import logging
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from .models import Base

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


def get_db_path() -> Path:
    """获取数据库文件路径，存储在 data 目录下"""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    data_dir = base / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "video_organizer.db"


def init_db(db_path: str = None) -> str:
    """
    初始化数据库引擎和表结构
    
    Args:
        db_path: 数据库文件路径，None 则使用默认路径
        
    Returns:
        实际使用的数据库路径
    """
    global _engine, _SessionLocal

    path = db_path or str(get_db_path())
    _engine = create_engine(
        f"sqlite:///{path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    Base.metadata.create_all(bind=_engine)
    logger.info(f"数据库已初始化: {path}")
    return path


def get_engine():
    global _engine
    if _engine is None:
        init_db()
    return _engine


def get_session_local():
    global _SessionLocal
    if _SessionLocal is None:
        init_db()
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：获取数据库会话"""
    db = get_session_local()()
    try:
        yield db
    finally:
        db.close()
