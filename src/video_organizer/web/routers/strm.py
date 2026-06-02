"""
STRM 302 代理路由

提供 Cloud189 和 Yun139 的秒传直链代理服务（302 重定向）。
兼容现有 STRM 文件的 URL 格式。
"""

import base64
import json
import logging
import threading
import time
from typing import Any, Optional
from urllib.parse import unquote, urlparse, parse_qs

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse, JSONResponse

from ..services.state import get_state_manager

logger = logging.getLogger(__name__)

router = APIRouter()

# ==================== 下载链接缓存 ====================
_strm_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
CACHE_DEFAULT_TTL = 300


def _cache_key(prefix: str, client_ip: str, *parts: str) -> str:
    return f"{prefix}:{client_ip}:" + ":".join(parts)


def _cache_get(key: str) -> Optional[str]:
    with _cache_lock:
        entry = _strm_cache.get(key)
        if entry and entry["expires_at"] > time.time():
            return entry["url"]
        if entry:
            del _strm_cache[key]
    return None


def _cache_set(key: str, url: str, ttl: int = CACHE_DEFAULT_TTL):
    with _cache_lock:
        _strm_cache[key] = {"url": url, "expires_at": time.time() + ttl}


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    host = request.client.host if request.client else "unknown"
    return host


def _extract_ttl_from_url(url: str) -> Optional[int]:
    """从下载链接中提取缓存 TTL（秒）"""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        amz = params.get("X-Amz-Expires")
        if amz:
            return int(amz[0])
        exp = params.get("Expires")
        if exp:
            return int(exp[0])
    except Exception:
        pass
    return None


def _make_302(url: str, ttl: Optional[int] = None) -> RedirectResponse:
    max_age = ttl if ttl and ttl > 0 else CACHE_DEFAULT_TTL
    resp = RedirectResponse(url=url, status_code=302)
    resp.headers["Cache-Control"] = f"max-age={max_age}"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


# ==================== Cloud189 直链获取 ====================


def _cloud189_get_download_url(
    client: Any,
    file_id: str,
    family_id: Optional[str] = None,
) -> Optional[str]:
    """通过 Cloud189 PC API 获取文件下载直链
    
    模仿 cloud189_pc.py 的 get_download_url / get_family_download_url 方法：
    - 个人云: API_URL/getFileDownloadUrl.action + HMAC-SHA1 签名
    - 家庭云: API_URL/family/file/getFileDownloadUrl.action + HMAC-SHA1 签名
    """
    API_URL = "https://api.cloud.189.cn"

    if family_id:
        params = {"familyId": family_id, "fileId": file_id}
        is_family = True
        endpoint = f"{API_URL}/family/file/getFileDownloadUrl.action"
    else:
        params = {"fileId": file_id}
        is_family = False
        endpoint = f"{API_URL}/getFileDownloadUrl.action"

    headers = client._sign_pc_request(endpoint, "GET", params, is_family)

    # 参数作为 query 参数（不参与签名，签名只覆盖 SessionKey+Operate+URI+Date）
    client.session.headers.update({"Accept": "application/json;charset=UTF-8"})
    resp = client.session.get(endpoint, params=params, headers=headers, timeout=30)
    logger.info(f"getFileDownloadUrl 响应: {resp.text[:1000]}")
    result = resp.json()

    download_url = result.get("fileDownloadUrl", "")
    if not download_url:
        logger.error(f"响应中无 fileDownloadUrl: {resp.text[:500]}")
        return None

    if not download_url.startswith("http"):
        download_url = "https:" + download_url

    download_url = download_url.replace("amp;", "")

    # 跟随 302 获取真实 CDN 链接（参考 main.js 模式）
    try:
        redirect_resp = client.session.get(
            download_url,
            allow_redirects=False,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
            timeout=30,
        )
        if redirect_resp.status_code in (302, 301):
            location = redirect_resp.headers.get("Location")
            if location:
                return location
    except Exception as e:
        logger.warning(f"跟随重定向失败: {e}")

    return download_url


# ==================== Cloud189 秒传代理 ====================


