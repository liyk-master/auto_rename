"""
GuessIt 集成模块 - 增强视频文件名识别能力

GuessIt 是一个强大的视频文件名解析库，能够从文件名中提取丰富的元数据信息。
本模块将其集成到 Video Organizer 项目中，作为正则表达式识别的补充和增强。
"""

import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# 尝试导入 guessit，如果不可用则使用 None
try:
    from guessit import guessit
    GUESSIT_AVAILABLE = True
    logger.info("GuessIt 库已加载")
except ImportError:
    GUESSIT_AVAILABLE = False
    logger.warning("GuessIt 库未安装，将使用正则表达式识别")


class GuessItParser:
    """GuessIt 解析器封装类"""

    # guessit 属性名到项目内部属性名的映射
    PROPERTY_MAPPING = {
        'title': 'show_name',
        'film_title': 'show_name',
        'season': 'season',
        'episode': 'episode',
        'year': 'year',
        'release_group': 'release_group',
        'screen_size': 'screen_size',
        'source': 'source',
        'video_codec': 'video_codec',
        'audio_codec': 'audio_codec',
        'container': 'container',
        'streaming_service': 'streaming_service',
        'language': 'language',
        'subtitle_language': 'subtitle_languages',
        'episode_title': 'episode_title',
        'other': 'other_tags',
    }

    # 质量标签映射（将 guessit 的多个属性合并为 quality_tags）
    QUALITY_PROPERTIES = [
        'screen_size', 'source', 'video_codec', 'audio_codec',
        'streaming_service', 'other'
    ]

    def __init__(self, enabled: bool = True):
        """
        初始化 GuessIt 解析器

        Args:
            enabled: 是否启用 GuessIt 解析
        """
        self.enabled = enabled and GUESSIT_AVAILABLE
        if self.enabled:
            logger.info("GuessIt 解析器已启用")
        else:
            logger.info("GuessIt 解析器已禁用或不可用")

    def parse(self, filename: str, options: Optional[Dict] = None) -> Dict[str, Any]:
        """
        解析视频文件名

        Args:
            filename: 视频文件名（可以是完整路径或仅文件名）
            options: guessit 选项，如 {'type': 'episode'} 或 {'type': 'movie'}

        Returns:
            解析后的元数据字典
        """
        if not self.enabled:
            return {}

        try:
            # 中文剧集格式预处理
            # 如果文件名是纯中文格式（如 "第1集.strm"），尝试从父目录提取剧名
            preprocessed_filename = self._preprocess_chinese_filename(filename)
            
            # 使用 guessit 解析
            result = guessit(preprocessed_filename, options or {})

            # 转换为项目内部格式
            metadata = self._convert_result(result, filename)
            
            # 后处理：修正中文剧集的识别结果
            metadata = self._postprocess_chinese_result(metadata, filename)

            logger.debug(f"GuessIt 解析结果: {metadata}")
            return metadata

        except Exception as e:
            logger.error(f"GuessIt 解析失败: {e}")
            return {}

    # 中文数字映射
    CHINESE_NUM_MAP = {
        '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
        '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
        '十': 10, '十一': 11, '十二': 12, '十三': 13, '十四': 14,
        '十五': 15, '十六': 16, '十七': 17, '十八': 18, '十九': 19,
        '二十': 20, '二十一': 21, '二十二': 22, '二十三': 23, '二十四': 24,
        '二十五': 25, '二十六': 26, '二十七': 27, '二十八': 28, '二十九': 29,
        '三十': 30,
    }

    def _preprocess_chinese_filename(self, filename: str) -> str:
        """
        预处理中文文件名，改善 guessit 对中文格式的识别

        支持的格式：
        - 纯集号格式：第1集、第01话、第一集、第1-2集（连集）
        - 带季目录：第一季/第1集、Season 1/第1集、S01/第1集
        - 字幕组格式：【字幕组】剧名 第1集

        Args:
            filename: 原始文件名或路径

        Returns:
            预处理后的文件名
        """
        path = Path(filename)
        stem = path.stem
        
        # 1. 尝试从文件名中提取集号信息
        episode_info = self._extract_episode_from_chinese(stem)
        
        if episode_info:
            episode_num, episode_end = episode_info  # episode_end 用于连集
            
            # 尝试从路径中提取剧名和季号
            show_name, season = self._extract_show_info_from_path(path)
            
            if show_name:
                # 构造标准格式
                if episode_end and episode_end != episode_num:
                    # 连集格式
                    new_filename = f"{show_name} E{episode_num:02d}-E{episode_end:02d}{path.suffix}"
                else:
                    new_filename = f"{show_name} E{episode_num:02d}{path.suffix}"
                
                # 如果有季号，添加季号
                if season:
                    new_filename = f"{show_name} S{season:02d}E{episode_num:02d}{path.suffix}"
                    if episode_end and episode_end != episode_num:
                        new_filename = f"{show_name} S{season:02d}E{episode_num:02d}-E{episode_end:02d}{path.suffix}"
                
                logger.debug(f"中文格式预处理: '{filename}' -> '{new_filename}'")
                return new_filename
        
        # 2. 处理字幕组格式：【字幕组】剧名 第1集 或 【字幕组】剧名 第N集
        subtitle_match = re.match(r'^【[^】]+】(.+)$', stem)
        if subtitle_match:
            remaining = subtitle_match.group(1).strip()
            
            # 尝试从剩余部分提取剧名和集号
            # 格式1：剧名 第1集、剧名 第01话、剧名 第1話
            match = re.match(r'^(.+?)\s*第(\d+)[集话話]$', remaining)
            if match:
                show_name = match.group(1).strip()
                episode_num = int(match.group(2))
                new_filename = f"{show_name} E{episode_num:02d}{path.suffix}"
                logger.debug(f"字幕组格式预处理: '{filename}' -> '{new_filename}'")
                return new_filename
            
            # 格式2：剧名 第一集、剧名 第二集（中文数字）
            for chinese_num, num in self.CHINESE_NUM_MAP.items():
                cn_match = re.match(rf'^(.+?)\s*第{chinese_num}[集话話]$', remaining)
                if cn_match:
                    show_name = cn_match.group(1).strip()
                    new_filename = f"{show_name} E{num:02d}{path.suffix}"
                    logger.debug(f"字幕组格式预处理: '{filename}' -> '{new_filename}'")
                    return new_filename
            
            # 格式3：剧名 - 01、剧名 E01
            match = re.match(r'^(.+?)\s*[-\s]+[Ee]?(\d+)$', remaining)
            if match:
                show_name = match.group(1).strip()
                episode_num = int(match.group(2))
                new_filename = f"{show_name} E{episode_num:02d}{path.suffix}"
                logger.debug(f"字幕组格式预处理: '{filename}' -> '{new_filename}'")
                return new_filename
            
            # 格式4：纯集号（已在前面的逻辑处理）
            episode_info = self._extract_episode_from_chinese(remaining)
            if episode_info:
                episode_num, episode_end = episode_info
                # 提取剧名（去掉集号部分）
                show_name = re.sub(r'\s*第?\d+[-\d]*[集话話]?\s*$', '', remaining)
                show_name = re.sub(r'\s*[Ee][Pp]?\d+(-\d+)?\s*$', '', show_name)
                show_name = show_name.strip()
                
                if show_name:
                    if episode_end and episode_end != episode_num:
                        new_filename = f"{show_name} E{episode_num:02d}-E{episode_end:02d}{path.suffix}"
                    else:
                        new_filename = f"{show_name} E{episode_num:02d}{path.suffix}"
                    logger.debug(f"字幕组格式预处理: '{filename}' -> '{new_filename}'")
                    return new_filename
        
        return filename

    def _extract_episode_from_chinese(self, stem: str) -> Optional[tuple]:
        """
        从中文文件名中提取集号

        Args:
            stem: 文件名（不含扩展名）

        Returns:
            (集号, 结束集号) 元组，如果不是中文集号格式则返回 None
            对于单集，两个值相同；对于连集，返回范围
        """
        # 中文数字集号：第一集、第二集...（精确匹配）
        for chinese_num, num in self.CHINESE_NUM_MAP.items():
            if stem == f'第{chinese_num}集' or stem == f'第{chinese_num}话' or stem == f'第{chinese_num}話':
                return (num, num)
        
        # 数字集号：第1集、第01集、第1话、第01话、第1話（精确匹配）
        match = re.match(r'^第(\d+)[集话話]$', stem)
        if match:
            return (int(match.group(1)), int(match.group(1)))
        
        # 带额外文本的数字集号：第1集 4K、第01集.HDR、第1话.1080p 等
        # 匹配以 "第N集" 或 "第N话" 开头的文件名
        match = re.match(r'^第(\d+)[集话話](?:\s|\.|$)', stem)
        if match:
            return (int(match.group(1)), int(match.group(1)))
        
        # 带额外文本的中文数字集号：第一集 4K、第二集.HDR 等
        for chinese_num, num in self.CHINESE_NUM_MAP.items():
            if re.match(rf'^第{chinese_num}[集话話](?:\s|\.|$)', stem):
                return (num, num)
        
        # 连集格式：第1-2集、第01-02话、第1-2話
        match = re.match(r'^第(\d+)-(\d+)[集话話]', stem)
        if match:
            return (int(match.group(1)), int(match.group(2)))
        
        # 英文格式：EP01, E01, ep01
        match = re.match(r'^[Ee][Pp]?(\d+)$', stem)
        if match:
            return (int(match.group(1)), int(match.group(1)))
        
        # 纯数字：1, 01, 001（一位及以上数字）
        match = re.match(r'^(\d+)$', stem)
        if match:
            return (int(match.group(1)), int(match.group(1)))
        
        return None

    def _extract_show_info_from_path(self, path: Path) -> tuple:
        """
        从路径中提取剧名和季号

        Args:
            path: 文件路径对象

        Returns:
            (剧名, 季号) 元组，季号可能为 None
        """
        show_name = None
        season = None
        
        # 遍历路径的父目录
        current = path.parent
        parent_parts = list(current.parts)
        
        # 从后向前查找剧名和季号
        for i, part in enumerate(reversed(parent_parts)):
            part_str = str(part)
            
            # 检查是否是季目录
            if season is None:
                # 中文季：第一季、第二季...
                for chinese_num, num in self.CHINESE_NUM_MAP.items():
                    if part_str == f'第{chinese_num}季':
                        season = num
                        continue
                
                # 数字季：第1季、Season 1、S01、S1
                match = re.match(r'^第(\d+)季$', part_str)
                if match:
                    season = int(match.group(1))
                    continue
                
                match = re.match(r'^Season\s*(\d+)$', part_str, re.IGNORECASE)
                if match:
                    season = int(match.group(1))
                    continue
                
                match = re.match(r'^S(\d+)$', part_str, re.IGNORECASE)
                if match:
                    season = int(match.group(1))
                    continue
            
            # 如果还没找到剧名，检查当前部分
            if show_name is None:
                # 清理父目录名中的年份和其他干扰信息
                clean_name = re.sub(r'[（\(]\d{4}[）\)]', '', part_str)
                clean_name = re.sub(r'\s*\d{4}\s*$', '', clean_name)
                clean_name = clean_name.strip()
                
                # 排除纯季目录名
                if not clean_name or re.match(r'^(第\d+季|Season\s*\d+|S\d+)$', clean_name, re.IGNORECASE):
                    continue
                
                # 检查名称中是否包含嵌入的季号信息
                # 格式1：剧名 第N季（如 "修罗武神 第二季"）
                embedded_season_match = re.search(r'\s*第(\d+)季\s*$', clean_name)
                if embedded_season_match and season is None:
                    season = int(embedded_season_match.group(1))
                    clean_name = clean_name[:embedded_season_match.start()].strip()
                
                # 格式2：剧名 第N季（中文数字，如 "修罗武神 第二季"）
                for chinese_num, num in self.CHINESE_NUM_MAP.items():
                    cn_match = re.search(rf'\s*第{chinese_num}季\s*$', clean_name)
                    if cn_match and season is None:
                        season = num
                        clean_name = clean_name[:cn_match.start()].strip()
                        break
                
                # 格式3：剧名 Season N（如 "Show Name Season 2"）
                embedded_season_match_en = re.search(r'\s+Season\s*(\d+)\s*$', clean_name, re.IGNORECASE)
                if embedded_season_match_en and season is None:
                    season = int(embedded_season_match_en.group(1))
                    clean_name = clean_name[:embedded_season_match_en.start()].strip()
                
                # 格式4：剧名 SN 或 S0N（如 "Show Name S02"）
                embedded_s_match = re.search(r'\s+S(\d+)\s*$', clean_name, re.IGNORECASE)
                if embedded_s_match and season is None:
                    season = int(embedded_s_match.group(1))
                    clean_name = clean_name[:embedded_s_match.start()].strip()
                
                if clean_name:
                    show_name = clean_name
        
        return (show_name, season)

    def _postprocess_chinese_result(self, metadata: Dict, original_filename: str) -> Dict:
        """
        后处理中文剧集的识别结果

        Args:
            metadata: guessit 解析结果
            original_filename: 原始文件名

        Returns:
            修正后的元数据
        """
        path = Path(original_filename)
        stem = path.stem
        
        # 如果 show_name 被识别为 "第1集" 或类似的集号格式
        show_name = metadata.get('show_name', '')
        
        # 检查 show_name 是否是无效的集号格式
        invalid_patterns = [
            r'^第\d+集',
            r'^第\d+话',
            r'^第\d+話',
            r'^第[一二三四五六七八九十]+集',
            r'^第[一二三四五六七八九十]+话',
            r'^[Ee][Pp]?\d+',
        ]
        
        is_invalid_show_name = any(re.match(p, show_name) for p in invalid_patterns)
        
        if is_invalid_show_name:
            # 尝试从父目录获取剧名
            show_name_from_path, season_from_path = self._extract_show_info_from_path(path)
            
            if show_name_from_path:
                metadata['show_name'] = show_name_from_path
                logger.debug(f"修正剧名: '{show_name}' -> '{show_name_from_path}' (来自父目录)")
                
                # 如果没有季号但从路径中提取到了季号，也添加
                if metadata.get('season') is None and season_from_path is not None:
                    metadata['season'] = season_from_path
                    logger.debug(f"从路径补充季号: {season_from_path}")
        
        # 处理字幕组格式：【字幕组】剧名 第1集
        if '【' in show_name and '】' in show_name:
            # 移除字幕组标记
            cleaned_name = re.sub(r'^【[^】]+】\s*', '', show_name)
            # 移除可能的集号部分
            cleaned_name = re.sub(r'\s*第?\d+[-\d]*[集话話]?\s*$', '', cleaned_name)
            cleaned_name = cleaned_name.strip()
            
            if cleaned_name:
                metadata['show_name'] = cleaned_name
                logger.debug(f"清理字幕组格式剧名: '{show_name}' -> '{cleaned_name}'")
        
        return metadata

    def _convert_result(self, result: Dict, filename: str) -> Dict[str, Any]:
        """
        将 guessit 结果转换为项目内部格式

        Args:
            result: guessit 返回的原始结果
            filename: 原始文件名

        Returns:
            转换后的元数据字典
        """
        metadata = {
            'original_filename': filename,  # 保留完整路径
        }

        # 类型判断
        guessit_type = result.get('type', '')
        if guessit_type == 'episode':
            metadata['media_type'] = 'tv'
        elif guessit_type == 'movie':
            metadata['media_type'] = 'movie'

        # 转换基本属性
        for guessit_key, internal_key in self.PROPERTY_MAPPING.items():
            if guessit_key in result:
                value = result[guessit_key]

                # 特殊处理
                if guessit_key == 'language':
                    # guessit 返回的是 babelfish.Language 对象列表
                    if isinstance(value, list):
                        metadata[internal_key] = [str(lang) for lang in value]
                    else:
                        metadata[internal_key] = str(value)
                elif guessit_key == 'subtitle_language':
                    if isinstance(value, list):
                        metadata[internal_key] = [str(lang) for lang in value]
                    else:
                        metadata[internal_key] = [str(value)]
                elif guessit_key == 'season':
                    # 确保季号是整数
                    if isinstance(value, list):
                        season_val = value[0] if value else None
                    else:
                        season_val = value
                    # 检查 season 是否看起来像年份（如 2008），应该识别为 year
                    if season_val and isinstance(season_val, int) and 1900 <= season_val <= 2030:
                        # 将年份值移到 year 字段
                        metadata['year'] = season_val
                        logger.debug(f"将 season 值 {season_val} 识别为年份")
                        metadata['season'] = None
                    else:
                        metadata[internal_key] = season_val
                elif guessit_key == 'episode':
                    # 处理集号（可能是列表，如连集）
                    if isinstance(value, list):
                        metadata[internal_key] = value[0] if value else None
                        if len(value) > 1:
                            metadata['episode_range'] = value
                    else:
                        metadata[internal_key] = value
                else:
                    metadata[internal_key] = value

        # 构建质量标签
        quality_tags = self._build_quality_tags(result)
        if quality_tags:
            metadata['quality_tags'] = quality_tags

        # 清理标题
        if 'show_name' in metadata:
            metadata['show_name'] = self._clean_title(metadata['show_name'])

        return metadata

    def _build_quality_tags(self, result: Dict) -> str:
        """
        从 guessit 结果构建质量标签字符串

        Args:
            result: guessit 原始结果

        Returns:
            质量标签字符串，如 "1080p.WEB-DL.x265"
        """
        tags = []

        # 按顺序添加质量标签
        quality_order = ['screen_size', 'source', 'video_codec', 'audio_codec', 'streaming_service']

        for prop in quality_order:
            if prop in result:
                value = result[prop]
                if isinstance(value, list):
                    value = value[0] if value else None
                if value:
                    # 格式化值
                    value_str = str(value)
                    tags.append(value_str)

        # 添加 other 标签（如 HDR, Dolby Vision 等）
        if 'other' in result:
            other = result['other']
            if isinstance(other, list):
                for item in other:
                    if str(item) not in ['Extras', 'Bonus']:  # 排除一些不需要的标签
                        tags.append(str(item))
            else:
                tags.append(str(other))

        return '.'.join(tags) if tags else ''

    def _clean_title(self, title: str) -> str:
        """
        清理标题中的干扰字符

        Args:
            title: 原始标题

        Returns:
            清理后的标题
        """
        if not title:
            return title

        # 移除常见的发布组前缀
        title = re.sub(r'^\[[^\]]+\]\s*', '', title)
        title = re.sub(r'^【[^】]+】\s*', '', title)

        # 将点号和下划线替换为空格
        title = title.replace('.', ' ').replace('_', ' ')

        # 移除多余空格
        title = ' '.join(title.split())

        return title.strip()

    def _is_invalid_show_name(self, show_name: Optional[str]) -> bool:
        """
        判断剧名是否不合理（需要被 GuessIt 结果覆盖）

        Args:
            show_name: 待检查的剧名

        Returns:
            True 如果剧名不合理，False 如果剧名合理
        """
        if not show_name:
            return True

        # 纯数字（如 "01", "123"）
        if show_name.isdigit():
            return True

        # 仅包含季集信息（如 "S01E81"）
        if re.match(r'^S\d+E\d+$', show_name.upper()):
            return True

        # 中文集号格式（如 "第7集"、"第01话"、"第1話"）
        if re.match(r'^第\d+[集话話]$', show_name):
            return True

        # 中文数字集号（如 "第一集"、"第二话"）
        for chinese_num in self.CHINESE_NUM_MAP.keys():
            if re.match(rf'^第{chinese_num}[集话話]$', show_name):
                return True

        # 太短（如单字母或单个汉字）
        if len(show_name.strip()) <= 1:
            return True

        # 片段关键词（如 "OP", "ED" 等）
        fragment_keywords = [
            "OP", "ED", "NCOP", "NCED", "PV", "Trailer", "SP",
            "Special", "OVA", "ONA", "NC", "EXTRAS"
        ]
        if show_name.upper() in fragment_keywords:
            return True

        return False

    def parse_with_fallback(
        self,
        filename: str,
        regex_metadata: Optional[Dict[str, Any]],
        prefer_guessit: bool = False
    ) -> Dict[str, Any]:
        """
        结合 guessit 和正则表达式的解析结果

        优先级策略：
        1. 如果 prefer_guessit=True，优先使用 guessit 结果
        2. 否则，对于关键字段（show_name, season, episode），优先使用已有值
        3. 对于质量标签等，合并两边的结果

        Args:
            filename: 视频文件名
            regex_metadata: 正则表达式解析的结果（可能为 None）
            prefer_guessit: 是否优先使用 guessit 结果

        Returns:
            合并后的元数据
        """
        guessit_metadata = self.parse(filename)

        # 处理 regex_metadata 为 None 的情况
        if regex_metadata is None:
            regex_metadata = {}

        if not guessit_metadata:
            return regex_metadata

        # 合并策略
        merged = regex_metadata.copy()

        # 保留 original_filename：优先使用传入的完整路径 filename
        # 如果传入的 filename 比 regex_metadata 的更长（通常是完整路径），使用它
        regex_original = regex_metadata.get('original_filename', '')
        if filename and len(filename) > len(regex_original):
            merged['original_filename'] = filename
            logger.debug(f"使用传入的完整路径作为 original_filename: {filename}")
        elif regex_original:
            merged['original_filename'] = regex_original
        else:
            merged['original_filename'] = filename

        # 关键字段：优先使用正则结果（除非正则结果不合理）
        key_fields = ['show_name', 'season', 'episode', 'year']

        for field in key_fields:
            regex_value = regex_metadata.get(field)
            guessit_value = guessit_metadata.get(field)

            if prefer_guessit and guessit_value is not None:
                merged[field] = guessit_value
            elif regex_value is None and guessit_value is not None:
                # 正则没有提取到，使用 guessit 结果
                merged[field] = guessit_value
                logger.debug(f"从 GuessIt 补全字段 {field}: {guessit_value}")
            elif field == 'show_name' and guessit_value is not None:
                # 特殊处理：检查正则提取的剧名是否合理
                # 如果正则结果不合理（如纯数字、仅季集信息），使用 guessit 结果
                if self._is_invalid_show_name(regex_value):
                    merged[field] = guessit_value
                    logger.debug(f"正则剧名 '{regex_value}' 不合理，使用 GuessIt 结果: {guessit_value}")
                # 检查是否 GuessIt 结果包含续集编号（如 "Lethal Weapon 2"）
                # 而正则结果丢失了续集编号（如 "Lethal Weapon"）
                elif regex_value and guessit_value:
                    guessit_stripped = guessit_value.strip()
                    regex_stripped = regex_value.strip()
                    
                    # 情况0（新增）：GuessIt 的 show_name 是正则 show_name 的前缀
                    # 且正则 show_name 包含额外信息（如季集、质量标签等）
                    # 这说明正则把额外信息也当成剧名了，应该使用 GuessIt 结果
                    if regex_stripped.startswith(guessit_stripped) and len(regex_stripped) > len(guessit_stripped):
                        # 正则的剧名以 GuessIt 剧名开头，但更长
                        # 检查额外部分是否包含非标题信息
                        extra_part = regex_stripped[len(guessit_stripped):].strip()
                        # 如果额外部分包含季集信息、质量标签等，使用 GuessIt 结果
                        non_title_patterns = [
                            r'S\d+E?\d*',  # S03E08 或 S03
                            r'\d{3,4}p',   # 2160p, 1080p
                            r'WEB', r'BluRay', r'BDRip',  # 来源
                            r'H\.?265', r'H\.?264', r'HEVC',  # 编码
                            r'DD[P]?', r'DTS', r'Atmos',  # 音频
                            r'DV', r'HDR',  # HDR 格式
                        ]
                        has_non_title_info = any(re.search(p, extra_part, re.IGNORECASE) for p in non_title_patterns)
                        if has_non_title_info:
                            merged[field] = guessit_value
                            logger.debug(f"正则剧名 '{regex_value}' 包含额外的非标题信息，使用 GuessIt 结果: {guessit_value}")
                            continue
                    
                    # 情况1：空格分隔的续集编号（如 "Lethal Weapon 2"）
                    match_space = re.match(r'^(.+?)\s+(\d+)$', guessit_stripped)
                    if match_space:
                        # GuessIt 结果以空格+数字结尾
                        base_name = match_space.group(1).strip()
                        sequel_num = match_space.group(2)
                        # 如果正则结果等于去掉续集编号的基础名称，使用 GuessIt 结果
                        if regex_stripped == base_name:
                            merged[field] = guessit_value
                            logger.debug(f"GuessIt 标题 '{guessit_value}' 包含续集编号，正则 '{regex_value}' 丢失了编号，使用 GuessIt 结果")
                            continue
                    
                    # 情况2：直接连接的数字（如 "唐探1900"）
                    # 正则可能把标题中的数字误识别为年份，导致 show_name 被截断
                    match_direct = re.match(r'^(.+?)(\d+)$', guessit_stripped)
                    if match_direct:
                        base_name_direct = match_direct.group(1).strip()
                        # 如果正则结果正好是 GuessIt 标题去掉数字后的部分
                        # 说明正则可能把数字误识别为年份
                        if regex_stripped == base_name_direct:
                            merged[field] = guessit_value
                            logger.debug(f"GuessIt 标题 '{guessit_value}' 以数字结尾，正则 '{regex_value}' 可能误把数字识别为年份，使用 GuessIt 结果")
            elif field == 'season' and guessit_value is not None:
                # 特殊处理：如果正则 season 是默认值 1，而 GuessIt 有明确的 season，使用 GuessIt
                # 检查文件名或路径中是否有明确的季号标识
                has_explicit_season = bool(
                    re.search(r'\[S\d+\]|\(S\d+\)|\.S\d+\.|-S\d+-', filename, re.IGNORECASE) or
                    re.search(r'S\d+E\d+', filename, re.IGNORECASE) or
                    re.search(r'第\d+季', filename) or
                    re.search(r'第[一二三四五六七八九十]+季', filename) or
                    re.search(r'Season\s*\d+', filename, re.IGNORECASE)
                )
                # 转换为整数进行比较（regex_value 可能是字符串）
                try:
                    regex_season = int(regex_value) if regex_value else None
                    guessit_season = int(guessit_value) if guessit_value else None
                except (ValueError, TypeError):
                    regex_season = None
                    guessit_season = None
                
                # 如果 GuessIt 识别出季号大于1，且正则是默认值1或没有季号，使用 GuessIt 结果
                if guessit_season and guessit_season > 1:
                    if regex_season is None or regex_season == 1:
                        merged[field] = guessit_value
                        logger.debug(f"GuessIt 识别到季号 {guessit_value}，正则季号为 {regex_value}，使用 GuessIt 结果")

        # 媒体类型：如果正则没有识别，使用 guessit 结果
        if not merged.get('media_type') and guessit_metadata.get('media_type'):
            merged['media_type'] = guessit_metadata['media_type']

        # 年份特殊处理：如果 show_name 被修正（正则结果与合并结果不同）
        # 说明正则可能把标题中的数字误识别为年份，此时应使用 GuessIt 的年份
        regex_show_name = regex_metadata.get('show_name', '')
        merged_show_name = merged.get('show_name', '')
        regex_year = regex_metadata.get('year')
        guessit_year = guessit_metadata.get('year')
        
        if regex_show_name != merged_show_name and guessit_year is not None:
            # show_name 被修正了，检查正则的年份是否来自标题中的数字
            # 例如：正则把 "唐探1900" 拆成 show_name="唐探", year="1900"
            # 而 GuessIt 正确识别为 show_name="唐探1900", year="2025"
            if regex_year:
                # 检查正则年份是否在 GuessIt 标题末尾（被误提取）
                if str(regex_year) in str(merged_show_name):
                    merged['year'] = guessit_year
                    logger.debug(f"正则年份 '{regex_year}' 来自标题中的数字，使用 GuessIt 年份: {guessit_year}")

        # 发布组：优先使用正则结果，如果没有则使用 guessit
        if not merged.get('release_group') and guessit_metadata.get('release_group'):
            merged['release_group'] = guessit_metadata['release_group']

        # 质量标签：合并两边的结果（去重，保持原始顺序）
        if guessit_metadata.get('quality_tags'):
            existing_tags_str = merged.get('quality_tags', '')
            existing_tags = existing_tags_str.split('.') if existing_tags_str else []
            guessit_tags = guessit_metadata['quality_tags'].split('.')
            
            # 去重并保持顺序
            seen = set()
            merged_tags = []
            for tag in existing_tags + guessit_tags:
                tag_lower = tag.lower()
                if tag_lower not in seen and tag:
                    seen.add(tag_lower)
                    merged_tags.append(tag)
            
            merged['quality_tags'] = '.'.join(merged_tags)

        # 语言信息
        if guessit_metadata.get('language'):
            merged['language'] = guessit_metadata['language']
        if guessit_metadata.get('subtitle_languages'):
            merged['subtitle_languages'] = guessit_metadata['subtitle_languages']

        # 流媒体平台
        if guessit_metadata.get('streaming_service'):
            merged['streaming_service'] = guessit_metadata['streaming_service']

        # 集标题
        if guessit_metadata.get('episode_title') and not merged.get('episode_title'):
            merged['episode_title'] = guessit_metadata['episode_title']

        return merged


def create_guessit_parser(config: Optional[Dict] = None) -> GuessItParser:
    """
    创建 GuessIt 解析器实例

    Args:
        config: 配置字典

    Returns:
        GuessItParser 实例
    """
    if config is None:
        return GuessItParser(enabled=False)

    # 从配置读取 guessit 设置
    guessit_config = config.get('guessit', {})
    enabled = guessit_config.get('enabled', True)

    return GuessItParser(enabled=enabled)
