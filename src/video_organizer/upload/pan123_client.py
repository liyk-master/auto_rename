"""
123云盘 Python 原生驱动
基于 OpenList (Go) 驱动逻辑翻译，替换 p123client 第三方库
"""

import binascii
import hashlib
import json
import logging
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
from tqdm import tqdm
from colorama import Fore, init
from functools import wraps

init(autoreset=True)

logger = logging.getLogger(__name__)

MAIN_API = "https://yun.123pan.com/b/api"
LOGIN_API = "https://login.123pan.com/api"

SIGN_IN = f"{LOGIN_API}/user/sign_in"
USER_INFO = f"{MAIN_API}/user/info"
FILE_LIST = f"{MAIN_API}/file/list/new"
DOWNLOAD_INFO = f"{MAIN_API}/file/download_info"
UPLOAD_REQUEST = f"{MAIN_API}/file/upload_request"
UPLOAD_COMPLETE = f"{MAIN_API}/file/upload_complete"
S3_PRE_SIGNED_URLS = f"{MAIN_API}/file/s3_repare_upload_parts_batch"
S3_AUTH = f"{MAIN_API}/file/s3_upload_object/auth"
UPLOAD_COMPLETE_V2 = f"{MAIN_API}/file/upload_complete/v2"
MOVE = f"{MAIN_API}/file/mod_pid"
RENAME = f"{MAIN_API}/file/rename"
TRASH = f"{MAIN_API}/file/trash"


# ========== 签名工具（OpenList GetApi/signPath 翻译） ==========

_SIGN_TABLE = [ord(c) for c in "adefghlymijopkqrstubcwvsz"]


def _sign_path(path: str, os_type: str = "web", version: str = "3") -> Tuple[str, str]:
    now = datetime.utcnow() + timedelta(hours=8)
    timestamp = str(int(now.timestamp()))
    random_num = str(round(1e7 * random.random()))
    now_str = now.strftime("%Y%m%d%H%M")
    now_encoded = bytearray(len(now_str))
    for i, b in enumerate(now_str.encode()):
        digit = b - 48
        now_encoded[i] = _SIGN_TABLE[digit] if 0 <= digit < len(_SIGN_TABLE) else b
    time_sign = str(binascii.crc32(now_encoded) & 0xFFFFFFFF)
    data = "|".join([timestamp, random_num, path, os_type, version, time_sign])
    data_sign = str(binascii.crc32(data.encode()) & 0xFFFFFFFF)
    return time_sign, "-".join([timestamp, random_num, data_sign])


_TOKEN_EXPIRE_KEYWORDS = (
    "token",
    "expired",
    "过期",
    "未授权",
    "authorization",
    "401",
)


def _is_token_expired(code: int, message: str) -> bool:
    if code == 401:
        return True
    msg = (message or "").lower()
    return any(k in msg for k in _TOKEN_EXPIRE_KEYWORDS)


_VERIFY_KEYWORDS = ("验证", "verify", "captcha", "geetest", "人机")


def _is_verification_required(message: str) -> bool:
    msg = (message or "").lower()
    return any(k in msg for k in _VERIFY_KEYWORDS)


def _parse_expire(value) -> int:
    """把登录响应中的 expire（可能是 ISO 时间或时间戳）转为 epoch 秒"""
    if not value:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return 0


DATA_DIR = Path(__file__).resolve().parent / "data"

_GLOBAL_LOGIN_LOCK = threading.Lock()
_last_login_at = 0.0
_login_cooldown = 5.0


def _get_api_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    k, v = _sign_path(parsed.path)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query.setdefault(k, []).append(v)
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


# ========== 通用工具 ==========


def retry(max_retries=3, delay=5):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    print(
                        f"[WARNING] 操作失败，尝试重试 {retries}/{max_retries}: {str(e)}"
                    )
                    if retries < max_retries:
                        time.sleep(delay)
                    else:
                        raise

        return wrapper

    return decorator


def calculate_md5(file_path: str) -> str:
    file_size = Path(file_path).stat().st_size
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        with tqdm(total=file_size, unit='B', unit_scale=True, desc="MD5", ncols=80) as pbar:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                hash_md5.update(chunk)
                pbar.update(len(chunk))
    return hash_md5.hexdigest()


def get_file_size(file_path: str) -> int:
    return Path(file_path).stat().st_size


# ========== 通用上传 Headers ==========

UPLOAD_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Origin": "https://www.123pan.com",
    "Pragma": "no-cache",
    "Referer": "https://www.123pan.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


