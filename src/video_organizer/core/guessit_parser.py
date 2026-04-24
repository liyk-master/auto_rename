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

            # PT 命名法检测：在预处理之前检查，因为 PT 模式需要原始的 "Title.20" 格式
            # 匹配 "[中文标题].英文标题.年份.其他标签.分辨率" 格式
            # 例如：[第二十条].Article.20.2024.60FPS.2160p...
            # 注意：年份和分辨率之间可能有其他标签（如 60FPS、HDR 等）
            # 修复：en_title 使用贪婪匹配 +，确保 "Article.20" 这样的标题被完整捕获
            # 从完整路径中提取文件名部分进行匹配
            filename_only = Path(preprocessed_filename).name
            pt_pattern = r'^\[(?P<cn_title>[\u4e00-\u9fff]+)\]\.(?P<en_title>[A-Za-z0-9\'"\.\s]+)\.(?P<year>\d{4})\.(?:[^\.]+\.)*?(?P<resolution>2160p|4K|UHD|FHD|1080p|720p|480p|360p|240p)'
            pt_match = re.search(pt_pattern, filename_only)
            if pt_match:
                cn_title = pt_match.group('cn_title')
                en_title = pt_match.group('en_title').strip()
                year = pt_match.group('year')
                resolution = pt_match.group('resolution')

                # 提取剩余部分中的质量标签和发布组
                # 注意：必须在 filename_only 上切片，因为 pt_match 是在 filename_only 上匹配的
                remaining = filename_only[pt_match.end():]
                logger.debug(f"PT 剩余部分: '{remaining}'")

                # 从剩余部分提取质量标签（如 WEB-DL, H.265, DTS 等）
                quality_tags = []
                # 简单的标签提取：按点分割，过滤掉空字符串
                parts = [p for p in remaining.split('.') if p]
                for part in parts:
                    # 跳过文件扩展名
                    if part.lower() in ['strm', 'mp4', 'mkv', 'avi']:
                        continue
                    # 常见的质量标签
                    if any(k in part.upper() for k in ['WEB', 'DL', 'H.', 'X.', 'DTS', 'AC3', 'AAC', 'FLAC']):
                        quality_tags.append(part)
                    elif 'P' in part and any(c.isdigit() for c in part):
                        quality_tags.append(part)

                # 提取发布组（最后一个 - 之后的部分）
                release_group = None
                if '-' in remaining:
                    release_group = remaining.split('-')[-1].strip()
                    # 移除扩展名
                    if '.' in release_group:
                        release_group = release_group.split('.')[0]

                # 直接构造元数据，跳过 GuessIt（避免误判为电视剧）
                logger.debug(f"PT 命名法检测到，直接构造元数据: cn_title={cn_title}, en_title={en_title}, year={year}")
                # quality_tags 需要是字符串（用点连接），以便与后续代码兼容
                quality_tags_str = '.'.join(quality_tags) if quality_tags else None
                metadata = {
                    'show_name': cn_title,  # 使用中文标题作为主标题
                    'en_title': en_title,
                    'year': int(year),
                    'media_type': 'movie',  # 强制指定为电影
                    'origin_filename': Path(filename).name,
                    'quality_tags': quality_tags_str,
                    'release_group': release_group,
                    'screen_size': resolution,
                    'extension': Path(filename).suffix.lower().lstrip('.'),  # 添加扩展名
                }
                logger.debug(f"PT 命名法直接构造结果: {metadata}")
                return metadata

            # PT 命名法预处理：处理 "英文标题.数字" 模式（如 "Article.20"）
            # GuessIt 会把这种格式错误拆分为 title='Article', episode=20
            # 我们的处理：把 "Title.20" 转换成 "Title 20"，让 GuessIt 正确识别完整标题
            # 注意：只处理"字母单词.数字"模式，不处理"数字.数字"（如 2160p）
            preprocessed_filename = re.sub(r'(?<!\d)([A-Za-z]+)\.(\d+)(?!\d)', r'\1 \2', preprocessed_filename)

            # 调试：记录预处理后的文件名
            logger.debug(f"预处理后文件名: '{preprocessed_filename}'")

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

    # 中文数字映射（简体+繁体）
    CHINESE_NUM_MAP = {
        # 简体
        '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
        '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
        '十': 10, '十一': 11, '十二': 12, '十三': 13, '十四': 14,
        '十五': 15, '十六': 16, '十七': 17, '十八': 18, '十九': 19,
        '二十': 20, '二十一': 21, '二十二': 22, '二十三': 23, '二十四': 24,
        '二十五': 25, '二十六': 26, '二十七': 27, '二十八': 28, '二十九': 29,
        '三十': 30,
        # 繁体
        '壹': 1, '贰': 2, '叁': 3, '肆': 4, '伍': 5,
        '陆': 6, '柒': 7, '捌': 8, '玖': 9, '拾': 10,
        '廿': 20,  # 二十的简写
    }

    # 罗马数字映射（支持 I, II, III 到 XXX）
    ROMAN_NUM_MAP = {
        'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5,
        'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10,
        'XI': 11, 'XII': 12, 'XIII': 13, 'XIV': 14, 'XV': 15,
        'XVI': 16, 'XVII': 17, 'XVIII': 18, 'XIX': 19, 'XX': 20,
        'XXI': 21, 'XXII': 22, 'XXIII': 23, 'XXIV': 24, 'XXV': 25,
        'XXVI': 26, 'XXVII': 27, 'XXVIII': 28, 'XXIX': 29, 'XXX': 30,
    }

    def _extract_season_from_string(self, text: str) -> Optional[int]:
        """
        从字符串中提取季号
        支持多种格式：第2季、第 2 季、第二季、Season 2、S2、Season I 等

        Args:
            text: 要解析的字符串

        Returns:
            季号（整数），如果无法识别则返回 None
        """
        if not text or not isinstance(text, str):
            return None

        text = text.strip()
        if not text:
            return None

        # 统一的季号提取模式（按优先级排序）
        season_patterns = [
            # 模式1: 数字季（支持空格）：第2季、第 2 季、第02季、第 02 季
            (r'^第\s*(\d+)\s*季$', lambda m: int(m.group(1))),
            # 模式2: 中文数字季（支持空格）：第二季、第 二 季
            (r'^第\s*([一二三四五六七八九十壹贰叁肆伍陆柒捌玖拾廿]+)\s*季$',
             lambda m: self.CHINESE_NUM_MAP.get(
                 m.group(1).translate(str.maketrans('壹贰叁肆伍陆柒捌玖拾', '一二三四五六七八九十'))
             )),
            # 模式3: 英文 Season（支持空格）：Season 2、Season02
            (r'^Season\s*(\d+)$', lambda m: int(m.group(1)), re.IGNORECASE),
            # 模式4: 罗马数字季：Season I、Season II
            (r'^Season\s*([IVXLC]+)$', lambda m: self.ROMAN_NUM_MAP.get(m.group(1).upper()), re.IGNORECASE),
            # 模式5: 简写 Sxx：S2、S02
            (r'^S(\d+)$', lambda m: int(m.group(1)), re.IGNORECASE),
            # 模式6: 中文简写：S2季、S02季
            (r'^S(\d+)季$', lambda m: int(m.group(1)), re.IGNORECASE),
        ]

        for pattern_config in season_patterns:
            if len(pattern_config) == 2:
                pattern, extractor = pattern_config
                flags = 0
            else:
                pattern, extractor, flags = pattern_config

            match = re.match(pattern, text, flags)
            if match:
                try:
                    season = extractor(match)
                    if season is not None and isinstance(season, int) and season >= 0:
                        return season
                except (ValueError, TypeError):
                    continue

        return None

    def _is_pure_season_directory(self, text: str) -> bool:
        """
        检查目录名是否仅为季号（不含剧名）
        例如："第2季"、"第二季"、"Season 2"、"S2" 都是纯季目录
        而 "剧名 第2季" 不是纯季目录

        Args:
            text: 目录名

        Returns:
            如果是纯季目录返回 True，否则返回 False
        """
        if not text or not isinstance(text, str):
            return False

        text = text.strip()
        if not text:
            return False

        # 检查是否完全匹配纯季号格式
        # 模式：第N季、第 N 季、第二季、第 二 季、Season N、S N、SN
        pure_season_patterns = [
            r'^第\s*\d+\s*季$',
            r'^第\s*[一二三四五六七八九十壹贰叁肆伍陆柒捌玖拾廿]+\s*季$',
            r'^Season\s*\d+$',
            r'^Season\s*[IVXLC]+$',
            r'^S\d+$',
        ]

        for pattern in pure_season_patterns:
            if re.match(pattern, text, re.IGNORECASE):
                return True

        return False

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

            # 检查是否是季目录（使用统一的提取模式）
            extracted_season = self._extract_season_from_string(part_str)
            if extracted_season is not None:
                if season is None:
                    season = extracted_season
                # 如果是纯季号目录，跳过，继续查找剧名
                is_pure_season = self._is_pure_season_directory(part_str)
                if is_pure_season:
                    continue
                # 如果不是纯季目录（目录名包含剧名+季号），继续处理剧名提取

            # 如果还没找到剧名，检查当前部分
            if show_name is None:
                # 清理父目录名中的年份和其他干扰信息
                clean_name = re.sub(r'[（\(]\d{4}[）\)]', '', part_str)
                clean_name = re.sub(r'\s*\d{4}\s*$', '', clean_name)
                clean_name = clean_name.strip()

                if not clean_name:
                    continue

                # 检查名称中是否包含嵌入的季号信息（使用 search 模式，支持剧名末尾的季号）
                # 支持的格式：
                # - 第2季、第 2 季、第二季、第 二 季
                # - Season 2、Season02、Season I
                # - S2、S02
                embedded_season = self._extract_season_from_filename(clean_name)
                if embedded_season is not None:
                    if season is None:
                        season = embedded_season
                    # 从剧名中移除季号部分（使用正则匹配并移除）
                    # 匹配可能的季号格式并从末尾移除
                    clean_name = re.sub(r'\s*(?:第\s*[\d一二三四五六七八九十壹贰叁肆伍陆柒捌玖拾廿]+\s*季|Season\s*[\dIVXLC]+|S\d+)\s*$', '', clean_name, flags=re.IGNORECASE).strip()

                if clean_name:
                    show_name = clean_name

        return (show_name, season)

    def _extract_season_from_filename(self, text: str) -> Optional[int]:
        """
        从包含剧名的字符串中提取季号（搜索模式）
        支持剧名末尾的季号格式，如 "Show Name 第2季"、"Show Name Season 2"、"Show Name 2"

        Args:
            text: 包含剧名和可能的季号的字符串

        Returns:
            季号（整数），如果无法识别则返回 None
        """
        if not text or not isinstance(text, str):
            return None

        text = text.strip()
        if not text:
            return None

        # 搜索季号格式（在字符串中查找）
        # 模式：第2季、第 2 季、第二季、第 二 季、Season 2、S2、Show Name 2
        patterns = [
            # 数字季：第2季、第 2 季、第02季（后跟空格或非季字符）
            (r'第\s*(\d+)\s*季(?:\s|[^季\w]|$)', lambda m: int(m.group(1))),
            # 中文数字季：第二季、第 二 季
            (r'第\s*([一二三四五六七八九十壹贰叁肆伍陆柒捌玖拾廿]+)\s*季(?:\s|[^季\w]|$)',
             lambda m: self.CHINESE_NUM_MAP.get(
                 m.group(1).translate(str.maketrans('壹贰叁肆伍陆柒捌玖拾', '一二三四五六七八九十'))
             )),
            # 英文 Season：Season 2、Season02（后跟空格或非单词字符）
            (r'Season\s*(\d+)(?:\s|\W|$)', lambda m: int(m.group(1)), re.IGNORECASE),
            # 罗马数字季：Season I、Season II
            (r'Season\s*([IVXLC]+)(?:\s|\W|$)', lambda m: self.ROMAN_NUM_MAP.get(m.group(1).upper()), re.IGNORECASE),
            # 简写 Sxx：S2、S02（后跟空格或非单词字符）
            (r'S(\d+)(?:\s|\W|$)', lambda m: int(m.group(1)), re.IGNORECASE),
            # 末尾直接跟数字：Show Name 2、Show Name 02
            # 条件：
            # 1. 数字前不能是"第"、"E"、"Ep"、"P"等集号标记
            # 2. 数字前不能有其他数字（避免匹配年份的前两位）
            # 3. 数字后不能是"集"、"话"、"話"等集号后缀
            # 4. 数字后不能跟更多数字（避免匹配年份的后两位）
            (r'(?<![第EePp\d])(?<![集话話])(\d{1,2})(?![集话話\d])(?=\s|\W|$)', lambda m: int(m.group(1))),
        ]

        for pattern_config in patterns:
            if len(pattern_config) == 2:
                pattern, extractor = pattern_config
                flags = 0
            else:
                pattern, extractor, flags = pattern_config

            match = re.search(pattern, text, flags)
            if match:
                try:
                    season = extractor(match)
                    if season is not None and isinstance(season, int) and season >= 0:
                        return season
                except (ValueError, TypeError):
                    continue

        return None

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

        # 如果 show_name 被识别为 "第1集" 或类似的集号格式，或被误识别为文件扩展名
        show_name = metadata.get('show_name', '')

        # 使用 _is_invalid_show_name 方法判断剧名是否无效
        # 这会检查：纯数字、季集格式、文件扩展名等无效情况
        is_invalid_show_name = self._is_invalid_show_name(show_name)

        # 清理剧名中的分类标签和季数范围
        if show_name:
            original_show_name = show_name
            # 去除开头的分类标签（如 "美剧"、"国漫"、"日漫"、"韩剧" 等）
            category_tags = ['美剧', '国漫', '日漫', '韩剧', '日剧', '泰剧', '英剧', '欧美剧', '国产剧', '动漫', '动画']
            for tag in category_tags:
                if show_name.startswith(tag):
                    show_name = show_name[len(tag):].strip()
                    logger.debug(f"去除分类标签 '{tag}': '{original_show_name}' -> '{show_name}'")
                    break

            # 从剧名中提取季号（如果还没有季号）
            # 支持格式：剧名 第2季、剧名 第 2 季、剧名 Season 2、剧名 S2
            embedded_season = self._extract_season_from_filename(show_name)
            if embedded_season is not None:
                # 如果还没有季号，使用提取的季号
                if metadata.get('season') is None:
                    metadata['season'] = embedded_season
                    logger.debug(f"从剧名中提取季号: {embedded_season}")
                # 从剧名中移除季号部分
                show_name = re.sub(
                    r'\s*(?:第\s*[\d一二三四五六七八九十壹贰叁肆伍陆柒捌玖拾廿]+\s*季|Season\s*[\dIVXLC]+|S\d+)\s*$',
                    '', show_name, flags=re.IGNORECASE
                ).strip()

            # 去除季数范围（如 "（1-5季）"、"（第一季）"、"(1-5季)" 等）
            show_name = re.sub(r'\s*[（\(][^）\)]*季[）\)]\s*$', '', show_name)
            show_name = re.sub(r'\s*[（\(]\d+[-~]\d+季[）\)]\s*$', '', show_name)
            show_name = show_name.strip()

            if show_name != original_show_name:
                metadata['show_name'] = show_name
                logger.debug(f"清理剧名: '{original_show_name}' -> '{show_name}'")

        if is_invalid_show_name:
            # 尝试从父目录获取剧名
            show_name_from_path, season_from_path = self._extract_show_info_from_path(path)

            if show_name_from_path:
                # 检查从父目录提取的剧名是否以"短数字+中文"开头
                # 如 "4驭灵师" 可能是分类编号+剧名，应去除数字
                # 但 "唐探1900" 这种末尾数字是剧名的一部分，不应去除
                # 规则：只去除开头的1-2位数字+中文的情况
                match = re.match(r'^(\d{1,2})([\u4e00-\u9fff].*)$', show_name_from_path)
                if match:
                    # 去除开头的短数字，保留中文部分
                    cleaned_name = match.group(2)
                    logger.debug(f"去除父目录剧名开头的分类编号: '{show_name_from_path}' -> '{cleaned_name}'")
                    show_name_from_path = cleaned_name

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
            show_name_val = metadata['show_name']
            # 如果 show_name 是 list，合并成字符串
            if isinstance(show_name_val, list):
                show_name_val = ' '.join(str(v) for v in show_name_val)
                logger.debug(f"GuessIt title 是 list，合并为: {show_name_val}")
            metadata['show_name'] = self._clean_title(show_name_val)

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

        # 文件扩展名被误识别为剧名（如 "strm", "mp4", "mkv" 等）
        # 当 GuessIt 解析特殊文件名时，可能将扩展名误识别为 title
        # 也检查剧名以扩展名结尾的情况（如 "FLUX strm"）
        video_extensions = [
            "strm", "mp4", "mkv", "avi", "mov", "wmv", "flv",
            "webm", "m4v", "ts", "m2ts", "iso", "vob"
        ]
        if show_name.lower() in video_extensions:
            return True
        # 检查剧名是否以扩展名结尾（如 "FLUX strm"）
        for ext in video_extensions:
            if show_name.lower().endswith(' ' + ext) or show_name.lower().endswith('.' + ext):
                return True

        # 流媒体平台名称被误识别为剧名
        # 当文件名只包含季集和技术标签时，GuessIt 可能将流媒体平台识别为 title
        streaming_services = [
            "Apple TV", "Apple TV+", "AppleTV", "AppleTV+",
            "Netflix", "NF", "Disney+", "Disney", "DisneyPlus",
            "HBO", "HBO Max", "HBOMax", "Amazon", "AMZN", "Prime",
            "Amazon Prime", "Apple+", "iTunes", "Hulu", "Peacock",
            "Paramount+", "Paramount", "Showtime", "Crunchyroll",
            "Funimation", "VRV", "Tubi", "Pluto TV", "Roku",
        ]
        if show_name in streaming_services or show_name.lower() in [s.lower() for s in streaming_services]:
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
                            r'\d{3,4}p',  # 2160p, 1080p
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
                # 使用统一的季号提取模式检测
                has_explicit_season = bool(
                    re.search(r'\[S\d+\]|\(S\d+\)|\.S\d+\.|-S\d+-', filename, re.IGNORECASE) or
                    re.search(r'S\d+E\d+', filename, re.IGNORECASE) or
                    # 支持空格的季号格式：第 2 季、第 02 季
                    re.search(r'第\s*\d+\s*季', filename) or
                    # 支持空格的中文数字季：第 二 季
                    re.search(r'第\s*[一二三四五六七八九十壹贰叁肆伍陆柒捌玖拾廿]+\s*季', filename) or
                    # 支持空格的英文季：Season 2、Season 02
                    re.search(r'Season\s*\d+', filename, re.IGNORECASE) or
                    # 罗马数字季：Season I、Season II
                    re.search(r'Season\s*[IVXLC]+', filename, re.IGNORECASE)
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
