"""
STRM 302 代理路由

提供 Cloud189、Yun139 和 123 云盘的秒传直链代理服务（302 重定向）。
兼容现有 STRM 文件的 URL 格式。
"""

import base64
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import unquote, urlparse, parse_qs

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse, JSONResponse, Response

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


def _make_139_302(url: str) -> Response:
    """用于 Yun139 反代的 302 响应（带 HTML body + 完整 headers）"""
    html_content = f'<a href="{url}">Found</a>.\n'
    content_length = len(html_content.encode("utf-8"))
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    headers = {
        "Location": url,
        "Cache-Control": "max-age=0, no-cache, no-store, must-revalidate",
        "Content-Type": "text/html; charset=utf-8",
        "Referrer-Policy": "no-referrer",
        "Date": now,
        "Content-Length": str(content_length),
    }
    return Response(html_content, status_code=302, headers=headers)


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

    # sessionKey 失效时清除缓存并重试一次
    if result.get("errorCode") == "InvalidSessionKey":
        logger.warning("Cloud189 sessionKey 已失效，清除缓存后重试...")
        client._clear_token_cache()
        headers = client._sign_pc_request(endpoint, "GET", params, is_family)
        client.session.headers.update({"Accept": "application/json;charset=UTF-8"})
        resp = client.session.get(endpoint, params=params, headers=headers, timeout=30)
        logger.info(f"getFileDownloadUrl 重试响应: {resp.text[:1000]}")
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
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            },
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
        download_url = _cloud189_get_download_url(
            client, result.user_file_id, family_id
        )
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
            check_result = client.check_batch_task(
                task_id, family_id=str(family_id or 0)
            )
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
    app_mode: Optional[str] = Query(None),
    pc_client: Optional[str] = Query(None),
):
    """
    Yun139 秒传代理
    通过 SHA256 创建文件并返回视频直链（302 重定向）。

    兼容现有 STRM 文件格式:
    /139getDownloadUrl/{sha256}/{size}/{fileName}?part_info={base64}

    pc_client 参数默认开启，使用 PC 客户端秒传请求格式（force_rename + 完整 x-yun-* headers）
    """
    client_ip = _get_client_ip(request)
    key = _cache_key("139", client_ip, sha256)

    cached = _cache_get(key)
    if cached:
        return _make_139_302(cached)

    state = get_state_manager()
    handler = state.get_video_handler()
    if not handler or not handler.yun139_uploader:
        return JSONResponse(status_code=503, content={"error": "Yun139 客户端不可用"})

    client = handler.yun139_uploader.client
    config = state.get_config()
    yun139_cfg = config.get("yun139", {})
    parent_id = yun139_cfg.get("parent_id", "/")

    decoded_name = unquote(fileName)
    # 查询参数未提供时回退到客户端配置的模式
    if app_mode is None:
        is_app_mode = client.app_mode
    else:
        is_app_mode = app_mode.lower() in ("true", "1", "yes")

    # PC 客户端秒传格式默认开启
    if pc_client is None:
        is_pc_client = True
    else:
        is_pc_client = pc_client.lower() in ("true", "1", "yes")

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
        app_mode=is_app_mode,
        is_pc_client=is_pc_client,
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
            delete_result = client._request(
                "/hcy/recyclebin/batchTrash", delete_data, is_personal=True
            )
            task_id = delete_result.get("data", {}).get("taskId", "")
            if task_id:
                check_result = client.check_task(task_id, is_personal=True)
                task_status = (
                    check_result.get("data", {}).get("taskInfo", {}).get("status", "")
                )
                if task_status == "Succeed":
                    err_codes = [
                        r.get("errCode", "")
                        for r in check_result.get("data", {}).get(
                            "batchFileResults", []
                        )
                    ]
                    all_ok = all(c == "0000" for c in err_codes)
                    logger.info(
                        f"Yun139 删除任务 {task_id} 完成: status={task_status}, errCodes={err_codes}"
                    )
                else:
                    logger.warning(
                        f"Yun139 删除任务 {task_id} 未成功: status={task_status}"
                    )
        except Exception as e:
            logger.warning(f"删除 Yun139 临时文件失败: {e}")

    _cache_set(key, download_url)
    return _make_139_302(download_url)


