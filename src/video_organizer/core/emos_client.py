"""
Emos 三方识别客户端
负责从 Emos API 获取视频文件识别信息
"""

import logging
from typing import Dict, Optional, Any
import requests
from urllib.parse import quote


class EmosClient:
    """Emos 三方识别客户端"""
    
    def __init__(
        self,
        api_url: str = "https://emos.prlo.de/api/recognize",
        timeout: int = 30,
        enabled: bool = True
    ):
        """
        初始化 Emos 客户端
        
        Args:
            api_url: Emos API 地址
            timeout: 请求超时时间（秒）
            enabled: 是否启用 Emos 识别
        """
        self.api_url = api_url
        self.timeout = timeout
        self.enabled = enabled
        self.logger = logging.getLogger(__name__)
    
    def recognize(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        识别视频文件
        
        Args:
            file_path: 视频文件路径（可以是相对路径或文件名）
            
        Returns:
            识别信息字典，失败返回 None
        """
        if not self.enabled:
            self.logger.debug("Emos 识别未启用")
            return None
        
        try:
            # URL 编码文件路径
            encoded_path = quote(file_path, safe='')
            url = f"{self.api_url}?path={encoded_path}"
            
            self.logger.debug(f"请求 Emos API: {url}")
            
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            self.logger.debug(f"Emos 识别成功: {data.get('meta_info', {}).get('name')}")
            
            return data
            
        except requests.exceptions.Timeout:
            self.logger.warning(f"Emos API 请求超时: {file_path}")
            return None
        except requests.exceptions.RequestException as e:
            self.logger.warning(f"Emos API 请求失败: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Emos 识别发生错误: {e}")
            return None
    
    def parse_media_info(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析 Emos API 返回的媒体信息
        
        Args:
            response_data: Emos API 返回的完整数据
            
        Returns:
            标准化的媒体信息字典
        """
        if not response_data or 'meta_info' not in response_data:
            return {}
        
        meta = response_data['meta_info']
        
        # 提取媒体类型
        media_type = self._parse_media_type(meta.get('type'))
        
        # 提取季数和集数
        season = meta.get('begin_season')
        episode = meta.get('begin_episode')
        
        # 构建标准化的媒体信息
        media_info = {
            'title': meta.get('cn_name') or meta.get('name') or meta.get('org_string', ''),
            'original_title': meta.get('en_name'),
            'year': meta.get('year'),
            'season': int(season) if season else None,
            'episode': int(episode) if episode else None,
            'episode_title': meta.get('subtitle'),
            'type': media_type,
            'total_season': meta.get('total_season'),
            'total_episode': meta.get('total_episode'),
            'season_episode': meta.get('season_episode'),
            'episode_list': meta.get('episode_list', []),
            'original_filename': meta.get('title'),
            'resource_type': meta.get('resource_type'),
            'resource_pix': meta.get('resource_pix'),
            'resource_team': meta.get('resource_team'),
            'video_encode': meta.get('video_encode'),
            'audio_encode': meta.get('audio_encode'),
            'edition': meta.get('edition'),
            'web_source': meta.get('web_source'),
        }
        
        return media_info
    
    def _parse_media_type(self, type_str: Optional[str]) -> str:
        """
        解析媒体类型
        
        Args:
            type_str: Emos 返回的类型字符串
            
        Returns:
            标准化的媒体类型 (tv_show, movie, anime, unknown)
        """
        if not type_str:
            return 'unknown'
        
        type_str = type_str.lower()
        
        if '电视剧' in type_str or '剧集' in type_str or 'tv' in type_str:
            return 'tv_show'
        elif '电影' in type_str or 'movie' in type_str:
            return 'movie'
        else:
            return 'unknown'
    
    def is_confident(self, response_data: Dict[str, Any]) -> bool:
        """
        判断识别结果是否可信
        
        Args:
            response_data: Emos API 返回的数据
            
        Returns:
            是否可信
        """
        if not response_data or 'meta_info' not in response_data:
            return False
        
        meta = response_data['meta_info']
        
        # 检查是否有基本的识别信息
        if not meta.get('name') and not meta.get('cn_name'):
            return False
        
        return True