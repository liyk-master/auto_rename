"""
配置管理路由

提供配置的读取和更新 API。
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.state import get_state_manager

logger = logging.getLogger(__name__)

router = APIRouter()


class ConfigUpdateRequest(BaseModel):
    """配置更新请求"""
    section: str
    key: str
    value: Any


class ConfigSectionUpdateRequest(BaseModel):
    """配置节更新请求"""
    section: str
    values: Dict[str, Any]


class ConfigResponse(BaseModel):
    """配置响应"""
    success: bool
    message: str
    config: Optional[Dict[str, Any]] = None


@router.get("", response_model=ConfigResponse)
async def get_config():
    """
    获取完整配置
    
    返回当前加载的所有配置项。
    """
    try:
        state = get_state_manager()
        config = state.get_config()
        return ConfigResponse(
            success=True,
            message="获取配置成功",
            config=config,
        )
    except Exception as e:
        logger.error(f"获取配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {e}")


@router.get("/{section}", response_model=ConfigResponse)
async def get_config_section(section: str):
    """
    获取指定配置节
    
    Args:
        section: 配置节名称（如 monitoring, tmdb, logging）
    """
    try:
        state = get_state_manager()
        config = state.get_config()
        
        if section not in config:
            raise HTTPException(status_code=404, detail=f"配置节 '{section}' 不存在")
        
        return ConfigResponse(
            success=True,
            message=f"获取配置节 '{section}' 成功",
            config={section: config[section]},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取配置节失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置节失败: {e}")


@router.put("/item", response_model=ConfigResponse)
async def update_config_item(request: ConfigUpdateRequest):
    """
    更新单个配置项
    
    Args:
        request: 包含 section, key, value 的更新请求
    """
    try:
        state = get_state_manager()
        config = state.get_config()
        config_path = state.get_config_path()
        
        if request.section not in config:
            raise HTTPException(
                status_code=404,
                detail=f"配置节 '{request.section}' 不存在"
            )
        
        # 更新内存配置
        config[request.section][request.key] = request.value
        
        # 保存到文件
        if config_path:
            from ...core.config_loader import update_config
            update_config(config, config_path)
        
        logger.info(f"配置已更新: [{request.section}] {request.key} = {request.value}")
        
        return ConfigResponse(
            success=True,
            message=f"配置项 '{request.section}.{request.key}' 已更新",
            config=config,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {e}")


@router.put("/section", response_model=ConfigResponse)
async def update_config_section(request: ConfigSectionUpdateRequest):
    """
    更新整个配置节
    
    Args:
        request: 包含 section 和 values 的更新请求
    """
    try:
        state = get_state_manager()
        config = state.get_config()
        config_path = state.get_config_path()
        
        # 更新内存配置
        config[request.section] = request.values
        
        # 保存到文件
        if config_path:
            from ...core.config_loader import update_config
            update_config(config, config_path)
        
        logger.info(f"配置节已更新: [{request.section}]")
        
        return ConfigResponse(
            success=True,
            message=f"配置节 '{request.section}' 已更新",
            config=config,
        )
    except Exception as e:
        logger.error(f"更新配置节失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置节失败: {e}")


@router.post("/reload", response_model=ConfigResponse)
async def reload_config():
    """
    重新加载配置文件
    
    从磁盘重新读取配置文件。
    """
    try:
        state = get_state_manager()
        config_path = state.get_config_path()
        
        if not config_path or not config_path.exists():
            raise HTTPException(status_code=404, detail="配置文件不存在")
        
        from ...core.config_loader import load_config
        new_config = load_config(config_path)
        state.set_config(new_config, config_path)
        
        logger.info("配置已重新加载")
        
        return ConfigResponse(
            success=True,
            message="配置已重新加载",
            config=new_config,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重新加载配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"重新加载配置失败: {e}")


@router.get("/schema/description")
async def get_config_schema():
    """
    获取配置说明
    
    返回各配置项的说明文档。
    """
    schema = {
        "monitoring": {
            "description": "监控配置",
            "fields": {
                "watch_dir": "监控目录路径",
                "output_dir": "输出目录路径",
                "poll_interval": "轮询间隔（秒）",
                "supported_extensions": "支持的视频扩展名列表",
                "use_polling": "是否使用轮询模式",
                "polling_interval": "轮询模式扫描间隔（秒）",
            }
        },
        "tmdb": {
            "description": "TMDB API 配置",
            "fields": {
                "api_key": "TMDB API 密钥",
                "language": "语言代码（如 zh-CN）",
                "region": "地区代码（如 CN）",
            }
        },
        "logging": {
            "description": "日志配置",
            "fields": {
                "level": "日志级别（DEBUG, INFO, WARNING, ERROR）",
                "file": "日志文件路径",
                "max_bytes": "单个日志文件最大大小",
                "backup_count": "日志文件备份数量",
            }
        },
        "p123": {
            "description": "123云盘配置",
            "fields": {
                "token": "123云盘 API Token",
                "organize_source_id": "整理源目录ID",
                "organize_target_id": "整理目标目录ID",
            }
        },
        "naming": {
            "description": "命名规则配置",
            "fields": {
                "tv_show": "电视剧命名模板",
                "movie": "电影命名模板",
                "anime": "动漫命名模板",
            }
        },
        "processing": {
            "description": "处理配置",
            "fields": {
                "auto_upload": "是否自动上传",
                "delete_after_upload": "上传后是否删除源文件",
                "max_upload_workers": "最大上传工作线程数",
            }
        },
    }
    
    return {"success": True, "schema": schema}