@router.get("/createSecondUpload/{fileMd5}/{fileSize}/{sliceMd5}/{fileName}")
async def cloud189_second_upload(
    fileMd5: str,
    fileSize: int,
    sliceMd5: str,
    fileName: str,
    request: Request,
):
    """
    Cloud189 秒传代理
    通过 MD5 信息创建文件并返回视频直链（302 重定向）。

    兼容现有 STRM 文件格式:
    /createSecondUpload/{fileMd5}/{fileSize}/{sliceMd5}/{fileName}
    """
    client_ip = _get_client_ip(request)
    key = _cache_key("189", client_ip, fileMd5, str(fileSize), sliceMd5)

    cached = _cache_get(key)
    if cached:
        return _make_302(cached)

    state = get_state_manager()
    handler = state.get_video_handler()
    if not handler or not handler.cloud189_uploader:
        return JSONResponse(status_code=503, content={"error": "Cloud189 客户端不可用"})

    client = handler.cloud189_uploader.client
    config = state.get_config()
    cloud189_cfg = config.get("cloud189", {})
    parent_folder_id = cloud189_cfg.get("parent_folder_id", "-11")
    family_id = cloud189_cfg.get("family_id")

    decoded_name = unquote(fileName)

    # 秒传
    result = client.rapid_upload(
        file_md5=fileMd5,
        file_size=fileSize,
        slice_md5=sliceMd5,
        file_name=decoded_name,
        parent_folder_id=parent_folder_id,
        family_id=family_id,
    )

    if not result.success or not result.user_file_id:
        return JSONResponse(
            status_code=500,
            content={"error": "秒传失败", "message": result.message},
        )

    # 获取直链
    try:
        download_url = _cloud189_get_download_url(client, result.user_file_id, family_id)
    except Exception as e:
        logger.error(f"获取直链异常: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": f"获取直链异常: {e}"})

    if not download_url:
        return JSONResponse(status_code=500, content={"error": "获取直链失败"})

    # 删除临时文件（提交 + 轮询确认）
    try:
        delete_result = client.delete_file(
            file_id=result.user_file_id,
            file_name=decoded_name,
            familyId=family_id or 0,
        )
        task_id = delete_result.get("taskId")
        if task_id:
            check_result = client.check_batch_task(task_id, family_id=str(family_id or 0))
            if check_result.get("successedCount", 0) > 0:
                logger.info(f"Cloud189 临时文件已删除: {decoded_name}")
            else:
                logger.warning(f"Cloud189 删除文件可能失败: {check_result}")
    except Exception as e:
        logger.warning(f"删除 Cloud189 临时文件失败: {e}")

    # 缓存 + 302
    ttl = _extract_ttl_from_url(download_url)
    if ttl:
        safe_ttl = max(ttl - 60, 60)
        _cache_set(key, download_url, safe_ttl)
    else:
        _cache_set(key, download_url)

    return _make_302(download_url, ttl)


# ==================== Yun139 秒传代理 ====================


@router.get("/139getDownloadUrl/{sha256}/{size}/{fileName}")
async def yun139_download_url(
    sha256: str,
    size: int,
    fileName: str,
    request: Request,
    part_info: Optional[str] = Query(None),
    app_mode: Optional[str] = Query("false"),
):
    """
    Yun139 秒传代理
    通过 SHA256 创建文件并返回视频直链（302 重定向）。

    兼容现有 STRM 文件格式:
    /139getDownloadUrl/{sha256}/{size}/{fileName}?part_info={base64}
    """
    client_ip = _get_client_ip(request)
    key = _cache_key("139", client_ip, sha256)

    cached = _cache_get(key)
    if cached:
        return _make_302(cached)

    state = get_state_manager()
    handler = state.get_video_handler()
    if not handler or not handler.yun139_uploader:
        return JSONResponse(status_code=503, content={"error": "Yun139 客户端不可用"})

    client = handler.yun139_uploader.client
    config = state.get_config()
    yun139_cfg = config.get("yun139", {})
    parent_id = yun139_cfg.get("parent_id", "/")

    decoded_name = unquote(fileName)
    is_app_mode = app_mode and app_mode.lower() in ("true", "1", "yes")

    # 解析分片信息
    part_infos = None
    if part_info:
        try:
            decoded_json = base64.urlsafe_b64decode(part_info).decode()
            part_infos = json.loads(decoded_json)
        except Exception as e:
            logger.warning(f"解析 part_info 失败: {e}")

    # 秒传
    upload_data = client.rapid_upload(
        sha256=sha256,
        size=size,
        filename=decoded_name,
        parent_id=parent_id,
        part_infos=part_infos,
        is_app_mode=is_app_mode,
    )

    if not upload_data["success"]:
        return JSONResponse(
            status_code=500,
            content={
                "error": "秒传失败",
                "code": 404,
                "data": {
                    "fileId": upload_data.get("fileId", ""),
                    "uploadId": upload_data.get("uploadId", ""),
                    "partInfos": upload_data.get("partInfos", []),
                    "appMode": is_app_mode,
                },
            },
        )

    file_id = upload_data["fileId"]

    # 获取直链
    download_url = client._personal_get_link(file_id)

    if not download_url:
        return JSONResponse(status_code=500, content={"error": "获取直链失败"})
    
    logger.info(f"Yun139 秒传成功，文件ID: {file_id}, 直链: {download_url[:100]}...")

    # 删除临时文件（移入回收站）
    if upload_data.get("rapidUpload"):
        try:
            delete_data = {"fileIds": [file_id]}
            delete_result = client._request("/hcy/recyclebin/batchTrash", delete_data, is_personal=True)
            task_id = delete_result.get("data", {}).get("taskId", "")
            if task_id:
                check_result = client.check_task(task_id, is_personal=True)
                task_status = check_result.get("data", {}).get("taskInfo", {}).get("status", "")
                if task_status == "Succeed":
                    err_codes = [r.get("errCode", "") for r in check_result.get("data", {}).get("batchFileResults", [])]
                    all_ok = all(c == "0000" for c in err_codes)
                    logger.info(f"Yun139 删除任务 {task_id} 完成: status={task_status}, errCodes={err_codes}")
                else:
                    logger.warning(f"Yun139 删除任务 {task_id} 未成功: status={task_status}")
        except Exception as e:
            logger.warning(f"删除 Yun139 临时文件失败: {e}")

    _cache_set(key, download_url)
    return _make_302(download_url)
