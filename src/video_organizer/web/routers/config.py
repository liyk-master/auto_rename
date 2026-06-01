"""
配置管理路由

提供配置的读取和更新 API，包括 INI 配置和数据库配置。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.state import get_state_manager
from ...database.session import get_session_local
from ...database.models import ManualRule, ReleaseGroupMapping, LlmProvider, RuntimeConfig

logger = logging.getLogger(__name__)

router = APIRouter()


class ConfigUpdateRequest(BaseModel):
    section: str
    key: str
    value: Any


class ConfigSectionUpdateRequest(BaseModel):
    section: str
    values: Dict[str, Any]


class ConfigResponse(BaseModel):
    success: bool
    message: str
    config: Optional[Dict[str, Any]] = None


# ===== DB Config Request Models =====

class ManualRuleCreateRequest(BaseModel):
    rule_text: str
    enabled: bool = True
    sort_order: int = 0


class ReleaseGroupCreateRequest(BaseModel):
    group_name: str
    content_type: str


class LlmProviderCreateRequest(BaseModel):
    name: str
    api_url: str
    api_key: Optional[str] = ""
    model: Optional[str] = ""
    enabled: bool = True
    weight: int = 1
    timeout: int = 30
    max_retries: int = 2


class RuntimeConfigUpdateRequest(BaseModel):
    value: str
    description: Optional[str] = None


# ===== DB Config CRUD Endpoints (must be before /{section} catch-all) =====


# 手动规则
@router.get("/db/manual-rules")
async def get_manual_rules():
    try:
        with get_session_local()() as db:
            rules = db.query(ManualRule).order_by(ManualRule.sort_order).all()
            return {"success": True, "rules": [
                {"id": r.id, "rule_text": r.rule_text, "enabled": r.enabled, "sort_order": r.sort_order,
                 "created_at": r.created_at.isoformat() if r.created_at else None,
                 "updated_at": r.updated_at.isoformat() if r.updated_at else None}
                for r in rules
            ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取手动规则失败: {e}")


@router.post("/db/manual-rules", status_code=201)
async def create_manual_rule(request: ManualRuleCreateRequest):
    try:
        with get_session_local()() as db:
            rule = ManualRule(
                rule_text=request.rule_text,
                enabled=request.enabled,
                sort_order=request.sort_order,
                created_at=datetime.now(),
            )
            db.add(rule)
            db.commit()
            return {"success": True, "id": rule.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建手动规则失败: {e}")


@router.put("/db/manual-rules/{rule_id}")
async def update_manual_rule(rule_id: int, request: ManualRuleCreateRequest):
    try:
        with get_session_local()() as db:
            rule = db.query(ManualRule).filter(ManualRule.id == rule_id).first()
            if not rule:
                raise HTTPException(status_code=404, detail="规则不存在")
            rule.rule_text = request.rule_text
            rule.enabled = request.enabled
            rule.sort_order = request.sort_order
            rule.updated_at = datetime.now()
            db.commit()
            return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新手动规则失败: {e}")


@router.delete("/db/manual-rules/{rule_id}")
async def delete_manual_rule(rule_id: int):
    try:
        with get_session_local()() as db:
            rule = db.query(ManualRule).filter(ManualRule.id == rule_id).first()
            if not rule:
                raise HTTPException(status_code=404, detail="规则不存在")
            db.delete(rule)
            db.commit()
            return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除手动规则失败: {e}")


# 字幕组映射
@router.get("/db/release-groups")
async def get_release_groups():
    try:
        with get_session_local()() as db:
            groups = db.query(ReleaseGroupMapping).order_by(ReleaseGroupMapping.group_name).all()
            return {"success": True, "groups": [
                {"id": g.id, "group_name": g.group_name, "content_type": g.content_type,
                 "created_at": g.created_at.isoformat() if g.created_at else None}
                for g in groups
            ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取字幕组映射失败: {e}")


@router.post("/db/release-groups", status_code=201)
async def create_release_group(request: ReleaseGroupCreateRequest):
    try:
        with get_session_local()() as db:
            existing = db.query(ReleaseGroupMapping).filter(
                ReleaseGroupMapping.group_name == request.group_name
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail="字幕组已存在")
            group = ReleaseGroupMapping(
                group_name=request.group_name,
                content_type=request.content_type,
                created_at=datetime.now(),
            )
            db.add(group)
            db.commit()
            return {"success": True, "id": group.id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建字幕组映射失败: {e}")


@router.put("/db/release-groups/{group_id}")
async def update_release_group(group_id: int, request: ReleaseGroupCreateRequest):
    try:
        with get_session_local()() as db:
            group = db.query(ReleaseGroupMapping).filter(ReleaseGroupMapping.id == group_id).first()
            if not group:
                raise HTTPException(status_code=404, detail="字幕组不存在")
            group.group_name = request.group_name
            group.content_type = request.content_type
            group.updated_at = datetime.now()
            db.commit()
            return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新字幕组映射失败: {e}")


@router.delete("/db/release-groups/{group_id}")
async def delete_release_group(group_id: int):
    try:
        with get_session_local()() as db:
            group = db.query(ReleaseGroupMapping).filter(ReleaseGroupMapping.id == group_id).first()
            if not group:
                raise HTTPException(status_code=404, detail="字幕组不存在")
            db.delete(group)
            db.commit()
            return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除字幕组映射失败: {e}")


# LLM 提供商
@router.get("/db/llm-providers")
async def get_llm_providers():
    try:
        with get_session_local()() as db:
            providers = db.query(LlmProvider).order_by(LlmProvider.weight.desc()).all()
            return {"success": True, "providers": [
                {"id": p.id, "name": p.name, "api_url": p.api_url, "api_key": '***' if p.api_key else '',
                 "has_key": bool(p.api_key),
                 "model": p.model, "enabled": p.enabled, "weight": p.weight,
                 "timeout": p.timeout, "max_retries": p.max_retries,
                 "created_at": p.created_at.isoformat() if p.created_at else None}
                for p in providers
            ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取 LLM 提供商失败: {e}")


@router.post("/db/llm-providers", status_code=201)
async def create_llm_provider(request: LlmProviderCreateRequest):
    try:
        with get_session_local()() as db:
            provider = LlmProvider(
                name=request.name,
                api_url=request.api_url,
                api_key=request.api_key or "",
                model=request.model or "",
                enabled=request.enabled,
                weight=request.weight,
                timeout=request.timeout,
                max_retries=request.max_retries,
                created_at=datetime.now(),
            )
            db.add(provider)
            db.commit()
            return {"success": True, "id": provider.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建 LLM 提供商失败: {e}")


@router.put("/db/llm-providers/{provider_id}")
async def update_llm_provider(provider_id: int, request: LlmProviderCreateRequest):
    try:
        with get_session_local()() as db:
            p = db.query(LlmProvider).filter(LlmProvider.id == provider_id).first()
            if not p:
                raise HTTPException(status_code=404, detail="提供商不存在")
            p.name = request.name
            p.api_url = request.api_url
            if request.api_key:
                p.api_key = request.api_key
            p.model = request.model or ""
            p.enabled = request.enabled
            p.weight = request.weight
            p.timeout = request.timeout
            p.max_retries = request.max_retries
            p.updated_at = datetime.now()
            db.commit()
            return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新 LLM 提供商失败: {e}")


@router.delete("/db/llm-providers/{provider_id}")
async def delete_llm_provider(provider_id: int):
    try:
        with get_session_local()() as db:
            p = db.query(LlmProvider).filter(LlmProvider.id == provider_id).first()
            if not p:
                raise HTTPException(status_code=404, detail="提供商不存在")
            db.delete(p)
            db.commit()
            return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除 LLM 提供商失败: {e}")


# 运行时配置
@router.get("/db/runtime")
async def get_runtime_config():
    try:
        with get_session_local()() as db:
            items = db.query(RuntimeConfig).order_by(RuntimeConfig.key).all()
            return {"success": True, "configs": [
                {"key": c.key, "value": c.value, "description": c.description,
                 "updated_at": c.updated_at.isoformat() if c.updated_at else None}
                for c in items
            ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取运行时配置失败: {e}")


@router.put("/db/runtime/{config_key}")
async def update_runtime_config(config_key: str, request: RuntimeConfigUpdateRequest):
    try:
        with get_session_local()() as db:
            item = db.query(RuntimeConfig).filter(RuntimeConfig.key == config_key).first()
            if not item:
                item = RuntimeConfig(key=config_key, value=request.value,
                                     description=request.description or "")
                db.add(item)
            else:
                item.value = request.value
                if request.description is not None:
                    item.description = request.description
                item.updated_at = datetime.now()
            db.commit()
            return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新运行时配置失败: {e}")


# ===== INI Config Endpoints =====


@router.get("", response_model=ConfigResponse)
async def get_config():
    try:
        state = get_state_manager()
        config = state.get_config()
        return ConfigResponse(success=True, message="获取配置成功", config=config)
    except Exception as e:
        logger.error(f"获取配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {e}")


@router.get("/{section}", response_model=ConfigResponse)
async def get_config_section(section: str):
    try:
        state = get_state_manager()
        config = state.get_config()
        if section not in config:
            raise HTTPException(status_code=404, detail=f"配置节 '{section}' 不存在")
        return ConfigResponse(
            success=True, message=f"获取配置节 '{section}' 成功",
            config={section: config[section]},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取配置节失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置节失败: {e}")


@router.put("/item", response_model=ConfigResponse)
async def update_config_item(request: ConfigUpdateRequest):
    try:
        state = get_state_manager()
        config = state.get_config()
        config_path = state.get_config_path()
        if request.section not in config:
            raise HTTPException(status_code=404, detail=f"配置节 '{request.section}' 不存在")
        config[request.section][request.key] = request.value
        if config_path:
            from ...core.config_loader import update_config
            update_config(config, config_path)
        return ConfigResponse(
            success=True, message=f"配置项 '{request.section}.{request.key}' 已更新", config=config,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {e}")


@router.put("/section", response_model=ConfigResponse)
async def update_config_section(request: ConfigSectionUpdateRequest):
    try:
        state = get_state_manager()
        config = state.get_config()
        config_path = state.get_config_path()
        config[request.section] = request.values
        if config_path:
            from ...core.config_loader import update_config, load_config
            update_config(config, config_path)
            new_config = load_config(config_path)
            state.set_config(new_config, config_path)
        else:
            state.set_config(config, config_path)
        return ConfigResponse(success=True, message=f"配置节 '{request.section}' 已更新", config=config)
    except Exception as e:
        logger.error(f"更新配置节失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置节失败: {e}")


@router.delete("/section/{section}", response_model=ConfigResponse)
async def delete_config_section(section: str):
    try:
        state = get_state_manager()
        config = state.get_config()
        config_path = state.get_config_path()
        if section not in config:
            raise HTTPException(status_code=404, detail=f"配置节 '{section}' 不存在")
        del config[section]
        if config_path:
            from ...core.config_loader import update_config, load_config
            update_config(config, config_path)
            new_config = load_config(config_path)
            state.set_config(new_config, config_path)
        else:
            state.set_config(config, config_path)
        return ConfigResponse(success=True, message=f"配置节 '{section}' 已删除", config=config)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除配置节失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除配置节失败: {e}")

@router.post("/reload", response_model=ConfigResponse)
async def reload_config():
    try:
        state = get_state_manager()
        config_path = state.get_config_path()
        if not config_path or not config_path.exists():
            raise HTTPException(status_code=404, detail="配置文件不存在")
        from ...core.config_loader import load_config
        new_config = load_config(config_path)
        state.set_config(new_config, config_path)
        return ConfigResponse(success=True, message="配置已重新加载", config=new_config)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重新加载配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"重新加载配置失败: {e}")


@router.get("/schema/description")
async def get_config_schema():
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
