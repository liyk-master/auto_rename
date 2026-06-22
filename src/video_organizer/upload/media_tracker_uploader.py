"""
Media Tracker 上传器
用于在 139 云盘上传完成后，将文件信息推送到 Media Tracker
"""

import logging
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class MediaTrackerUploader:
    """Media Tracker 上传器"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 Media Tracker 上传器

        Args:
            config: media_tracker 配置字典
        """
        self.enabled = config.get("upload_enabled", False)
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 8082)
        self.cloud = config.get("upload_cloud", "cloud-1")
        self.token = config.get("token", "")
        self.timeout = 30

        # 自动构建 API URL
        self.api_url = f"http://{self.host}:{self.port}/api/upload"

        if self.enabled and not self.token:
            logger.warning("Media Tracker 上传已启用，但未配置 token")
            self.enabled = False

    def upload(
        self,
        sha256: str,
        size: int,
        name: str,
        cloud: Optional[str] = None,
    ) -> bool:
        """
        上传文件信息到 Media Tracker

        Args:
            sha256: 文件 SHA256 哈希值（64字符）
            size: 文件大小（字节）
            name: 文件名
            cloud: 云盘标识，默认使用配置中的值

        Returns:
            是否上传成功
        """
        if not self.enabled:
            logger.debug("Media Tracker 上传未启用，跳过")
            return False

        if not sha256 or len(sha256) != 64:
            logger.warning("SHA256 哈希值无效: %s", sha256)
            return False

        if not name:
            logger.warning("文件名为空，无法上传到 Media Tracker")
            return False

        cloud_id = cloud or self.cloud

        try:
            payload = {
                "sha256": sha256,
                "size": size,
                "name": name,
                "cloud": cloud_id,
            }

            headers = {
                "Content-Type": "application/json",
            }

            # 如果配置了 token，使用 X-API-Key 请求头
            if self.token:
                headers["X-API-Key"] = self.token

            logger.info(
                "上传文件信息到 Media Tracker: %s (SHA256: %s, 大小: %d bytes, 云盘: %s)",
                name, sha256[:16] + "...", size, cloud_id
            )

            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )

            response.raise_for_status()
            result = response.json()

            # 检查响应
            if result.get("code") == 0 or result.get("success"):
                data = result.get("data", {})
                batch_id = data.get("batch_id", "")
                total = data.get("total", 0)
                logger.info(
                    "✓ Media Tracker 上传成功: %s (batch_id: %s, total: %d)",
                    name, batch_id, total
                )
                return True
            else:
                error_msg = result.get("message", "未知错误")
                logger.warning("Media Tracker 上传失败: %s - %s", name, error_msg)
                return False

        except requests.exceptions.Timeout:
            logger.error("Media Tracker 上传超时: %s", name)
            return False
        except requests.exceptions.RequestException as e:
            logger.error("Media Tracker 上传请求失败: %s - %s", name, e)
            return False
        except Exception as e:
            logger.error("Media Tracker 上传异常: %s - %s", name, e, exc_info=True)
            return False
