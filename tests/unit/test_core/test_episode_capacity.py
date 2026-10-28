"""
集数容量过滤测试：同名「电视剧 vs 动漫」双条目按文件集号剔除容量不足候选。

背景：《凡人修仙传》TMDB 有两个同名条目——2020 动画（206 集，人气 59.7）
与 2025 真人剧（30 集，人气 12.98）。S01E194 文件放在 "(2025)" 目录下时，
目录年份命中真人剧首播年触发季年份加分，旧逻辑会选进只更新到 30 集的真人剧。
集号是硬约束：集数容不下该集的条目一定不是本文件所属条目。
"""

from unittest.mock import MagicMock, patch

import pytest

from video_organizer.core.renamer import VideoRenamer


class TestEpisodeCapacityFilter:
    """_filter_candidates_by_episode_capacity 的判定与保守策略。"""

    @pytest.fixture
    def renamer(self):
        return VideoRenamer("your_tmdb_api_key")

    def _stub_capacity(self, renamer, details_by_id):
        def fake_details(tid, **kwargs):
            return details_by_id.get(tid)

        renamer.tmdb_client = type(
            "Stub", (), {"get_tv_details": staticmethod(fake_details)}
        )()

    def test_drops_candidate_with_too_few_total_episodes(self, renamer):
        """总集数小于文件集号的候选被剔除（30 集条目容不下 E194）。"""
        self._stub_capacity(
            renamer,
            {
                1: {"number_of_episodes": 206, "seasons": []},
                2: {"number_of_episodes": 30, "seasons": []},
            },
        )
        candidates = [
            {"id": 1, "name": "动画", "media_type": "tv"},
            {"id": 2, "name": "真人剧", "media_type": "tv"},
        ]
        kept = renamer._filter_candidates_by_episode_capacity(
            candidates, {"episode": "194"}, "测试"
        )
        assert [c["id"] for c in kept] == [1]

    def test_unknown_capacity_never_dropped(self, renamer):
        """容量未知（详情缺失/集数 0）的候选一律保留，不得据此剔除。"""
        self._stub_capacity(
            renamer,
            {
                1: {"number_of_episodes": 206, "seasons": []},
                2: None,
                3: {"number_of_episodes": 0, "seasons": []},
            },
        )
        candidates = [
            {"id": 1, "name": "A", "media_type": "tv"},
            {"id": 2, "name": "B", "media_type": "tv"},
            {"id": 3, "name": "C", "media_type": "tv"},
        ]
        kept = renamer._filter_candidates_by_episode_capacity(
            candidates, {"episode": "194"}, "测试"
        )
        assert [c["id"] for c in kept] == [1, 2, 3]

    def test_uses_season_count_only_with_explicit_season(self, renamer):
        """显式季标记时按该季集数判定；默认补的 season=1 只按总集数判定。"""
        self._stub_capacity(
            renamer,
            {
                # 总集数 100，但第 1 季只有 12 集
                1: {
                    "number_of_episodes": 100,
                    "seasons": [{"season_number": 1, "episode_count": 12}],
                },
                # 正向替代：能容纳 E50
                2: {
                    "number_of_episodes": 200,
                    "seasons": [{"season_number": 1, "episode_count": 200}],
                },
            },
        )
        candidates = [
            {"id": 1, "name": "A", "media_type": "tv"},
            {"id": 2, "name": "B", "media_type": "tv"},
        ]
        # 显式 S01：第 1 季只有 12 集容不下 E50
        explicit = {
            "episode": "50",
            "season": "1",
            "show_name": "剧名",
            "original_filename": "剧名 S01E50.mkv",
        }
        # 无显式季标记（season=1 是解析器补的默认值）：只按总集数 100 判定
        defaulted = {
            "episode": "50",
            "season": "1",
            "show_name": "剧名",
            "original_filename": "剧名/50.mkv",
        }
        assert renamer._has_explicit_season(explicit) is True
        assert renamer._has_explicit_season(defaulted) is False

        def _ids(metadata):
            return [
                c["id"]
                for c in renamer._filter_candidates_by_episode_capacity(
                    [dict(c) for c in candidates], metadata, "测试"
                )
            ]

        assert _ids(explicit) == [2]
        assert _ids(defaulted) == [1, 2]

    def test_keeps_season_candidate_when_episode_within_season(self, renamer):
        """E194 落在第 1 季 206 集内时保留，落到 30 集条目时剔除。"""
        self._stub_capacity(
            renamer,
            {
                1: {
                    "number_of_episodes": 206,
                    "seasons": [{"season_number": 1, "episode_count": 206}],
                },
                2: {
                    "number_of_episodes": 30,
                    "seasons": [{"season_number": 1, "episode_count": 30}],
                },
            },
        )
        metadata = {
            "episode": "194",
            "season": "1",
            "show_name": "凡人修仙传",
            "original_filename": "凡人修仙传 S01E194.mkv",
        }
        kept = renamer._filter_candidates_by_episode_capacity(
            [
                {"id": 1, "name": "动画", "media_type": "tv"},
                {"id": 2, "name": "真人剧", "media_type": "tv"},
            ],
            metadata,
            "测试",
        )
        assert [c["id"] for c in kept] == [1]

    def test_single_tv_candidate_with_movie_not_dropped(self, renamer):
        """只有一个 tv 候选时不做容量剔除，movie 候选不会因此上位。

        《真男人》S02 在 TMDB 只收录 1 集而文件是 S02E05：若按容量剔除，
        唯一标题精确匹配的 tv 条目出局，退化成同名 movie《Pria》。
        """
        calls = []

        def fake_details(tid, **kwargs):
            calls.append(tid)
            return {
                "number_of_episodes": 9,
                "seasons": [{"season_number": 2, "episode_count": 1}],
            }

        renamer.tmdb_client = type(
            "Stub", (), {"get_tv_details": staticmethod(fake_details)}
        )()
        candidates = [
            {"id": 255650, "name": "真男人", "media_type": "tv"},
            {"id": 449126, "title": "真男人", "media_type": "movie"},
        ]
        metadata = {
            "episode": "05",
            "season": "2",
            "show_name": "真男人",
            "original_filename": "真男人 S02E05 1080p.mkv",
        }
        kept = renamer._filter_candidates_by_episode_capacity(
            candidates, metadata, "测试"
        )
        assert [c["id"] for c in kept] == [255650, 449126]
        # 单 tv 候选直接短路，不探测 TMDB
        assert calls == []

    def test_no_positive_alternative_keeps_candidates(self, renamer):
        """两个 tv 候选都容不下集号（无正向替代）时退回原列表。"""
        self._stub_capacity(
            renamer,
            {
                1: {"number_of_episodes": 10, "seasons": []},
                2: {"number_of_episodes": 20, "seasons": []},
            },
        )
        candidates = [
            {"id": 1, "name": "A", "media_type": "tv"},
            {"id": 2, "name": "B", "media_type": "tv"},
        ]
        kept = renamer._filter_candidates_by_episode_capacity(
            candidates, {"episode": "900"}, "测试"
        )
        assert [c["id"] for c in kept] == [1, 2]

    def test_non_tv_candidates_untouched(self, renamer):
        """movie 候选不参与集数容量判定，也不会因 tv 被剔除而受影响。"""
        self._stub_capacity(
            renamer,
            {
                1: {"number_of_episodes": 10, "seasons": []},
                2: {"number_of_episodes": 200, "seasons": []},
            },
        )
        candidates = [
            {"id": 1, "name": "短剧", "media_type": "tv"},
            {"id": 2, "name": "长剧", "media_type": "tv"},
            {"id": 3, "title": "电影", "media_type": "movie"},
        ]
        kept = renamer._filter_candidates_by_episode_capacity(
            candidates, {"episode": "194"}, "测试"
        )
        # id1 容量不足被剔除，id2 通过（正向替代），movie 原样保留
        assert [c["id"] for c in kept] == [2, 3]

    def test_single_candidate_short_circuits(self, renamer):
        """候选不足 2 个时不探测 TMDB（无歧义可消）。"""
        calls = []

        def fake_details(tid, **kwargs):
            calls.append(tid)
            return {"number_of_episodes": 1, "seasons": []}

        renamer.tmdb_client = type(
            "Stub", (), {"get_tv_details": staticmethod(fake_details)}
        )()
        candidates = [{"id": 1, "name": "A", "media_type": "tv"}]
        kept = renamer._filter_candidates_by_episode_capacity(
            candidates, {"episode": "194"}, "测试"
        )
        assert kept == candidates
        assert calls == []

    def test_episode_range_uses_first_number(self, renamer):
        """连集（115-120）取首个集号判定，与剧集详情查询保持一致。"""
        self._stub_capacity(
            renamer,
            {
                1: {"number_of_episodes": 200, "seasons": []},
                2: {"number_of_episodes": 100, "seasons": []},
            },
        )
        kept = renamer._filter_candidates_by_episode_capacity(
            [
                {"id": 1, "name": "A", "media_type": "tv"},
                {"id": 2, "name": "B", "media_type": "tv"},
            ],
            {"episode": "115-120"},
            "测试",
        )
        assert [c["id"] for c in kept] == [1]

    def test_capacity_queried_once_per_id(self, renamer):
        """同一 tmdb_id 的容量查询命中缓存，不重复请求。"""
        calls = []

        def fake_details(tid, **kwargs):
            calls.append(tid)
            return {"number_of_episodes": 30, "seasons": []}

        renamer.tmdb_client = type(
            "Stub", (), {"get_tv_details": staticmethod(fake_details)}
        )()
        candidates = [
            {"id": 1, "name": "A", "media_type": "tv"},
            {"id": 1, "name": "A", "media_type": "tv"},
        ]
        renamer._filter_candidates_by_episode_capacity(
            candidates, {"episode": "194"}, "测试"
        )
        renamer._filter_candidates_by_episode_capacity(
            candidates, {"episode": "194"}, "测试"
        )
        assert calls == [1]

    def test_failed_lookup_is_retried(self, renamer):
        """瞬时失败不被固化为「容量未知」，下次调用重新探测。"""
        calls = []

        def fake_details(tid, **kwargs):
            calls.append(tid)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return {"number_of_episodes": 30, "seasons": []}

        renamer.tmdb_client = type(
            "Stub", (), {"get_tv_details": staticmethod(fake_details)}
        )()
        candidates = [
            {"id": 1, "name": "A", "media_type": "tv"},
            {"id": 2, "name": "B", "media_type": "tv"},
        ]
        first = renamer._filter_candidates_by_episode_capacity(
            candidates, {"episode": "194"}, "测试"
        )
        # 第一次 id=1 失败（保留），id=2 容量 30 ≤ 194 被剔除
        assert [c["id"] for c in first] == [1]
        second = renamer._filter_candidates_by_episode_capacity(
            candidates, {"episode": "194"}, "测试"
        )
        # 第二次 id=1 重新探测并命中缓存成功 → 两个候选都不足 → 退回原列表
        assert [c["id"] for c in second] == [1, 2]
        assert calls == [1, 2, 1]


