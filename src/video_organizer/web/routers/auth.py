"""
认证路由

提供登录、用户管理等 API。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..services.state import get_state_manager
from ..auth import create_token, verify_token, hash_password, verify_password
from ...database.models import AuthUser
from ...database.config_operations import get_first_run_credentials
from ...database.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== 请求/响应模型 =====

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "user"
    enabled: bool = True


class UserUpdateRequest(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    enabled: Optional[bool] = None


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    enabled: bool
    created_at: Optional[datetime] = None


class UserListResponse(BaseModel):
    success: bool = True
    users: List[UserResponse]


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str


# ===== 首次运行凭证 =====

@router.get("/first-run-credentials")
async def first_run_credentials():
    """返回首次运行生成的临时账号密码（仅首次运行有效，登录后失效）"""
    username, password = get_first_run_credentials()
    if not password:
        return {"has_credentials": False}
    return {
        "has_credentials": True,
        "username": username,
        "password": password,
    }


# ===== 登录 =====

@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    用户登录 — 从 DB AuthUser 表验证，支持明文回退。
    """
    user = db.query(AuthUser).filter(
        AuthUser.username == request.username
    ).first()

    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.enabled:
        raise HTTPException(status_code=401, detail="用户已被禁用")

    # 1. 先用哈希验证
    matched = verify_password(request.password, user.password_hash)
    # 2. 回退：如果存储的密码不含 $，当作明文对比（旧版 INI 导入）
    if not matched and "$" not in user.password_hash:
        matched = request.password == user.password_hash

    if not matched:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 如果是明文密码，升级为哈希
    if "$" not in user.password_hash:
        user.password_hash = hash_password(request.password)
        db.commit()

    token = create_token(request.username)
    logger.info(f"用户 '{request.username}' 登录成功")

    return LoginResponse(
        access_token=token,
        username=request.username,
    )


@router.get("/me")
async def get_current_user(request: Request):
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


# ===== 用户 CRUD =====

@router.get("/users", response_model=UserListResponse)
async def list_users(db: Session = Depends(get_db)):
    """获取所有用户"""
    users = db.query(AuthUser).order_by(AuthUser.id).all()
    return UserListResponse(users=[
        UserResponse(
            id=u.id, username=u.username, role=u.role,
            enabled=u.enabled, created_at=u.created_at,
        ) for u in users
    ])


@router.post("/users")
async def create_user(req: UserCreateRequest, db: Session = Depends(get_db)):
    """创建用户"""
    exists = db.query(AuthUser).filter(AuthUser.username == req.username).first()
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在")
    now = datetime.now()
    user = AuthUser(
        username=req.username,
        password_hash=hash_password(req.password),
        role=req.role,
        enabled=req.enabled,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"创建用户: {user.username} (role={user.role})")
    return {"success": True, "user": {
        "id": user.id, "username": user.username,
        "role": user.role, "enabled": user.enabled,
    }}


@router.put("/users/{user_id}")
async def update_user(user_id: int, req: UserUpdateRequest, db: Session = Depends(get_db)):
    """更新用户"""
    user = db.query(AuthUser).filter(AuthUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if req.username is not None:
        conflict = db.query(AuthUser).filter(
            AuthUser.username == req.username, AuthUser.id != user_id
        ).first()
        if conflict:
            raise HTTPException(status_code=400, detail="用户名已被占用")
        user.username = req.username
    if req.password is not None:
        user.password_hash = hash_password(req.password)
    if req.role is not None:
        user.role = req.role
    if req.enabled is not None:
        user.enabled = req.enabled
    user.updated_at = datetime.now()
    db.commit()
    logger.info(f"更新用户: {user.username}")
    return {"success": True, "message": "用户已更新"}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, db: Session = Depends(get_db)):
    """删除用户"""
    user = db.query(AuthUser).filter(AuthUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    db.delete(user)
    db.commit()
    logger.info(f"删除用户: {user.username}")
    return {"success": True, "message": "用户已删除"}


@router.put("/users/{user_id}/password")
async def change_password(
    user_id: int, req: PasswordChangeRequest, request: Request,
    db: Session = Depends(get_db),
):
    """修改密码（需要旧密码验证）"""
    user = db.query(AuthUser).filter(AuthUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=403, detail="旧密码错误")
    user.password_hash = hash_password(req.new_password)
    user.updated_at = datetime.now()
    db.commit()
    return {"success": True, "message": "密码已修改"}
