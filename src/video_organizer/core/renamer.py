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
from src.video_organizer.utils.llm_translator import LLMTranslator

logger = logging.getLogger(__name__)


class VideoRenamer:
    """Extracts metadata from video files and generates organized paths."""
    
    # 默认命名规则模板
    DEFAULT_NAMING_RULES = {
        "tv_show": "{show_name}{year_suffix}{tmdbid_suffix}/Season {season:02d}/{show_name} {season_episode}{quality_tags_suffix}{release_group_suffix}",
        "movie": "{movie_name}{year_suffix}{tmdbid_suffix}/{movie_name}{en_title_suffix}{year_suffix}{quality_tags_suffix}{release_group_suffix}",
        "anime": "{anime_name}/{season_name}/{anime_name} - S{season:02d}E{episode:02d}{quality_tags_suffix}{release_group_suffix}",
        "simple": "{title}{quality_tags_suffix}{release_group_suffix}"
    }
    
    def __init__(self, tmdb_api_key: str, ai_service_url: Optional[str] = None, watch_path: Optional[Path] = None, naming_rules: Optional[Dict] = None, llm_config: Optional[Dict] = None, config: Optional[Dict] = None):
        self.tmdb_client = TMDBClient(tmdb_api_key) if tmdb_api_key else None
        self.ai_service_url = ai_service_url
        self.watch_path = watch_path
        self.naming_rules = naming_rules or self.DEFAULT_NAMING_RULES
        self.config = config  # 保存完整配置对象
        
        # 初始化 LLM 翻译器
        self.llm_translator = None
        
        # 检查是否有 LLM 翻译配置
        llm_enabled = False
        llm_api_key = None
        llm_api_url = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
        llm_model = 'GLM-4.5-Flash'
        
        # 优先使用 llm_translation 配置
        if llm_config and isinstance(llm_config, dict):
            llm_enabled = llm_config.get('enabled', False)
            llm_api_key = llm_config.get('api_key')
            llm_api_url = llm_config.get('api_url', llm_api_url)
            llm_model = llm_config.get('model', llm_model)
        
        # 如果没有 llm_translation 配置，尝试使用 ai_translate 配置
        if not llm_enabled or not llm_api_key:
            # 从配置中获取 ai_translate 配置
            ai_translate_config = {}  # 默认空配置
            if hasattr(self, 'config') and isinstance(self.config, dict):
                ai_translate_config = self.config.get('ai_translate', {})
            elif hasattr(self, '_config') and isinstance(self._config, dict):
                ai_translate_config = self._config.get('ai_translate', {})
            
            # 检查 ai_translate 配置
            ai_translate_enabled = ai_translate_config.get('enabled', False)
            ai_translate_api_key = ai_translate_config.get('api_key')
            
            if ai_translate_enabled and ai_translate_api_key:
                llm_enabled = True
                llm_api_key = ai_translate_api_key
                llm_api_url = ai_translate_config.get('api_url', llm_api_url)
                llm_model = ai_translate_config.get('model', llm_model)
        
        # 如果有有效的配置，初始化 LLM 翻译器
        if llm_enabled and llm_api_key:
            self.llm_translator = LLMTranslator(
                api_key=llm_api_key,
                api_url=llm_api_url,
                model=llm_model
            )
            logger.info("VideoRenamer: LLM 翻译器初始化成功")
        
    def extract_metadata(self, file_path: Union[str, Path], media_type_hint: Optional[str] = None) -> Dict:
        """
        从视频文件路径中提取元数据，支持父目录信息补全。
        
        Args:
            file_path (Union[str, Path]): 文件路径
            media_type_hint (str, optional): 媒体类型提示（tv, movie等）
            
        Returns:
            Dict: 提取的元数据
        """
        try:
            if isinstance(file_path, str):
                file_path = Path(file_path)
            
            if not hasattr(file_path, 'name'):
                logger.error(f"无效的file_path参数: {file_path}")
                return {}
            
            # 1. 首先尝试从文件名提取
            metadata = self._extract_with_regex(file_path.name)
            
            # 2. 判断是否需要从父目录补全信息
            fragment_keywords = ['OP', 'ED', 'NCOP', 'NCED', 'PV', 'Trailer', 'SP', 'Special', 'OVA', 'ONA', 'NC', 'EXTRAS']
            extracted_show_name = metadata.get('show_name', '')
            
            is_fragment = extracted_show_name.upper() in fragment_keywords
            # 如果剧名全是数字（有些正则误抓），也视为无效
            is_invalid_name = extracted_show_name.isdigit()
            
            should_lookup_parent = not metadata.get('show_name') or is_fragment or is_invalid_name
            
            if should_lookup_parent:
                try:
                    # 向上查找最多两级父目录
                    parent_dirs = []
                    current = file_path.parent
                    search_limit = 2
                    for _ in range(search_limit):
                        if current and current.name and not (current.name.endswith(':') or current.name == '/'):
                            parent_dirs.append(current)
                            current = current.parent
                        else:
                            break
                    
                    for p_dir in parent_dirs:
                        parent_metadata = self._extract_with_regex(p_dir.name)
                        # 如果父目录能提取到剧名
                        if parent_metadata.get('show_name'):
                            # 补全缺失字段
                            for key in ['show_name', 'season', 'year', 'tmdb_id']:
                                # 特殊逻辑：如果父目录提取的剧名包含季号（如 GGO S02），进行二次清洗
                                val = parent_metadata.get(key)
                                if key == 'show_name' and val:
                                    # 再次清洗以去除 BDrip, S02 等干扰
                                    val = self._clean_filename_for_search(val)
                                
                                if is_fragment and key == 'show_name':
                                    metadata[key] = val
                                elif not metadata.get(key) and val:
                                    metadata[key] = val
                            
                            logger.info(f"从父目录 '{p_dir.name}' 中补全了剧名: {metadata.get('show_name')}")
                            if metadata.get('show_name'):
                                break
                                
                    if not metadata.get('show_name') and len(file_path.parts) > 1:
                        # 最后的尝试：直接拿父目录名并清洗
                        raw_parent_name = file_path.parent.name
                        metadata['show_name'] = self._clean_filename_for_search(raw_parent_name)
                        
                except Exception as e:
                    logger.error(f"父目录元数据提取失败: {e}")

            # 3. 补全媒体类型
            if media_type_hint:
                metadata['media_type'] = media_type_hint
            
            # 4. 如果仍没有 show_name，使用智能清洗
            if not metadata.get('show_name'):
                metadata['show_name'] = self._clean_filename_for_search(file_path.name) or file_path.stem

            # # 5. AI 服务辅助
            # if (self.ai_service_url and 
            #     (not metadata.get('show_name') or not metadata.get('season') or not metadata.get('episode'))):
            #     try:
            #         metadata = self._extract_with_ai(file_path.name, metadata)
            #     except Exception as e:
            #         logger.error(f"AI服务提取元数据失败: {e}")
            
            # 6. TMDB 丰富
            if metadata.get('show_name'):
                try:
                    metadata = self._enrich_with_tmdb(metadata)
                except Exception as e:
                    logger.error(f"TMDB元数据丰富失败: {e}")
            
            # 7. 最终兜底填充
            metadata.setdefault('show_name', file_path.stem)
            metadata.setdefault('original_filename', file_path.name)
            metadata.setdefault('quality_tags', '')
            metadata.setdefault('year', '')
            metadata.setdefault('tmdb_id', '')
            # 确保season和episode有默认值1，即使它们已经存在但值为None
            if metadata.get('season') is None:
                metadata['season'] = 1
            if metadata.get('episode') is None:
                metadata['episode'] = 1
            
            return metadata
        except Exception as e:
            logger.error(f"提取元数据时发生未处理的异常: {e}")
            return {
                'show_name': getattr(file_path, 'stem', 'Unknown'),
                'original_filename': getattr(file_path, 'name', 'unknown'),
                'season': 1, 'episode': 1, 'error': str(e)
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
        
        # 定义要提取的关键词模式，使用非单词边界匹配，支持点号和下划线分隔
        # 优化顺序，先匹配长模式，避免短模式被重复匹配
        keyword_patterns = [
            r'(?:[^\w]|^)(2160p|4K|UHD|FHD|1080p|720p|480p|360p|240p|Ma10p|Ma10p_1080p)(?:[^\w]|$)',
            r'(?:[^\w]|^)(Dolby\s*Vision|HDR10|HDR|SDR)(?:[^\w]|$)',
            r'(?:[^\w]|^)(Netflix|Disney\+|HBO|Amazon|Prime|Apple\+|iTunes)(?:[^\w]|$)',
            r'(?:[^\w]|^)(BDRip|BluRay|DVDRip|WEB-DL|WEBRip|WEB|BD|DVD)(?:[^\w]|$)',
            r'(?:[^\w]|^)(x265|x264|h265|h264|HEVC|AVC|MPEG4|x265_flac|x264_flac)(?:[^\w]|$)',
            r'(?:[^\w]|^)(DTS-HD|TrueHD|Atmos|DDP|DTS|AAC|AC3|FLAC|flac)(?:[^\w]|$)',
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
        # 预处理：将全角括号替换为标准方括号，将+号替换为空格
        base_name = filename.replace('【', '[').replace('】', ']').replace('+', ' ')
        
        metadata = {
            'original_filename': filename,
            'season': None,
            'episode': None,
            'release_group': None
        }
        
        # 提取文件基本信息
        name_only, ext = os.path.splitext(base_name)
        metadata['extension'] = ext.lower()
        
        # 提取关键词
        metadata['quality_tags'] = self._extract_keywords(name_only)
        
        # 提取tmdbid信息
        tmdbid_pattern = r'\{tmdbid[=-](\d+)\}'
        tmdbid_match = re.search(tmdbid_pattern, name_only, re.IGNORECASE)
        if tmdbid_match:
            metadata['tmdb_id'] = tmdbid_match.group(1)
        
        # 提取年份信息
        year_patterns = [
            r'\((\d{4})(?:-\d{4})?\)',
            r'\[(\d{4})(?:-\d{4})?\]',
            r'\.(\d{4})(?:-\d{4})?\.',
            r'\.(\d{4})(?:-\d{4})?\s',
            r'(?<!\d)(19\d{2}|20\d{2})(?!\d|[xXpP])', # 匹配 19xx 或 20xx，且排除 1920x1080
        ]
        
        year_match = None
        for pattern in year_patterns:
            year_match = re.search(pattern, name_only)
            if year_match:
                metadata['year'] = year_match.group(1)
                break
        
        # 清理文件名，用于搜索
        cleaned_name = self._clean_filename_for_search(base_name)
        metadata['cleaned_name'] = cleaned_name
        
        # Common patterns
        patterns = [
            # Movie-specific patterns - 电影专用匹配模式
            # 匹配带发布组、年份、技术信息和语言标签的电影格式
            r"^\[(?P<release_group>[^\]]+)\]\s*(?P<show_name>[^\(]+?)\s*\((?P<year>\d{4})\)\s*(?:\([^\)]+\))+\s*(?:(?P<language>[A-Z]+)\s*)?\[[^\]]+\]",
            # 匹配带发布组和年份的电影格式
            r"^\[(?P<release_group>[^\]]+)\]\s*(?P<show_name>[^\(]+?)\s*\((?P<year>\d{4})\)\s*(?:\([^\)]+\))+",
            # 匹配点分隔的电影格式 (731.Operation.Cherry.Blossoms.at.Night.2025.2160p.WEB-DL.H265.DTS.mkv)
            r"^(?P<show_name>[\w\s\.]+?)\.(?P<year>\d{4})\.(?P<quality>[\w\-\.]+)",
            # 匹配简化的点分隔电影格式 (电影名称.年份)
            r"^(?P<show_name>[\w\s\.]+?)\.(?P<year>\d{4})\.",
            # 1. Show Name Season 01 Episode 01
            r"^(?P<show_name>.*?)[. ]?S(?P<season>\d+)E(?P<episode>\d+)",
            # 2. Season patterns (English & Chinese)
            r"(?P<show_name>.*?)\s*Season\s*(?P<season>\d+)",
            r"(?P<show_name>.*?)\s*(?P<season>\d+)(?:st|nd|rd|th)\s*Season",
            r"(?P<show_name>.*?)\s*第(?P<season_cn>[一二三四五六七八九十\d]+)季",
            r"\[(?P<show_name>[^\]]+?)\s+第(?P<season_cn>[一二三四五六七八九十\d]+)季\]",
            
            # 2.5 罗马数字季号识别 (例如: 龍族II, 进击的巨人IV)
            # 模式 A: 较长的或不常见的罗马数字 (II-IX, V, VI...) 允许后随空格、中横杠或中文附属标题
            r"(?P<show_name>.*?)(?<![a-zA-Z0-9])(?P<roman_season>VIII|VII|VI|III|II|IX|IV|V)(?![a-zA-Z0-9])\s*(?::|-|\s|$)",
            # 模式 B: 极其高频误触的单字母罗马数字 (X, I) 要求后随必须是行尾或元数据标记 (防止切断 Spy x Family)
            r"(?P<show_name>.*?)(?<![a-zA-Z0-9])(?P<roman_season>X|I)(?![a-zA-Z0-9])\s*(?::|-|\[|\(|\r?$)",
            
            # 3. Episode patterns with strict boundaries (avoiding Hash [Checksum])
            # 匹配 Show Name - 09 (严格限制show_name不能只含数字)
            r"^(?:\[[^\]]+\])?\s*(?P<show_name>(?!^\d+$).*?)\s*-\s*(?P<episode>\d+(?:-\d+)?)\s*(?:\[|\(|$)",
            # 匹配 Show Name EP09 / Ep09 / Show.Name.EP09 (严格限制show_name不能只含数字，支持点分隔)
            r"^(?:\[[^\]]+\])?\s*(?P<show_name>(?!^\d+$).*?)(?=[.\s]*(?:EP|Ep|第)[.\s]*\d)[.\s]*(?:EP|Ep|第)[.\s]*(?P<episode>\d+(?:-\d+)?)[.\s]*(?:集)?[.\s]*(?:\[|\(|$)",

            # 修复：匹配 "Spy x Family 2 - 05" 格式 (季号在集号前面，用空格分隔)
            r"^(?P<show_name>(?!^\d+$).+?)\s+(?P<season>\d+)\s*-\s*(?P<episode>\d{2})(?:\s|\.|$)",
            
            # --- 常用 BT 资源/动漫格式匹配 ---
            # 匹配 [VCB-Studio] Show Name [12] 或 [denisplay] Detective Conan Movie 12 - Full Score of Fear (2008) [20th] 等格式
            r"^\[[^\]]+\]\s*(?P<show_name>.*?)\s*(?:\(\d{4}\))?\s*(?:\[[^\]\d]+\])?\s*\[(?P<episode>\d{1,4}(?:-\d{1,4})?)\]",
            # 匹配 [VCB-Studio] Show Name [OVA03] 等OVA格式
            r"^\[[^\]]+\]\s*(?P<show_name>.*?)\s*\[OVA(?P<episode>\d{1,4})\]",
            # 匹配 Show Name [OVA03] 等不带字幕组的OVA格式
            r"^(?P<show_name>(?!^\d+$).*?)\s*\[OVA(?P<episode>\d{1,4})\]",
            # 匹配 Show Name [12][...] (严格限制show_name不能只含数字)
            r"^(?P<show_name>(?!^\d+$).*?)\s*\[(?P<episode>\d{1,4}(?:-\d{1,4})?)\]",
            # 匹配 剧名 22 [GB] (空格集号，严格限制show_name不能只含数字且不含年份，且集号必须小于1000)
            # 添加年份前向否定断言，避免将年份误识别为集号
            r"^(?:\[[^\]]+\]\s+)?(?P<show_name>(?!^\d+$)[\u4e00-\u9fff\w\s]+?(?<!\d{4}))\s+(?P<episode>\d{1,3}(?:-\d{1,3})?)(?<!\d{4})(?:\s|$)",
            # 匹配 [Nekomoe kissaten][Watashi wo Tabetai, Hitodenashi][12][1080p][JPSC] 格式
            r"^\[[^\]]+\]\s*\[(?P<show_name>[^\]]+)\]\s*\[(?P<episode>\d{1,4}(?:-\d{1,4})?)\]",
            
            # 基础降级模式 (只抓集号，添加年份排除)
            # 匹配 [Doomdos] - 荒古恩仇录·破 风篇 - 第32话 - [1080P] 这种格式
            r"^(?:\[[^\]]+\])?\s*(?P<show_name>(?!^\d+$).*?)\s*-\s*第(?P<episode>\d+(?:-\d+)?)话\s*",
            r"(?<!\d{4})第(?P<episode>\d+(?:-\d+)?)集",
            r"(?<!\d{4})第(?P<episode>\d+(?:-\d+)?)话",
            r"(?<!\d{4})EP(?P<episode>\d+(?:-\d+)?)",
            r"(?<!\d{4})\[(?P<episode>\d{1,4}(?:-\d{1,4})?)\]",
        ]
        
        match_found = False
        for pattern in patterns:
            match = re.search(pattern, base_name, re.IGNORECASE)
            if match:
                match_data = match.groupdict()
                
                # 处理中文季号转换
                if 'season_cn' in match_data and match_data['season_cn']:
                    cn_val = match_data['season_cn']
                    digit = self._chinese_to_digit(cn_val)
                    if digit:
                        match_data['season'] = str(digit)
                
                # 补全元数据
                for key, value in match_data.items():
                    if value and key != 'season_cn' and not metadata.get(key):
                        metadata[key] = value
                match_found = True

        # 提取字幕组信息（通常在文件名开头，格式为[字幕组名称]）
        # 在所有其他正则匹配之后提取，确保不会被覆盖
        release_group_pattern = r'^\[([^\]]+)\]'
        release_group_match = re.search(release_group_pattern, base_name)
        if release_group_match:
            metadata['release_group'] = release_group_match.group(1)

        # 先移除此处的媒体类型相关代码，将在后面统一处理

        if match_found:
            # Clean up show name
            if 'show_name' in metadata:
                # 1. 优先处理罗马数字转换
                if 'roman_season' in metadata and metadata['roman_season']:
                    digit = self._roman_to_digit(metadata['roman_season'])
                    if digit:
                         metadata['season'] = str(digit)
                         # 从剧名中剔除罗马数字后缀
                         metadata['show_name'] = re.sub(fr"\s*{metadata['roman_season']}\s*$", "", metadata['show_name']).strip()

                # 接下来执行常规清理
                show_name = metadata['show_name']
                # 1. 移除首部的发布组方括号，如 [Dynamis One]
                show_name = re.sub(r'^\[[^\]]+\]\s*', '', show_name)
                # 2. 移除括号内的年份 (2022) - 无论位置如何
                show_name = re.sub(r'\s*\(\d{4}(?:-\d{4})?\)\s*', ' ', show_name)
                # 3. 移除方括号内的标签，如 [国漫]、[中文配音] 等
                # 先移除特定的常见标签
                common_tags = ['国漫', '日漫', '美漫', '新番', 'GM-Team', 'Team', 'Group', 'Raws', 'Studio', '中文配音', '中配', '配音', '繁中', '简中', 'CHT', 'CHS']
                for tag in common_tags:
                    show_name = re.sub(r'\[\s*' + re.escape(tag) + r'\s*\]', '', show_name, flags=re.IGNORECASE)
                # 4. 移除剩余的所有方括号内容（用于搜索时更干净）
                show_name = re.sub(r'\[[^\]]+\]', '', show_name)
                
                # 5. 移除常见的语言标签
                language_tags = ['CHINESE', 'ENGLISH', 'JAPANESE', 'KOREAN', '中文', '英语', '日语', '韩语', '中字', '英字', '双语']
                for tag in language_tags:
                    show_name = re.sub(r'\s+' + re.escape(tag) + r'\s*$', '', show_name, flags=re.IGNORECASE)
                    show_name = re.sub(r'^\s*' + re.escape(tag) + r'\s+', '', show_name, flags=re.IGNORECASE)
                    show_name = re.sub(r'\s+' + re.escape(tag) + r'\s+', ' ', show_name, flags=re.IGNORECASE)
                
                # 6. 额外清理：如果剧名末尾残存了连集信息（如 Pocket Monsters 115），剔除它
                show_name = re.sub(r'\s+\d+(?:-\d+)?$', '', show_name)
                
                metadata['show_name'] = show_name.strip()
                show_name = show_name.strip().rstrip('.')
                # 移除多余的空格
                show_name = re.sub(r'\s+', ' ', show_name)
                
                # 特别处理中文名称，不进行title()转换
                if re.search(r'[\u4e00-\u9fff]', show_name):
                    # 只替换英文点(.)，保留中文点(·)
                    show_name = re.sub(r'\.', ' ', show_name).strip()
                    # 移除副标题（只移除明确的副标题关键词，保留正式剧名部分）
                    # 使用与 _clean_filename_for_search 相同的逻辑
                    if '·' in show_name:
                        subtitle_keywords = [
                            r'篇', r'章', r'回', r'卷', r'部', r'季', r'传',
                            r'特别篇', r'番外篇', r'外传', r'前传', r'后传'
                        ]
                        subtitle_pattern = r'·.*?(?:' + '|'.join(subtitle_keywords) + r')(?=$|\s|\.|\-|\(|\[|，|、)'
                        show_name = re.sub(subtitle_pattern, '', show_name)
                else:
                    show_name = re.sub(r'\.', ' ', show_name).title().strip()
                
                # 专门处理EPxx格式：如果有episode信息，直接从原始文件名提取show_name
                if metadata.get('episode'):
                    episode_str = metadata['episode']
                    filename_parts = metadata['original_filename'].split('.')
                    new_show_name = []
                    found_ep = False
                    
                    for part in filename_parts:
                        # 检查是否包含EPxx模式
                        if re.search(r'(?i)EP' + re.escape(episode_str) + r'[a-zA-Z]*', part):
                            found_ep = True
                            break
                        new_show_name.append(part)
                    
                    if found_ep and new_show_name:
                        # 重新组合show_name
                        show_name = '.'.join(new_show_name)
                        # 移除可能的字幕组标记（如[xxx]）
                        show_name = re.sub(r'^\[[^\]]+\]\s*', '', show_name)
                        # 处理点分隔的情况
                        if '.' in show_name:
                            # 对于包含中文的名称，直接替换点为空格
                            if re.search(r'[\u4e00-\u9fff]', show_name):
                                show_name = show_name.replace('.', ' ').strip()
                            # 对于英文名称，替换点为空格并转为title格式
                            else:
                                show_name = show_name.replace('.', ' ').title().strip()
                
                metadata['show_name'] = show_name.strip()
        
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
                            show_name = show_name.replace('.', ' ').strip()
                        else:
                            show_name = show_name.replace('.', ' ').title().strip()
                        
                        # 移除show_name中EPxx及之后的部分（处理点分隔文件名）
                        ep_match = re.search(r'(?i)\s+EP\d+\s*', show_name)
                        if ep_match:
                            show_name = show_name[:ep_match.start()].strip()
                            
                        metadata['show_name'] = show_name
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
        
        # 媒体类型检测逻辑改进：
        # 1. 优先检测明显的剧集格式
        is_tv = False
        
        # 检查是否有明确的SxxExx格式（即使包含PT/网盘标签）
        # SxxExx格式是最明确的剧集标识，应该优先识别
        if re.search(r'(?i)(^|[^a-zA-Z])S\d+E\d+($|[^a-zA-Z])', base_name):
            is_tv = True
        # 检查其他季集信息，包括中文季集格式和OVA/SP标识，即使包含分辨率等信息
        # 只要有明确的季集标识就应识别为TV，避免将包含分辨率的中文剧集或OVA/SP误判为电影
        elif re.search(r'(?i)(^|[^a-zA-Z])(第\d+季|第\d+集|EP\d+|\d+话|OVA\d+|SP\d+)', base_name):
            is_tv = True
        elif metadata.get('season') and metadata.get('episode'):
            # 检查season和episode是否合理（避免将年份等数字误识别）
            try:
                season_num = int(metadata['season'])
                episode_num = int(metadata['episode'])
                # 如果season大于10或episode大于1000，可能是误识别
                if season_num > 10 or episode_num > 1000:
                    is_tv = False
                else:
                    # 进一步检查：如果集号等于年份，很可能是误识别
                    if metadata.get('year') and str(episode_num) == metadata.get('year'):
                        is_tv = False
                    else:
                        is_tv = True
            except (ValueError, TypeError):
                is_tv = False
        elif metadata.get('season') or metadata.get('episode'):
            # 只有season或只有episode的情况
            try:
                if metadata.get('season'):
                    season_num = int(metadata['season'])
                    if season_num > 10:
                        is_tv = False
                    else:
                        # 进一步检查：如果季号等于年份，很可能是误识别
                        if metadata.get('year') and str(season_num) == metadata.get('year'):
                            is_tv = False
                        else:
                            is_tv = True
                if metadata.get('episode'):
                    episode_num = int(metadata['episode'])
                    if episode_num > 1000:
                        is_tv = False
                    else:
                        # 进一步检查：如果集号等于年份，很可能是误识别
                        if metadata.get('year') and str(episode_num) == metadata.get('year'):
                            is_tv = False
                        else:
                            is_tv = True
            except (ValueError, TypeError):
                is_tv = False
        
        # 2. 检测电影类型
        is_movie = False
        # 优先检测PT/网盘常见的电影命名格式（包含分辨率、编码、来源等信息）
        if re.search(r'(?i)(2160p|4k|uhd|fhd|1080p|720p|480p|360p|240p)(?:\.|\s)(web-dl|bluray|bdrip|hdrip|dvdrip|webdl|bd|dvd)(?:\.|\s)(x264|x265|h264|h265|hevc|xvid|divx)', base_name):
            is_movie = True
        elif re.search(r'\bMovie\b|\bmovie\b|\bFilm\b|\bfilm\b', base_name, re.IGNORECASE):
            is_movie = True
        elif metadata.get('year'):
            # 如果season或episode等于年份，很可能是电影
            if metadata.get('season') == metadata.get('year') or metadata.get('episode') == metadata.get('year'):
                is_movie = True
            # 如果文件名中包含年份，且没有明确的剧集格式，倾向于判定为电影
            elif not re.search(r'(?i)(^|[^a-zA-Z])S\d+E\d+($|[^a-zA-Z])|第\d+季|第\d+集|EP\d+', base_name):
                is_movie = True
        # 3. 如果文件名看起来像电影格式（包含分辨率、编码等信息），判定为电影
        elif re.search(r'(?i)(2160p|4k|uhd|fhd|1080p|720p|480p|360p|240p)\s*(?:\[|\()?\d{4}(?:\]|\))?', base_name):
            is_movie = True
        
        # 3. 确定最终媒体类型
        # 优先考虑明确的剧集格式，即使同时满足电影格式也应识别为TV
        if is_tv:
            metadata['media_type'] = 'tv'
        elif is_movie:
            metadata['media_type'] = 'movie'
        else:
            # 默认情况，根据是否有季集信息判断
            if metadata.get('season') or metadata.get('episode'):
                metadata['media_type'] = 'tv'
            else:
                metadata['media_type'] = 'movie'
        
        # 根据媒体类型处理season和episode的默认值
        media_type = metadata.get('media_type')
        if media_type == 'tv':
            # 对于电视剧，如果有明确的episode但没有season，默认设置season=1
            # 无论是否有显式的季号标识（Sxx或第x季），只要是TV类型且有集号，就应该有季号
            if metadata.get('episode') and not metadata.get('season'):
                metadata['season'] = '1'
        else:  # movie类型
            # 对于电影，清空season和episode
            metadata['season'] = None
            metadata['episode'] = None
        
        # 额外的安全检查：如果是电影，确保没有season和episode
        if metadata.get('media_type') == 'movie':
            metadata['season'] = None
            metadata['episode'] = None
        
        # 统一清理show_name：处理点分隔的文件名
        if metadata.get('show_name') and metadata.get('episode'):
            # 直接使用original_filename处理，确保能正确提取
            filename_parts = metadata['original_filename'].split('.')
            episode_str = metadata.get('episode')
            new_parts = []
            found_ep = False
            
            for part in filename_parts:
                # 检查是否包含EPxx模式
                if re.search(r'(?i)EP' + re.escape(episode_str) + r'[a-zA-Z]*', part):
                    found_ep = True
                    break
                new_parts.append(part)
            
            if found_ep and new_parts:
                # 重新组合show_name
                show_name = '.'.join(new_parts)
                # 移除可能的字幕组标记（如[xxx]）
                show_name = re.sub(r'^\[[^\]]+\]\s*', '', show_name)
                # 对于英文名称，替换点为空格并转为title格式
                if not re.search(r'[\u4e00-\u9fff]', show_name):
                    show_name = show_name.replace('.', ' ').title().strip()
                else:
                    show_name = show_name.replace('.', ' ').strip()
                metadata['show_name'] = show_name
        
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
            # 但保留类似"假面骑士.ZEZTZ"中的系列标识
            if '.' in show_name and re.search(r'[\u4e00-\u9fff]', show_name) and metadata.get('media_type') != 'movie':
                parts = show_name.split('.')
                # 收集所有相关部分：包含中文的部分和可能的系列标识
                relevant_parts = []
                found_chinese = False
                for part in parts:
                    if re.search(r'[\u4e00-\u9fff]', part):
                        relevant_parts.append(part)
                        found_chinese = True
                    elif found_chinese and (part.isupper() or re.match(r'^[A-Z0-9]{2,}$', part)):
                        # 如果已经找到了中文部分，并且下一个部分是大写字母组合（可能是系列标识），则保留
                        relevant_parts.append(part)
                    elif found_chinese:
                        # 否则停止收集
                        break
                if relevant_parts:
                    show_name = ' '.join(relevant_parts)
            # 对于电影，不要截断英文名称，保留所有有意义的部分
            # 只移除明显的质量标签和年份信息
            elif '.' in show_name and metadata.get('media_type') == 'movie':
                # 保留所有点号分隔的部分，但移除年份和质量标签
                parts = show_name.split('.')
                filtered_parts = []
                quality_tags = ['2160p', '4k', 'uhd', 'fhd', '1080p', '720p', '480p', '360p', '240p', 
                              'web-dl', 'bluray', 'bdrip', 'hdrip', 'dvdrip', 'webdl', 'bd', 'dvd',
                              'x264', 'x265', 'h264', 'h265', 'hevc', 'xvid', 'divx',
                              'dts', 'ac3', 'dd5.1', 'aac', '5.1', '7.1']
                for part in parts:
                    # 跳过明显的年份和质量标签
                    if re.match(r'^\d{4}$', part) or part.lower() in quality_tags:
                        continue
                    filtered_parts.append(part)
                if filtered_parts:
                    show_name = ' '.join(filtered_parts)
                else:
                    # 如果过滤后没有内容，保留原始show_name
                    show_name = metadata['show_name']
            
            # 4. 处理空格分隔的副标题
            # 例如：瑞草洞 Law and the City -> 瑞草洞
            # 但保留类似"假面骑士 ZEZTZ"中的系列标识
            if ' ' in show_name and re.search(r'[\u4e00-\u9fff]', show_name):
                parts = show_name.split(' ')
                # 收集所有相关部分：包含中文的部分和可能的系列标识
                relevant_parts = []
                found_chinese = False
                for part in parts:
                    if re.search(r'[\u4e00-\u9fff]', part):
                        relevant_parts.append(part)
                        found_chinese = True
                    elif found_chinese and (part.isupper() or re.match(r'^[A-Z0-9]{2,}$', part)):
                        # 如果已经找到了中文部分，并且下一个部分是大写字母组合（可能是系列标识），则保留
                        relevant_parts.append(part)
                    elif found_chinese:
                        # 否则停止收集
                        break
                if relevant_parts:
                    show_name = ' '.join(relevant_parts)
            
            # 5. 移除常见的修饰词
            modifiers = [
                r'\s+特别版\s*$',
                r'\s+导演剪辑版\s*$',
                r'\s+加长版\s*$',
                r'\s+最终版\s*$'
            ]
            for modifier in modifiers:
                show_name = re.sub(modifier, '', show_name, flags=re.IGNORECASE)
            
            # 6. 移除多余的空格和特殊字符（保留中文点(·)）
            show_name = show_name.strip().rstrip('.')
            show_name = re.sub(r'\s+', ' ', show_name)
            # 移除非字母数字和中文的字符（包括中文点(·)）
            show_name = re.sub(r'[^\w\s\u4e00-\u9fff·]', '', show_name)
            
            metadata['show_name'] = show_name
        # 如果没有提取到show_name，使用清理后的文件名作为默认值
        elif cleaned_name:
            # 移除明显的年份和质量标签
            default_show_name = cleaned_name
            # 移除括号内的内容
            default_show_name = re.sub(r'[\[\(].*?[\]\)]', '', default_show_name)
            # 移除年份
            default_show_name = re.sub(r'\s*\d{4}\s*', '', default_show_name)
            # 移除多余的空格和特殊字符
            default_show_name = default_show_name.strip().rstrip('.')
            default_show_name = re.sub(r'\s+', ' ', default_show_name)
            default_show_name = re.sub(r'[^\w\s\u4e00-\u9fff]', '', default_show_name)
            metadata['show_name'] = default_show_name
        # 最后的备用方案：使用文件名的基本部分
        else:
            metadata['show_name'] = os.path.splitext(base_name)[0]
                        
        return metadata
    
    def _roman_to_digit(self, roman: str) -> Optional[int]:
        """将罗马数字转换为阿拉伯数字 (I-X)"""
        roman_dict = {
            'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5,
            'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10
        }
        if not roman:
            return None
        return roman_dict.get(roman.upper())

    def _chinese_to_digit(self, cn_str: str) -> Optional[int]:
        """将中文数字转换为阿拉伯数字 (1-99)"""
        cn_map = {
            '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
            '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
            '0': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5,
            '6': 6, '7': 7, '8': 8, '9': 9
        }
        
        if not cn_str:
            return None
            
        # 如果是纯数字字符串
        if cn_str.isdigit():
            return int(cn_str)
            
        # 处理简单的中文数字
        if len(cn_str) == 1:
            return cn_map.get(cn_str)
        
        # 处理“十”开头的（如：十一、十二）
        if len(cn_str) == 2 and cn_str[0] == '十':
            return 10 + cn_map.get(cn_str[1], 0)
            
        # 处理“二十”、“三十”等
        if len(cn_str) == 2 and cn_str[1] == '十':
            return cn_map.get(cn_str[0], 0) * 10
            
        # 处理“二十一”等
        if len(cn_str) == 3 and cn_str[1] == '十':
            return cn_map.get(cn_str[0], 0) * 10 + cn_map.get(cn_str[2], 0)
            
        return None

    def _extract_with_ai(self, filename: str, existing_metadata: Dict) -> Dict:
        """
        Use AI service to extract metadata from filename.
        """
        logger.warning("AI extraction not implemented, using regex results only")

        
        return existing_metadata
    
    def _clean_filename_for_search(self, filename: str) -> str:
        """清理文件名，移除常见的修饰词和标记，为搜索做准备"""
        # 1. 移除后缀
        cleaned = os.path.splitext(filename)[0]
        
        # 2. 预处理：移除括号内的技术参数和发布组
        # 质量标记正则表达式
        quality_patterns = r'HD|FHD|UHD|4K|1080p|720p|480p|360p|240p|2160p|2160|HDR|SDR|HDR10|Dolby\s*Vision|DV|dv|Dv|x264|x265|h264|h265|HEVC|AVC|MPEG4|10bit|AAC|DTS|DDP|TrueHD|Atmos|FLAC|AC3|DTS-HD|OPUS|BD|BDRip|BluRay|DVD|DVDRip|WEB|WEBRip|WEB-DL|REPACK|PROPER|INTERNAL|CHS|ENG|双语|字幕|中字|英字|JPN|简日内嵌|繁体|简体|日语版|国语版|粤语版|MP4|MKV|AVI|GB|BIG5|CHT|CHS|TC|SC|JAP|CN|JP|Dub|JP\s*Dub|TV|Web'
        
        # 移除包含质量标记的方括号/圆括号块
        # 使用正则表达式匹配括号及其中内容，如果内容包含 quality 关键字则移除
        def remove_tag_blocks(match):
            content = match.group(1)
            # 如果是纯数字或年份，或者集号范围，移除
            if content.isdigit() or re.match(r'^(19|20)\d{2}$', content) or re.match(r'^\d+(?:-\d+)?$', content):
                return ""
            # 如果包含技术关键词，移除
            if re.search(quality_patterns, content, re.IGNORECASE):
                logger.debug(f"移除质量/技术标记块: [{content}] (匹配规则)")
                return ""
            # 如果包含常用的 Hash 校验码 (8位 16进制)
            if re.match(r'^[0-9A-Fa-f]{8}$', content):
                return ""
            # 如果包含发布组关键词
            group_keywords = ['raws', 'team', 'sub', 'studio', 'group', '字幕组', '组', 'raw', 'ACG', 'Dynamis', 'FYSub', 'Lilith-Raws', 'LowPower-Raws', 'EMR']
            if any(kw.lower() in content.lower() for kw in group_keywords):
                return ""
            
            logger.debug(f"保留未知标记块: [{content}]")
            return match.group(0) # 保留其他块 (如剧名块)

        cleaned = re.sub(r'\[([^\]]+)\]', remove_tag_blocks, cleaned)
        cleaned = re.sub(r'\(([^\)]+)\)', remove_tag_blocks, cleaned)
        
        # 3. 移除常见的修饰符和季集信息 (Season 2, Episode 11 等)
        cleaned = re.sub(r'Season\s*\d+', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'第\d+季', '', cleaned)
        cleaned = re.sub(r'-\s*\d+\s*', ' ', cleaned) # 移除集号
        
        # 特别移除末尾的罗马数字 (防止干扰剧名搜索)
        cleaned = re.sub(r'\s+(VIII|VII|VI|III|II|IX|IV|V|X|I)$', '', cleaned, flags=re.IGNORECASE)
        
        # 移除副标题（只移除明确的副标题关键词，保留正式剧名部分）
        # 使用非贪婪匹配 .*? 来匹配副标题前的内容
        # 使用前瞻断言 (?=...) 确保副标题后面跟着分隔符，但不匹配分隔符本身
        subtitle_keywords = [
            r'篇', r'章', r'回', r'卷', r'部', r'季', r'传',
            r'特别篇', r'番外篇', r'外传', r'前传', r'后传'
        ]
        # 副标题后面可以跟：字符串结束、空格、点、连字符、括号、中文标点（使用前瞻断言）
        subtitle_pattern = r'·.*?(?:' + '|'.join(subtitle_keywords) + r')(?=$|\s|\.|\-|\(|\[|，|、)'
        cleaned = re.sub(subtitle_pattern, '', cleaned)
        
        # 4. 最后清理符号和多余空格 - 明确列出要替换的字符，不包含中文点(·)
        cleaned = re.sub(r'\[|\]|\.|\_|\-|\&|\+|\(|\)', ' ', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # 针对剧名的额外优化：如果清理后太短或包含太多非剧名信息，做最后保护
        if not cleaned:
             cleaned = filename # 退回到原始文件名处理
        
        return cleaned
        
    def _prepare_search_term(self, search_term: str) -> str:
        """准备搜索词，为TMDB搜索优化"""
        prepared = re.sub(r'\s+', ' ', search_term).strip()
        
        # 移除版本描述词 (日语版, 国语版 等)
        version_patterns = r'日语版|国语版|粤语版|中字|字幕|双语|内嵌'
        prepared = re.sub(version_patterns, '', prepared)
        
        if re.search(r'[\u4e00-\u9fff]', prepared):
            prepared = re.sub(r'S\d+E\d+', '', prepared, flags=re.IGNORECASE)
            prepared = re.sub(r'S\d+', '', prepared, flags=re.IGNORECASE)
            prepared = re.sub(r'第\d+季(第\d+集)?', '', prepared, flags=re.IGNORECASE)
            prepared = re.sub(r'\d+集', '', prepared)
            prepared = prepared.strip()
        else:
            prepared = prepared.title()
            
        return prepared.strip()
        
    def _translate_text(self, text: str, target_language: str = 'en-US') -> str:
        """
        将文本翻译为目标语言，支持多种语言互译
        
        Args:
            text (str): 要翻译的文本
            target_language (str): 目标语言，默认为英文(en-US)
            
        Returns:
            str: 翻译后的文本
        """
        # 统一翻译字典，支持多种语言互译
        translation_dict = {
            # 中文到英文
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
            "星期三": "Wednesday",
            "龙族": "Dragon Raja",
            "龍族": "Dragon Raja",
            "间谍过家家": "Spy x Family",
            "宝可梦": "Pokémon",
            "宝可梦 地平线": "Pokémon Horizons",
            
            # 英文到中文
            "Stranger Things": "怪奇物语",
            "Game of Thrones": "权力的游戏",
            "Squid Game": "鱿鱼游戏",
            "The Wandering Earth": "流浪地球",
            "Minning Town": "山海情",
            "Running Man": "奔跑吧兄弟",
            "Peppa Pig": "小猪佩奇",
            "One Piece": "海贼王",
            "Soul Land": "斗罗大陆",
            "A Bite of China": "舌尖上的中国",
            "Wednesday": "星期三",
            "Dragon Raja": "龙族",
            "Spy x Family": "间谍过家家",
            "Spy Family": "间谍过家家",
            "Pokémon": "宝可梦",
            "Pokémon Horizons": "宝可梦 地平线"
        }
        
        # 尝试直接翻译
        if text in translation_dict:
            translated = translation_dict[text]
            logger.info(f"使用翻译字典将 '{text}' 翻译为 '{translated}'")
            return translated
        
        # AI 翻译兜底
        if self.llm_translator:
            try:
                translated = self.llm_translator.translate_video_name(text, target_language=target_language)
                if translated and translated != text:
                    logger.info(f"使用 AI 翻译将 '{text}' 翻译为 '{target_language}' 的 '{translated}'")
                    return translated
            except Exception as e:
                logger.error(f"AI 翻译失败: {e}")
        
        # 尝试拆分翻译
        words = text.split()
        translated_words = []
        for word in words:
            translated_words.append(translation_dict.get(word, word))
        
        translated = " ".join(translated_words)
        if translated != text:
            logger.info(f"使用拆分翻译将 '{text}' 翻译为 '{translated}'")
        return translated
    
    def _translate_to_english(self, text: str) -> str:
        """
        将文本翻译为英文（向后兼容方法）
        
        Args:
            text (str): 要翻译的文本
            
        Returns:
            str: 翻译后的英文文本
        """
        return self._translate_text(text, target_language='en-US')
    
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
            
            # 安全地处理年份参数，避免无效年份导致搜索失败
            year_param = None
            if year:
                try:
                    year_param = int(year)
                except (ValueError, TypeError):
                    logger.warning(f"无效的年份值: '{year}'，将不使用年份过滤条件进行搜索")
                    year_param = None
            
            # 搜索方法选择
            if media_type_hint == 'tv':
                search_method = self.tmdb_client.search_tv
            elif media_type_hint == 'movie':
                search_method = self.tmdb_client.search_movie
            else:
                return results
            
            # 1. 第一次搜索：使用年份参数
            search_results = search_method(
                final_search_term, 
                year_param,
                language=language
            )
            if isinstance(search_results, dict) and 'results' in search_results:
                results = search_results['results']
            
            # 2. 降级搜索：如果没有找到结果且使用了年份参数，则去掉年份重新搜索
            if not results and year_param:
                logger.info(f"使用年份 {year_param} 搜索无结果，尝试去掉年份参数重新搜索")
                search_results = search_method(
                    final_search_term, 
                    None,
                    language=language
                )
                if isinstance(search_results, dict) and 'results' in search_results:
                    results = search_results['results']
                    if results:
                        logger.info(f"去掉年份后搜索到 {len(results)} 个结果")
        except Exception as e:
            logger.error(f"语言搜索失败: {e}")
        
        return results
        
    # 添加缓存机制，避免重复搜索
    _search_cache = {}
    
    def _enrich_with_tmdb(self, metadata: Dict) -> Dict:
        """使用TMDB API丰富元数据信息，获取更完整的视频详情"""
        # 确保metadata是字典类型
        if not isinstance(metadata, dict):
            logger.error("元数据不是字典类型，直接返回")
            return {}
        
        try:
            logger.info(f"开始TMDB搜索: metadata={metadata}")
            # 保存原始的quality_tags和release_group，避免被覆盖
            original_quality_tags = metadata.get('quality_tags', '')
            original_release_group = metadata.get('release_group', '')
            
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
            logger.info(f"搜索TMDB: 原始搜索词长度={len(search_term)}, 优化后搜索词长度={len(prepared_search_term)}")
            
            # 搜索匹配的视频信息
            # 首先尝试明确的类型搜索
            media_type_hint = metadata.get('media_type', metadata.get('type', ''))
            year = metadata.get('year')
            
            # 定义缓存键
            cache_key = (prepared_search_term, media_type_hint, year)
            
            # 检查缓存
            if cache_key in self._search_cache:
                logger.info(f"使用缓存的搜索结果: {cache_key}")
                results = self._search_cache[cache_key]
            else:
                # 优化的搜索策略：减少API调用次数
                # 1. 优先使用精确搜索（明确类型+语言匹配）
                # 2. 仅在必要时进行跨语言搜索
                # 3. 合并搜索结果，避免重复请求
                
                # 定义语言检测函数（移到类级别或作为静态方法可进一步优化）
                def is_chinese(text):
                    """检测文本是否包含中文"""
                    return bool(re.search(r'[\u4e00-\u9fff]', text))
                
                # 定义完全匹配检查函数
                def has_exact_match(search_results, target_term):
                    if not search_results:
                        return False, None
                    # 确保search_results是列表类型
                    if isinstance(search_results, dict) and 'results' in search_results:
                        search_results = search_results['results']
                    if not isinstance(search_results, list):
                        return False, None
                        
                    # 提前翻译目标术语，避免在循环中重复翻译
                    target_term_lower = target_term.lower()
                    
                    for result in search_results:
                        result_title = result.get('name', result.get('title', '')).lower()
                        original_name = result.get('original_name', '').lower()
                        
                        # 1. 直接匹配
                        if result_title == target_term_lower or original_name == target_term_lower:
                            return True, result
                        
                        # 2. 简繁基础兼容 (针对 Dragon Raja)
                        if (target_term_lower == "龍族" and result_title == "龙族") or \
                           (target_term_lower == "龙族" and result_title == "龍族"):
                            return True, result
                        
                    return False, None
                
                # 检测优化后搜索词的语言
                search_term_is_chinese = is_chinese(prepared_search_term)
                logger.info(f"检测到优化后的搜索词 '{prepared_search_term}' 包含中文: {search_term_is_chinese}")
                
                # 初始搜索语言选择
                primary_language = 'zh-CN' if search_term_is_chinese else 'en-US'
                secondary_language = 'en-US' if search_term_is_chinese else 'zh-CN'
                
                all_results = []
                unique_ids = set()
                exact_match_result = None
                
                # 1. 第一次搜索：精确类型+主要语言搜索
                logger.info(f"第一次搜索：使用优化后的搜索词 '{prepared_search_term}' 进行{primary_language}搜索")
                primary_results = []
                
                # 如果有明确的媒体类型，优先使用专用搜索
                if media_type_hint:
                    primary_results = self._search_with_language(prepared_search_term, media_type_hint, year, primary_language)
                    if primary_results:
                        logger.info(f"专用类型搜索返回 {len(primary_results)} 个结果")
                
                # 如果专用搜索没有结果，尝试通用搜索
                if not primary_results:
                    general_results = self.tmdb_client.search_video_show(prepared_search_term, year, language=primary_language)
                    if isinstance(general_results, dict) and 'results' in general_results:
                        primary_results = general_results['results']
                        logger.info(f"通用搜索返回 {len(primary_results)} 个结果")
                
                # 检查是否有完全匹配
                if primary_results:
                    exact_match_found, exact_match_result = has_exact_match(primary_results, prepared_search_term)
                    if not exact_match_found:
                        exact_match_found, exact_match_result = has_exact_match(primary_results, search_term)
                
                if exact_match_result:
                    logger.info(f"找到完全匹配: {exact_match_result.get('name', exact_match_result.get('title'))}")
                    results = [exact_match_result]
                else:
                    # 保存第一次搜索结果
                    for result in primary_results:
                        if result.get('id') not in unique_ids:
                            all_results.append(result)
                            unique_ids.add(result.get('id'))
                    
                    # 2. 仅在必要时进行第二次跨语言搜索
                    # 只有当第一次搜索结果少于3个或者没有明确匹配时，才进行跨语言搜索
                    if len(all_results) < 3:
                        logger.info(f"第一次搜索结果较少({len(all_results)}个)，进行跨语言搜索")
                        
                        # 翻译搜索词
                        translated_search_term = self._translate_text(prepared_search_term, target_language=secondary_language)
                        
                        # 如果翻译结果与原词不同，进行跨语言搜索
                        if translated_search_term != prepared_search_term:
                            logger.info(f"将搜索词 '{prepared_search_term}' 翻译为 '{translated_search_term}' 进行{secondary_language}搜索")
                            
                            # 跨语言搜索
                            secondary_results = []
                            if media_type_hint:
                                secondary_results = self._search_with_language(translated_search_term, media_type_hint, year, secondary_language)
                            
                            if not secondary_results:
                                general_secondary_results = self.tmdb_client.search_video_show(translated_search_term, year, language=secondary_language)
                                if isinstance(general_secondary_results, dict) and 'results' in general_secondary_results:
                                    secondary_results = general_secondary_results['results']
                            
                            # 检查跨语言搜索结果
                            if secondary_results:
                                exact_match_found, exact_match_result = has_exact_match(secondary_results, translated_search_term)
                                if exact_match_result:
                                    logger.info(f"在跨语言搜索中找到完全匹配: {exact_match_result.get('name', exact_match_result.get('title'))}")
                                    results = [exact_match_result]
                                else:
                                    # 合并跨语言搜索结果
                                    for result in secondary_results:
                                        if result.get('id') not in unique_ids:
                                            all_results.append(result)
                                            unique_ids.add(result.get('id'))
                                    results = all_results
                            else:
                                results = all_results
                        else:
                            logger.info(f"翻译结果与原词相同，跳过跨语言搜索")
                            results = all_results
                    else:
                        logger.info(f"第一次搜索结果充足({len(all_results)}个)，跳过跨语言搜索")
                        results = all_results
                
                # 保存到缓存
                if results:
                    self._search_cache[cache_key] = results
            
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
                search_term_lower = search_term.lower()
                
                def calculate_score(result):
                    title = result.get('name', result.get('title', '')).lower()
                    original_name = result.get('original_name', '').lower()
                    
                    # 标准化搜索词和标题，移除所有非字母数字和中文的字符（包括中文点(·)）
                    normalized_search = re.sub(r'[^\w\s\u4e00-\u9fff]', '', search_term_lower)
                    normalized_search = re.sub(r'\s+', '', normalized_search)
                    
                    normalized_title = re.sub(r'[^\w\s\u4e00-\u9fff]', '', title)
                    normalized_title = re.sub(r'\s+', '', normalized_title)
                    
                    normalized_original = re.sub(r'[^\w\s\u4e00-\u9fff]', '', original_name)
                    normalized_original = re.sub(r'\s+', '', normalized_original)
                    
                    # 定义通用数字字符集（用于模糊匹配）
                    # 包括：阿拉伯数字(0-9)、中文数字(一二三四五六七八九十)、罗马数字(Ⅰ-Ⅹ, ⅰ-ⅹ)
                    digit_pattern = '[0-9一二三四五六七八九十ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅰⅱⅲⅳⅵⅶⅷⅸⅹⅺⅻⅼⅽⅾⅿ]+'
                    # 进一步标准化：移除所有数字（用于模糊匹配）
                    fuzzy_search = re.sub(digit_pattern, '', normalized_search)
                    fuzzy_title = re.sub(digit_pattern, '', normalized_title)
                    fuzzy_original = re.sub(digit_pattern, '', normalized_original)
                    
                    score = 0
                    # 1. 模糊匹配：移除所有数字后，搜索词和标题完全匹配
                    if fuzzy_search == fuzzy_title or fuzzy_search == fuzzy_original:
                        score = 12000
                    # 2. 搜索词是标题的前缀（标题更长，更精确）
                    elif (normalized_title.startswith(normalized_search) and len(normalized_title) > len(normalized_search)) or \
                         (normalized_original.startswith(normalized_search) and len(normalized_original) > len(normalized_search)):
                        score = 15000
                    # 3. 完全匹配得分极高（在标准化后的字符串上）
                    elif normalized_search == normalized_title or normalized_search == normalized_original:
                        score = 10000
                    # 4. 搜索词是标题的显著子集（在标准化后的字符串上）
                    elif normalized_search in normalized_title and len(normalized_search) > 1:
                        score = 1000
                    # 5. 标题是搜索词的子集（在标准化后的字符串上）
                    elif normalized_title in normalized_search and len(normalized_title) > 1:
                        score = 500
                    
                    total_score = score + result.get('popularity', 0)
                    return total_score
                
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
                    if details:
                        logger.info("中文电视剧信息不完整，使用英文信息")
                if not details:
                    logger.warning(f"无法获取TV详情(ID: {best_match['id']})")
                    # 确保返回原始metadata，而不是False
                    return metadata
                # 保存原始标题
                original_name = metadata.get('show_name')
                metadata['original_show_name'] = original_name
                # 丰富元数据，优先使用中文标题
                # 无论标题是否为中文，都设置完整的元数据
                if details.get('name') and is_chinese(details['name']):
                    metadata['show_name'] = details['name']
                    logger.info(f"使用中文标题: {details['name']}")
                else:
                    metadata['show_name'] = original_name  # 优先使用原始标题，不覆盖为英文
                
                # 无论标题是否为中文，都设置完整的元数据
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
                    # 处理连集 (如 115-120)，提取第一个集号用于搜索
                    search_episode = str(metadata['episode']).split('-')[0] if '-' in str(metadata['episode']) else metadata['episode']
                    
                    try:
                        # 获取剧集详细信息，优先使用中文
                        episode_details = self.tmdb_client.get_tv_episode_details(
                            best_match['id'], 
                            metadata['season'], 
                            search_episode,
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
                    if details:
                        logger.info("中文电影信息不完整，使用英文信息")
                if not details:
                    logger.warning(f"无法获取电影详情(ID: {best_match['id']})")
                    # 确保返回原始metadata，而不是False
                    return metadata
                # 保存原始标题，并处理None值情况
                original_title = metadata.get('title')
                # 丰富元数据，优先使用中文标题
                # 无论是否是中文标题，都设置所有元数据字段
                if details.get('title') and is_chinese(details['title']):
                    metadata['title'] = details['title']
                    logger.info(f"使用中文标题: {details['title']}")
                else:
                    # 如果原始标题为None或空字符串，使用TMDB的原始标题
                    metadata['title'] = original_title or details.get('original_title', '')
                    logger.info(f"使用原始标题: {metadata['title']}")
                
                # 始终设置其他元数据字段
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
                    logger.info(f"获取到外部ID: IMDB={metadata['imdb_id']}, TMDB={metadata['tmdb_id']}")
                
                # 获取评论（如果可用）
                if 'reviews' in details and details['reviews'].get('results'):
                    metadata['reviews'] = [
                        {'author': review['author'], 'content': review['content']}
                        for review in details['reviews']['results'][:3]  # 只取前3条评论
                    ]
            
            # 设置媒体类型
            metadata['media_type'] = media_type
            # 恢复原始的quality_tags和release_group
            metadata['quality_tags'] = original_quality_tags
            metadata['release_group'] = original_release_group
            return metadata
        except Exception as e:
            logger.error(f"TMDB enrichment failed: {e}")
            # 确保quality_tags和release_group存在
            metadata['quality_tags'] = original_quality_tags
            metadata['release_group'] = original_release_group
            # 确保year和tmdb_id字段存在，避免后续处理出错
            if 'year' not in metadata:
                metadata['year'] = ''
            if 'tmdb_id' not in metadata:
                metadata['tmdb_id'] = ''
            return metadata
    
    def _determine_category(self, metadata: Dict) -> str:
        """
        根据元数据确定视频的分类目录
        
        Args:
            metadata (Dict): 包含视频元数据的字典
            
        Returns:
            str: 分类目录路径
        """
        # 确定基础分类（电视剧/电影/其他）
        media_type = metadata.get('media_type')
        if media_type == 'movie':
            base_category = 'Movies'
        elif media_type == 'tv':
            base_category = 'TV Shows'
        else:
            base_category = 'Other'
        
        # 获取语言和地区信息
        original_language = metadata.get('original_language', '').lower()
        origin_countries = metadata.get('origin_country', [])
        genres = metadata.get('genres', [])
        
        # 扩展的国家/地区识别列表
        chinese_countries = ['CN', 'HK', 'TW']
        english_countries = ['US', 'GB', 'CA', 'AU', 'NZ']
        asian_countries = ['JP', 'KR', 'TH', 'IN']
        
        # 子分类逻辑
        sub_category = ''
        
        if base_category == 'TV Shows':
            # 电视剧子分类
            genre_names = [genre.lower() for genre in genres]
            
            # 1. 特殊类型分类
            if any(genre in genre_names for genre in ['documentary', '纪录片']):
                sub_category = '纪录片'
            elif any(genre in genre_names for genre in ['reality', 'variety', '综艺', 'game show']):
                sub_category = '综艺'
            elif any(genre in genre_names for genre in ['animation', 'animated', '动画']):
                # 动画类型进一步细分
                # 首先检查是否是日漫
                if original_language in ['ja', 'ja-jp'] or any(country in ['JP', '日本'] for country in origin_countries):
                    sub_category = '日番'
                # 然后检查是否是国漫
                elif original_language in ['zh', 'cn', 'zh-cn', 'zh-tw', 'zh-hk'] or any(country in chinese_countries for country in origin_countries):
                    sub_category = '国漫'
                # 接着检查是否是欧美动漫
                elif original_language in ['en', 'en-us', 'en-gb'] or any(country in english_countries for country in origin_countries):
                    sub_category = '欧美动漫'
                else:
                    # 额外检查：通过标题中的日文假名识别日漫
                    title = metadata.get('show_name', '') or metadata.get('original_show_name', '')
                    if re.search(r'[\u3040-\u30FF]', title):  # 检查是否包含日文假名
                        sub_category = '日番'
                    elif re.search(r'[\u4E00-\u9FFF]', title):  # 检查是否包含中文汉字
                        sub_category = '国漫'
                    else:
                        sub_category = '其他动漫'
            elif any(genre in genre_names for genre in ['kids', 'children', 'child', '儿童', 'family']):
                sub_category = '儿童'
            else:
                # 2. 普通电视剧分类
                if original_language in ['zh', 'cn'] or any(country in chinese_countries for country in origin_countries):
                    sub_category = '国产剧'
                elif original_language in ['en'] or any(country in english_countries for country in origin_countries):
                    sub_category = '欧美剧'
                elif original_language in ['ja', 'ko', 'th', 'hi'] or any(country in asian_countries for country in origin_countries):
                    sub_category = '日韩剧'
                else:
                    # 3. 如果语言和地区无法确定，检查原始名称
                    original_show_name = metadata.get('original_show_name', '')
                    if original_show_name and re.search(r'[\u4e00-\u9fff]', original_show_name):
                        sub_category = '国产剧'
                    else:
                        sub_category = '未分类'
        else:
            # 电影子分类
            # 1. 检查是否为动画电影
            genre_names = [genre.lower() for genre in genres]
            if any(genre in genre_names for genre in ['animation', 'animated', '动画']):
                sub_category = '动画电影'
            else:
                # 2. 检查语言和地区
                original_title = metadata.get('original_title', '')
                if original_title and re.search(r'[\u4e00-\u9fff]', original_title):
                    sub_category = '华语电影'
                elif original_language in ['zh', 'cn'] or any(country in chinese_countries for country in origin_countries):
                    sub_category = '华语电影'
                else:
                    sub_category = '外语电影'
        
        # 组合分类路径
        return f"{base_category}/{sub_category}"
    
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
            if media_type == 'movie':
                rule_type = 'movie'
            elif media_type == 'tv' or (metadata.get('season') and metadata.get('episode')):
                rule_type = 'tv_show'
            else:
                rule_type = 'simple'
        
        # 获取对应的命名模板
        template = self.naming_rules.get(rule_type, self.naming_rules['simple'])
        
        # 准备用于格式化的变量字典，优先使用原始标题
        def safe_int(val, default=1):
            if not val: return default
            if isinstance(val, int): return val
            if str(val).isdigit(): return int(val)
            return val # 保持为字符串 (如 115-120)

        # 检查是否是OVA/特别篇，如果是则设置为Season 0
        is_special = False
        if original_path and original_path.name:
            # 检查文件名是否包含特别篇标识（使用正则表达式精确匹配，避免部分匹配）
            special_patterns = [
                r'\bOVA\b',  # 匹配独立的OVA
                r'\bOVA0?1\b', r'\bOVA0?2\b', r'\bOVA0?3\b', r'\bOVA0?4\b', r'\bOVA0?5\b',
                r'\bOVA0?6\b', r'\bOVA0?7\b', r'\bOVA0?8\b', r'\bOVA0?9\b', r'\bOVA10\b',
                r'(?<!\w)SP(?!\w)',  # 匹配独立的SP，排除SPY等词
                r'(?<=\[)Special(?=\])',  # [Special] 格式
                r'\bSpecial\s*(?:Episode|EP|Ep)\b',  # Special Episode 格式
                r'\bSpecial\s*\d+\b',  # Special 01 格式
                r'\bSpecial\b(?=\s*\.\w+$)',  # Special.mkv 格式（在文件名末尾）
                r'特别篇',  # 中文关键词
                r'番外篇',  # 中文关键词
            ]
            filename_upper = original_path.name.upper()
            for pattern in special_patterns:
                if re.search(pattern, filename_upper, re.IGNORECASE):
                    is_special = True
                    break
        
        # 如果是特别篇，设置季数为0，否则使用正常的安全转换
        if is_special:
            season = 0
        else:
            season = safe_int(metadata.get('season', 1))
            
        episode = safe_int(metadata.get('episode', 1))
        
        # 补零辅助
        s_str = f"{season:02d}" if isinstance(season, int) else str(season)
        e_str = f"{episode:02d}" if isinstance(episode, int) else str(episode)
        
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
        season_episode = f"S{s_str}E{e_str}"
        
        format_vars = {
            'title': self._sanitize_filename(metadata.get('title') or metadata.get('original_title') or metadata.get('show_name', 'Unknown Title')),
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
            'movie_name': self._sanitize_filename(metadata.get('title') or metadata.get('original_title') or metadata.get('show_name', 'Unknown Movie')),
            'anime_name': self._sanitize_filename(metadata.get('show_name', metadata.get('original_show_name', 'Unknown Anime'))),
            'season_name': f"Season {s_str}",
            'quality_tags': metadata.get('quality_tags', ''),
            'quality_tags_suffix': f" {metadata.get('quality_tags', '')}" if metadata.get('quality_tags', '') else ''
        }
        
        # 添加调试日志，追踪变量值和模板渲染

        
        try:
            # 提取后缀名：优先使用 original_path，其次使用 metadata 中的 extension 备份
            file_ext = ""
            if original_path and original_path.suffix:
                file_ext = original_path.suffix
            elif metadata.get('extension'):
                 # 正则表达式阶段提取的后缀
                 file_ext = metadata.get('extension')
                 if file_ext and not file_ext.startswith('.'):
                     file_ext = '.' + file_ext

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
                    'fileExt': file_ext, # 注入后缀变量
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
            
            # 强化后缀保护：如果生成的路径还没有后缀，强制追加
            if file_ext and not path_str.lower().endswith(file_ext.lower()):
                 path_str = path_str + file_ext
            
            path = Path(path_str)
            
            # 确定分类目录
            category_path = self._determine_category(metadata)
            
            # 获取基础分类
            base_category = "TV Shows" if media_type == 'tv' else "Movies"
            
            # 组合分类目录和文件名，避免重复的基础分类
            if path.parts and path.parts[0] == base_category:
                # 如果path已经包含了base_category，就去掉path的第一个部分
                full_path = Path(category_path) / Path(*path.parts[1:])
            else:
                full_path = Path(category_path) / path
            
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