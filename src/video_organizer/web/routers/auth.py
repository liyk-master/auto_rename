"""
认证路由

提供登录、登出、获取当前用户等 API。
"""

import logging
import hmac
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..services.state import get_state_manager
from ..auth import create_token, verify_token

logger = logging.getLogger(__name__)

router = APIRouter()


class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str


class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str
    token_type: str = "bearer"
    username: str


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    用户登录

    验证用户名和密码，返回访问令牌。
    """
    state = get_state_manager()
    config = state.get_config()
    auth_config = config.get("auth", {})

    if not auth_config.get("enabled", False):
        # 认证未启用，允许任意登录（使用默认凭据）
        expected_username = "admin"
        expected_password = "admin"
    else:
        expected_username = auth_config.get("username", "")
        expected_password = auth_config.get("password", "")

    # 使用 hmac.compare_digest 防止时序攻击
    if not hmac.compare_digest(request.username, expected_username):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not hmac.compare_digest(request.password, expected_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_token(request.username)
    logger.info(f"用户 '{request.username}' 登录成功")

    return LoginResponse(
        access_token=token,
        username=request.username,
    )


@router.get("/me")
async def get_current_user(request: Request):
    """
    获取当前登录用户信息

    通过 Authorization header 中的令牌获取。
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未授权")

    token = auth_header[7:]
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")

    return {
        "username": payload["username"],
        "authenticated": True,
    }
