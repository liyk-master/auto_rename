"""
中国移动云盘（139云盘）Python 实现
支持：个人云（新版）、家庭云、群组云
"""

import hashlib
import base64
import time
import random
import string
import json
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum
from urllib.parse import quote

import requests

_logger = logging.getLogger(__name__)




def _report_upload_progress(
    file_path: str,
    filename: str,
    uploader: str,
    progress: float,
    uploaded_bytes: int,
    total_bytes: int,
    speed: str = "",
    status: str = "uploading",
    error: Optional[str] = None
):
    """报告上传进度到 Web 状态管理器"""
    try:
        from ..web.services.state import report_upload_progress
        report_upload_progress(
            file_path=file_path,
            filename=filename,
            uploader=uploader,
            progress=progress,
            uploaded_bytes=uploaded_bytes,
            total_bytes=total_bytes,
            speed=speed,
            status=status,
            error=error
        )
    except Exception:
        pass  # Web 模块未加载时忽略


class CloudType(Enum):
    PERSONAL_NEW = "personal_new"  # 新版个人云
    PERSONAL = "personal"          # 旧版个人云
    FAMILY = "family"              # 家庭云
    GROUP = "group"                # 群组云


@dataclass
class FileInfo:
    """文件/文件夹信息"""
    id: str
    name: str
    size: int
    is_folder: bool
    created_time: datetime
    modified_time: datetime
    thumbnail: str = ""
    path: str = ""


