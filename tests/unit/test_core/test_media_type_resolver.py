"""
MediaTypeResolver 单元测试
"""

import pytest
from video_organizer.core.media_type_resolver import MediaTypeResolver


class TestMediaTypeResolver:
    """MediaTypeResolver 的单元测试"""

    def setup_method(self):
        """测试初始化"""
        # 创建一个带有字幕组映射的 resolver
        release_group_mapping = {
            "ANi": "anime",
            "VCB-Studio": "anime",
            "RARBG": "movie",
        }
        self.resolver = MediaTypeResolver(release_group_mapping)

    def test_manual_rule_locked_highest_priority(self):
        """测试手动规则锁定具有最高优先级（置信度 1.0）"""
        sources = {
            'manual_rule': 'tv',
            'regex': 'movie',
            'guessit': 'movie',
            'locked': True
        }
        metadata = {}

        media_type, confidence = self.resolver.resolve(metadata, sources)

        assert media_type == 'tv'
        assert confidence == 1.0

    def test_regex_and_guessit_agree(self):
        """测试正则和 GuessIt 一致时置信度为 0.9"""
        sources = {
            'manual_rule': None,
            'regex': 'tv',
            'guessit': 'tv',
            'locked': False
        }
        metadata = {}

        media_type, confidence = self.resolver.resolve(metadata, sources)

        assert media_type == 'tv'
        assert confidence == 0.9

    def test_guessit_only(self):
        """测试仅 GuessIt 判定时置信度为 0.7"""
        sources = {
            'manual_rule': None,
            'regex': None,
            'guessit': 'movie',
            'locked': False
        }
        metadata = {}

        media_type, confidence = self.resolver.resolve(metadata, sources)

        assert media_type == 'movie'
        assert confidence == 0.7

    def test_regex_only(self):
        """测试仅正则判定时置信度为 0.6"""
        sources = {
            'manual_rule': None,
            'regex': 'movie',
            'guessit': None,
            'locked': False
        }
        metadata = {}

        media_type, confidence = self.resolver.resolve(metadata, sources)

        assert media_type == 'movie'
        assert confidence == 0.6

    def test_smart_tv_indicators(self):
        """测试智能判断：有 season 和 episode 时判定为 tv（置信度 0.5）"""
        sources = {
            'manual_rule': None,
            'regex': None,
            'guessit': None,
            'locked': False
        }
        metadata = {'season': 1, 'episode': 5}

        media_type, confidence = self.resolver.resolve(metadata, sources)

        assert media_type == 'tv'
        assert confidence == 0.5

    def test_smart_tv_requires_both_season_and_episode(self):
        """测试智能判断必须同时有 season 和 episode"""
        # 只有 season，没有 episode
        sources = {
            'manual_rule': None,
            'regex': None,
            'guessit': None,
            'locked': False
        }
        metadata = {'season': 1}

        media_type, confidence = self.resolver.resolve(metadata, sources)

        # 应该继续到 release_group 或返回空
        assert media_type != 'tv' or confidence != 0.5

    def test_release_group_anime_mapping(self):
        """测试字幕组映射：anime 映射到 tv"""
        sources = {
            'manual_rule': None,
            'regex': None,
            'guessit': None,
            'locked': False
        }
        metadata = {'release_group': 'ANi'}

        media_type, confidence = self.resolver.resolve(metadata, sources)

        assert media_type == 'tv'  # anime -> tv
        assert confidence == 0.4

    def test_release_group_movie_mapping(self):
        """测试字幕组映射：movie 映射到 movie"""
        sources = {
            'manual_rule': None,
            'regex': None,
            'guessit': None,
            'locked': False
        }
        metadata = {'release_group': 'RARBG'}

        media_type, confidence = self.resolver.resolve(metadata, sources)

        assert media_type == 'movie'
        assert confidence == 0.4

    def test_unknown_media_type(self):
        """测试未知类型时返回空字符串和置信度 0.0"""
        sources = {
            'manual_rule': None,
            'regex': None,
            'guessit': None,
            'locked': False
        }
        metadata = {}

        media_type, confidence = self.resolver.resolve(metadata, sources)

        assert media_type == ''
        assert confidence == 0.0

    def test_content_type_to_media_type_conversion(self):
        """测试 content_type 到 media_type 的转换"""
        # anime -> tv
        assert self.resolver._content_type_to_media_type('anime') == 'tv'

        # drama -> tv
        assert self.resolver._content_type_to_media_type('drama') == 'tv'

        # movie -> movie
        assert self.resolver._content_type_to_media_type('movie') == 'movie'

        # unknown -> ''
        assert self.resolver._content_type_to_media_type('unknown') == ''

    def test_strong_tv_marker_detection(self):
        """测试强 TV 标记检测"""
        # 有强标记
        assert self.resolver.should_override_by_strong_marker(
            "Show.Name.S01E01.1080p.mkv", "tv", 0.5
        ) is True

        assert self.resolver.should_override_by_strong_marker(
            "剧名 第01集.mkv", "tv", 0.5
        ) is True

        assert self.resolver.should_override_by_strong_marker(
            "Show EP01.mkv", "tv", 0.5
        ) is True

        # 无强标记
        assert self.resolver.should_override_by_strong_marker(
            "Movie.Name.2024.1080p.mkv", "tv", 0.5
        ) is False

        # 高置信度不检查
        assert self.resolver.should_override_by_strong_marker(
            "Movie.Name.2024.mkv", "tv", 0.8
        ) is False
