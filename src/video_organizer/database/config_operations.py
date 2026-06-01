import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..web.auth import hash_password
from .models import (
    ManualRule, ReleaseGroupMapping, LlmProvider, AuthUser, RuntimeConfig,
)
from .session import get_session_local

logger = logging.getLogger(__name__)


def seed_from_ini(config: Dict[str, Any]) -> bool:
    """从 INI 配置字典导入数据到数据库（表为空时才导入）"""
    try:
        session_local = get_session_local()
    except Exception:
        return False

    seeded = False
    try:
        with session_local() as db:
            now = datetime.now()

            # 1. Manual Rules — 存储原始规则字符串
            if db.query(ManualRule).count() == 0:
                rules_config = config.get("manual_rules", {})
                if str(rules_config.get("enabled", "true")).lower() == "true":
                    # 优先处理 rules 列表（list[dict] 格式），回退到 rule1/rule2 旧格式
                    raw_rules = rules_config.get("rules", [])
                    if isinstance(raw_rules, list):
                        for idx, entry in enumerate(raw_rules):
                            rule_str = ""
                            if isinstance(entry, dict):
                                rule_str = str(entry.get("rule", "")).strip()
                            elif isinstance(entry, str):
                                rule_str = entry.strip()
                            if rule_str:
                                db.add(ManualRule(rule_text=rule_str, sort_order=idx, created_at=now))
                    else:
                        for key in sorted(rules_config.keys()):
                            if key.startswith("rule") and key[4:].isdigit():
                                rule_str = str(rules_config[key]).strip()
                                if rule_str:
                                    db.add(ManualRule(
                                        rule_text=rule_str,
                                        sort_order=int(key[4:]),
                                        created_at=now,
                                    ))
                    logger.info("已从 INI 导入手动规则到数据库")
                    seeded = True

            # 2. Release Group Mapping
            if db.query(ReleaseGroupMapping).count() == 0:
                rg_config = config.get("release_group_mapping", {})
                for name, ctype in rg_config.items():
                    if name and ctype:
                        db.add(ReleaseGroupMapping(
                            group_name=name.strip(),
                            content_type=ctype.strip(),
                            created_at=now,
                        ))
                if rg_config:
                    logger.info("已从 INI 导入字幕组映射到数据库")
                    seeded = True

            # 3. LLM Providers
            if db.query(LlmProvider).count() == 0:
                for section, values in config.items():
                    if section.startswith("llm_provider_"):
                        db.add(LlmProvider(
                            name=str(values.get("name", "")),
                            api_url=str(values.get("api_url", "")),
                            api_key=str(values.get("api_key", "")),
                            model=str(values.get("model", "")),
                            enabled=str(values.get("enabled", "true")).lower() == "true",
                            weight=int(values.get("weight", 1)),
                            timeout=int(values.get("timeout", 30)),
                            max_retries=int(values.get("max_retries", 2)),
                            created_at=now,
                        ))
                logger.info("已从 INI 导入 LLM Provider 到数据库")
                seeded = True

            # 4. Auth Users
            if db.query(AuthUser).count() == 0:
                auth_config = config.get("auth", {})
                if str(auth_config.get("enabled", "false")).lower() == "true":
                    raw_pw = str(auth_config.get("password", "admin"))
                    db.add(AuthUser(
                        username=str(auth_config.get("username", "admin")),
                        password_hash=hash_password(raw_pw),
                        role="admin",
                        enabled=True,
                        created_at=now,
                    ))
                    logger.info("已从 INI 导入用户到数据库")
                    seeded = True

            # 5. Runtime Config
            if db.query(RuntimeConfig).count() == 0:
                proc = config.get("processing", {})
                items = {
                    "upload_targets": str(proc.get("upload_targets", "")),
                    "delete_after_upload": str(proc.get("delete_after_upload", "false")),
                    "max_upload_workers": str(proc.get("max_upload_workers", "1")),
                }
                for k, v in items.items():
                    db.add(RuntimeConfig(key=k, value=v, description="", updated_at=now))
                logger.info("已从 INI 导入运行时配置到数据库")
                seeded = True

            if seeded:
                db.commit()
        return seeded
    except Exception as e:
        logger.warning(f"从 INI 导入配置到数据库失败: {e}")
        return False


def get_manual_rule_dicts() -> List[Dict]:
    """获取手动规则（引擎需要的 List[Dict] 格式）"""
    try:
        with get_session_local()() as db:
            rules = db.query(ManualRule).filter(ManualRule.enabled == True).order_by(ManualRule.sort_order).all()
            return [{"rule": r.rule_text, "enabled": r.enabled} for r in rules]
    except Exception:
        return []


def get_release_groups() -> Dict[str, str]:
    """获取字幕组映射 {name: content_type}"""
    try:
        with get_session_local()() as db:
            items = db.query(ReleaseGroupMapping).all()
            return {r.group_name: r.content_type for r in items}
    except Exception:
        return {}


def get_llm_providers() -> List[Dict]:
    """获取所有 LLM Provider"""
    try:
        with get_session_local()() as db:
            providers = db.query(LlmProvider).filter(LlmProvider.enabled == True).order_by(LlmProvider.weight.desc()).all()
            return [
                {
                    "name": p.name,
                    "api_url": p.api_url,
                    "api_key": p.api_key,
                    "model": p.model,
                    "weight": p.weight,
                    "timeout": p.timeout,
                    "max_retries": p.max_retries,
                }
                for p in providers
            ]
    except Exception:
        return []


def get_auth_users() -> Dict[str, str]:
    """获取用户列表 {username: password_hash}"""
    try:
        with get_session_local()() as db:
            users = db.query(AuthUser).filter(AuthUser.enabled == True).all()
            return {u.username: u.password_hash for u in users}
    except Exception:
        return {}


def get_runtime_config(key: str, default: str = "") -> str:
    """获取运行时配置项"""
    try:
        with get_session_local()() as db:
            item = db.query(RuntimeConfig).filter(RuntimeConfig.key == key).first()
            return item.value if item else default
    except Exception:
        return default
