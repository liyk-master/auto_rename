"""
Module for extracting metadata from video files and generating new names.
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

from jinja2 import Template
from src.video_organizer.core.tmdb_client import TMDBClient

logger = logging.getLogger(__name__)


class VideoRenamer:
    """Extracts metadata from video files and generates organized paths."""
    
    # 默认命名规则模板
    DEFAULT_NAMING_RULES = {
        "tv_show": "{show_name}{year_suffix}{tmdbid_suffix}/Season {season:02d}/{show_name} {season_episode}{quality_tags_suffix}",
        "movie": "{movie_name}{year_suffix}{tmdbid_suffix}/{movie_name}{en_title_suffix}{year_suffix}{quality_tags_suffix}",
        "anime": "{anime_name}/{season_name}/{anime_name} - S{season:02d}E{episode:02d}{quality_tags_suffix}",
        "simple": "{title}{quality_tags_suffix}"
    }
    
    def __init__(self, tmdb_api_key: str, ai_service_url: Optional[str] = None, watch_path: Optional[Path] = None, naming_rules: Optional[Dict] = None):
        self.tmdb_client = TMDBClient(tmdb_api_key)
        self.ai_service_url = ai_service_url
        self.watch_path = watch_path
        # 使用提供的命名规则或默认规则
        self.naming_rules = naming_rules if naming_rules else self.DEFAULT_NAMING_RULES
        
    def extract_metadata(self, file_path: Union[str, Path], media_type_hint: Optional[str] = None) -> Dict:
        """
        从视频文件路径中提取元数据。
        
        Args:
            file_path (Union[str, Path]): 文件路径
            media_type_hint (str, optional): 媒体类型提示（tv, movie等）
            
        Returns:
            Dict: 提取的元数据
        """
        # 确保返回的是字典类型，即使发生异常
        try:
            # 转换file_path为Path对象，如果它是字符串的话
            if isinstance(file_path, str):
                file_path = Path(file_path)
            
            # 验证file_path参数
            if not hasattr(file_path, 'name'):
                logger.error(f"无效的file_path参数: {file_path}")
                return {}
            
            # First try to extract using regex patterns
            metadata = self._extract_with_regex(file_path.name)
            
            # 如果提供了媒体类型提示，添加到元数据中
            if media_type_hint:
                metadata['media_type'] = media_type_hint
            
            # 如果没有show_name就使用文件名或目录名
            if not metadata.get('show_name'):
                try:
                    if self.watch_path:
                        relative_path = file_path.relative_to(self.watch_path)
                        # 使用相对路径的第一级目录名称作为视频名称
                        if len(relative_path.parts) > 1:
                            metadata['show_name'] = relative_path.parts[0]  # 第一级目录名称
                        else:
                            metadata['show_name'] = file_path.stem  # 如果文件直接在watch_path下，使用文件名
                    else:
                        metadata['show_name'] = file_path.stem  # 如果没有watch_path，直接使用文件名
                except Exception as e:
                    logger.error(f"获取show_name失败: {e}")
                    # 退回到使用完整文件名
                    metadata['show_name'] = file_path.stem
            
            # If regex fails or results are incomplete, try AI service
            if (self.ai_service_url and 
                (not metadata.get('show_name') or not metadata.get('season') or not metadata.get('episode'))):
                try:
                    # 获取相对于watch_path的路径作为视频名称
                    if self.watch_path:
                        try:
                            # 计算相对路径
                            relative_path = file_path.relative_to(self.watch_path)
                            # 使用相对路径的第一级目录名称作为视频名称
                            video_name = relative_path.parts[0] if len(relative_path.parts) > 1 else file_path.stem
                            logger.info(f"Using directory name as video name: {video_name}")
                            metadata = self._extract_with_ai(video_name, metadata)
                        except ValueError:
                            # 如果文件不在watch_path下，使用文件名
                            logger.warning(f"File {file_path} is not under watch_path {self.watch_path}, using filename")
                            metadata = self._extract_with_ai(file_path.name, metadata)
                    else:
                        metadata = self._extract_with_ai(file_path.name, metadata)
                except Exception as e:
                    logger.error(f"AI服务提取元数据失败: {e}")
                    # AI服务失败不影响后续流程，继续使用已有的元数据
            
            # 从tmdb中获取视频信息生成刮削元数据
            if metadata.get('show_name'):
                try:
                    metadata = self._enrich_with_tmdb(metadata)
                    # 如果没有季号就使用1
                    if not metadata.get('season'):
                        metadata['season'] = 1
                except Exception as e:
                    logger.error(f"TMDB元数据丰富失败: {e}")
                    # TMDB失败不影响后续流程，确保必要字段存在
                    metadata.setdefault('season', 1)
            
            # 确保返回的metadata包含必要字段
            metadata.setdefault('show_name', file_path.stem)
            metadata.setdefault('original_filename', file_path.name)
            metadata.setdefault('quality_tags', '')
            metadata.setdefault('year', '')
            metadata.setdefault('tmdb_id', '')
            metadata.setdefault('season', 1)
            
            return metadata
        except Exception as e:
            logger.error(f"提取元数据时发生未处理的异常: {e}")
            # 发生严重异常时，返回基础元数据
            return {
                'show_name': getattr(file_path, 'stem', 'Unknown'),
                'original_filename': getattr(file_path, 'name', 'unknown'),
                'quality_tags': '',
                'year': '',
                'tmdb_id': '',
                'season': 1,
                'error': str(e)
            }
    
    def _extract_keywords(self, filename: str) -> str:
        """从文件名中提取关键词，如质量、来源等"""
        # 常见的质量标记和标签
        quality_markers = [
            r'(?:\b(?:HD|FHD|UHD|4K|1080p|720p|480p|360p|240p)\b)',
            r'(?:\b(?:HDR|SDR|HDR10|Dolby\s*Vision)\b)',
            r'(?:\b(?:x264|x265|h264|h265|HEVC|AVC|MPEG4)\b)',
            r'(?:\b(?:AAC|DTS|DDP|TrueHD|Atmos)\b)',
            r'(?:\b(?:BD|BDRip|BluRay|DVD|DVDRip|WEB|WEBRip|WEB-DL)\b)',
            r'(?:\b(?:REPACK|PROPER|INTERNAL)\b)',
            r'(?:\b(?:CHS|ENG|双语|字幕|中字|英字)\b)',
            r'(?:\b(?:AC3|DTS-HD)\b)',
            r'(?:\b(?:Netflix|Disney\+|HBO|Amazon|Prime|Apple\+|iTunes)\b)'  # 流媒体平台
        ]
        
        extracted_keywords = []
        
        # 提取所有匹配的关键词
        extracted_keywords = []
        
        # 从原始文件名中提取关键词，保留原始顺序
        original_filename = filename
        
        # 定义要提取的关键词模式，使用非单词边界匹配，支持点号分隔
        # 优化顺序，先匹配长模式，避免短模式被重复匹配
        keyword_patterns = [
            r'(?:[^\w]|^)(2160p|4K|UHD|FHD|1080p|720p|480p|360p|240p)(?:[^\w]|$)',
            r'(?:[^\w]|^)(Dolby\s*Vision|HDR10|HDR|SDR)(?:[^\w]|$)',
            r'(?:[^\w]|^)(Netflix|Disney\+|HBO|Amazon|Prime|Apple\+|iTunes)(?:[^\w]|$)',
            r'(?:[^\w]|^)(BDRip|BluRay|DVDRip|WEB-DL|WEBRip|WEB|BD|DVD)(?:[^\w]|$)',
            r'(?:[^\w]|^)(x265|x264|h265|h264|HEVC|AVC|MPEG4)(?:[^\w]|$)',
            r'(?:[^\w]|^)(DTS-HD|TrueHD|Atmos|DDP|DTS|AAC|AC3)(?:[^\w]|$)',
            r'(?:[^\w]|^)(REPACK|PROPER|INTERNAL)(?:[^\w]|$)',
            r'(?:[^\w]|^)(CHS|ENG|双语|字幕|中字|英字)(?:[^\w]|$)'
        ]
        
        # 提取所有匹配的关键词
        all_matches = []
        for pattern in keyword_patterns:
            matches = re.finditer(pattern, original_filename, re.IGNORECASE)
            for match in matches:
                all_matches.append((match.start(), match.group(1)))
        
        # 按在文件名中出现的顺序排序
        all_matches.sort(key=lambda x: x[0])
        
        # 去重，保留第一次出现的关键词
        seen = set()
        unique_keywords = []
        for _, keyword in all_matches:
            if keyword.lower() not in seen:
                seen.add(keyword.lower())
                unique_keywords.append(keyword)
        
        # 用点连接关键词
        return '.'.join(unique_keywords)
    
    def _extract_with_regex(self, filename: str) -> Dict:
        """Extract metadata using regular expressions."""
        metadata = {}
        
        # 提取文件基本信息
        base_name, ext = os.path.splitext(filename)
        metadata['extension'] = ext.lower()
        metadata['original_filename'] = filename
        
        # 提取关键词
        metadata['quality_tags'] = self._extract_keywords(base_name)
        
        # 提取tmdbid信息，支持 {tmdbid=xxx} 和 {tmdbid-xxx} 格式
        tmdbid_pattern = r'\{tmdbid[=-](\d+)\}'
        tmdbid_match = re.search(tmdbid_pattern, base_name, re.IGNORECASE)
        if tmdbid_match:
            metadata['tmdb_id'] = tmdbid_match.group(1)
            logger.debug(f"从文件名中提取到tmdbid: {metadata['tmdb_id']}")
        
        # 提取年份信息（支持多种格式：(2022)、2022、.2022.、[2022]、.2022.S02E01等）
        # 先尝试从括号中提取 (2022) 或 [2022]
        year_patterns = [
            r'\((\d{4})(?:-\d{4})?\)',  # 格式：(2022)
            r'\[(\d{4})(?:-\d{4})?\]',  # 格式：[2022]
            r'\.(\d{4})(?:-\d{4})?\.',  # 格式：.2022.
            r'\.(\d{4})(?:-\d{4})?\s',  # 格式：.2022 
            r'\.(\d{4})(?:-\d{4})?\w',  # 格式：.2022.S02E01
            r'\s(\d{4})(?:-\d{4})?\s',  # 格式： 2022 
            r'\s(\d{4})(?:-\d{4})?\w',  # 格式： 2022S02E01
            r'^(\d{4})(?:-\d{4})?\.',    # 格式：2022.
            r'^(\d{4})(?:-\d{4})?\w',    # 格式：2022S02E01
            r'\.(\d{4})(?:-\d{4})?$'     # 格式：.2022
        ]
        
        year_match = None
        for pattern in year_patterns:
            year_match = re.search(pattern, base_name)
            if year_match:
                break
        
        if year_match:
            metadata['year'] = year_match.group(1)
            logger.debug(f"从文件名中提取到年份: {metadata['year']}")
        
        # 清理文件名，移除常见的修饰词和标记，用于搜索
        cleaned_name = self._clean_filename_for_search(base_name)
        metadata['cleaned_name'] = cleaned_name
        
        # Common patterns for TV shows
        patterns = [
            # Pattern: Show Name S01E01, Show.Name.S01E01, ShowNameS01E01
            r"^(?P<show_name>.*?)[. ]?S(?P<season>\d+)E(?P<episode>\d+)",
            # Pattern: 中文名 S01E01 - 剧集标题 (排除末尾的 (1) 等后缀)
            r"^(?P<show_name>[\w\s\u4e00-\u9fff]+?)\s*S(?P<season>\d+)E(?P<episode>\d+)\s*-\s*(?P<episode_name>.+?)(?:\s*\(\d+\))?(?=\s*\.|$)",
            # Pattern: 中文名 S01E01
            r"^(?P<show_name>[\w\s\u4e00-\u9fff]+?)\s*S(?P<season>\d+)E(?P<episode>\d+)",
            # Pattern: 中文名 Season 1 Episode 2 - Episode Title (排除末尾的 (1) 等后缀)
            r"^(?P<show_name>[\w\s\u4e00-\u9fff]+)\s+Season\s+(?P<season>\d+)\s+Episode\s+(?P<episode>\d+)\s*-\s*(?P<episode_name>.+?)(?:\s*\(\d+\))?(?=\s*\.|$)",
            # Pattern: 中文名 Season 1 Episode 2
            r"^(?P<show_name>[\w\s\u4e00-\u9fff]+)\s+Season\s+(?P<season>\d+)\s+Episode\s+(?P<episode>\d+)",
            # Pattern: 中文名 - 第1季第2集 - 剧集标题 (排除末尾的 (1) 等后缀)
            r"^(?P<show_name>[\w\s\u4e00-\u9fff]+)\s*-\s*第(?P<season>\d+)季第(?P<episode>\d+)集\s*-\s*(?P<episode_name>.+?)(?:\s*\(\d+\))?(?=\s*\.|$)",
            # Pattern: 中文名 - 第1季第2集
            r"^(?P<show_name>[\w\s\u4e00-\u9fff]+)\s*-\s*第(?P<season>\d+)季第(?P<episode>\d+)集",
            # Pattern: 中文名 第1集 - 剧集标题 (排除末尾的 (1) 等后缀)
            r"^(?P<show_name>[\w\s\u4e00-\u9fff]+)\s*第(?P<episode>\d+)集\s*-\s*(?P<episode_name>.+?)(?:\s*\(\d+\))?(?=\s*\.|$)",
            # Pattern: 中文名 第1集
            r"^(?P<show_name>[\w\s\u4e00-\u9fff]+)\s*第(?P<episode>\d+)集",
            # Pattern: S01E01.ext (simple format without show name)
            r"^S(?P<season>\d+)E(?P<episode>\d+)",
            r"^E(?P<episode>\d+)",
            r"^(?P<episode>\d+)",
            # Pattern: Show.Name.S01E02.quality-group.ext
            r"(?P<show_name>[\w\.]+)\.S(?P<season>\d+)E(?P<episode>\d+)",
            # Pattern: Show Name - s01e02 - Episode Title.ext (排除末尾的 (1) 等后缀)
            r"(?P<show_name>[\w\s]+)\s*-\s*s(?P<season>\d+)e(?P<episode>\d+)\s*-\s*(?P<episode_name>.+?)(?:\s*\(\d+\))?(?=\s*\.|$)",
            # Pattern: Show Name Season 1 Episode 2.ext
            r"(?P<show_name>[\w\s]+)\s+Season\s+(?P<season>\d+)\s+Episode\s+(?P<episode>\d+)",
            # Pattern: Show Name - Season 1 - Episode 2.ext
            r"(?P<show_name>[\w\s]+)\s*-\s*Season\s+(?P<season>\d+)\s*-\s*Episode\s+(?P<episode>\d+)",
            # Pattern: Show Name - S01E02 - Episode Title.ext (排除末尾的 (1) 等后缀)
            r"(?P<show_name>[\w\s]+)\s*-\s*S(?P<season>\d+)E(?P<episode>\d+)\s*-\s*(?P<episode_name>.+?)(?:\s*\(\d+\))?(?=\s*\.|$)"
        ]
        
        # 优先使用中文模式匹配，直接从原始文件名中提取
        match_found = False
        for pattern in patterns:
            match = re.search(pattern, base_name, re.IGNORECASE)
            if match:
                metadata.update(match.groupdict())
                # Clean up show name
                if 'show_name' in metadata:
                    # 移除show_name中的年份信息
                    show_name = metadata['show_name']
                    # 移除括号内的年份 (2022) - 无论位置如何
                    show_name = re.sub(r'\s*\(\d{4}(?:-\d{4})?\)\s*', ' ', show_name)
                    # 移除末尾的空格和点
                    show_name = show_name.strip().rstrip('.')
                    # 移除多余的空格
                    show_name = re.sub(r'\s+', ' ', show_name)
                    
                    # 特别处理中文名称，不进行title()转换
                    if re.search(r'[\u4e00-\u9fff]', show_name):
                        metadata['show_name'] = show_name.replace('.', ' ').strip()
                    else:
                        metadata['show_name'] = show_name.replace('.', ' ').title().strip()
                match_found = True
                break
        
        # 如果直接从原始文件名中没有匹配到，再尝试从清理后的文件名中匹配
        if not match_found:
            for pattern in patterns:
                match = re.search(pattern, cleaned_name, re.IGNORECASE)
                if match:
                    metadata.update(match.groupdict())
                    # Clean up show name
                    if 'show_name' in metadata:
                        # 移除show_name中的年份信息
                        show_name = metadata['show_name']
                        # 移除括号内的年份 (2022) - 无论位置如何
                        show_name = re.sub(r'\s*\(\d{4}(?:-\d{4})?\)\s*', ' ', show_name)
                        # 移除末尾的空格和点
                        show_name = show_name.strip().rstrip('.')
                        # 移除多余的空格
                        show_name = re.sub(r'\s+', ' ', show_name)
                        
                        # 特别处理中文名称，不进行title()转换
                        if re.search(r'[\u4e00-\u9fff]', show_name):
                            metadata['show_name'] = show_name.replace('.', ' ').strip()
                        else:
                            metadata['show_name'] = show_name.replace('.', ' ').title().strip()
                    break
                
        # 如果没有匹配到show_name但有cleaned_name，尝试提取show_name
        if not metadata.get('show_name') and cleaned_name:
            # 从清理后的名称中提取可能的剧集信息，然后获取show_name
            season_episode_pattern = r'(S\d+E\d+|第\d+季第\d+集|第\d+集)'
            match = re.search(season_episode_pattern, cleaned_name, re.IGNORECASE)
            if match:
                # 提取show_name为剧集信息前的部分
                show_name = cleaned_name[:match.start()].strip()
                if show_name:
                    metadata['show_name'] = show_name
        
        # 如果检测到剧集信息（season或episode），自动设置为电视剧类型
        if metadata.get('season') or metadata.get('episode'):
            metadata['media_type'] = 'tv'
        
        # 最终清理：确保show_name纯净，不包含年份、副标题等无关信息
        if 'show_name' in metadata:
            show_name = metadata['show_name']
            
            # 1. 移除括号内的年份和其他信息
            # 例如：(2022), [2023], (2021-2024) 等
            show_name = re.sub(r'\s*[\[\(]\d{4}(?:-\d{4})?[\]\)]\s*', ' ', show_name)
            
            # 2. 移除独立的年份数字
            show_name = re.sub(r'\s+\d{4}\s*$', '', show_name)
            
            # 3. 处理点号分隔的情况
            # 例如：瑞草洞.Law.and.the.City.2025 -> 瑞草洞
            # 中文+英文组合，只保留中文部分
            if '.' in show_name and re.search(r'[\u4e00-\u9fff]', show_name):
                parts = show_name.split('.')
                # 找到第一个包含中文的部分
                for part in parts:
                    if re.search(r'[\u4e00-\u9fff]', part):
                        show_name = part
                        break
            elif '.' in show_name:
                # 纯英文或数字，只保留第一个点号前的内容
                show_name = show_name.split('.')[0]
            
            # 4. 处理空格分隔的副标题
            # 例如：瑞草洞 Law and the City -> 瑞草洞
            if ' ' in show_name and re.search(r'[\u4e00-\u9fff]', show_name):
                parts = show_name.split(' ')
                # 找到第一个包含中文的部分
                for part in parts:
                    if re.search(r'[\u4e00-\u9fff]', part):
                        show_name = part
                        break
            
            # 5. 移除常见的修饰词
            modifiers = [
                r'\s+特别版\s*$',
                r'\s+导演剪辑版\s*$',
                r'\s+加长版\s*$',
                r'\s+最终版\s*$'
            ]
            for modifier in modifiers:
                show_name = re.sub(modifier, '', show_name, flags=re.IGNORECASE)
            
            # 6. 移除多余的空格和特殊字符
            show_name = show_name.strip().rstrip('.')
            show_name = re.sub(r'\s+', ' ', show_name)
            # 移除非字母数字和中文的字符
            show_name = re.sub(r'[^\w\s\u4e00-\u9fff]', '', show_name)
            
            metadata['show_name'] = show_name
                        
        return metadata
    
    def _extract_with_ai(self, filename: str, existing_metadata: Dict) -> Dict:
        """
        Use AI service to extract metadata from filename.
        """
        logger.warning("AI extraction not implemented, using regex results only")

        
        return existing_metadata
    
    def _clean_filename_for_search(self, filename: str) -> str:
        """清理文件名，移除常见的修饰词和标记，为搜索做准备"""
        # 移除常见的质量标记和标签
        quality_markers = [
            r'(?:\b(?:HD|FHD|UHD|4K|1080p|720p|480p|360p|240p|2160p|2160)\b)',
            r'(?:\b(?:HDR|SDR|HDR10|Dolby\s*Vision)\b)',
            r'(?:\b(?:x264|x265|h264|h265|HEVC|AVC|MPEG4)\b)',
            r'(?:\b(?:AAC|DTS|DDP|TrueHD|Atmos)\b)',
            r'(?:\b(?:BD|BDRip|BluRay|DVD|DVDRip|WEB|WEBRip|WEB-DL)\b)',
            r'(?:\b(?:REPACK|PROPER|INTERNAL)\b)',
            r'(?:\b(?:CHS|ENG|双语|字幕|中字|英字)\b)',
            r'(?:\b(?:AC3|DTS-HD)\b)',
            r'(?:\b(?:MP4|MKV|AVI)\b)'
        ]
        
        cleaned = filename
        
        # 移除质量标记
        for marker in quality_markers:
            cleaned = re.sub(marker, '', cleaned, flags=re.IGNORECASE)
        
        # 移除方括号及内容
        cleaned = re.sub(r'\[[^\]]+\]', '', cleaned)
        
        # 保留年份信息，只移除非年份的圆括号内容
        # 年份格式：(YYYY) 或 (YYYY-YYYY)
        cleaned = re.sub(r'\((?!\d{4}(?:-\d{4})?\))[^\)]+\)', '', cleaned)
        
        # 移除大括号及内容（如 {tmdbid-xxx}）
        cleaned = re.sub(r'\{[^\}]+\}', '', cleaned)
        
        # 移除多余的空格和特殊字符
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = re.sub(r'[^\w\s\u4e00-\u9fff\-]', '', cleaned)
        cleaned = cleaned.strip()
        
        return cleaned
        
    def _prepare_search_term(self, search_term: str) -> str:
        """准备搜索词，为TMDB搜索优化"""
        # 移除多余空格
        prepared = re.sub(r'\s+', ' ', search_term).strip()
        
        # 对于中文，保留原始格式
        if re.search(r'[\u4e00-\u9fff]', prepared):
            # 对于中文名称，移除可能的季集信息
            prepared = re.sub(r'S\d+E\d+', '', prepared, flags=re.IGNORECASE)
            prepared = re.sub(r'第\d+季(第\d+集)?', '', prepared, flags=re.IGNORECASE)
            prepared = re.sub(r'\d+集', '', prepared)
            prepared = prepared.strip()
        else:
            # 对于英文，确保空格分离
            prepared = prepared.title()
            
        return prepared
        
    def _translate_to_english(self, text: str) -> str:
        """
        将中文文本翻译为英文
        
        Args:
            text (str): 要翻译的中文文本
            
        Returns:
            str: 翻译后的英文文本
        """
        # 这里可以集成实际的翻译API，比如百度翻译、Google翻译等
        # 为了简化，先使用一个简单的模拟翻译字典
        # 实际使用时，应该替换为真实的翻译服务
        translation_dict = {
            "怪奇物语": "Stranger Things",
            "权力的游戏": "Game of Thrones",
            "鱿鱼游戏": "Squid Game",
            "流浪地球": "The Wandering Earth",
            "山海情": "Minning Town",
            "奔跑吧兄弟": "Running Man",
            "小猪佩奇": "Peppa Pig",
            "海贼王": "One Piece",
            "斗罗大陆": "Soul Land",
            "舌尖上的中国": "A Bite of China",
            "星期三": "Wednesday"
        }
        
        # 尝试直接翻译
        if text in translation_dict:
            translated = translation_dict[text]
            logger.info(f"使用翻译字典将 '{text}' 翻译为 '{translated}'")
            return translated
        
        # 尝试拆分翻译
        words = text.split()
        translated_words = []
        for word in words:
            translated_words.append(translation_dict.get(word, word))
        
        translated = " ".join(translated_words)
        logger.info(f"使用拆分翻译将 '{text}' 翻译为 '{translated}'")
        return translated
    
    def _search_with_language(self, search_term: str, media_type_hint: str, year: str, language: str) -> List[Dict]:
        """
        基于语言的搜索辅助方法
        
        Args:
            search_term (str): 搜索词
            media_type_hint (str): 媒体类型提示
            year (str): 年份
            language (str): 搜索语言
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        results = []
        try:
            # 如果搜索语言是英文，且搜索词包含中文，先翻译为英文
            final_search_term = search_term
            if language == 'en-US' and re.search(r'[\u4e00-\u9fff]', search_term):
                final_search_term = self._translate_to_english(search_term)
                logger.info(f"将中文搜索词 '{search_term}' 翻译为英文 '{final_search_term}' 进行搜索")
            
            if media_type_hint == 'tv':
                # 使用专门的电视剧搜索
                search_results = self.tmdb_client.search_tv(
                    final_search_term, 
                    int(year) if year and year.isdigit() else None,
                    language=language
                )
                if isinstance(search_results, dict) and 'results' in search_results:
                    results = search_results['results']
            elif media_type_hint == 'movie':
                # 使用专门的电影搜索
                search_results = self.tmdb_client.search_movie(
                    final_search_term, 
                    int(year) if year and year.isdigit() else None,
                    language=language
                )
                if isinstance(search_results, dict) and 'results' in search_results:
                    results = search_results['results']
        except Exception as e:
            logger.error(f"语言搜索失败: {e}")
        
        return results
        
    def _enrich_with_tmdb(self, metadata: Dict) -> Dict:
        """使用TMDB API丰富元数据信息，获取更完整的视频详情"""
        # 确保metadata是字典类型
        if not isinstance(metadata, dict):
            logger.error("元数据不是字典类型，直接返回")
            return {}
        
        try:
            logger.info(f"开始TMDB搜索: metadata={metadata}")
            # 保存原始的quality_tags，避免被覆盖
            original_quality_tags = metadata.get('quality_tags', '')
            
            # 优先使用show_name搜索，否则使用title，确保搜索词存在
            search_term = metadata.get('show_name', metadata.get('title', ''))
            if not search_term:
                logger.warning("搜索词为空，无法进行TMDB搜索")
                # 确保返回的metadata包含必要字段
                metadata.setdefault('quality_tags', original_quality_tags)
                metadata.setdefault('year', '')
                metadata.setdefault('tmdb_id', '')
                return metadata
            
            # 准备优化后的搜索词
            prepared_search_term = self._prepare_search_term(search_term)
            logger.info(f"搜索TMDB: 原始搜索词='{search_term}', 优化后搜索词='{prepared_search_term}'")
            
            # 搜索匹配的视频信息
            # 首先尝试明确的类型搜索
            media_type_hint = metadata.get('media_type', metadata.get('type', ''))
            year = metadata.get('year')
            
            results = []
            
            # 智能搜索策略：
            # 1. 判断优化后的搜索词的语言（中文/英文）
            # 2. 根据语言自动选择搜索语言进行第一次搜索
            # 3. 如果没有完全匹配到，将搜索词翻译成另一种语言
            # 4. 用翻译后的搜索词进行第二次搜索
            # 5. 检查第二次搜索结果中是否有完全匹配的
            # 6. 如果有完全匹配就用，没有的话结合两次搜索的结果进行筛选
            # 7. 优先使用中文元数据
            
            all_results = []
            unique_ids = set()
            
            # 定义完全匹配检查函数
            def has_exact_match(search_results, target_term):
                if not search_results:
                    return False, None
                # 确保search_results是列表类型
                if isinstance(search_results, dict) and 'results' in search_results:
                    search_results = search_results['results']
                if not isinstance(search_results, list):
                    return False, None
                    
                for result in search_results:
                    result_title = result.get('name', result.get('title', '')).lower()
                    if result_title == target_term.lower():
                        return True, result
                return False, None
            
            # 定义语言检测函数
            def is_chinese(text):
                """检测文本是否包含中文"""
                return bool(re.search(r'[\u4e00-\u9fff]', text))
            
            # 检测优化后搜索词的语言
            search_term_is_chinese = is_chinese(prepared_search_term)
            logger.info(f"检测到优化后的搜索词 '{prepared_search_term}' 包含中文: {search_term_is_chinese}")
            
            # 第一步：根据语言自动选择搜索语言进行第一次搜索
            first_search_language = 'zh-CN' if search_term_is_chinese else 'en-US'
            logger.info(f"第一步：使用优化后的搜索词 '{prepared_search_term}' 进行{first_search_language}搜索")
            
            # 策略1: 优化后的搜索词 + 明确类型 + 自动选择语言
            first_language_results = self._search_with_language(prepared_search_term, media_type_hint, year, first_search_language)
            
            # 策略2: 优化后的搜索词 + 通用搜索 + 自动选择语言
            general_first_language_results = self.tmdb_client.search_video_show(prepared_search_term, year, language=first_search_language)
            
            # 合并第一步搜索结果
            first_pass_results = []
            for results_list in [first_language_results, general_first_language_results]:
                if isinstance(results_list, list):
                    first_pass_results.extend(results_list)
                elif isinstance(results_list, dict) and 'results' in results_list:
                    first_pass_results.extend(results_list['results'])
            
            # 检查第一步搜索结果中是否有完全匹配
            exact_match_found, exact_match_result = has_exact_match(first_pass_results, prepared_search_term)
            if exact_match_found:
                logger.info(f"在第一步搜索结果中找到完全匹配: {exact_match_result.get('name', exact_match_result.get('title'))}")
                results = [exact_match_result]
            else:
                # 保存第一步搜索结果，继续第二次搜索
                logger.info(f"第一步搜索未找到完全匹配，保存搜索结果 ({len(first_pass_results)} 个)")
                # 保存第一步搜索结果到总结果中
                for result in first_pass_results:
                    if result.get('id') not in unique_ids:
                        all_results.append(result)
                        unique_ids.add(result.get('id'))
                
                # 第二步：将优化后的搜索词翻译成另一种语言进行搜索
                second_search_language = 'en-US' if search_term_is_chinese else 'zh-CN'
                logger.info(f"第二步：将优化后的搜索词 '{prepared_search_term}' 翻译成{second_search_language}进行搜索")
                
                # 翻译优化后的搜索词
                if search_term_is_chinese:
                    # 中文翻译成英文
                    translated_search_term = self._translate_to_english(prepared_search_term)
                    logger.info(f"将中文搜索词 '{prepared_search_term}' 翻译为英文 '{translated_search_term}' 进行搜索")
                else:
                    # 英文翻译成中文（暂时使用简单的翻译字典，实际应用中可以集成翻译API）
                    # 这里我们使用反向翻译字典
                    reverse_translation_dict = {
                        "Wednesday": "星期三",
                        "Stranger Things": "怪奇物语",
                        "Squid Game": "鱿鱼游戏",
                        "The Wandering Earth": "流浪地球",
                        "Minning Town": "山海情",
                        "Running Man": "奔跑吧兄弟",
                        "Peppa Pig": "小猪佩奇",
                        "One Piece": "海贼王",
                        "Soul Land": "斗罗大陆",
                        "A Bite of China": "舌尖上的中国"
                    }
                    translated_search_term = reverse_translation_dict.get(prepared_search_term, prepared_search_term)
                    logger.info(f"将英文搜索词 '{prepared_search_term}' 翻译为中文 '{translated_search_term}' 进行搜索")
                
                # 策略3: 翻译后的搜索词 + 明确类型 + 第二种语言
                second_language_results = self._search_with_language(translated_search_term, media_type_hint, year, second_search_language)
                
                # 策略4: 翻译后的搜索词 + 通用搜索 + 第二种语言
                general_second_language_results = self.tmdb_client.search_video_show(translated_search_term, year, language=second_search_language)
                
                # 合并第二次搜索结果
                second_pass_results = []
                for results_list in [second_language_results, general_second_language_results]:
                    if isinstance(results_list, list):
                        second_pass_results.extend(results_list)
                    elif isinstance(results_list, dict) and 'results' in results_list:
                        second_pass_results.extend(results_list['results'])
                
                # 检查第二次搜索结果中是否有与翻译后的搜索词完全匹配的
                exact_match_found, exact_match_result = has_exact_match(second_pass_results, translated_search_term)
                if exact_match_found:
                    logger.info(f"在{second_search_language}搜索结果中找到完全匹配: {exact_match_result.get('name', exact_match_result.get('title'))}")
                    results = [exact_match_result]
                else:
                    # 没有完全匹配，合并两次搜索结果
                    logger.info(f"{second_search_language}搜索未找到完全匹配，合并两次搜索结果")
                    
                    # 保存第二次搜索结果到总结果中
                    for result in second_pass_results:
                        if result.get('id') not in unique_ids:
                            all_results.append(result)
                            unique_ids.add(result.get('id'))
                    
                    results = all_results
            
            # 确保results是列表类型
            if not isinstance(results, list):
                results = []
            
            if not results:
                logger.warning(f"没有找到匹配 '{search_term}' 的结果")
                # 确保返回的metadata包含必要字段
                metadata.setdefault('quality_tags', original_quality_tags)
                metadata.setdefault('year', '')
                metadata.setdefault('tmdb_id', '')
                return metadata
            
            # 寻找最匹配的结果
            best_match = None
            
            # 1. 优先匹配年份和媒体类型
            for result in results:
                # 尝试匹配年份
                date_field = 'first_air_date' if result.get('media_type') == 'tv' else 'release_date'
                if date_field in result and result[date_field]:
                    result_year = result[date_field].split('-')[0]
                    if result_year == metadata.get('year'):
                        best_match = result
                        logger.info(f"找到年份匹配的结果: {result.get('name', result.get('title'))} ({result_year})")
                        break
            
            # 2. 无论是否有媒体类型提示，都使用标题相似度和流行度排序选择最佳结果
            if not best_match:
                # 优先考虑媒体类型匹配的结果
                if media_type_hint:
                    # 筛选出匹配媒体类型的结果
                    type_matched_results = [result for result in results if result.get('media_type') == media_type_hint]
                    if type_matched_results:
                        target_results = type_matched_results
                    else:
                        # 如果没有匹配媒体类型的结果，使用所有结果
                        target_results = results
                else:
                    # 没有媒体类型提示，使用所有结果
                    target_results = results
                
                # 计算标题相似度并按相似度和流行度排序
                def calculate_score(result):
                    title = result.get('name', result.get('title', '')).lower()
                    search_term_lower = search_term.lower()
                    # 完全匹配得分最高
                    if search_term_lower == title:
                        return 1000 + result.get('popularity', 0)
                    # 搜索词是标题的子集
                    elif search_term_lower in title:
                        return 500 + result.get('popularity', 0)
                    # 标题是搜索词的子集
                    elif title in search_term_lower:
                        return 300 + result.get('popularity', 0)
                    # 只按流行度排序
                    else:
                        return result.get('popularity', 0)
                
                # 按得分排序
                sorted_results = sorted(target_results, key=calculate_score, reverse=True)
                best_match = sorted_results[0]
                logger.info(f"找到最匹配的结果: {best_match.get('name', best_match.get('title'))}")
            
            # 3. 确保结果有效
            if not best_match:
                logger.warning(f"没有找到有效的匹配结果")
                # 确保返回的metadata包含必要字段
                metadata.setdefault('quality_tags', original_quality_tags)
                metadata.setdefault('year', '')
                metadata.setdefault('tmdb_id', '')
                return metadata
            
            # 获取详细信息
            media_type = best_match.get('media_type', 'tv')
            
            # 定义获取中文详细信息的辅助函数
            def is_chinese(text):
                """检测文本是否包含中文"""
                return bool(re.search(r'[\u4e00-\u9fff]', text))
            
            # 使用专门的API获取更详细的信息，优先使用中文
            if media_type == 'tv':
                # 先尝试获取中文详细信息
                details = self.tmdb_client.get_tv_details(best_match['id'], language='zh-CN')
                # 如果中文信息不完整，尝试获取英文信息
                if not details or not (details.get('name') or details.get('overview')):
                    details = self.tmdb_client.get_tv_details(best_match['id'], language='en-US')
                    logger.info("中文电视剧信息不完整，使用英文信息")
                if details:
                    # 保存原始标题
                    original_name = metadata.get('show_name')
                    metadata['original_show_name'] = original_name
                    # 丰富元数据，优先使用中文标题
                    # 如果获取到的是中文详情，使用中文标题；否则使用原始标题
                    if details.get('name') and is_chinese(details['name']):
                        metadata['show_name'] = details['name']
                        logger.info(f"使用中文标题: {details['name']}")
                    else:
                        metadata['show_name'] = original_name  # 优先使用原始标题，不覆盖为英文
                    metadata['overview'] = details.get('overview', '')
                    metadata['rating'] = details.get('vote_average', 0)
                    metadata['genres'] = [genre['name'] for genre in details.get('genres', [])]
                    metadata['original_name'] = details.get('original_name', '')
                    metadata['original_language'] = details.get('original_language', '')
                    metadata['origin_country'] = details.get('origin_country', [])
                    metadata['first_air_date'] = details.get('first_air_date', '')
                    metadata['last_air_date'] = details.get('last_air_date', '')
                    metadata['status'] = details.get('status', '')
                    metadata['number_of_seasons'] = details.get('number_of_seasons', 0)
                    metadata['number_of_episodes'] = details.get('number_of_episodes', 0)
                    metadata['tmdb_id'] = best_match['id']
                    
                    # 提取年份 - 确保年份被正确设置
                    if details.get('first_air_date'):
                        metadata['year'] = details['first_air_date'].split('-')[0]
                        logger.debug(f"从TMDB获取到年份: {metadata['year']}")
                    else:
                        # 如果没有first_air_date，尝试从搜索结果中获取
                        if 'first_air_date' in best_match and best_match['first_air_date']:
                            metadata['year'] = best_match['first_air_date'].split('-')[0]
                            logger.debug(f"从搜索结果获取到年份: {metadata['year']}")
                        else:
                            # 确保year字段存在，避免后续处理出错
                            if 'year' not in metadata:
                                metadata['year'] = ''
                            logger.debug(f"没有找到年份信息，使用现有year: {metadata['year']}")
                    
                    # 获取网络信息
                    if 'networks' in details:
                        metadata['networks'] = [network['name'] for network in details['networks']]
                    
                    # 获取演职人员信息
                    credits = self.tmdb_client.get_tv_credits(best_match['id'])
                    if credits:
                        # 只取前10位演员
                        metadata['cast'] = [
                            {'name': actor['name'], 'character': actor.get('character', ''), 'profile_path': actor.get('profile_path', '')}
                            for actor in credits.get('cast', [])[:10]
                        ]
                        # 只取导演和编剧
                        metadata['crew'] = [
                            {'name': crew['name'], 'job': crew.get('job', '')}
                            for crew in credits.get('crew', []) 
                            if crew.get('job') in ['Director', 'Writer', 'Creator']
                        ][:5]  # 限制数量
                    
                    # 如果有剧集信息，尝试找到对应的剧集
                    if 'season' in metadata and 'episode' in metadata:
                        try:
                            # 获取剧集详细信息，优先使用中文
                            episode_details = self.tmdb_client.get_tv_episode_details(
                                best_match['id'], 
                                metadata['season'], 
                                metadata['episode'],
                                language='zh-CN'
                            )
                            # 如果中文剧集信息不完整，尝试获取英文信息
                            if not episode_details or not episode_details.get('name'):
                                episode_details = self.tmdb_client.get_tv_episode_details(
                                    best_match['id'], 
                                    metadata['season'], 
                                    metadata['episode'],
                                    language='en-US'
                                )
                                logger.info("中文剧集信息不完整，使用英文信息")
                            
                            if episode_details:
                                # 设置剧集名称
                                metadata['episode_name'] = episode_details.get('name', '')
                                metadata['episode_overview'] = episode_details.get('overview', '')
                                metadata['air_date'] = episode_details.get('air_date', '')
                                metadata['episode_rating'] = episode_details.get('vote_average', 0)
                        except Exception as e:
                            logger.warning(f"获取剧集详情失败: {e}")
            else:
                # 获取电影详细信息，优先使用中文
                details = self.tmdb_client.get_movie_details(best_match['id'], language='zh-CN')
                # 如果中文信息不完整，尝试获取英文信息
                if not details or not (details.get('title') or details.get('overview')):
                    details = self.tmdb_client.get_movie_details(best_match['id'], language='en-US')
                    logger.info("中文电影信息不完整，使用英文信息")
                if details:
                    # 保存原始标题
                    original_title = metadata.get('title')
                    metadata['original_title'] = original_title
                    # 丰富元数据，优先使用中文标题
                    # 如果获取到的是中文详情，使用中文标题；否则使用原始标题
                    if details.get('title') and is_chinese(details['title']):
                        metadata['title'] = details['title']
                        logger.info(f"使用中文标题: {details['title']}")
                    else:
                        metadata['title'] = original_title  # 优先使用原始标题，不覆盖为英文
                    metadata['overview'] = details.get('overview', '')
                    metadata['rating'] = details.get('vote_average', 0)
                    metadata['genres'] = [genre['name'] for genre in details.get('genres', [])]
                    metadata['original_title'] = details.get('original_title', '')
                    metadata['original_language'] = details.get('original_language', '')
                    metadata['origin_country'] = details.get('origin_country', [])
                    metadata['release_date'] = details.get('release_date', '')
                    metadata['runtime'] = details.get('runtime', 0)
                    metadata['status'] = details.get('status', '')
                    metadata['budget'] = details.get('budget', 0)
                    metadata['revenue'] = details.get('revenue', 0)
                    
                    # 获取外部ID信息
                    external_ids = self.tmdb_client.get_external_ids(best_match['id'], 'movie')
                    if external_ids:
                        metadata['imdb_id'] = external_ids.get('imdb_id', '')
                        metadata['tmdb_id'] = external_ids.get('id', '')
                    
                    # 获取评论（如果可用）
                    if 'reviews' in details and details['reviews'].get('results'):
                        metadata['reviews'] = [
                            {'author': review['author'], 'content': review['content']}
                            for review in details['reviews']['results'][:3]  # 只取前3条评论
                        ]
            
            # 设置媒体类型
            metadata['media_type'] = media_type
            # 恢复原始的quality_tags
            metadata['quality_tags'] = original_quality_tags
            return metadata
        except Exception as e:
            logger.error(f"TMDB enrichment failed: {e}")
            # 确保quality_tags存在
            metadata['quality_tags'] = original_quality_tags
            # 确保year和tmdb_id字段存在，避免后续处理出错
            if 'year' not in metadata:
                metadata['year'] = ''
            if 'tmdb_id' not in metadata:
                metadata['tmdb_id'] = ''
            return metadata
    
    def _determine_category(self, metadata: Dict) -> str:
        """
        简化的分类方法，不进行复杂分类
        
        Args:
            metadata (Dict): 包含视频元数据的字典
            
        Returns:
            str: 空字符串，不添加分类目录
        """
        return ""
    
    def generate_new_path(self, metadata: Dict, rule_type: Optional[str] = None, original_path: Optional[Union[str, Path]] = None, output_dir: Optional[Path] = None) -> Path:
        """
        根据元数据和指定的命名规则生成新的组织路径。
        
        Args:
            metadata (Dict): 包含视频元数据的字典
            rule_type (str, optional): 命名规则类型 (tv_show, movie, anime, simple)
            original_path (Path, optional): 原始文件路径，用于保留文件扩展名
            output_dir (Path, optional): 输出目录，用于检测文件冲突
            
        Returns:
            Path: 生成的新路径
        """
        # 转换original_path为Path对象，如果它是字符串的话
        if original_path and isinstance(original_path, str):
            original_path = Path(original_path)
        
        # 确定媒体类型和适当的命名规则
        media_type = metadata.get('media_type')
        if rule_type is None:
            if media_type == 'tv' or (metadata.get('season') and metadata.get('episode')):
                rule_type = 'tv_show'
            elif media_type == 'movie':
                rule_type = 'movie'
            else:
                rule_type = 'simple'
        
        # 获取对应的命名模板
        template = self.naming_rules.get(rule_type, self.naming_rules['simple'])
        
        # 准备用于格式化的变量字典，优先使用原始标题
        season = int(metadata.get('season', 1)) if metadata.get('season') else 1
        episode = int(metadata.get('episode', 1)) if metadata.get('episode') else 1
        
        # 处理各种条件后缀
        year = metadata.get('year', '')
        tmdb_id = metadata.get('tmdb_id', '')
        
        # 确保年份被正确添加，即使year为空也不影响其他逻辑
        year_suffix = f" ({year})" if year and year != "" else ""
        year_bracket_suffix = f" [{year}]" if year and year != "" else ""
        year_dot_suffix = f".{year}" if year and year != "" else ""
        
        tmdbid_suffix = f" {{tmdbid={tmdb_id}}}" if tmdb_id else ""
        tmdbid_bracket_suffix = f" [{tmdb_id}]" if tmdb_id else ""
        tmdbid_dot_suffix = f".{tmdb_id}" if tmdb_id else ""
        tmdbid_raw = tmdb_id if tmdb_id else ""
        
        en_title_suffix = f".{metadata.get('en_title')}" if metadata.get('en_title') else ""
        web_source = f".{metadata.get('web_source')}" if metadata.get('web_source') else ""
        edition = f".{metadata.get('edition')}" if metadata.get('edition') else ""
        part = f".{metadata.get('part')}" if metadata.get('part') else ""
        video_format = f"{metadata.get('video_format')}" if metadata.get('video_format') else ""
        video_codec = f".{metadata.get('video_codec')}" if metadata.get('video_codec') else ""
        audio_codec = f".{metadata.get('audio_codec')}" if metadata.get('audio_codec') else ""
        customization = f".{metadata.get('customization')}" if metadata.get('customization') else ""
        customization_suffix = f"-{metadata.get('customization')}" if metadata.get('customization') else ""
        release_group = f"-{metadata.get('release_group')}" if metadata.get('release_group') else ""
        release_group_suffix = f"-{metadata.get('release_group')}" if metadata.get('release_group') else ""
        
        # 电视剧季集格式
        season_episode = f"S{season:02d}E{episode:02d}"
        
        format_vars = {
            'title': self._sanitize_filename(metadata.get('title', metadata.get('original_title', metadata.get('show_name', 'Unknown Title')))),
            'year': metadata.get('year', ''),
            'year_suffix': year_suffix,
            'year_bracket_suffix': year_bracket_suffix,
            'year_dot_suffix': year_dot_suffix,
            'tmdbid_suffix': tmdbid_suffix,
            'tmdbid_bracket_suffix': tmdbid_bracket_suffix,
            'tmdbid_dot_suffix': tmdbid_dot_suffix,
            'tmdb_id': tmdb_id,  # 直接提供tmdb_id变量
            'tmdbid_raw': tmdbid_raw,  # 直接提供原始tmdb_id
            'en_title_suffix': en_title_suffix,
            'web_source': web_source,
            'edition': edition,
            'part': part,
            'video_format': video_format,
            'video_codec': video_codec,
            'audio_codec': audio_codec,
            'customization': customization,
            'customization_suffix': customization_suffix,
            'release_group': release_group,
            'release_group_suffix': release_group_suffix,
            'season_episode': season_episode,
            'show_name': self._sanitize_filename(metadata.get('show_name', metadata.get('original_show_name', 'Unknown Show'))),
            'season': season,
            'episode': episode,
            'episode_name': self._sanitize_filename(metadata.get('episode_name', '')),
            'movie_name': self._sanitize_filename(metadata.get('title', metadata.get('original_title', 'Unknown Movie'))),
            'anime_name': self._sanitize_filename(metadata.get('show_name', metadata.get('original_show_name', 'Unknown Anime'))),
            'season_name': f"Season {season:02d}",
            'quality_tags': metadata.get('quality_tags', ''),
            'quality_tags_suffix': f" {metadata.get('quality_tags', '')}" if metadata.get('quality_tags', '') else ''
        }
        
        try:
            # 检查模板是否使用了Jinja2语法
            if '{{' in template and '}}' in template:
                # 使用Jinja2模板引擎处理
                jinja_template = Template(template)
                
                # 准备Jinja2模板需要的变量
                jinja_vars = {
                    'title': format_vars['show_name'] if format_vars.get('show_name') else format_vars.get('movie_name', 'Unknown Title'),
                    'year': year,
                    'tmdbid': tmdb_id,
                    'season': season,
                    'episode': episode,
                    'season_episode': format_vars['season_episode'],
                    'videoFormat': format_vars.get('video_format', ''),
                    'webSource': metadata.get('web_source', ''),
                    'edition': metadata.get('edition', ''),
                    'videoCodec': metadata.get('video_codec', ''),
                    'audioCodec': metadata.get('audio_codec', ''),
                    'customization': metadata.get('customization', ''),
                    'releaseGroup': metadata.get('release_group', ''),
                    'fileExt': original_path.suffix if original_path else '',
                    'quality_tags': format_vars['quality_tags'],
                    'quality_tags_suffix': format_vars['quality_tags_suffix'],
                    'show_name': format_vars['show_name'],
                    'movie_name': format_vars['movie_name'],
                    'episode_name': format_vars['episode_name']
                }
                
                # 渲染Jinja2模板
                path_str = jinja_template.render(**jinja_vars)
            else:
                # 使用原始的Python format字符串处理
                # 预处理模板，处理自定义的 {tmdbid=tmdbid} 格式
                processed_template = template
                
                # 预处理年份格式，当year为空时移除年份部分
                if not year:
                    processed_template = processed_template.replace(' ({year})', '')
                    processed_template = processed_template.replace('({year})', '')
                
                # 使用临时占位符避免format()解析
                tmdbid_placeholder = "__TMDBID_PLACEHOLDER__"
                if tmdb_id:
                    # 将 {tmdbid=tmdbid} 替换为临时占位符
                    processed_template = processed_template.replace('{tmdbid=tmdbid}', tmdbid_placeholder)
                else:
                    # 如果没有tmdb_id，移除这个占位符
                    processed_template = processed_template.replace(' {tmdbid=tmdbid}', '')
                    processed_template = processed_template.replace('{tmdbid=tmdbid}', '')
                
                # 使用模板生成路径
                path_str = processed_template.format(**format_vars)
                
                # 替换临时占位符为实际的tmdbid字符串
                if tmdb_id:
                    tmdbid_str = f"{{tmdbid={tmdb_id}}}"
                    path_str = path_str.replace(tmdbid_placeholder, tmdbid_str)
            
            # 如果提供了原始路径，保留扩展名
            if original_path and original_path.suffix:
                # 直接将扩展名添加到路径字符串，避免Path.with_suffix()错误处理多个点的情况
                path_str = path_str + original_path.suffix
            
            path = Path(path_str)
            
            # 直接使用文件名，不添加分类目录前缀
            full_path = path
            
            # 检测并处理文件冲突
            if output_dir:
                full_output_path = output_dir / full_path
                full_path = self._handle_file_conflict(full_output_path)
            
            return full_path
        except KeyError as e:
            logger.error(f"Naming template missing required variable: {e}. Using default path structure.")
            # 如果模板格式失败，使用默认结构
            if not metadata.get('show_name'):
                raise ValueError("Cannot generate path without show name")
                
            # Base structure: Show Name/Season X/Show Name - SXXEXX - Episode Name
            show_name = self._sanitize_filename(metadata['show_name'])
            season = metadata.get('season', '1')
            episode = metadata.get('episode', '1')
            episode_name = self._sanitize_filename(metadata.get('episode_name', ''))
            
            # Format season and episode numbers
            season_str = f"Season {int(season):02d}" if str(season).isdigit() else f"Season {season}"
            episode_str = f"E{int(episode):02d}" if str(episode).isdigit() else f"E{episode}"
            
            # Build filename
            filename_parts = [show_name, f"S{int(season):02d}{episode_str}"]
            if episode_name:
                filename_parts.append(episode_name)
                
            filename = " - ".join(filename_parts)
            
            # 如果提供了原始路径，保留扩展名
            if original_path and original_path.suffix:
                filename += original_path.suffix
            
            # 直接使用文件名，不添加分类目录前缀
            base_path = Path(f"{filename}")
            
            # 不添加分类目录前缀
            return base_path
        
        return path
    
    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string to be safe for use as a filename."""
        if not name:
            return ""
            
        # Replace problematic characters
        import re
        name = re.sub(r'[<>:/\\|?*]', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        return name
        
    def _handle_file_conflict(self, file_path: Path) -> Path:
        """
        处理文件冲突，当文件存在时发出警告但保留原始文件名
        
        Args:
            file_path (Path): 原始文件路径
            
        Returns:
            Path: 原始文件路径
            
        Raises:
            FileExistsError: 当文件已存在时抛出异常，提醒冲突
        """
        if file_path.exists():
            logger.warning(f"文件已存在，无法覆盖: {file_path}")
            # 不自动生成新名称，而是提醒冲突
            raise FileExistsError(f"文件已存在，无法覆盖: {file_path}")
            
        # 如果文件不存在，直接返回原始路径
        return file_path
        
    def set_naming_rules(self, rules: Dict[str, str]) -> None:
        """设置自定义命名规则
        
        Args:
            rules (Dict[str, str]): 命名规则字典，键为媒体类型，值为模板字符串
        """
        for media_type, template in rules.items():
            if media_type in self.naming_rules:
                self.naming_rules[media_type] = template
                logger.info(f"Updated naming rule for {media_type}: {template}")
            else:
                logger.warning(f"Unknown media type for naming rule: {media_type}")