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
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum
from urllib.parse import quote

import requests


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
        """解析认证信息，提取账号"""
        try:
            decoded = base64.b64decode(self.authorization).decode('utf-8')
            parts = decoded.split(':')
            if len(parts) >= 2:
                self.account = parts[1]
        except Exception as e:
            raise ValueError(f"认证信息解析失败: {e}")
    
    def _encode_uri_component(self, s: str) -> str:
        """JavaScript encodeURIComponent 的 Python 实现"""
        return quote(s, safe='!~*()\'')
    
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
        
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Basic {self.authorization}",
            "mcloud-channel": "1000101",
            "mcloud-client": "10701",
            "mcloud-sign": f"{ts},{rand_str},{sign}",
            "mcloud-version": "7.14.0",
            "Origin": "https://yun.139.com",
            "Referer": "https://yun.139.com/w/",
            "x-DeviceInfo": "||9|7.14.0|chrome|120.0.0.0|||windows 10||zh-CN|||",
            "x-huawei-channelSrc": "10000034",
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
                "X-Yun-App-Channel": "10000034",
                "X-Yun-Channel-Source": "10000034",
                "X-Yun-Client-Info": "||9|7.14.0|chrome|120.0.0.0|||windows 10||zh-CN|||dW5kZWZpbmVk||",
                "X-Yun-Module-Type": "100",
                "X-Yun-Svc-Type": "1",
            })
        
        return headers
    
    def _request(
        self,
        path: str,
        data: Dict,
        method: str = "POST",
        is_personal: bool = False
    ) -> Dict:
        """发送请求"""
        base_url = self.PERSONAL_URL if is_personal else self.BASE_URL
        url = base_url + path
        body = json.dumps(data)
        headers = self._get_headers(body, is_personal)

        response = self.session.request(
            method=method,
            url=url,
            headers=headers,
            data=body
        )
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
            self._request("/hcy/recyclebin/batchTrash", data, is_personal=True)
            return True
        
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
        """计算分片大小"""
        if self.custom_part_size > 0:
            return self.custom_part_size
        
        if size > 30 * self.GB:
            return 512 * self.MB
        return 100 * self.MB
    
    def upload(
        self,
        parent_id: str,
        file_path: str,
        progress_callback=None
    ) -> bool:
        """
        上传文件（简化版，仅支持新版个人云）
        
        Args:
            parent_id: 目标文件夹ID
            file_path: 本地文件路径
            progress_callback: 进度回调函数
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
            "parallelUpload": False,
            "partInfos": part_infos[:1],  # 秒传时只需一个分片
            "size": file_size,
            "parentFileId": parent_id,
            "name": file_name,
            "type": "file",
            "fileRenameMode": "auto_rename"
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
        
        # 文件已存在相同内容
        if upload_data.get('exist', False):
            print(f"✓ 文件已存在相同内容，跳过上传")
            return True
        
        # 支持秒传
        if upload_data.get('rapidUpload', False):
            print(f"✓ 秒传成功")
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
                }
            }
            more_result = self._request(
                "/hcy/file/getUploadUrl",
                more_data,
                is_personal=True
            )
            upload_part_infos.extend(more_result['data']['partInfos'])
        
        # 上传分片
        uploaded = 0
        with open(file_path, 'rb') as f:
            for part_info in upload_part_infos:
                part_num = part_info['partNumber'] - 1
                upload_url = part_info['uploadUrl']
                
                f.seek(part_num * part_size)
                chunk_data = f.read(part_size)
                
                # 上传分片
                headers = {
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(len(chunk_data)),
                    "Origin": "https://yun.139.com",
                    "Referer": "https://yun.139.com/"
                }
                
                response = requests.put(upload_url, data=chunk_data, headers=headers)
                response.raise_for_status()
                
                uploaded += len(chunk_data)
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
        return True


# ==================== 使用示例 ====================

if __name__ == "__main__":
    # 示例用法
    # authorization 需要从网页端获取，格式为 Base64 编码的认证信息
    
    auth = "cGM6MTU2MDA3MTc5NTg6RUtLMkM1WTR8MXxSQ1N8MTc3NTM5MDQ1NjE2MnxVbzA0aFF0aGo0TVphamFGcGRaaUN1c1NYUmoydGlkLllyWmh3V2hYVUdIcVlvbjdkalVVWGxTSlgxdVRUbjViSUVjdEhPd1NtMHBVSlRaNTBadXNXdzVzU3BKdWpMaV9BWnhyQ0c3ZGVKeDZ0M0JtNXZaS19JemF0Z2JEMmwuQ3RpYXRHRWR0MmxTSGxPdGUxV0RQcXFGaVQ4b0JYdEdfdndDT1NFS2EudnMt"
    
    # 新版个人云
    client = Yun139(auth, CloudType.PERSONAL_NEW)
    
    # 刷新令牌
    client.refresh_token()
    
    # 列出根目录文件
    # files = client.list_files("/")
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
    # client.upload("/", "/path/to/local/file.txt", progress)
    # client.upload("/", "F:\\XunLeiDownLoad\\media\\[ANi] 蘑菇魔女 - 10 [1080P][Baha][WEB-DL][AAC AVC][CHT].mp4", lambda u, t: print(f"{u*100//t}%"))