# ========== Pan123 原生客户端 ==========


class Pan123Client:
    """123云盘原生客户端（替换 p123client.P123Client）"""

    def __init__(
        self,
        token: str = "",
        username: str = "",
        password: str = "",
        platform: str = "web",
        app_version: str = "3",
        upload_thread: int = 3,
        token_file: Optional[str] = None,
    ):
        self.token = token
        self.username = username
        self.password = password
        self.platform = platform
        self.app_version = app_version
        self.upload_thread = upload_thread
        self.expire = 0
        if token_file:
            self.token_file = token_file
        elif username:
            self.token_file = str(DATA_DIR / f"p123_{username}.json")
        else:
            self.token_file = ""
        self._auth_lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "origin": "https://yun.123pan.com",
                "referer": "https://yun.123pan.com/",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "platform": self.platform,
                "app-version": self.app_version,
            }
        )
        self._load_token()

    # ----- 认证 -----

    def _load_token(self):
        """从缓存文件加载 token"""
        if self.token or not self.token_file:
            return
        try:
            path = Path(self.token_file)
            if not path.exists():
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            self.token = data.get("token", "")
            self.expire = int(data.get("expire", 0) or 0)
            if self.token:
                self._session.headers["authorization"] = f"Bearer {self.token}"
                logger.info(f"123云盘已加载缓存的 token: {path}")
        except Exception as e:
            logger.warning(f"加载 123 缓存 token 失败: {e}")

    def _save_token(self):
        """保存 token 到缓存文件"""
        if not self.username or not self.token_file or not self.token:
            return
        try:
            path = Path(self.token_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {"token": self.token, "expire": self.expire},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            logger.info(f"123云盘 token 已缓存到: {path}")
        except Exception as e:
            logger.warning(f"保存 123 缓存 token 失败: {e}")

    def _token_near_expiry(self) -> bool:
        """判断缓存 token 是否接近过期"""
        if not self.expire:
            return False
        ts = self.expire if self.expire < 10000000000 else self.expire / 1000
        return ts < time.time() + 60

    def login(self) -> bool:
        global _last_login_at, _login_cooldown
        if not self.username or not self.password:
            logger.error("未配置 123 云盘用户名密码，无法登录")
            return False
        with _GLOBAL_LOGIN_LOCK:
            wait = _login_cooldown - (time.time() - _last_login_at)
            if wait > 0:
                logger.info(f"123 登录进入冷却期，{wait:.0f}s 后重试（避免触发人机验证）")
                return False
            body: Dict[str, Any]
            if re.match(r"^[^@]+@[^@]+\.[^@]+$", self.username):
                body = {"mail": self.username, "password": self.password, "type": 2}
            else:
                body = {
                    "passport": self.username,
                    "password": self.password,
                    "remember": True,
                }
            try:
                _last_login_at = time.time()
                resp = self._session.post(
                    SIGN_IN,
                    json=body,
                    headers={
                        "origin": "https://yun.123pan.com",
                        "referer": "https://yun.123pan.com/",
                        "user-agent": "Dart/2.19(dart:io)-openlist",
                        "platform": "web",
                        "app-version": "3",
                    },
                )
                data = resp.json()
                if data.get("code") == 200:
                    self.token = data["data"]["token"]
                    self.expire = _parse_expire(data["data"].get("expire"))
                    self._session.headers["authorization"] = (
                        f"Bearer {self.token}"
                    )
                    self._save_token()
                    logger.info("123云盘登录成功")
                    return True
                message = data.get("message")
                logger.error(f"123云盘登录失败: {message}")
                if _is_verification_required(message):
                    _login_cooldown = 300
                    logger.error(
                        "123云盘要求人机验证（请进行验证），无法自动登录。"
                        "请手动获取 token 填入配置 [p123] token，"
                        "或等待风控解除后再试。"
                    )
                else:
                    _login_cooldown = 60
                return False
            except Exception as e:
                _last_login_at = time.time()
                logger.error(f"123云盘登录异常: {e}")
                _login_cooldown = 60
                return False

    def ensure_auth(self):
        if not self.token:
            if self.username and self.password:
                self.login()
            else:
                raise ValueError("Pan123Client 未配置 token 或用户名密码")
        elif self._token_near_expiry():
            logger.info("123 token 即将过期，提前刷新")
            self.login()

    # ----- 核心请求方法 -----

    def request(
        self,
        url: str,
        method: str = "POST",
        json_data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        result_obj: bool = False,
    ) -> Dict[str, Any]:
        self.ensure_auth()
        api_url = _get_api_url(url)
        is_retry = 0
        while True:
            try:
                resp = self._session.request(
                    method,
                    api_url,
                    json=json_data,
                    params=params,
                )
                body = resp.json()
                code = body.get("code")
                if code == 0 or code == 200:
                    return body
                message = body.get("message", "未知错误")
                if is_retry < 2 and _is_token_expired(code, message):
                    logger.info(f"Token 过期，尝试重新登录: {message}")
                    with self._auth_lock:
                        if self.login():
                            is_retry += 1
                            api_url = _get_api_url(url)
                            continue
                logger.error(f"API 请求失败 [{url}]: {message}")
                return body
            except Exception as e:
                logger.error(f"API 请求异常 [{url}]: {e}")
                raise

    # ----- 文件/目录操作 -----

    def get_user_info(self) -> Dict[str, Any]:
        return self.request(USER_INFO, "GET")

    def fs_list(self, *args, **kwargs) -> Dict[str, Any]:
        if args:
            data = args[0]
        elif kwargs:
            data = kwargs
        else:
            data = {}
        params = {
            "driveId": str(data.get("driveId", data.get("drive_id", 0))),
            "limit": str(data.get("limit", data.get("per_page", 100))),
            "next": "0",
            "orderBy": data.get("orderBy", data.get("order_by", "file_id")),
            "orderDirection": data.get(
                "orderDirection", data.get("order_direction", "desc")
            ),
            "parentFileId": str(
                data.get("parentFileId", data.get("parent_file_id", 0))
            ),
            "trashed": "false",
            "Page": str(data.get("page", data.get("Page", 1))),
            "event": data.get("event", "homeListFile"),
        }
        if "SearchData" in data:
            params["SearchData"] = data["SearchData"]
        if "OnlyLookAbnormalFile" in data:
            params["OnlyLookAbnormalFile"] = str(data["OnlyLookAbnormalFile"])
        return self.request(FILE_LIST, "GET", params=params)

    def get_all_files(self, parent_id: int) -> List[Dict[str, Any]]:
        all_files = []
        page = 1
        while True:
            resp = self.fs_list({"parentFileId": parent_id, "page": page, "limit": 100})
            if resp.get("code") != 0:
                break
            items = resp.get("data", {}).get("InfoList", [])
            if not items:
                break
            for item in items:
                all_files.append(
                    {
                        "id": item.get("FileId"),
                        "name": item.get("FileName"),
                        "type": item.get("Type"),
                        "size": item.get("FileSize"),
                        "create_time": item.get("CreateTime"),
                        "update_time": item.get("UpdateTime"),
                        "etag": item.get("Etag"),
                        "s3keyflag": item.get("S3KeyFlag"),
                    }
                )
            if len(items) < 100:
                break
            page += 1
        return all_files

    def iterdir(
        self,
        parent_id: int,
        min_depth: int = 1,
        max_depth: int = 5,
    ):
        def _recurse(folder_id: int, depth: int):
            if depth > max_depth:
                return
            page = 1
            while True:
                resp = self.fs_list(
                    {"parentFileId": folder_id, "page": page, "limit": 100}
                )
                if resp.get("code") != 0:
                    break
                items = resp.get("data", {}).get("InfoList", [])
                if not items:
                    break
                for item in items:
                    is_dir = item.get("Type") == 1
                    entry = {
                        "id": item.get("FileId"),
                        "name": item.get("FileName"),
                        "is_dir": is_dir,
                        "size": item.get("FileSize"),
                        "ctime": item.get("CreateTime"),
                        "mtime": item.get("UpdateTime"),
                        "parent_id": folder_id,
                    }
                    if depth >= min_depth:
                        yield entry
                    if is_dir and depth < max_depth:
                        yield from _recurse(item["FileId"], depth + 1)
                if len(items) < 100:
                    break
                page += 1

        yield from _recurse(parent_id, 1)

    def fs_detail(self, data: Dict[str, Any]) -> Dict[str, Any]:
        file_id = data.get("fileID", data.get("file_id", data.get("fileId", 0)))
        return self.request(
            f"{MAIN_API}/file/detail", "POST", json_data={"fileId": file_id}
        )

    def fs_mkdir(self, name: str, parent_id: int = 0, **kwargs) -> Dict[str, Any]:
        pid = kwargs.get("parent_id", parent_id)
        return self.request(
            UPLOAD_REQUEST,
            "POST",
            json_data={
                "driveId": 0,
                "etag": "",
                "fileName": name,
                "parentFileId": pid,
                "size": 0,
                "type": 1,
            },
        )

    def fs_rename(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.request(
            RENAME,
            "POST",
            json_data={
                "driveId": 0,
                "fileId": data.get("fileId", data.get("file_id")),
                "fileName": data.get("fileName", data.get("file_name")),
            },
        )

    def fs_move(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.request(
            MOVE,
            "POST",
            json_data={
                "fileIdList": data.get("fileIdList", []),
                "parentFileId": data.get("parentFileId", data.get("parent_file_id")),
            },
        )

    def fs_trash(self, file_id: int) -> Dict[str, Any]:
        return self.request(
            TRASH,
            "POST",
            json_data={
                "driveId": 0,
                "operation": True,
                "fileTrashInfoList": [{"FileId": file_id}],
            },
        )

    def get_download_info(self, file: Dict[str, Any]) -> Optional[str]:
        data = {
            "driveId": 0,
            "etag": file.get("etag", file.get("Etag", "")),
            "fileId": file.get("id", file.get("FileId")),
            "fileName": file.get("name", file.get("FileName")),
            "s3keyFlag": file.get("s3keyflag", file.get("S3KeyFlag", "")),
            "size": file.get("size", file.get("Size", 0)),
            "type": file.get("type", file.get("Type", 0)),
        }
        resp = self.request(DOWNLOAD_INFO, "POST", json_data=data)
        logger.info(f"123 get_download_info 响应: code={resp.get('code')}, data={resp.get('data')}")
        if resp.get("code") == 0:
            du = resp.get("data", {}).get("DownloadUrl", "")
            if not du:
                return None
            parsed = urlparse(du)
            nu = parse_qs(parsed.query).get("params", [None])[0]
            if nu:
                try:
                    import base64

                    decoded = base64.b64decode(nu).decode()
                    return self._resolve_vip_redirect(decoded)
                except Exception:
                    pass
            return self._resolve_vip_redirect(du)
        return None

    def _resolve_vip_redirect(self, url: str) -> str:
        try:
            r = requests.get(url, timeout=10)
            if r.ok:
                j = r.json()
                redirect_url = j.get("data", {}).get("redirect_url")
                if redirect_url:
                    logger.info(
                        f"123 解析到最终直链: {redirect_url[:100]}..."
                    )
                    return redirect_url
        except Exception:
            pass
        return url

    # ----- 上传 API -----

    def upload_request(
        self,
        etag: str,
        file_name: str,
        size: int,
        parent_file_id: int,
        duplicate: int = 2,
    ) -> Dict[str, Any]:
        return self.request(
            UPLOAD_REQUEST,
            "POST",
            json_data={
                "driveId": 0,
                "duplicate": duplicate,
                "etag": etag,
                "fileName": file_name,
                "parentFileId": parent_file_id,
                "size": size,
                "type": 0,
            },
        )

    def upload_list(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.request(
            f"{MAIN_API}/file/upload_list",
            "POST",
            json_data={
                "bucket": data.get("bucket", data.get("Bucket")),
                "key": data.get("key", data.get("Key")),
                "storageNode": data.get("storageNode", data.get("StorageNode")),
                "uploadId": data.get("uploadId", data.get("UploadId")),
            },
        )

    def upload_prepare(self, data: Dict[str, Any]) -> Dict[str, Any]:
        start = data.get("partNumberStart", 1)
        end = data.get("partNumberEnd", 2)
        return self.request(
            S3_PRE_SIGNED_URLS,
            "POST",
            json_data={
                "bucket": data.get("bucket", data.get("Bucket")),
                "key": data.get("key", data.get("Key")),
                "partNumberEnd": end,
                "partNumberStart": start,
                "uploadId": data.get("uploadId", data.get("UploadId")),
                "StorageNode": data.get("StorageNode", data.get("storageNode", "")),
            },
        )

    def upload_auth(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.request(
            S3_AUTH,
            "POST",
            json_data={
                "StorageNode": data.get("StorageNode", data.get("storageNode", "")),
                "bucket": data.get("bucket", data.get("Bucket")),
                "key": data.get("key", data.get("Key")),
                "partNumberEnd": data.get("partNumberEnd", 2),
                "partNumberStart": data.get("partNumberStart", 1),
                "uploadId": data.get("uploadId", data.get("UploadId")),
            },
        )

    def upload_complete(self, data: Dict[str, Any]) -> Dict[str, Any]:
        file_id = data.get("fileId", data.get("FileId", data.get("file_id", 0)))
        return self.request(
            UPLOAD_COMPLETE,
            "POST",
            json_data={
                "fileId": file_id,
            },
        )

    def upload_complete_v2(
        self,
        storage_node: str,
        bucket: str,
        file_id: int,
        file_size: int,
        is_multipart: bool,
        key: str,
        upload_id: str,
    ) -> Dict[str, Any]:
        return self.request(
            UPLOAD_COMPLETE_V2,
            "POST",
            json_data={
                "StorageNode": storage_node,
                "bucket": bucket,
                "fileId": file_id,
                "fileSize": file_size,
                "isMultipart": is_multipart,
                "key": key,
                "uploadId": upload_id,
            },
        )


# ========== 上传逻辑（兼容现有接口） ==========


def upload_file(
    client: Pan123Client,
    file_path: str,
    parent_id: int,
    new_name: Optional[str] = None,
    max_retries: int = 3,
    callback=None,
    max_workers: int = 2,
) -> Optional[Dict[str, Any]]:
    file_path = Path(file_path)
    target_name = new_name or file_path.name
    target_name = re.sub(r'[\\/:*?"<>|]', "", target_name)
    file_size = file_path.stat().st_size

    md5_start_time = time.time()
    print(
        f"\n{Fore.CYAN}📁{Fore.RESET} {Fore.YELLOW}开始计算文件MD5{Fore.RESET}: {Fore.MAGENTA}{file_path.name}{Fore.RESET}"
    )
    file_md5 = calculate_md5(file_path)
    md5_end_time = time.time()
    md5_time = md5_end_time - md5_start_time
    print(
        f"{Fore.GREEN}✓{Fore.RESET} MD5计算完成: {Fore.YELLOW}{md5_time:.2f} 秒{Fore.RESET}"
    )

    upload_start_time = time.time()

    try:
        resp = client.upload_request(file_md5, target_name, file_size, parent_id)

        if resp.get("code") != 0:
            raise Exception(f"上传请求失败: {resp.get('message')}")

        data = resp.get("data", {})
        if data.get("Reuse") or not data.get("Key"):
            print(
                f"\n{Fore.GREEN}⚡{Fore.RESET} {Fore.CYAN}秒传成功{Fore.RESET}: {Fore.YELLOW}{target_name}{Fore.RESET}"
            )
            end_time = time.time()
            upload_time = end_time - upload_start_time
            avg_speed = file_size / upload_time if upload_time > 0 else 0
            _print_upload_stats(
                target_name, file_size, md5_time, upload_time, avg_speed, True
            )
            return {
                "name": target_name,
                "size": file_size,
                "etag": file_md5,
                "fileid": str(data.get("FileId") or data.get("Info", {}).get("FileId", "")),
                "modify_time": int(datetime.now().timestamp()),
                "upload_time": upload_time,
                "avg_speed": avg_speed,
            }

        has_s3_creds = all(
            data.get(k) for k in ("AccessKeyId", "SecretAccessKey", "SessionToken")
        )
        if has_s3_creds:
            result = _upload_via_s3_sdk(
                client, file_path, data, target_name, file_size, callback
            )
        else:
            result = _upload_via_presigned_url(
                client, file_path, data, target_name, file_size, callback, max_workers
            )

        end_time = time.time()
        upload_time = end_time - upload_start_time
        avg_speed = file_size / upload_time if upload_time > 0 else 0
        _print_upload_stats(
            target_name, file_size, md5_time, upload_time, avg_speed, False
        )
        return result

    except Exception as e:
        print(f"[ERROR] 上传过程出错: {str(e)}")
        import traceback

        traceback.print_exc()
        return None


def _print_upload_stats(
    name: str, size: int, md5_time: float, upload_time: float, speed: float, reuse: bool
):
    status = "秒传成功" if reuse else "上传成功"
    print(f"\n{Fore.CYAN}{'='*50}{Fore.RESET}")
    print(
        f"{Fore.GREEN}✓{Fore.RESET} {Fore.CYAN}{status}{Fore.RESET}: {Fore.YELLOW}{name}{Fore.RESET}"
    )
    print(f"{Fore.CYAN}{'='*50}{Fore.RESET}")
    print(f"{Fore.CYAN}📊 上传统计信息{Fore.RESET}")
    print(
        f"  {Fore.CYAN}文件大小:{Fore.RESET} {Fore.MAGENTA}{size / (1024 * 1024):.2f} MB{Fore.RESET}"
    )
    print(
        f"  {Fore.CYAN}MD5耗时:{Fore.RESET} {Fore.YELLOW}{md5_time:.2f} 秒{Fore.RESET}"
    )
    print(
        f"  {Fore.CYAN}上传耗时:{Fore.RESET} {Fore.YELLOW}{upload_time:.2f} 秒{Fore.RESET}"
    )
    print(
        f"  {Fore.CYAN}平均速度:{Fore.RESET} {Fore.GREEN}{speed / (1024 * 1024):.2f} MB/s{Fore.RESET}"
    )
    print(f"{Fore.CYAN}{'='*50}{Fore.RESET}\n")


def _upload_via_s3_sdk(
    client: Pan123Client,
    file_path: Path,
    data: Dict[str, Any],
    target_name: str,
    file_size: int,
    callback=None,
) -> Dict[str, Any]:
    print(
        f"\n{Fore.CYAN}🚀{Fore.RESET} {Fore.YELLOW}开始 S3 直传{Fore.RESET}: {Fore.MAGENTA}{target_name}{Fore.RESET}"
    )
    bucket = data.get("Bucket")
    key = data.get("Key")
    access_key = data.get("AccessKeyId")
    secret_key = data.get("SecretAccessKey")
    session_token = data.get("SessionToken")

    if not all([bucket, key, access_key, secret_key, session_token]):
        raise Exception("S3 凭证不完整")

    file_id = data.get("FileId")

    with tqdm(
        total=file_size,
        unit="B",
        unit_scale=True,
        desc=f"S3上传 {target_name}",
        ncols=120,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
    ) as pbar:
        chunk_size = 16 * 1024 * 1024
        total_parts = max(1, (file_size + chunk_size - 1) // chunk_size)

        with open(file_path, "rb") as f:
            for part_num in range(1, total_parts + 1):
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                upload_url = _get_s3_upload_url(client, data, part_num, part_num + 1)
                presigned_url = upload_url.get("presignedUrls", {}).get(
                    str(part_num), ""
                )
                if not presigned_url:
                    raise Exception(f"获取分片 {part_num} 上传URL失败")

                headers = UPLOAD_HEADERS.copy()
                headers["Content-Length"] = str(len(chunk))
                resp = requests.put(
                    presigned_url, data=chunk, headers=headers, timeout=(180, 900)
                )
                if resp.status_code != 200:
                    raise Exception(f"分片 {part_num} 上传失败: {resp.status_code}")

                pbar.update(len(chunk))
                if callback:
                    try:
                        callback(pbar.n, pbar.total)
                    except Exception:
                        pass

        complete_resp = client.upload_complete_v2(
            storage_node=data.get("StorageNode", ""),
            bucket=bucket,
            file_id=file_id,
            file_size=file_size,
            is_multipart=total_parts > 1,
            key=key,
            upload_id=data.get("UploadId", ""),
        )
        if complete_resp.get("code") != 0:
            raise Exception(f"上传完成失败: {complete_resp.get('message')}")

        file_info = complete_resp.get("data", {}).get("file_info", {})
        return {
            "name": target_name,
            "size": file_size,
            "etag": file_info.get("Etag", ""),
            "keyflag": file_info.get("S3KeyFlag", ""),
            "fileid": str(file_info.get("FileId", file_id)),
            "modify_time": int(datetime.now().timestamp()),
        }


def _get_s3_upload_url(
    client: Pan123Client, data: Dict[str, Any], start: int, end: int
) -> Dict[str, Any]:
    payload = {
        "bucket": data.get("Bucket"),
        "key": data.get("Key"),
        "partNumberStart": start,
        "partNumberEnd": end,
        "uploadId": data.get("UploadId"),
        "StorageNode": data.get("StorageNode"),
    }
    return client.upload_prepare(payload)


def _upload_via_presigned_url(
    client: Pan123Client,
    file_path: Path,
    data: Dict[str, Any],
    target_name: str,
    file_size: int,
    callback=None,
    max_workers: int = 2,
) -> Dict[str, Any]:
    slice_size = int(data.get("SliceSize", 16 * 1024 * 1024))

    if file_size <= slice_size:
        return _upload_small_file(client, file_path, data, target_name, callback)
    else:
        return _upload_large_file(
            client,
            file_path,
            data,
            target_name,
            file_size,
            slice_size,
            callback,
            max_workers,
        )


def _upload_small_file(
    client: Pan123Client,
    file_path: Path,
    upload_data: Dict[str, Any],
    target_name: str,
    callback=None,
) -> Dict[str, Any]:
    print(
        f"\n{Fore.CYAN}🚀{Fore.RESET} {Fore.YELLOW}开始直接上传{Fore.RESET}: {Fore.MAGENTA}{target_name}{Fore.RESET}"
    )
    resp = client.upload_auth(upload_data)
    if resp.get("code") != 0:
        raise Exception(f"获取上传授权失败: {resp.get('message', '未知错误')}")

    with open(file_path, "rb") as f:
        file_data = f.read()

    file_size = len(file_data)
    file_hash = hashlib.md5(str(file_path).encode()).hexdigest()[:8]
    position = int(file_hash, 16) % 10

    with tqdm(
        total=file_size,
        unit="B",
        unit_scale=True,
        desc=f"上传 {target_name}",
        ncols=120,
        position=position,
        leave=True,
        file=__import__("sys").stdout,
    ) as pbar:
        max_retries = 6
        for attempt in range(max_retries):
            try:
                headers = UPLOAD_HEADERS.copy()
                presigned_url = (
                    resp.get("data", {}).get("presignedUrls", {}).get("1", "")
                )
                if not presigned_url:
                    raise Exception("未获取到上传URL")
                response = requests.put(
                    presigned_url, data=file_data, headers=headers, timeout=600
                )
                response.raise_for_status()
                pbar.update(file_size)
                if callback:
                    try:
                        callback(file_size, file_size)
                    except Exception:
                        pass
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"[WARNING] 上传失败，重试 ({attempt+1}/{max_retries}): {e}")
                    time.sleep(5)
                    resp = client.upload_auth(upload_data)
                else:
                    raise

    file_id = upload_data.get("fileId", upload_data.get("FileId", 0))
    complete_resp = client.upload_complete({"fileId": file_id})
    if complete_resp.get("code") != 0:
        raise Exception(f"上传完成失败: {complete_resp.get('message', '未知错误')}")

    data = complete_resp.get("data", {}).get("file_info", {})
    return {
        "name": target_name,
        "size": file_size,
        "etag": data.get("Etag", ""),
        "keyflag": data.get("S3KeyFlag", ""),
        "fileid": str(data.get("FileId", file_id)),
        "modify_time": int(datetime.now().timestamp()),
    }


def _upload_large_file(
    client: Pan123Client,
    file_path: Path,
    upload_data: Dict[str, Any],
    target_name: str,
    file_size: int,
    slice_size: int,
    callback=None,
    max_workers: int = 2,
    uploaded_part_numbers: Optional[Set[int]] = None,
) -> Dict[str, Any]:
    if uploaded_part_numbers is None:
        uploaded_part_numbers = set()

    total_parts = max(1, (file_size + slice_size - 1) // slice_size)
    optimal_workers = min(max_workers, total_parts, max(2, os.cpu_count() or 2 + 2))

    print(
        f"\n{Fore.CYAN}🚀{Fore.RESET} {Fore.YELLOW}开始分块上传{Fore.RESET}: {Fore.MAGENTA}{target_name}{Fore.RESET}"
    )
    print(
        f"{Fore.CYAN}ℹ️{Fore.RESET} 使用 {Fore.YELLOW}{optimal_workers}{Fore.RESET} 个线程并发上传 {Fore.YELLOW}{total_parts}{Fore.RESET} 个分片"
    )

    lock = threading.Lock()
    uploaded_bytes = len(uploaded_part_numbers) * slice_size
    file_hash = hashlib.md5(str(file_path).encode()).hexdigest()[:8]
    position = int(file_hash, 16) % 10

    with tqdm(
        total=file_size,
        unit="B",
        unit_scale=True,
        desc=f"上传 {target_name}",
        ncols=120,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
        position=position,
        leave=True,
        file=__import__("sys").stdout,
    ) as pbar:
        pbar.update(uploaded_bytes)
        slices_to_upload = [
            i for i in range(1, total_parts + 1) if i not in uploaded_part_numbers
        ]

        with ThreadPoolExecutor(max_workers=optimal_workers) as executor:
            futures = []
            for slice_no in slices_to_upload:
                future = executor.submit(
                    _upload_single_chunk,
                    client,
                    file_path,
                    upload_data.copy(),
                    slice_no,
                    slice_size,
                    pbar,
                    lock,
                    callback,
                )
                futures.append((future, slice_no))

            success_count = 0
            for future, slice_no in futures:
                try:
                    future.result()
                    success_count += 1
                except Exception as e:
                    print(f"\n{Fore.RED}✗{Fore.RESET} 分片 {slice_no} 上传失败: {e}")
                    for f, _ in futures:
                        if not f.done():
                            f.cancel()
                    raise Exception(f"上传失败: 已成功 {success_count} 个分片")

    file_id = upload_data.get("fileId", upload_data.get("FileId", 0))
    complete_resp = client.upload_complete_v2(
        storage_node=upload_data.get("StorageNode", ""),
        bucket=upload_data.get("Bucket", ""),
        file_id=file_id,
        file_size=file_size,
        is_multipart=True,
        key=upload_data.get("Key", ""),
        upload_id=upload_data.get("UploadId", ""),
    )
    if complete_resp.get("code") != 0:
        raise Exception(f"上传完成失败: {complete_resp.get('message')}")

    file_info = complete_resp.get("data", {}).get("file_info", {})
    return {
        "name": target_name,
        "size": file_size,
        "etag": file_info.get("Etag", ""),
        "keyflag": file_info.get("S3KeyFlag", ""),
        "fileid": str(file_info.get("FileId", file_id)),
        "modify_time": int(datetime.now().timestamp()),
    }


def _upload_single_chunk(
    client: Pan123Client,
    file_path: Path,
    upload_data: Dict[str, Any],
    slice_no: int,
    slice_size: int,
    pbar: tqdm,
    lock: threading.Lock,
    callback=None,
) -> int:
    max_retries = 8
    upload_session = requests.Session()

    try:
        for retry_count in range(max_retries):
            try:
                offset = (slice_no - 1) * slice_size
                with open(file_path, "rb") as f:
                    f.seek(offset)
                    chunk_data = f.read(slice_size)

                if not chunk_data:
                    raise Exception(f"分片 {slice_no} 数据为空")

                upload_data["partNumberStart"] = slice_no
                upload_data["partNumberEnd"] = slice_no + 1

                presigned_resp = client.upload_prepare(upload_data)
                if presigned_resp.get("code") != 0:
                    raise Exception(
                        f"获取分片 {slice_no} 上传URL失败: {presigned_resp.get('message')}"
                    )

                presigned_url = (
                    presigned_resp.get("data", {})
                    .get("presignedUrls", {})
                    .get(str(slice_no), "")
                )
                if not presigned_url:
                    raise Exception(f"分片 {slice_no} 未获取到上传URL")

                headers = UPLOAD_HEADERS.copy()
                headers["Content-Length"] = str(len(chunk_data))

                response = upload_session.put(
                    presigned_url,
                    data=chunk_data,
                    headers=headers,
                    timeout=(180, 900),
                    stream=False,
                )

                if response.status_code == 403:
                    presigned_resp = client.upload_prepare(upload_data)
                    presigned_url = (
                        presigned_resp.get("data", {})
                        .get("presignedUrls", {})
                        .get(str(slice_no), "")
                    )
                    if presigned_url:
                        response = upload_session.put(
                            presigned_url,
                            data=chunk_data,
                            headers=headers,
                            timeout=(180, 900),
                            stream=False,
                        )

                response.raise_for_status()

                if response.status_code == 200:
                    with lock:
                        pbar.update(len(chunk_data))
                        if callback:
                            try:
                                callback(pbar.n, pbar.total)
                            except Exception:
                                pass
                    return len(chunk_data)

            except requests.exceptions.Timeout as e:
                print(f"{Fore.RED}⏱️{Fore.RESET} 分片 {slice_no} 上传超时: {e}")
            except requests.exceptions.ConnectionError as e:
                print(f"{Fore.RED}🔌{Fore.RESET} 分片 {slice_no} 网络连接失败: {e}")
            except Exception as upload_err:
                print(
                    f"{Fore.YELLOW}⚠️{Fore.RESET} 分片 {slice_no} 上传失败 ({retry_count+1}/{max_retries}): {upload_err}"
                )

            if retry_count < max_retries - 1:
                backoff = (2**retry_count) + random.uniform(0, 1)
                print(
                    f"{Fore.CYAN}⏳{Fore.RESET} 分片 {slice_no} 将在 {Fore.YELLOW}{backoff:.1f}{Fore.RESET} 秒后重试"
                )
                time.sleep(backoff)
            else:
                raise Exception(f"分片 {slice_no} 上传失败，已达到最大重试次数")

    finally:
        upload_session.close()

    return 0
