"""Web 路由模块"""

from .config import router as config_router
from .tasks import router as tasks_router
from .logs import router as logs_router
from .manual import router as manual_router
from .downloaders import router as downloaders_router
from .auth import router as auth_router
from .strm import router as strm_router

__all__ = [
    "config_router",
    "tasks_router",
    "logs_router",
    "manual_router",
    "downloaders_router",
    "auth_router",
    "strm_router",
]
