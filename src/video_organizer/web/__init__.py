"""
Video Organizer Web 管理后台模块

提供 Web 界面用于：
- 配置管理
- 任务监控
- 日志查看
- 手动处理
"""

from .app import create_app, run_server

__all__ = ["create_app", "run_server"]