class Yun139:
    """139云盘驱动"""
    
    # API 端点
    BASE_URL = "https://yun.139.com"
    PERSONAL_URL = "https://personal-kd-njs.yun.139.com"
    AUTH_URL = "https://aas.caiyun.feixin.10086.cn:443/tellin/authTokenRefresh.do"
    
    # 分片大小常量
    KB = 1 << 10
    MB = 1 << 20
    GB = 1 << 30
    
    def __init__(
        self,
        authorization: str,
        cloud_type: CloudType = CloudType.PERSONAL_NEW,
        cloud_id: str = "",
        custom_part_size: int = 0
    ):
        """
        初始化139云盘
        
        Args:
            authorization: Base64编码的认证信息
            cloud_type: 云盘类型
            cloud_id: 家庭云/群组云ID
            custom_part_size: 自定义分片大小，0为自动
        """
        self.authorization = authorization
        self.cloud_type = cloud_type
        self.cloud_id = cloud_id
        self.custom_part_size = custom_part_size
        self.account = ""
        self.session = requests.Session()
        self._parse_authorization()
    
    def _parse_authorization(self):
        """解析认证信息，提取账号和过期时间"""
        try:
            decoded = base64.b64decode(self.authorization).decode('utf-8')
            parts = decoded.split(':')
            if len(parts) >= 2:
                self.account = parts[1]
            self._token_expires_at = 0
            if len(parts) >= 3:
                token_parts = parts[2].split('|')
                if len(token_parts) >= 4:
                    self._token_expires_at = int(token_parts[3]) / 1000
        except Exception as e:
            raise ValueError(f"认证信息解析失败: {e}")

    def _ensure_valid_token(self) -> None:
        """请求前检查token，提前10分钟自动刷新"""
        if self._token_expires_at and time.time() > self._token_expires_at - 600:
            try:
                self.refresh_token()
            except Exception as e:
                _logger.warning(f"Token刷新失败，将继续使用现有token: {e}")
    
    def _encode_uri_component(self, s: str) -> str:
        """JavaScript encodeURIComponent 的 Python 实现"""
        return quote(s, safe='')
    
    def _calculate_sign(self, body: str, ts: str, rand_str: str) -> str:
        """
        计算签名
        
        签名算法：
        1. URL编码请求体
        2. 按字符排序
        3. Base64编码
        4. MD5哈希
        5. 与时间戳+随机字符串的MD5组合
        6. 最终MD5并转大写
        """
        # URL编码
        encoded = self._encode_uri_component(body)
        # 按字符排序
        sorted_chars = sorted(encoded)
        sorted_str = ''.join(sorted_chars)
        # Base64编码
        b64 = base64.b64encode(sorted_str.encode()).decode()
        # MD5
        md5_body = hashlib.md5(b64.encode()).hexdigest()
        md5_ts = hashlib.md5(f"{ts}:{rand_str}".encode()).hexdigest()
        # 组合并最终MD5
        combined = md5_body + md5_ts
        final_md5 = hashlib.md5(combined.encode()).hexdigest()
        return final_md5.upper()
    
    def _get_headers(self, body: str, is_personal: bool = False) -> Dict[str, str]:
        """获取请求头"""
        rand_str = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sign = self._calculate_sign(body, ts, rand_str)
        
        svc_type = "2" if self.cloud_type == CloudType.FAMILY else "1"
        chrome_ver = "148.0.0.0"
        os_ver = "windows 11"
        client_ver = "1.0.0"
        
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Basic {self.authorization}",
            "mcloud-channel": "1000101",
            "mcloud-client": "10701",
            "mcloud-sign": f"{ts},{rand_str},{sign}",
            "mcloud-version": "7.14.0",
            "Origin": "https://yun.139.com",
            "Referer": "https://yun.139.com/w/",
            "x-DeviceInfo": f"||9|{client_ver}|chrome|{chrome_ver}|||{os_ver}||zh-CN|||",
            "x-huawei-channelSrc": "10200153",
            "x-inner-ntwk": "2",
            "x-m4c-caller": "PC",
            "x-m4c-src": "10002",
            "x-SvcType": svc_type,
            "Content-Type": "application/json",
        }
        
        if is_personal:
            headers.update({
                "Caller": "web",
                "Mcloud-Route": "001",
                "X-Yun-Api-Version": "v1",
                "X-Yun-App-Channel": "10200153",
                "X-Yun-Channel-Source": "10200153",
                "X-Yun-Client-Info": f"||9|{client_ver}|chrome|{chrome_ver}|||{os_ver}||zh-CN|||",
                "X-Yun-Module-Type": "100",
                "X-Yun-Svc-Type": "1",
            })
        
        return headers
    
    def _request(
        self,
        path: str,
        data: Dict,
        method: str = "POST",
        is_personal: bool = False,
    ) -> Dict:
        """发送请求"""
        self._ensure_valid_token()
        base_url = self.PERSONAL_URL if is_personal else self.BASE_URL
        url = base_url + path
        body = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        headers = self._get_headers(body, is_personal)

        _logger.debug(">>> 请求: %s %s", method, url)
        _logger.debug(">>> Body: %s", body)
        _logger.debug(">>> mcloud-sign: %s", headers.get("mcloud-sign", ""))
        _logger.debug(">>> Headers: %s", {k: v for k, v in headers.items() if k != "Authorization"})

        response = self.session.request(
            method=method,
            url=url,
            headers=headers,
            data=body
        )

        _logger.debug("<<< 状态码: %d", response.status_code)
        _logger.debug("<<< 响应: %s", response.text[:2000])

        response.raise_for_status()

        result = response.json()
        if not result.get('success', False):
            # 获取更详细的错误信息
            error_code = result.get('code', 'unknown')
            error_message = result.get('message', '请求失败')
            error_data = result.get('data', {})

            # 构建详细错误信息
            detailed_error = f"{error_message} (code: {error_code})"
            if error_data:
                detailed_error += f" - {error_data}"

            raise Exception(detailed_error)

        return result
    
    def check_task(
        self,
        task_id: str,
        is_personal: bool = False,
        max_retries: int = 10,
        interval: float = 1.0,
    ) -> Dict:
        """轮询检查异步任务执行结果\n
        POST /hcy/task/get，直到 taskInfo.status 为 Succeed/Failed
        """
        import time
        for i in range(max_retries):
            try:
                result = self._request(
                    "/hcy/task/get",
                    {"taskId": task_id},
                    is_personal=is_personal,
                )
                task_info = result.get("data", {}).get("taskInfo", {})
                status = task_info.get("status", "")
                if status in ("Succeed", "Failed"):
                    return result
                _logger.info(f"Yun139 任务 {task_id} 状态: {status}, 等待重试 ({i+1}/{max_retries})")
            except Exception as e:
                _logger.warning(f"Yun139 检查任务 {task_id} 失败: {e}")
            time.sleep(interval)
        return {"success": False, "message": "超时"}

    def _parse_time(self, t: str, fmt: str = "%Y%m%d%H%M%S") -> datetime:
        """解析时间字符串"""
        try:
            return datetime.strptime(t, fmt)
        except:
            return datetime.now()
    
    def _parse_personal_time(self, t: str) -> datetime:
        """解析新版个人云时间格式"""
        try:
            # ISO 8601 格式: 2024-01-01T12:00:00.000+08:00
            return datetime.fromisoformat(t.replace('Z', '+00:00'))
        except:
            return datetime.now()
    
    # ==================== 刷新令牌 ====================
    
    def refresh_token(self) -> bool:
        """刷新认证令牌"""
        try:
            decoded = base64.b64decode(self.authorization).decode('utf-8')
            parts = decoded.split(':')
            if len(parts) < 3:
                return False
            
            token_parts = parts[2].split('|')
            if len(token_parts) < 4:
                return False
            
            # 检查有效期
            expiration = int(token_parts[3])
            now = int(time.time() * 1000)
            
            # 大于15天不刷新
            if expiration - now > 1000 * 60 * 60 * 24 * 15:
                return True
            
            if expiration < now:
                raise Exception("认证已过期")
            
            # 刷新令牌
            req_body = f"<root><token>{parts[2]}</token><account>{parts[1]}</account><clienttype>656</clienttype></root>"
            
            response = self.session.post(
                self.AUTH_URL,
                headers={"Content-Type": "application/xml"},
                data=req_body
            )
            
            # 解析XML响应
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.text)
            
            return_code = root.find('return')
            if return_code is not None and return_code.text == '0':
                token = root.find('token')
                if token is not None:
                    new_auth = f"{parts[0]}:{parts[1]}:{token.text}"
                    self.authorization = base64.b64encode(new_auth.encode()).decode()
                    self._parse_authorization()
                    if self._on_refresh:
                        self._on_refresh()
                    return True
            
            desc = root.find('desc')
            raise Exception(f"刷新令牌失败: {desc.text if desc is not None else '未知错误'}")
            
        except Exception as e:
            raise Exception(f"刷新令牌错误: {e}")
    
    # ==================== 获取文件列表 ====================
    
    def list_files(self, folder_id: str = "/") -> List[FileInfo]:
        """列出目录下的文件"""
        if self.cloud_type == CloudType.PERSONAL_NEW:
            return self._personal_list_files(folder_id)
        elif self.cloud_type == CloudType.PERSONAL:
            return self._get_disk_files(folder_id)
        elif self.cloud_type == CloudType.FAMILY:
            return self._family_list_files(folder_id)
        elif self.cloud_type == CloudType.GROUP:
            return self._group_list_files(folder_id)
        else:
            raise NotImplementedError("不支持的云盘类型")
    
    def _personal_list_files(self, file_id: str) -> List[FileInfo]:
        """新版个人云获取文件列表"""
        files = []
        next_cursor = ""
        
        while True:
            data = {
                "imageThumbnailStyleList": ["Small", "Large"],
                "orderBy": "updated_at",
                "orderDirection": "DESC",
                "pageInfo": {
                    "pageCursor": next_cursor,
                    "pageSize": 100
                },
                "parentFileId": file_id
            }
            
            result = self._request("/hcy/file/list", data, is_personal=True)
            data = result.get('data', {})
            next_cursor = data.get('nextPageCursor', '')
            
            for item in data.get('items', []):
                is_folder = item['type'] == 'folder'
                thumbnails = item.get('thumbnailUrls', [])
                thumbnail = thumbnails[-1]['url'] if thumbnails else ""
                
                files.append(FileInfo(
                    id=item['fileId'],
                    name=item['name'],
                    size=item.get('size', 0),
                    is_folder=is_folder,
                    created_time=self._parse_personal_time(item['createdAt']),
                    modified_time=self._parse_personal_time(item['updatedAt']),
                    thumbnail=thumbnail
                ))
            
            if not next_cursor:
                break
        
        return files
    
    def _get_disk_files(self, catalog_id: str) -> List[FileInfo]:
        """旧版个人云获取文件列表"""
        files = []
        start = 0
        limit = 100
        
        while True:
            data = {
                "catalogID": catalog_id,
                "sortDirection": 1,
                "startNumber": start + 1,
                "endNumber": start + limit,
                "filterType": 0,
                "catalogSortType": 0,
                "contentSortType": 0,
                "commonAccountInfo": {
                    "account": self.account,
                    "accountType": 1
                }
            }
            
            result = self._request("/orchestration/personalCloud/catalog/v1.0/getDisk", data)
            disk_result = result['data']['getDiskResult']
            
            # 文件夹
            for catalog in disk_result.get('catalogList', []):
                files.append(FileInfo(
                    id=catalog['catalogID'],
                    name=catalog['catalogName'],
                    size=0,
                    is_folder=True,
                    created_time=self._parse_time(catalog['createTime']),
                    modified_time=self._parse_time(catalog['updateTime'])
                ))
            
            # 文件
            for content in disk_result.get('contentList', []):
                files.append(FileInfo(
                    id=content['contentID'],
                    name=content['contentName'],
                    size=content['contentSize'],
                    is_folder=False,
                    created_time=self._parse_time(content['createTime']),
                    modified_time=self._parse_time(content['updateTime']),
                    thumbnail=content.get('thumbnailURL', '')
                ))
            
            if start + limit >= disk_result['nodeCount']:
                break
            start += limit
        
        return files
    
    def _family_list_files(self, catalog_id: str) -> List[FileInfo]:
        """家庭云获取文件列表"""
        files = []
        page_num = 1
        
        while True:
            data = {
                "catalogID": catalog_id,
                "catalogType": 3,
                "cloudID": self.cloud_id,
                "cloudType": 1,
                "contentSortType": 0,
                "pageInfo": {
                    "pageNum": page_num,
                    "pageSize": 100
                },
                "sortDirection": 1,
                "commonAccountInfo": {
                    "account": self.account,
                    "accountType": 1
                }
            }
            
            result = self._request(
                "/orchestration/familyCloud-rebuild/content/v1.2/queryContentList",
                data
            )
            
            data = result['data']
            path = data.get('path', '')
            
            # 文件夹
            for catalog in data.get('cloudCatalogList', []):
                files.append(FileInfo(
                    id=catalog['catalogID'],
                    name=catalog['catalogName'],
                    size=0,
                    is_folder=True,
                    created_time=self._parse_time(catalog['createTime']),
                    modified_time=self._parse_time(catalog['lastUpdateTime']),
                    path=path
                ))
            
            # 文件
            for content in data.get('cloudContentList', []):
                files.append(FileInfo(
                    id=content['contentID'],
                    name=content['contentName'],
                    size=content['contentSize'],
                    is_folder=False,
                    created_time=self._parse_time(content['createTime']),
                    modified_time=self._parse_time(content['lastUpdateTime']),
                    thumbnail=content.get('thumbnailURL', ''),
                    path=path
                ))
            
            if data.get('totalCount', 0) == 0:
                break
            page_num += 1
        
        return files
    
    def _group_list_files(self, catalog_id: str) -> List[FileInfo]:
        """群组云获取文件列表"""
        files = []
        start = 1
        
        while True:
            data = {
                "groupID": self.cloud_id,
                "catalogID": catalog_id,
                "contentSortType": 0,
                "sortDirection": 1,
                "startNumber": start,
                "endNumber": start + 99,
                "path": catalog_id,
                "commonAccountInfo": {
                    "account": self.account,
                    "accountType": 1
                }
            }
            
            result = self._request(
                "/orchestration/group-rebuild/content/v1.0/queryGroupContentList",
                data
            )
            
            group_result = result['data']['getGroupContentResult']
            parent_path = group_result['parentCatalogID']
            
            # 文件夹
            for catalog in group_result.get('catalogList', []):
                files.append(FileInfo(
                    id=catalog['catalogID'],
                    name=catalog['catalogName'],
                    size=0,
                    is_folder=True,
                    created_time=self._parse_time(catalog['createTime']),
                    modified_time=self._parse_time(catalog['updateTime']),
                    path=catalog.get('path', '')
                ))
            
            # 文件
            for content in group_result.get('contentList', []):
                files.append(FileInfo(
                    id=content['contentID'],
                    name=content['contentName'],
                    size=content['contentSize'],
                    is_folder=False,
                    created_time=self._parse_time(content['createTime']),
                    modified_time=self._parse_time(content['updateTime']),
                    thumbnail=content.get('thumbnailURL', ''),
                    path=parent_path
                ))
            
            if start + 99 > group_result['nodeCount']:
                break
            start += 100
        
        return files
    
    # ==================== 获取下载链接 ====================
    
    def get_download_url(self, file_id: str, path: str = "") -> str:
        """获取文件下载链接"""
        if self.cloud_type == CloudType.PERSONAL_NEW:
            return self._personal_get_link(file_id)
        elif self.cloud_type == CloudType.PERSONAL:
            return self._get_link(file_id)
        elif self.cloud_type == CloudType.FAMILY:
            return self._family_get_link(file_id, path)
        elif self.cloud_type == CloudType.GROUP:
            return self._group_get_link(file_id, path)
        else:
            raise NotImplementedError()
    
    def _personal_get_link(self, file_id: str) -> str:
        """新版个人云获取下载链接"""
        data = {"fileId": file_id}
        result = self._request("/hcy/file/getDownloadUrl", data, is_personal=True)
        
        # 优先返回 CDN 链接
        cdn_url = result['data'].get('cdnUrl', '')
        if cdn_url:
            return cdn_url
        return result['data'].get('url', '')
    
    def _get_link(self, content_id: str) -> str:
        """旧版个人云获取下载链接"""
        data = {
            "appName": "",
            "contentID": content_id,
            "commonAccountInfo": {
                "account": self.account,
                "accountType": 1
            }
        }
        result = self._request(
            "/orchestration/personalCloud/uploadAndDownload/v1.0/downloadRequest",
            data
        )
        return result['data']['downloadURL']
    
    def _family_get_link(self, content_id: str, path: str) -> str:
        """家庭云获取下载链接"""
        data = {
            "contentID": content_id,
            "path": path,
            "catalogType": 3,
            "cloudID": self.cloud_id,
            "cloudType": 1,
            "commonAccountInfo": {
                "account": self.account,
                "accountType": 1
            }
        }
        result = self._request(
            "/orchestration/familyCloud-rebuild/content/v1.0/getFileDownLoadURL",
            data
        )
        return result['data']['downloadURL']
    
    def _group_get_link(self, content_id: str, path: str) -> str:
        """群组云获取下载链接"""
        data = {
            "contentID": content_id,
            "groupID": self.cloud_id,
            "path": path,
            "commonAccountInfo": {
                "account": self.account,
                "accountType": 1
            }
        }
        result = self._request(
            "/orchestration/group-rebuild/groupManage/v1.0/getGroupFileDownLoadURL",
            data
        )
        return result['data']['downloadURL']
    
    # ==================== 创建文件夹 ====================
    
    def mkdir(self, parent_id: str, dir_name: str) -> bool:
        """创建文件夹"""
        if self.cloud_type == CloudType.PERSONAL_NEW:
            # DEBUG: 打印 parent_id 的实际值
            print(f"  [DEBUG] mkdir: parent_id='{parent_id}' (type: {type(parent_id).__name__}), dir_name='{dir_name}'")
            # 新版个人云：parent_id 保持原样，可能是 "/" 或具体的文件夹ID
            data = {
                "parentFileId": parent_id if parent_id else "",
                "name": dir_name,
                "description": "",
                "type": "folder",
                "fileRenameMode": "force_rename"
            }
            print(f"  [DEBUG] mkdir request data: {data}")
            self._request("/hcy/file/create", data, is_personal=True)
            return True
        
        elif self.cloud_type == CloudType.PERSONAL:
            data = {
                "createCatalogExtReq": {
                    "parentCatalogID": parent_id,
                    "newCatalogName": dir_name,
                    "commonAccountInfo": {
                        "account": self.account,
                        "accountType": 1
                    }
                }
            }
            self._request(
                "/orchestration/personalCloud/catalog/v1.0/createCatalogExt",
                data
            )
            return True
        
        elif self.cloud_type == CloudType.FAMILY:
            data = {
                "cloudID": self.cloud_id,
                "docLibName": dir_name,
                "path": parent_id,
                "commonAccountInfo": {
                    "account": self.account,
                    "accountType": 1
                }
            }
            self._request(
                "/orchestration/familyCloud-rebuild/cloudCatalog/v1.0/createCloudDoc",
                data
            )
            return True
        
        elif self.cloud_type == CloudType.GROUP:
            data = {
                "catalogName": dir_name,
                "groupID": self.cloud_id,
                "parentFileId": parent_id,
                "path": parent_id,
                "commonAccountInfo": {
                    "account": self.account,
                    "accountType": 1
                }
            }
            self._request(
                "/orchestration/group-rebuild/catalog/v1.0/createGroupCatalog",
                data
            )
            return True
        
        return False
    
    # ==================== 重命名 ====================
    
    def rename(self, file: FileInfo, new_name: str) -> bool:
        """重命名文件/文件夹"""
        if self.cloud_type == CloudType.PERSONAL_NEW:
            data = {
                "fileId": file.id,
                "name": new_name,
                "description": ""
            }
            self._request("/hcy/file/update", data, is_personal=True)
            return True
        
        elif self.cloud_type == CloudType.PERSONAL:
            if file.is_folder:
                data = {
                    "catalogID": file.id,
                    "catalogName": new_name,
                    "commonAccountInfo": {
                        "account": self.account,
                        "accountType": 1
                    }
                }
                path = "/orchestration/personalCloud/catalog/v1.0/updateCatalogInfo"
            else:
                data = {
                    "contentID": file.id,
                    "contentName": new_name,
                    "commonAccountInfo": {
                        "account": self.account,
                        "accountType": 1
                    }
                }
                path = "/orchestration/personalCloud/content/v1.0/updateContentInfo"
            self._request(path, data)
            return True
        
        elif self.cloud_type == CloudType.GROUP:
            if file.is_folder:
                data = {
                    "groupID": self.cloud_id,
                    "modifyCatalogID": file.id,
                    "modifyCatalogName": new_name,
                    "path": file.path,
                    "commonAccountInfo": {
                        "account": self.account,
                        "accountType": 1
                    }
                }
                path = "/orchestration/group-rebuild/catalog/v1.0/modifyGroupCatalog"
            else:
                data = {
                    "groupID": self.cloud_id,
                    "contentID": file.id,
                    "contentName": new_name,
                    "path": file.path,
                    "commonAccountInfo": {
                        "account": self.account,
                        "accountType": 1
                    }
                }
                path = "/orchestration/group-rebuild/content/v1.0/modifyGroupContent"
            self._request(path, data)
            return True
        
        return False
    
    # ==================== 删除 ====================
    
    def delete(self, file: FileInfo) -> bool:
        """删除文件/文件夹（移入回收站）"""
        if self.cloud_type == CloudType.PERSONAL_NEW:
            data = {"fileIds": [file.id]}
            resp = self._request("/hcy/recyclebin/batchTrash", data, is_personal=True)
            task_id = resp.get("data", {}).get("taskId", "")
            if task_id:
                result = self.check_task(task_id, is_personal=True)
                status = result.get("data", {}).get("taskInfo", {}).get("status", "")
                if status == "Succeed":
                    err_codes = [r.get("errCode", "") for r in result.get("data", {}).get("batchFileResults", [])]
                    all_ok = all(c == "0000" for c in err_codes)
                    if all_ok:
                        return True
                    _logger.warning(f"Yun139 删除任务 {task_id} 部分文件失败: errCodes={err_codes}")
                else:
                    _logger.warning(f"Yun139 删除任务 {task_id} 未成功: status={status}")
            return False
        
        elif self.cloud_type == CloudType.GROUP:
            import os
            if file.is_folder:
                catalog_list = [file.path]
                content_list = []
            else:
                catalog_list = []
                content_list = [os.path.join(file.path, file.id)]
            
            data = {
                "taskType": 2,
                "srcGroupID": self.cloud_id,
                "contentList": content_list,
                "catalogList": catalog_list,
                "commonAccountInfo": {
                    "account": self.account,
                    "accountType": 1
                }
            }
            self._request(
                "/orchestration/group-rebuild/task/v1.0/createBatchOprTask",
                data
            )
            return True
        
        else:  # PERSONAL 和 FAMILY
            content_list = [] if file.is_folder else [file.id]
            catalog_list = [file.id] if file.is_folder else []
            
            if self.cloud_type == CloudType.FAMILY:
                data = {
                    "catalogList": catalog_list,
                    "contentList": content_list,
                    "sourceCloudID": self.cloud_id,
                    "sourceCatalogType": 1002,
                    "taskType": 2,
                    "path": file.path,
                    "commonAccountInfo": {
                        "account": self.account,
                        "accountType": 1
                    }
                }
                path = "/orchestration/familyCloud-rebuild/batchOprTask/v1.0/createBatchOprTask"
            else:
                data = {
                    "createBatchOprTaskReq": {
                        "taskType": 2,
                        "actionType": 201,
                        "taskInfo": {
                            "newCatalogID": "",
                            "contentInfoList": content_list,
                            "catalogInfoList": catalog_list
                        },
                        "commonAccountInfo": {
                            "account": self.account,
                            "accountType": 1
                        }
                    }
                }
                path = "/orchestration/personalCloud/batchOprTask/v1.0/createBatchOprTask"
            
            self._request(path, data)
            return True
    
    # ==================== 移动 ====================
    
    def move(self, src_file: FileInfo, dst_folder_id: str) -> bool:
        """移动文件/文件夹"""
        if self.cloud_type == CloudType.PERSONAL_NEW:
            data = {
                "fileIds": [src_file.id],
                "toParentFileId": dst_folder_id
            }
            self._request("/hcy/file/batchMove", data, is_personal=True)
            return True
        
        elif self.cloud_type == CloudType.GROUP:
            content_list = [] if src_file.is_folder else [src_file.id]
            catalog_list = [src_file.id] if src_file.is_folder else []
            
            data = {
                "taskType": 3,
                "srcType": 2,
                "srcGroupID": self.cloud_id,
                "destType": 2,
                "destGroupID": self.cloud_id,
                "destPath": dst_folder_id,
                "contentList": content_list,
                "catalogList": catalog_list,
                "commonAccountInfo": {
                    "account": self.account,
                    "accountType": 1
                }
            }
            self._request(
                "/orchestration/group-rebuild/task/v1.0/createBatchOprTask",
                data
            )
            return True
        
        elif self.cloud_type == CloudType.PERSONAL:
            content_list = [] if src_file.is_folder else [src_file.id]
            catalog_list = [src_file.id] if src_file.is_folder else []
            
            data = {
                "createBatchOprTaskReq": {
                    "taskType": 3,
                    "actionType": "304",
                    "taskInfo": {
                        "contentInfoList": content_list,
                        "catalogInfoList": catalog_list,
                        "newCatalogID": dst_folder_id
                    },
                    "commonAccountInfo": {
                        "account": self.account,
                        "accountType": 1
                    }
                }
            }
            self._request(
                "/orchestration/personalCloud/batchOprTask/v1.0/createBatchOprTask",
                data
            )
            return True
        
        return False
    
    # ==================== 复制 ====================
    
    def copy(self, src_file: FileInfo, dst_folder_id: str) -> bool:
        """复制文件/文件夹"""
        if self.cloud_type == CloudType.PERSONAL_NEW:
            data = {
                "fileIds": [src_file.id],
                "toParentFileId": dst_folder_id
            }
            self._request("/hcy/file/batchCopy", data, is_personal=True)
            return True
        
        elif self.cloud_type == CloudType.PERSONAL:
            content_list = [] if src_file.is_folder else [src_file.id]
            catalog_list = [src_file.id] if src_file.is_folder else []
            
            data = {
                "createBatchOprTaskReq": {
                    "taskType": 3,
                    "actionType": 309,
                    "taskInfo": {
                        "contentInfoList": content_list,
                        "catalogInfoList": catalog_list,
                        "newCatalogID": dst_folder_id
                    },
                    "commonAccountInfo": {
                        "account": self.account,
                        "accountType": 1
                    }
                }
            }
            self._request(
                "/orchestration/personalCloud/batchOprTask/v1.0/createBatchOprTask",
                data
            )
            return True
        
        return False
    
    # ==================== 上传 ====================
    
    def _get_part_size(self, size: int) -> int:
        """计算分片大小
        
        规则（参考网页端100MB分片，设置最大100MB）：
        - 小于100MB：整文件上传（1个分片）
        - 小于1GB：5个分片（每片约200MB，但限制最大100MB）
        - 小于10GB：每片100MB
        - 其他：每片100MB
        """
        if self.custom_part_size > 0:
            return self.custom_part_size
        
        MAX_PART_SIZE = 100 * self.MB  # 最大分片100MB
        
        if size < 100 * self.MB:
            # 1个分片
            return size
        elif size < self.GB:
            # 最少5个分片，但每片最大100MB
            part_size = (size + 4) // 5
            return min(part_size, MAX_PART_SIZE)
        else:
            # 每片100MB
            return MAX_PART_SIZE
    
    def upload(
        self,
        parent_id: str,
        file_path: str,
        progress_callback=None,
    ) -> bool:
        """
        上传文件（简化版，仅支持新版个人云）
        """
        if self.cloud_type != CloudType.PERSONAL_NEW:
            raise NotImplementedError("目前仅支持新版个人云上传")
        
        import os
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        
        # 计算SHA256
        sha256_hash = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256_hash.update(chunk)
        content_hash = sha256_hash.hexdigest()
        
        # 计算分片信息
        part_size = self._get_part_size(file_size)
        part_count = max(1, (file_size + part_size - 1) // part_size)
        
        part_infos = []
        for i in range(part_count):
            start = i * part_size
            byte_size = min(part_size, file_size - start)
            part_infos.append({
                "partNumber": i + 1,
                "partSize": byte_size,
                "parallelHashCtx": {"partOffset": start}
            })
        
        # 创建上传任务
        # 秒传时只需传一个分片信息，上传时会获取所有分片的上传地址
        data = {
            "contentHash": content_hash,
            "contentHashAlgorithm": "SHA256",
            "contentType": "application/octet-stream",
            "fileRenameMode": "auto_rename",
            "name": file_name,
            "parentFileId": parent_id,
            "parallelUpload": False,
            "partInfos": part_infos[:1],  # 秒传时只需一个分片
            "size": file_size,
            "type": "file",
        }

        result = self._request("/hcy/file/create", data, is_personal=True)
        upload_data = result['data']

        json_str = json.dumps(part_infos[:1], separators=(',', ':'))  # 去掉空格，更紧凑
        encoded = base64.urlsafe_b64encode(json_str.encode()).decode()
        
        # 打印上传任务信息
        print(f"\n{'='*50}")
        print(f"文件名: {file_name}")
        print(f"文件大小: {file_size} bytes")
        print(f"SHA256: {content_hash}")
        print(f"exist: {upload_data.get('exist', False)}")
        print(f"rapidUpload: {upload_data.get('rapidUpload', False)}")
        print(f"fileId: {upload_data.get('fileId', '')}")
        print(f"fileName: {upload_data.get('fileName', '')}")
        print(f"parts_encoded: {encoded}")
        
        # 报告上传开始
        _report_upload_progress(
            file_path=file_path,
            filename=file_name,
            uploader="yun139",
            progress=0,
            uploaded_bytes=0,
            total_bytes=file_size,
            speed="",
            status="uploading"
        )
        
        # 文件已存在相同内容
        if upload_data.get('exist', False):
            print(f"✓ 文件已存在相同内容，跳过上传")
            _report_upload_progress(
                file_path=file_path,
                filename=file_name,
                uploader="yun139",
                progress=100,
                uploaded_bytes=file_size,
                total_bytes=file_size,
                speed="",
                status="completed"
            )
            return True
        
        # 支持秒传
        if upload_data.get('rapidUpload', False):
            print(f"✓ 秒传成功")
            _report_upload_progress(
                file_path=file_path,
                filename=file_name,
                uploader="yun139",
                progress=100,
                uploaded_bytes=file_size,
                total_bytes=file_size,
                speed="rapid upload",
                status="completed"
            )
            return True
        
        # 获取所有分片上传地址
        upload_part_infos = upload_data.get('partInfos', [])
        file_id = upload_data['fileId']
        upload_id = upload_data['uploadId']
        
        # 获取剩余分片的上传地址（从第2个分片开始）
        for i in range(1, len(part_infos), 100):
            batch = part_infos[i:i+100]
            more_data = {
                "fileId": file_id,
                "uploadId": upload_id,
                "partInfos": batch,
                "commonAccountInfo": {
                    "account": self.account,
                    "accountType": 1
                },
            }
            more_result = self._request(
                "/hcy/file/getUploadUrl",
                more_data,
                is_personal=True,
            )
            upload_part_infos.extend(more_result['data']['partInfos'])
        
        # 上传分片
        uploaded = 0
        upload_start_time = time.time()
        with open(file_path, 'rb') as f:
            for part_info in upload_part_infos:
                part_num = part_info['partNumber'] - 1
                upload_url = part_info['uploadUrl']
                
                f.seek(part_num * part_size)
                chunk_data = f.read(part_size)
                
                # 上传分片（使用 session 复用连接，提升性能）
                headers = {
                    "Accept": "*/*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Connection": "keep-alive",
                    "Content-Length": str(len(chunk_data)),
                    "Content-Type": "application/octet-stream",
                    "Origin": "https://yun.139.com",
                    "Referer": "https://yun.139.com/",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-site",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
                    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                }
                
                response = self.session.put(upload_url, data=chunk_data, headers=headers)
                response.raise_for_status()
                
                uploaded += len(chunk_data)
                
                # 计算上传速度
                elapsed = time.time() - upload_start_time
                speed_str = ""
                if elapsed > 0:
                    speed = uploaded / elapsed / 1024 / 1024  # MB/s
                    speed_str = f"{speed:.2f} MB/s"
                
                # 报告上传进度
                _report_upload_progress(
                    file_path=file_path,
                    filename=file_name,
                    uploader="yun139",
                    progress=uploaded * 100 / file_size,
                    uploaded_bytes=uploaded,
                    total_bytes=file_size,
                    speed=speed_str,
                    status="uploading"
                )
                
                if progress_callback:
                    progress_callback(uploaded, file_size)
        
        # 完成上传
        # 构建已上传分片信息
        uploaded_part_infos = []
        for part_info in sorted(upload_part_infos, key=lambda x: x['partNumber']):
            uploaded_part_infos.append({
                "partNumber": part_info['partNumber'],
                "partSize": part_info['partSize'],
            })
        
        complete_data = {
            "contentHash": content_hash,
            "contentHashAlgorithm": "SHA256",
            "fileId": file_id,
            "uploadId": upload_id,
            "partInfos": uploaded_part_infos,
            "size": file_size,
        }
        self._request("/hcy/file/complete", complete_data, is_personal=True)
        
        print(f"上传完成: {file_name}")
        
        # 报告上传完成
        _report_upload_progress(
            file_path=file_path,
            filename=file_name,
            uploader="yun139",
            progress=100,
            uploaded_bytes=file_size,
            total_bytes=file_size,
            speed="",
            status="completed"
        )
        
        return True

    def rapid_upload(
        self,
        sha256: str,
        size: int,
        filename: str,
        parent_id: str = "/",
        part_infos: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        秒传文件（不实际上传，通过 SHA256 匹配已有文件）
        """
        if not part_infos:
            part_infos = [{"partNumber": 1, "partSize": 1000, "parallelHashCtx": {"partOffset": 0}}]

        data = {
            "contentHash": sha256,
            "contentHashAlgorithm": "SHA256",
            "contentType": "application/octet-stream",
            "fileRenameMode": "auto_rename",
            "name": filename,
            "parentFileId": parent_id,
            "parallelUpload": False,
            "partInfos": part_infos,
            "size": size,
            "type": "file",
        }

        result = self._request("/hcy/file/create", data, is_personal=True)
        upload_data = result.get("data", {})

        return {
            "success": upload_data.get("exist", False) or upload_data.get("rapidUpload", False),
            "fileId": upload_data.get("fileId", ""),
            "fileName": upload_data.get("fileName", ""),
            "exist": upload_data.get("exist", False),
            "rapidUpload": upload_data.get("rapidUpload", False),
            "uploadId": upload_data.get("uploadId", ""),
            "partInfos": upload_data.get("partInfos", []),
        }


# ==================== 使用示例 ====================

if __name__ == "__main__":
    # 示例用法
    # authorization 需要从网页端获取，格式为 Base64 编码的认证信息
    
    auth = "cGM6MTcyNzg2NjY5NjM6dnFJSGVwR3B8MXxSQ1N8MTc4MzQ3NjE4MzEwM3xQSTZZMWJza203dkc2WlF1NVJlOVZ2NlpwRGZNaGVhaWdHY0NUdU9RQ1gyV2FMa0VYd3V6b0ZlbF9CbkZBQk55VGc2ODRrZW5fTzllZGw3b2tqRFVIZDZyUGlLdFNldklLQ21pdkRYZDN1dEk3Smx5OGJSeUcxLjNNbnNJNzBDZFBzMHBlb1hTM2hiUGZOdU9hUGFRQXlLVTRyWkNuYmc3azkzY2dpaGQxQnMt"
    
    # 新版个人云
    client = Yun139(auth, CloudType.PERSONAL_NEW)
    
    # 刷新令牌
    client.refresh_token()
    
    # 列出根目录文件
    files = client.list_files("/")
    # for f in files:
    #     print(f"{'[文件夹]' if f.is_folder else '[文件]'} {f.name} - {f.size} bytes")
    
    # # 获取下载链接
    # if files and not files[0].is_folder:
    #     url = client.get_download_url(files[0].id)
    #     print(f"下载链接: {url}")

    # url = client.get_download_url("FoUqyjwPToSOoofvR--NBrbZmDtw0U7Ij")
    # print(f"下载链接: {url}")
    
    
    # 创建文件夹
    # client.mkdir("/", "新文件夹")
    
    # 上传文件
    # def progress(uploaded, total):
    #     print(f"进度: {uploaded}/{total} ({uploaded*100//total}%)")
    # # client.upload("/", "/path/to/local/file.txt", progress)
    # client.upload("/", "E:\\Media\\Downloads\\tmp\\租借女友 (2020) S03E27 .mp4", lambda u, t: print(f"{u*100//t}%"))