class TestEpisodeCapacityEndToEnd:
    """端到端回归：目录年份加分不得压倒集号硬约束。"""

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_dir_year_no_longer_overrides_episode_capacity(self, mock_tmdb_client):
        """《凡人修仙传》S01E194 在 (2025) 目录下应选 206 集动画而非 30 集真人剧。

        旧逻辑：243224（真人剧，2025 首播）季年份 +500 / 目标年份 +10000，
        压过人气更高的 106449（动画）→ 194 集文件被识别成 30 集真人剧。
        """
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance

        def _tv_details(tid, **kw):
            if tid == 106449:
                return {
                    "id": 106449,
                    "name": "凡人修仙传",
                    "first_air_date": "2020-07-25",
                    "number_of_episodes": 206,
                    "number_of_seasons": 1,
                    "seasons": [
                        {
                            "season_number": 1,
                            "air_date": "2020-07-25",
                            "episode_count": 206,
                        }
                    ],
                    "genres": [{"name": "动画"}],
                    "original_name": "凡人修仙传",
                    "original_language": "zh",
                    "origin_country": ["CN"],
                    "overview": "x",
                    "poster_path": "",
                    "backdrop_path": "",
                    "vote_average": 8.0,
                    "vote_count": 100,
                    "status": "Returning Series",
                }
            if tid == 243224:
                return {
                    "id": 243224,
                    "name": "凡人修仙传",
                    "first_air_date": "2025-07-27",
                    "number_of_episodes": 30,
                    "number_of_seasons": 1,
                    "seasons": [
                        {
                            "season_number": 1,
                            "air_date": "2025-07-27",
                            "episode_count": 30,
                        }
                    ],
                    "genres": [{"name": "剧情"}],
                    "original_name": "凡人修仙传",
                    "original_language": "zh",
                    "origin_country": ["CN"],
                    "overview": "x",
                    "poster_path": "",
                    "backdrop_path": "",
                    "vote_average": 6.0,
                    "vote_count": 50,
                    "status": "Ended",
                }
            return {"id": tid, "name": "凡人修仙传", "seasons": []}

        mock_client_instance.get_tv_details.side_effect = _tv_details
        mock_client_instance.search_all_pages.return_value = [
            {
                "id": 106449,
                "name": "凡人修仙传",
                "media_type": "tv",
                "first_air_date": "2020-07-25",
                "popularity": 59.6961,
                "genre_ids": [16, 10759, 18],
            },
            {
                "id": 243224,
                "name": "凡人修仙传",
                "media_type": "tv",
                "first_air_date": "2025-07-27",
                "popularity": 12.9835,
                "genre_ids": [18, 10765],
            },
        ]
        mock_client_instance.search_web_fallback.return_value = []
        mock_client_instance.find_by_imdb_id.return_value = None
        mock_client_instance.get_movie_details.return_value = {}
        mock_client_instance.get_external_ids.return_value = {}
        mock_client_instance.get_tv_credits.return_value = {"cast": [], "crew": []}
        mock_client_instance.get_tv_episode_details.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        md = renamer.extract_metadata(
            r"\影视资源\Downloads\凡人修仙传 (2025)\凡人修仙传 S01E194 "
            r"2160p.WEB-DL.H264.AAC-CMCTV.mkv"
        )

        assert md.get("tmdb_id") == 106449, md
        assert md.get("media_type") == "tv", md
        assert md.get("episode") == "194", md
        assert "动画" in (md.get("genres") or []), md

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_exact_tv_match_kept_when_tmdb_season_lags(self, mock_tmdb_client):
        """回归：《真男人》S02E05——TMDB 只收录 S02 第 1 集，也要以标题精确匹配的
        tv 条目为主，不能被集数容量剔除而退化成同名 movie。

        候选：tv id=255650（真男人/Maschi veri，总 9 集，S02 仅 1 集）+
        movie id=449126（真男人/Pria, 2017）。旧容量逻辑会因“第2季 1 集 < E5”
        剔除唯一的 tv 候选，把 movie 洗上去。
        """
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance

        def _tv_details(tid, **kw):
            if tid == 255650:
                return {
                    "id": 255650,
                    "name": "真男人",
                    "first_air_date": "2025-05-21",
                    "number_of_episodes": 9,
                    "number_of_seasons": 2,
                    "seasons": [
                        {
                            "season_number": 1,
                            "air_date": "2025-05-21",
                            "episode_count": 8,
                        },
                        {
                            "season_number": 2,
                            "air_date": "2026-10-07",
                            "episode_count": 1,
                        },
                    ],
                    "genres": [{"name": "喜剧"}],
                    "original_name": "Maschi veri",
                    "original_language": "it",
                    "origin_country": ["IT"],
                    "overview": "x",
                    "poster_path": "",
                    "backdrop_path": "",
                    "vote_average": 7.0,
                    "vote_count": 10,
                    "status": "Returning Series",
                }
            return {"id": tid, "name": "真男人", "seasons": []}

        mock_client_instance.get_tv_details.side_effect = _tv_details
        mock_client_instance.search_all_pages.return_value = [
            {
                "id": 255650,
                "name": "真男人",
                "media_type": "tv",
                "first_air_date": "2025-05-21",
                "popularity": 6.9724,
                "genre_ids": [35],
            },
            {
                "id": 449126,
                "title": "真男人",
                "media_type": "movie",
                "release_date": "2017-05-15",
                "popularity": 1.6053,
                "genre_ids": [18],
            },
        ]
        mock_client_instance.search_web_fallback.return_value = []
        mock_client_instance.find_by_imdb_id.return_value = None
        mock_client_instance.get_movie_details.return_value = {}
        mock_client_instance.get_external_ids.return_value = {}
        mock_client_instance.get_tv_credits.return_value = {"cast": [], "crew": []}
        mock_client_instance.get_tv_episode_details.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        md = renamer.extract_metadata(
            "真男人 S02E05 1080p.NF.WEB-DL.DDP.Web.H.264.Dolby Digital Plus."
            "Netflix-CHDWEB.mkv"
        )

        assert md.get("tmdb_id") == 255650, md
        assert md.get("media_type") == "tv", md
        assert str(md.get("episode")) in ("05", "5"), md
        assert "喜剧" in (md.get("genres") or []), md