@router.get("/139createGetDownloadUrl/{fileId}/{fileName}")
async def yun139_create_get_download_url(
    fileId: str,
    fileName: str,
    request: Request,
):
    """
    Yun139 根据 fileId 获取下载直链（302 重定向）

    用于 Media Tracker 秒传后直接获取直链，无需再次秒传。

    URL 格式:
    /139createGetDownloadUrl/{fileId}/{fileName}
    """
    client_ip = _get_client_ip(request)
    key = _cache_key("139_direct", client_ip, fileId)

    cached = _cache_get(key)
    if cached:
        return _make_139_302(cached)

    state = get_state_manager()
    handler = state.get_video_handler()
    if not handler or not handler.yun139_uploader:
        return JSONResponse(status_code=503, content={"error": "Yun139 客户端不可用"})

    client = handler.yun139_uploader.client
    decoded_name = unquote(fileName)

    # 直接通过 fileId 获取下载链接
    try:
        download_url = client._personal_get_link(fileId)
    except Exception as e:
        logger.error(f"获取直链异常: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": f"获取直链失败: {e}"})

    if not download_url:
        return JSONResponse(status_code=500, content={"error": "获取直链失败"})

    logger.info(
        f"Yun139 获取直链成功，文件ID: {fileId}, 文件名: {decoded_name}, 直链: {download_url[:100]}..."
    )

    _cache_set(key, download_url)
    return _make_139_302(download_url)


# ==================== 123 云盘秒传代理 ====================


def _p123_collect_trash_ids(data: dict) -> list:
    """从秒传响应里提取需要删除的全部 FileId

    123 的 `file/upload_request` 秒传响应里会同时出现**两个不同含义的 id**：

    - 顶层 ``data["FileId"]``：秒传会话/记录 id（实测 VIP 账号为 85144550215580、
      169665180427348 这种大数；有时又为 0）。它对 ``get_download_info`` **不一定有效**
      （线上出现过 ``code=5066 文件不存在``），所以取直链时只能当兜底候选
    - ``data["Info"]["FileId"]``：网盘里**真实的文件条目 id**（带 ParentFileId/CreateAt），
      取直链、删除都应该优先用它

    只拿顶层 id 去调 ``file/trash`` 会删一个不存在的条目，而接口照样返回成功，
    导致秒传临时文件永久残留在网盘目录里。两个 id 都发一遗删除，谁不存在谁
    报错（由 _p123_trash_temp 记录），不影响另一个。

    Args:
        data: 秒传响应中的 ``data`` 字段

    Returns:
        去重后的 FileId 列表（Info 优先），无有效 id 时返回空列表
    """
    info = data.get("Info") or {}
    candidates = [info.get("FileId"), data.get("FileId")]
    result = []
    for fid in candidates:
        try:
            fid_int = int(fid)
        except (TypeError, ValueError):
            continue
        if fid_int > 0 and fid_int not in result:
            result.append(fid_int)
    return result


def _p123_trash_temp(client, file_id, file_name: str) -> bool:
    """把秒传产生的临时文件移入回收站

    ``Pan123Client.request()`` 在接口返回非 0 code 时只记 error 日志、不抛异常，
    因此必须检查返回值；否则文件会静默残留在网盘目录里（不在回收站，
    定时清理也盖不到），且没有任何可用日志。

    Args:
        client: Pan123Client 实例
        file_id: 临时文件 FileId
        file_name: 文件名，仅用于残留告警日志

    Returns:
        是否删除成功
    """
    message = ""
    for attempt in (1, 2):
        try:
            resp = client.fs_trash(int(file_id))
        except Exception as exc:
            resp = {"code": -1, "message": str(exc)}
        if resp.get("code") in (0, 200):
            return True
        message = str(resp.get("message") or "")
        logger.warning(
            f"删除 123 秒传临时文件失败（第 {attempt} 次）: FileId={file_id}, {message}"
        )
        if attempt == 1:
            time.sleep(0.5)
    logger.error(
        f"⚠️ 123 秒传临时文件残留: FileId={file_id}, 文件名={file_name}，"
        f"已跳出回收站清理范围，需手动删除"
    )
    return False


