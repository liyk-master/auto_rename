"""
GuessItParser 单元测试
"""

import pytest

from video_organizer.core.guessit_parser.parser import (
    GuessItParser,
    GUESSIT_AVAILABLE,
)

pytestmark = pytest.mark.skipif(not GUESSIT_AVAILABLE, reason="guessit 库未安装")


class TestGuessItParser:
    """GuessItParser 的单元测试"""

    @pytest.fixture
    def parser(self):
        return GuessItParser(enabled=True)

    def test_parse_with_fallback_prefers_guessit_tv_over_regex_movie_default(
        self, parser
    ):
        """测试正则兜底 movie + GuessIt 识别 tv 带季集时，优先使用 GuessIt"""
        regex_metadata = {
            "original_filename": "8.mp4",
            "cleaned_name": "8",
            "media_type": "movie",  # 正则兜底默认
        }
        result = parser.parse_with_fallback(
            r"少年派 (2019)\Season01\8.mp4",
            regex_metadata,
            prefer_guessit=False,
        )

        assert result.get("media_type") == "tv"
        assert result.get("season") is not None

    def test_parse_with_fallback_keeps_regex_tv_when_guessit_says_movie(
        self, parser
    ):
        """测试正则 tv 与 GuessIt movie 冲突且正则无强 TV 标记时，优先 GuessIt"""
        regex_metadata = {
            "original_filename": "Movie.Name.mkv",
            "media_type": "tv",  # 弱信号 tv
        }
        result = parser.parse_with_fallback(
            "Movie.Name.mkv",
            regex_metadata,
            prefer_guessit=False,
        )

        # GuessIt 对无季集信息的纯文件名通常判为 movie，应覆盖正则的弱 tv
        assert result.get("media_type") == "movie"
