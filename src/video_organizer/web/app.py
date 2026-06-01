"""
FastAPI Web 应用

提供 Video Organizer 的 Web 管理后台。
"""

import logging
import asyncio
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .services.state import StateManager, get_state_manager
from .routers import (
    config_router,
    tasks_router,
    logs_router,
    manual_router,
    downloaders_router,
    auth_router,
)
from .auth import auth_middleware
from ..database.config_operations import seed_from_ini


logger = logging.getLogger(__name__)


def create_app(
    title: str = "Video Organizer 管理后台",
    version: str = "1.0.0",
) -> FastAPI:
    """
    创建 FastAPI 应用实例
    
    Args:
        title: 应用标题
        version: 版本号
        
    Returns:
        FastAPI 应用实例
    """
    # 如果状态管理器中的配置为空，尝试自动加载默认配置
    state = get_state_manager()
    if not state.get_config():
        try:
            from ..core.config_loader import load_config
            config_path = Path("config.ini")
            if config_path.exists():
                config = load_config(str(config_path))
                state.set_config(config, config_path)
                logger.info(f"已自动加载配置文件: {config_path.resolve()}")
            else:
                # 尝试从启动目录的 config 目录加载
                alt_path = Path("config") / "config.ini"
                if alt_path.exists():
                    config = load_config(str(alt_path))
                    state.set_config(config, alt_path)
                    logger.info(f"已自动加载配置文件: {alt_path.resolve()}")
        except Exception as e:
            logger.warning(f"自动加载配置失败（部分功能可能受限）: {e}")
    
    # 将 INI 配置导入数据库（首次运行时）
    config = state.get_config()
    if config:
        try:
            seed_from_ini(config)
        except Exception as e:
            logger.warning(f"导入配置到数据库失败: {e}")
    
    app = FastAPI(
        title=title,
        version=version,
        description="Video Organizer 视频文件自动重命名和组织工具的 Web 管理后台",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )
    
    # 添加 CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 注册路由（认证路由需要先注册，不受认证中间件影响）
    app.include_router(auth_router, prefix="/api/auth", tags=["认证管理"])
    app.include_router(config_router, prefix="/api/config", tags=["配置管理"])
    app.include_router(tasks_router, prefix="/api/tasks", tags=["任务监控"])
    app.include_router(logs_router, prefix="/api/logs", tags=["日志查看"])
    app.include_router(manual_router, prefix="/api/manual", tags=["手动处理"])
    app.include_router(downloaders_router, prefix="/api/downloaders", tags=["下载器监控"])
    
    # 认证中间件（对 API 请求进行登录检查）
    app.middleware("http")(auth_middleware)
    
    # 静态文件目录
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    
    # 首页路由
    @app.get("/", response_class=HTMLResponse)
    async def index():
        """返回管理后台首页"""
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return HTMLResponse(content="<h1>Video Organizer 管理后台</h1><p>前端文件未找到</p>")
    
    # 健康检查
    @app.get("/api/health")
    async def health_check():
        """健康检查端点"""
        state = get_state_manager()
        return {
            "status": "healthy",
            "system_running": state.is_system_running(),
        }
    
    # 系统状态
    @app.get("/api/status")
    async def system_status():
        """获取系统整体状态"""
        state = get_state_manager()
        return state.get_system_status()
    
    # 请求日志中间件
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        logger.debug(f"请求: {request.method} {request.url}")
        response = await call_next(request)
        return response
    
    logger.info(f"FastAPI 应用已创建: {title} v{version}")
    return app


def run_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    reload: bool = False,
    video_handler: Optional[object] = None,
    config: Optional[dict] = None,
    config_path: Optional[Path] = None,
    downloader_monitors: Optional[list] = None,
) -> None:
    """
    启动 Web 服务器
    
    Args:
        host: 监听地址
        port: 监听端口
        reload: 是否启用热重载（开发模式）
        video_handler: VideoFileHandler 实例
        config: 配置字典
        config_path: 配置文件路径
        downloader_monitors: 下载器监控器列表
    """
    import uvicorn
    
    # 初始化状态管理器
    state = get_state_manager()
    if video_handler is not None:
        state.set_video_handler(video_handler)
    if config is not None:
        state.set_config(config, config_path)
    if downloader_monitors is not None:
        state.set_downloader_monitors(downloader_monitors)
    
    # 创建应用
    app = create_app()
    
    logger.info(f"启动 Web 服务器: http://{host}:{port}")
    
    # 运行服务器
    uvicorn.run(
        "video_organizer.web.app:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )


# 用于 uvicorn --factory 模式
app = create_app()
