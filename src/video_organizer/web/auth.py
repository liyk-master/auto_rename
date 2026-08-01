"""
认证模块

提供 JWT-like 令牌生成和验证（使用 HMAC-SHA256，无外部依赖）。
"""

import hmac
import hashlib
import json
import time
import secrets
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# 服务器启动时生成的随机密钥
_secret_key = secrets.token_hex(32)

# 密码哈希 — 使用 hashlib.pbkdf2_hmac (SHA-256 + 随机盐)
_PWHASH_ALGO = "sha256"
_PWHASH_ITER = 600000
_PWHASH_SALT_LEN = 16


def hash_password(password: str) -> str:
    """返回 salt$digest （十六进制）"""
    salt = secrets.token_hex(_PWHASH_SALT_LEN)
    dk = hashlib.pbkdf2_hmac(_PWHASH_ALGO, password.encode(), salt.encode(), _PWHASH_ITER)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """验证密码是否与存储的 salt$digest 匹配"""
    try:
        salt, digest = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac(_PWHASH_ALGO, password.encode(), salt.encode(), _PWHASH_ITER)
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, AttributeError):
        return False

# 不受认证保护的路径前缀
PUBLIC_PATHS = [
    "/api/auth/",
    "/static/",
    "/api/health",
    "/api/tasks/ws/",
    "/api/logs/ws/",
]

# 令牌过期时间（天数）
TOKEN_EXPIRE_DAYS = 7


def create_token(username: str) -> str:
    """创建认证令牌"""
    payload = {
        "username": username,
        "exp": int(time.time()) + 86400 * TOKEN_EXPIRE_DAYS,
        "iat": int(time.time()),
    }
    payload_hex = json.dumps(payload, separators=(",", ":")).encode().hex()
    sig = hmac.new(
        _secret_key.encode(), payload_hex.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload_hex}.{sig}"


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """验证令牌，成功返回 payload，失败返回 None"""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        payload_hex, sig = parts
        expected = hmac.new(
            _secret_key.encode(), payload_hex.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(bytes.fromhex(payload_hex))
        if payload["exp"] < time.time():
            return None
        return payload
    except Exception as e:
        logger.debug(f"令牌验证失败: {e}")
        return None


# API Key 哈希算法标识
_APIKEY_ALGO = "sha256"


def hash_api_key(api_key: str) -> str:
    """返回 API Key 的哈希（sha256$<hex>），数据库中不存明文"""
    digest = hashlib.sha256(api_key.encode()).hexdigest()
    return f"{_APIKEY_ALGO}${digest}"


def verify_api_key(api_key: str) -> bool:
    """验证 API Key 是否存在于数据库中（enabled=True）"""
    if not api_key:
        return False
    try:
        from ..database.models import AuthApiKey
        from ..database.session import get_session_local
        with get_session_local()() as db:
            stored = db.query(AuthApiKey).filter(
                AuthApiKey.enabled == True,  # noqa: E712
            ).all()
            target = hash_api_key(api_key)
            for item in stored:
                if hmac.compare_digest(item.api_key_hash, target):
                    item.last_used_at = datetime.now()
                    db.commit()
                    return True
    except Exception as e:
        logger.debug(f"API Key 校验失败: {e}")
    return False


def is_public_path(path: str) -> bool:
    """判断路径是否需要认证"""
    for prefix in PUBLIC_PATHS:
        if path.startswith(prefix):
            return True
    return False


async def auth_middleware(request: Request, call_next):
    """
    FastAPI 中间件：对 API 请求进行认证检查
    跳过公开路径和静态文件。

    支持两种认证方式：
      1. Authorization: Bearer <token>（登录令牌）
      2. X-API-Key: <api_key>（API Key，Bearer 令牌验证失败时也回退尝试）
    """
    path = request.url.path

    # 非 API 路径或公开路径跳过
    if not path.startswith("/api/") or is_public_path(path):
        return await call_next(request)

    # 方式一：X-API-Key 请求头
    api_key = request.headers.get("X-API-Key", "")
    if api_key and verify_api_key(api_key):
        request.state.user = "apikey"
        request.state.auth_method = "apikey"
        return await call_next(request)

    # 方式二：Authorization: Bearer <token>
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]  # 去掉 "Bearer "
        payload = verify_token(token)
        if payload is not None:
            # 将用户信息存入 request.state
            request.state.user = payload["username"]
            request.state.auth_method = "token"
            return await call_next(request)

        # Bearer 令牌无效时，回退尝试当作 API Key
        if verify_api_key(token):
            request.state.user = "apikey"
            request.state.auth_method = "apikey"
            return await call_next(request)

    return JSONResponse(
        status_code=401,
        content={"detail": "未授权，请提供有效的登录令牌或 API Key"},
    )