def _p123_download_id_candidates(data: dict) -> list:
    """取直链时应依次尝试的 FileId 候选（真实条目 id 优先）

    秒传响应里的两个 id 语义不同（见 ``_p123_collect_trash_ids``），且**哪个能被
    ``get_download_info`` 接受取决于账号/接口版本**：

    - 有的账号顶层会话 id 能取到直链（此时 Info.FileId 同样能用，它是条目本体）
    - 线上又出现过顶层会话 id 直接 ``code=5066 文件不存在``，而 Info.FileId 才是
      真正落在网盘目录里的条目 → 只拿顶层 id 会取不到直链、播放 500

    因此这里返回 ``[Info.FileId, 顶层 FileId]``（去重、忽略 0/None），由调用方逐个试。

    Args:
        data: 秒传响应中的 ``data`` 字段

    Returns:
        去重后的 FileId 列表，无有效 id 时返回空列表
    """
    info = data.get("Info") or {}
    result = []
    for fid in (info.get("FileId"), data.get("FileId")):
        try:
            fid_int = int(fid)
        except (TypeError, ValueError):
            continue
        if fid_int > 0 and fid_int not in result:
            result.append(fid_int)
    return result


def _p123_resolve_download_url(
    client,
    data: dict,
    etag: str,
    file_size: int,
    file_name: str,
    s3keyflag: str,
) -> tuple:
    """按候选 FileId 逐个尝试取直链

    Args:
        client: Pan123Client 实例
        data: 秒传响应的 ``data`` 字段
        etag: 文件 MD5
        file_size: 文件大小
        file_name: 文件名
        s3keyflag: 秒传响应里的 S3KeyFlag

    Returns:
        ``(download_url, used_file_id)``，全部候选失败时返回 ``(None, None)``
    """
    candidates = _p123_download_id_candidates(data)
    logger.info(
        f"123 获取下载链接: 候选 FileId={candidates}, etag={etag}, "
        f"s3keyflag={s3keyflag}"
    )
    last_error: Optional[Exception] = None
    for candidate in candidates:
        file_info = {
            "FileId": candidate,
            "Etag": etag,
            "FileName": file_name,
            "S3KeyFlag": s3keyflag,
            "Size": file_size,
            "Type": 0,
        }
        try:
            download_url = client.get_download_info(file_info)
        except Exception as e:  # 单个候选失败不影响其它候选
            logger.error(f"123 获取直链异常: FileId={candidate}, {e}", exc_info=True)
            last_error = e
            continue
        if download_url:
            if candidate != candidates[0]:
                logger.info(f"123 取直链改用兜底 FileId={candidate}")
            return download_url, candidate

    # 全部候选都失败：把异常留给调用方决定返回 500 还是抛出去
    if last_error and len(candidates) == 1:
        raise last_error
    return None, None


