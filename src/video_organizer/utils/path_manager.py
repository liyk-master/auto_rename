"""
文件路径管理工具类
负责处理文件路径的编码/解码、映射和一致性管理
"""

import os
import json
import logging
from pathlib import Path
from urllib.parse import unquote, quote
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class PathManager:
    """
    文件路径管理类，负责：
    1. 统一处理URL编码/解码
    2. 管理路径映射关系
    3. 提供一致的文件定位和删除接口
    4. 持久化路径映射信息
    """
    
    def __init__(self, mappings: Dict[str, str] = None, mappings_file: str = None):
        """
        初始化路径管理器
        
        Args:
            mappings: 路径映射字典 {downloader_path: local_path}
            mappings_file: 映射关系持久化文件路径
        """
        self.path_mappings = mappings or {}
        self.mappings_file = mappings_file
        self.encoded_decoded_map: Dict[str, str] = {}  # 编码路径 -> 解码路径映射
        self.decoded_encoded_map: Dict[str, str] = {}  # 解码路径 -> 编码路径映射
        
        # 加载持久化的映射关系
        self._load_mappings()
    
    def decode_path(self, file_path: str) -> str:
        """
        解码URL编码的文件路径
        
        Args:
            file_path: URL编码的文件路径
            
        Returns:
            解码后的文件路径
        """
        if not file_path:
            return file_path
            
        try:
            decoded_path = unquote(file_path)
            
            # 保存映射关系
            if decoded_path != file_path:
                self.encoded_decoded_map[file_path] = decoded_path
                self.decoded_encoded_map[decoded_path] = file_path
                self._save_mappings()
                logger.debug(f"路径解码: {file_path} -> {decoded_path}")
            
            return decoded_path
        except Exception as e:
            logger.warning(f"路径解码失败 {file_path}: {e}")
            return file_path
    
    def encode_path(self, file_path: str) -> str:
        """
        编码文件路径为URL格式
        
        Args:
            file_path: 原始文件路径
            
        Returns:
            URL编码的文件路径
        """
        if not file_path:
            return file_path
            
        try:
            # 检查是否已有映射
            if file_path in self.decoded_encoded_map:
                return self.decoded_encoded_map[file_path]
                
            encoded_path = quote(file_path)
            logger.debug(f"路径编码: {file_path} -> {encoded_path}")
            return encoded_path
        except Exception as e:
            logger.warning(f"路径编码失败 {file_path}: {e}")
            return file_path
    
    def apply_path_mapping(self, file_path: str) -> str:
        """
        应用路径映射（下载器路径 -> 本地路径）
        
        Args:
            file_path: 下载器返回的文件路径
            
        Returns:
            映射后的本地文件路径
        """
        if not file_path or not self.path_mappings:
            return file_path
        
        # 规范化路径
        file_path = file_path.replace('\\', '/')
        
        for downloader_path, local_path in self.path_mappings.items():
            downloader_path = downloader_path.replace('\\', '/')
            local_path = local_path.replace('\\', '/')
            
            if file_path.startswith(downloader_path):
                # 替换为本地路径
                rel_path = file_path[len(downloader_path):].lstrip('/')
                new_path = f"{local_path.rstrip('/')}/{rel_path}"
                # 转换为系统路径格式
                new_path = new_path.replace('/', os.path.sep)
                logger.debug(f"路径映射应用: {file_path} -> {new_path}")
                return new_path
        
        return file_path
    
    def reverse_path_mapping(self, file_path: str) -> str:
        """
        反向应用路径映射（本地路径 -> 下载器路径）
        
        Args:
            file_path: 本地文件路径
            
        Returns:
            映射后的下载器文件路径
        """
        if not file_path or not self.path_mappings:
            return file_path
        
        # 规范化路径
        file_path = file_path.replace('\\', '/')
        
        for downloader_path, local_path in self.path_mappings.items():
            downloader_path = downloader_path.replace('\\', '/')
            local_path = local_path.replace('\\', '/')
            
            if file_path.startswith(local_path):
                # 替换为下载器路径
                rel_path = file_path[len(local_path):].lstrip('/')
                new_path = f"{downloader_path.rstrip('/')}/{rel_path}"
                logger.debug(f"路径反向映射: {file_path} -> {new_path}")
                return new_path
        
        return file_path
    
    def find_file(self, file_path: str, max_retries: int = 3) -> Optional[str]:
        """
        查找文件，支持多种策略
        
        Args:
            file_path: 要查找的文件路径
            max_retries: 最大重试次数
            
        Returns:
            找到的文件实际路径，找不到返回None
        """
        # 策略1: 直接使用提供的路径
        if os.path.exists(file_path):
            return file_path
        
        # 策略2: 尝试使用编码/解码的路径
        if file_path in self.decoded_encoded_map:
            encoded_path = self.decoded_encoded_map[file_path]
            if os.path.exists(encoded_path):
                logger.debug(f"通过编码路径找到文件: {encoded_path}")
                return encoded_path
        
        if file_path in self.encoded_decoded_map:
            decoded_path = self.encoded_decoded_map[file_path]
            if os.path.exists(decoded_path):
                logger.debug(f"通过解码路径找到文件: {decoded_path}")
                return decoded_path
        
        # 策略3: 尝试不同的路径格式（Windows/Linux风格）
        alt_path = file_path.replace('/', os.path.sep) if '/' in file_path else file_path.replace(os.path.sep, '/')
        if os.path.exists(alt_path):
            logger.debug(f"通过替代路径格式找到文件: {alt_path}")
            return alt_path
        
        # 策略4: 仅使用文件名查找
        file_name = os.path.basename(file_path)
        dir_path = os.path.dirname(file_path)
        
        if dir_path and os.path.exists(dir_path):
            for root, dirs, files in os.walk(dir_path):
                if file_name in files:
                    found_path = os.path.join(root, file_name)
                    logger.debug(f"通过文件名找到文件: {found_path}")
                    return found_path
                
                # 尝试匹配编码/解码的文件名
                for f in files:
                    if unquote(f) == file_name or quote(f) == file_name:
                        found_path = os.path.join(root, f)
                        logger.debug(f"通过编码/解码文件名找到文件: {found_path}")
                        return found_path
        
        logger.warning(f"无法找到文件: {file_path}")
        return None
    
    def delete_file(self, file_path: str, max_retries: int = 3) -> bool:
        """
        删除文件，支持多种删除策略
        
        Args:
            file_path: 要删除的文件路径
            max_retries: 最大重试次数
            
        Returns:
            删除成功返回True，否则返回False
        """
        for attempt in range(max_retries):
            try:
                # 尝试直接删除
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"成功删除文件: {file_path}")
                    return True
                
                # 尝试查找文件的实际路径
                actual_path = self.find_file(file_path)
                if actual_path and os.path.exists(actual_path):
                    os.remove(actual_path)
                    logger.info(f"通过查找实际路径成功删除文件: {actual_path}")
                    return True
                
                # 尝试删除编码/解码版本的文件
                if file_path in self.decoded_encoded_map:
                    encoded_path = self.decoded_encoded_map[file_path]
                    if os.path.exists(encoded_path):
                        os.remove(encoded_path)
                        logger.info(f"通过编码路径成功删除文件: {encoded_path}")
                        return True
                
                if file_path in self.encoded_decoded_map:
                    decoded_path = self.encoded_decoded_map[file_path]
                    if os.path.exists(decoded_path):
                        os.remove(decoded_path)
                        logger.info(f"通过解码路径成功删除文件: {decoded_path}")
                        return True
                        
                logger.debug(f"删除尝试 {attempt+1}/{max_retries} 失败: 文件不存在 {file_path}")
                
            except Exception as e:
                logger.warning(f"删除尝试 {attempt+1}/{max_retries} 失败: {e}")
                
                if attempt == max_retries - 1:
                    logger.error(f"所有删除尝试均失败: {e}")
                
        return False
    
    def _save_mappings(self):
        """
        持久化保存路径映射关系
        """
        if not self.mappings_file:
            return
            
        try:
            mappings_data = {
                'encoded_decoded_map': self.encoded_decoded_map,
                'decoded_encoded_map': self.decoded_encoded_map
            }
            
            with open(self.mappings_file, 'w', encoding='utf-8') as f:
                json.dump(mappings_data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"保存路径映射失败: {e}")
    
    def _load_mappings(self):
        """
        加载持久化的路径映射关系
        """
        if not self.mappings_file or not os.path.exists(self.mappings_file):
            return
            
        try:
            with open(self.mappings_file, 'r', encoding='utf-8') as f:
                mappings_data = json.load(f)
                
            self.encoded_decoded_map = mappings_data.get('encoded_decoded_map', {})
            self.decoded_encoded_map = mappings_data.get('decoded_encoded_map', {})
            
            logger.info(f"已加载 {len(self.encoded_decoded_map)} 条路径映射记录")
            
        except Exception as e:
            logger.error(f"加载路径映射失败: {e}")
    
    def get_consistent_path(self, file_path: str) -> str:
        """
        获取系统内部使用的一致路径格式（解码后的路径）
        
        Args:
            file_path: 原始文件路径
            
        Returns:
            一致格式的文件路径
        """
        # 先解码
        decoded = self.decode_path(file_path)
        # 应用路径映射
        mapped = self.apply_path_mapping(decoded)
        # 规范化路径
        return str(Path(mapped).resolve())
    
    def get_downloader_path(self, file_path: str) -> str:
        """
        获取下载器使用的路径格式（编码后的路径 + 反向映射）
        
        Args:
            file_path: 本地文件路径
            
        Returns:
            下载器使用的文件路径
        """
        # 反向映射路径
        reversed_path = self.reverse_path_mapping(file_path)
        # 编码路径
        encoded = self.encode_path(reversed_path)
        return encoded