"""
media_type 置信度解析器

统一管理 media_type 的判断逻辑，返回类型和置信度，解决多源冲突问题。
"""

import logging
import re
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


class MediaTypeResolver:
    """统一的 media_type 判断器，返回类型和置信度"""

    # 置信度阈值定义
    CONFIDENCE_MANUAL_RULE = 1.0      # 手动规则（用户明确指定）
    CONFIDENCE_BOTH_AGREE = 0.9       # 正则 + GuessIt 一致
    CONFIDENCE_GUESSIT = 0.7          # GuessIt 独立判定
    CONFIDENCE_REGEX = 0.6            # 正则独立判定
    CONFIDENCE_SMART = 0.5            # 智能判断（season+episode）
    CONFIDENCE_RELEASE_GROUP = 0.4   # release_group 推断
    CONFIDENCE_UNKNOWN = 0.0          # 未知

    def __init__(self, release_group_mapping: Optional[Dict[str, str]] = None):
        """
        初始化 MediaTypeResolver

        Args:
            release_group_mapping: 字幕组到 content_type 的映射字典
        """
        self.release_group_mapping = release_group_mapping or {}

    def resolve(self, metadata: Dict, sources: Dict[str, Optional[str]]) -> Tuple[str, float]:
        """
        根据多个来源解析 media_type 和置信度

        Args:
            metadata: 当前元数据（包含 season, episode, release_group 等）
            sources: 各来源的 media_type 判断结果
                     {
                         'manual_rule': 'tv' | 'movie' | None,
                         'regex': 'tv' | 'movie' | None,
                         'guessit': 'tv' | 'movie' | None,
                         'locked': True | False  # 是否被手动规则锁定
                     }

        Returns:
            (media_type, confidence): 最终的类型和置信度
        """
        manual_type = sources.get('manual_rule')
        regex_type = sources.get('regex')
        guessit_type = sources.get('guessit')
        is_locked = sources.get('locked', False)

        # 1. 手动规则优先（置信度 1.0，锁定）
        if is_locked and manual_type:
            logger.debug(f"media_type 来自手动规则（锁定）: {manual_type}, confidence=1.0")
            return manual_type, self.CONFIDENCE_MANUAL_RULE

        # 2. 正则 + GuessIt 都判定且一致（置信度 0.9）
        if regex_type and guessit_type and regex_type == guessit_type:
            logger.debug(f"media_type 正则与 GuessIt 一致: {regex_type}, confidence=0.9")
            return regex_type, self.CONFIDENCE_BOTH_AGREE

        # 3. GuessIt 单独判定（置信度 0.7）
        if guessit_type:
            logger.debug(f"media_type 来自 GuessIt: {guessit_type}, confidence=0.7")
            return guessit_type, self.CONFIDENCE_GUESSIT

        # 4. 正则单独判定（置信度 0.6）
        if regex_type:
            logger.debug(f"media_type 来自正则: {regex_type}, confidence=0.6")
            return regex_type, self.CONFIDENCE_REGEX

        # 5. 智能判断：有 season 和 episode（置信度 0.5）
        if self._has_tv_indicators(metadata):
            logger.debug("media_type 通过智能判断为 tv (season+episode), confidence=0.5")
            return "tv", self.CONFIDENCE_SMART

        # 6. release_group 推断（置信度 0.4）
        release_group = metadata.get("release_group", "")
        if release_group and release_group in self.release_group_mapping:
            preferred_type = self.release_group_mapping[release_group]
            # 将 content_type 转换为 media_type
            media_type = self._content_type_to_media_type(preferred_type)
            logger.debug(
                f"media_type 来自 release_group 映射: {release_group} -> "
                f"{preferred_type} -> {media_type}, confidence=0.4"
            )
            return media_type, self.CONFIDENCE_RELEASE_GROUP

        # 7. 默认：未知（置信度 0.0）
        logger.debug("media_type 未知, confidence=0.0")
        return "", self.CONFIDENCE_UNKNOWN

    def _has_tv_indicators(self, metadata: Dict) -> bool:
        """
        检查元数据是否包含强 TV 信号（season 和 episode）

        Args:
            metadata: 元数据

        Returns:
            是否为 TV 类型
        """
        season = metadata.get("season")
        episode = metadata.get("episode")

        # 必须同时有 season 和 episode 才认为是 TV
        return season is not None and episode is not None

    def _content_type_to_media_type(self, content_type: str) -> str:
        """
        将 content_type（anime, drama, movie）转换为 TMDB 的 media_type（tv, movie）

        Args:
            content_type: 内容类型（anime, drama, movie）

        Returns:
            TMDB media_type（tv 或 movie）
        """
        if content_type in ["anime", "drama"]:
            return "tv"
        elif content_type == "movie":
            return "movie"
        else:
            # 未知的 content_type，返回空
            return ""

    def should_override_by_strong_marker(self, filename: str, current_type: str,
                                         confidence: float) -> bool:
        """
        检查文件名是否包含强 TV 标记，用于决定是否覆盖当前判断

        Args:
            filename: 文件名
            current_type: 当前判断的类型
            confidence: 当前置信度

        Returns:
            是否应该保持当前类型（True = 有强标记，不应覆盖）
        """
        # 只有在置信度较低且当前判断为 tv 时才检查
        if current_type != "tv" or confidence >= self.CONFIDENCE_GUESSIT:
            return False

        # 检查是否有强 TV 标记（包含"第X话"）
        has_strong_tv_marker = bool(re.search(
            r'(?i)S\d+E\d+|第\d+[集季话]|EP\d+|Episode\s*\d+', filename
        ))

        return has_strong_tv_marker
