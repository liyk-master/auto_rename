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
            # 使用 guessit 解析
            result = guessit(filename, options or {})

            # 转换为项目内部格式
            metadata = self._convert_result(result, filename)

            logger.debug(f"GuessIt 解析结果: {metadata}")
            return metadata

        except Exception as e:
            logger.error(f"GuessIt 解析失败: {e}")
            return {}

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
            'original_filename': Path(filename).name if Path(filename).exists() else filename,
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
                        metadata[internal_key] = value[0] if value else None
                    else:
                        metadata[internal_key] = value
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
        regex_metadata: Dict[str, Any],
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
            regex_metadata: 正则表达式解析的结果
            prefer_guessit: 是否优先使用 guessit 结果

        Returns:
            合并后的元数据
        """
        guessit_metadata = self.parse(filename)

        if not guessit_metadata:
            return regex_metadata

        # 合并策略
        merged = regex_metadata.copy()

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
                # 检查文件名中是否有明确的季号标识（如 [S2]、S02 等）
                has_explicit_season = bool(
                    re.search(r'\[S\d+\]|\(S\d+\)|\.S\d+\.|-S\d+-', filename, re.IGNORECASE) or
                    re.search(r'S\d+E\d+', filename, re.IGNORECASE) or
                    re.search(r'第\d+季', filename)
                )
                # 转换为整数进行比较（regex_value 可能是字符串）
                try:
                    regex_season = int(regex_value) if regex_value else None
                    guessit_season = int(guessit_value) if guessit_value else None
                except (ValueError, TypeError):
                    regex_season = None
                    guessit_season = None
                
                if regex_season == 1 and has_explicit_season and guessit_season and guessit_season > 1:
                    merged[field] = guessit_value
                    logger.debug(f"正则 season={regex_value} 可能是默认值，文件名有明确季号标识，使用 GuessIt 结果: {guessit_value}")

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
