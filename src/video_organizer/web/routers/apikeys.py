"""
API Key 管理路由

提供 API Key 的增删改查（受登录令牌保护，位于 /api/apikeys 下）。
"""

import logging
import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import hash_api_key
from ...database.models import AuthApiKey
from ...database.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


class ApiKeyCreateRequest(BaseModel):
    name: str = ""


class ApiKeyUpdateRequest(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    enabled: bool
    created_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


class ApiKeyListResponse(BaseModel):
    success: bool = True
    api_keys: List[ApiKeyResponse]


def _generate_api_key() -> str:
    """生成 API Key（URL 安全，32 字节随机）"""
    return f"vk_{secrets.token_urlsafe(32)}"


@router.get("", response_model=ApiKeyListResponse)
async def list_api_keys(db: Session = Depends(get_db)):
    """获取所有 API Key（不返回明文）"""
    keys = db.query(AuthApiKey).order_by(AuthApiKey.id).all()
    return ApiKeyListResponse(api_keys=[
        ApiKeyResponse(
            id=k.id, name=k.name, enabled=k.enabled,
            created_at=k.created_at, last_used_at=k.last_used_at,
        ) for k in keys
    ])


@router.post("")
async def create_api_key(
    req: ApiKeyCreateRequest, db: Session = Depends(get_db)
):
    """创建 API Key，返回明文 key（仅此一次展示）"""
    api_key = _generate_api_key()
    now = datetime.now()
    item = AuthApiKey(
        name=req.name,
        api_key_hash=hash_api_key(api_key),
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    logger.info(f"创建 API Key: id={item.id} name={req.name}")
    return {
        "success": True,
        "api_key": api_key,
        "id": item.id,
        "name": item.name,
    }


@router.put("/{key_id}")
async def update_api_key(
    key_id: int, req: ApiKeyUpdateRequest, db: Session = Depends(get_db)
):
    """更新 API Key（名称/启用状态）"""
    item = db.query(AuthApiKey).filter(AuthApiKey.id == key_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    if req.name is not None:
        item.name = req.name
    if req.enabled is not None:
        item.enabled = req.enabled
    item.updated_at = datetime.now()
    db.commit()
    logger.info(f"更新 API Key: id={key_id} enabled={item.enabled}")
    return {"success": True, "message": "API Key 已更新"}


@router.delete("/{key_id}")
async def delete_api_key(key_id: int, db: Session = Depends(get_db)):
    """删除 API Key"""
    item = db.query(AuthApiKey).filter(AuthApiKey.id == key_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    db.delete(item)
    db.commit()
    logger.info(f"删除 API Key: id={key_id}")
    return {"success": True, "message": "API Key 已删除"}