def _p123_handle_redirect(
    file_size: int,
    etag: str,
    file_name: str,
    client_ip: str,
    s3keyflag: Optional[str] = None,
) -> Response:
    key = _cache_key("123", client_ip, etag)

    cached = _cache_get(key)
    if cached:
        return _make_302(cached)

    state = get_state_manager()
    handler = state.get_video_handler()
    if not handler or not handler.p123_uploader:
        return JSONResponse(status_code=503, content={"error": "123 云盘客户端不可用"})

    client = handler.p123_uploader.client
    config = state.get_config()
    p123_cfg = config.get("p123", {})
    parent_id = int(p123_cfg.get("parent_id", 0))

    decoded_name = unquote(file_name)

    # 秒传
    logger.info(
        f"123 秒传请求: etag={etag}, size={file_size}, parent_id={parent_id}, "
        f"filename={decoded_name}"
    )
    try:
        upload_resp = client.upload_request(
            etag=etag,
            file_name=decoded_name,
            size=file_size,
            parent_file_id=parent_id,
            duplicate=2,
        )
    except Exception as e:
        logger.error(f"123 秒传请求异常: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": f"秒传请求异常: {e}"})

    if upload_resp.get("code") != 0:
        return JSONResponse(
            status_code=500,
            content={"error": "秒传失败", "message": upload_resp.get("message")},
        )

    data = upload_resp.get("data", {})
    logger.info(f"data={data}")
    if not data.get("Reuse"):
        return JSONResponse(
            status_code=500,
            content={"error": "秒传失败", "message": "文件未命中秒传"},
        )

    file_id = data.get("FileId") or data.get("Info", {}).get("FileId")
    # 需要删除的条目 id（与取直链的 id 可能不是同一个，见 _p123_collect_trash_ids）
    trash_ids = _p123_collect_trash_ids(data)
    logger.info(
        f"123 秒传 data: Reuse={data.get('Reuse')}, FileId={file_id}, "
        f"待删除 id={trash_ids}, Key={data.get('Key')}"
    )
    if not file_id:
        for trash_id in trash_ids:
            _p123_trash_temp(client, trash_id, decoded_name)
        return JSONResponse(status_code=500, content={"error": "秒传响应中无 FileId"})

    # 未提供 s3keyflag 时从秒传响应中提取
    if not s3keyflag:
        s3keyflag = data.get("Info", {}).get("S3KeyFlag", "") or data.get(
            "S3KeyFlag", ""
        )

    # 获取直链（Info.FileId 优先，顶层会话 id 兜底）
    try:
        download_url, used_file_id = _p123_resolve_download_url(
            client,
            data=data,
            etag=etag,
            file_size=file_size,
            file_name=decoded_name,
            s3keyflag=s3keyflag,
        )
        if used_file_id:
            file_id = used_file_id
    except Exception as e:
        logger.error(f"获取直链异常: {e}", exc_info=True)
        # 取不到直链也要清理，否则临时文件残留在网盘目录中
        for trash_id in trash_ids:
            _p123_trash_temp(client, trash_id, decoded_name)
        return JSONResponse(status_code=500, content={"error": f"获取直链异常: {e}"})

    if not download_url:
        for trash_id in trash_ids:
            _p123_trash_temp(client, trash_id, decoded_name)
        return JSONResponse(status_code=500, content={"error": "获取直链失败"})

    logger.info(
        f"123 秒传成功，文件: {decoded_name}, FileID: {file_id}, 直链: {download_url[:100]}..."
    )

    # 删除临时文件（取直链用的 id 与网盘条目 id 可能不同，两个都发一遗）
    for trash_id in trash_ids:
        _p123_trash_temp(client, trash_id, decoded_name)

    # 缓存 1 小时 + 302
    _cache_set(key, download_url, 3600)
    return _make_302(download_url, 3600)


@router.get("/redirect/{file_size}/{etag}/{file_name}")
async def p123_get_download_url_no_s3keyflag(
    file_size: int,
    etag: str,
    file_name: str,
    request: Request,
):
    """
    123 云盘秒传代理（兼容旧链接，s3keyflag 从秒传响应中提取）
    兼容旧版 STRM 链接:
    /redirect/{file_size}/{etag}/{file_name}
    """
    client_ip = _get_client_ip(request)
    return _p123_handle_redirect(
        file_size=file_size,
        etag=etag,
        file_name=file_name,
        client_ip=client_ip,
    )


@router.get("/redirect/{file_size}/{etag}/{s3keyflag}/{file_name}")
async def p123_get_download_url(
    file_size: int,
    etag: str,
    s3keyflag: str,
    file_name: str,
    request: Request,
):
    """
    123 云盘秒传代理
    通过 etag(MD5) + s3keyflag 创建文件并返回视频直链（302 重定向）。

    专用于 123 STRM 文件播放流程:
    /redirect/{file_size}/{etag}/{s3keyflag}/{file_name}
    """
    client_ip = _get_client_ip(request)
    return _p123_handle_redirect(
        file_size=file_size,
        etag=etag,
        file_name=file_name,
        client_ip=client_ip,
        s3keyflag=s3keyflag,
    )
