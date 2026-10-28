from hmac import new
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from video_organizer.core.tmdb_client import TMDBClient


def _card(seq, media_type, entity_id, title, orig, date, adult="false"):
    """构造一张模拟 TMDB 网页搜索结果卡片（comp:media-card 结构）。"""
    orig_span = f'<span class="font-light"> ({orig})</span>' if orig else ""
    adult_span = (
        '<span class="adult bg-gray-500 rounded-lg text-white text-sm px-2 py-0 ml-2">成人内容</span>'
        if adult == "true"
        else ""
    )
    return (
        f'<div id="card-{seq}" class="comp:media-card w-full bg-white border '
        f'border-light-grey hover:border-gray-300 rounded-lg shadow-sm overflow-hidden tight" '
        f'data-object-id="obj-{seq}"><div class="flex flex-nowrap"><div class="relative '
        f'border-r border-light-grey min-w-[94px] w-[94px]"><a class="flex w-full" '
        f'data-id="obj-{seq}" data-media-type="{media_type}" data-media-adult="{adult}" '
        f'href="/{media_type}/{entity_id}-slug"><div class="image aspect-poster glyphicons '
        f'picture no_image_holder bg-light-grey! grey rounded-none! overflow-hidden">'
        f'<img alt="{title}" class="poster w-full block" loading="lazy" decoding="async" '
        f'fetchpriority="low" src="x.jpg" /></div></a></div><div class="flex flex-wrap '
        f'items-center content-center w-full p-3"><div class="w-full flex items-center">'
        f'<div class="flex flex-wrap w-full flex-wrap"><a class="font-normal hover:underline '
        f'hover:underline-offset-2 hover:decoration-current hover:text-tmdb-light-blue" '
        f'data-id="obj-{seq}" data-media-type="{media_type}" data-media-adult="{adult}" '
        f'href="/{media_type}/{entity_id}-slug"><h2 class="font-semibold text-base/6 m-0 '
        f'whitespace-normal"><span>{title}</span>{orig_span}{adult_span}</h2></a>'
        f'<span class="release_date w-full font-light">{date}</span></div></div></div></div></div></div>'
    )


class TestTMDBClient:
    """Test cases for TMDBClient."""

    @pytest.fixture
    def tmdb_client(self):
        """Create a TMDBClient instance for testing."""
        return TMDBClient(
            "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJmMzIxNzc3YjA1NzE0NTk1ZTA5YTVkZTlkYjc3ZmRlYyIsIm5iZiI6MTcxNzY3NTA3OS4zNDMwMDAyLCJzdWIiOiI2NjYxYTQ0NzJkZTI5YzdhMjdhNDI5YjIiLCJzY29wZXMiOlsiYXBpX3JlYWQiXSwidmVyc2lvbiI6MX0.cjyI_jYk5TkEqMfz5GZhfLCdET-qGM2wfKjTjboqNoY"
        )

    def _fake_page(self, query):
        """构造模拟 TMDB 网页搜索结果页：33 条热门噪音 + 第 34 位成人条目《映像》(1975)。"""
        cards = ""
        # 噪音：tv + movie 混合，标题含查询词子串但都不是精确匹配
        for i in range(33):
            mt = "tv" if i % 2 == 0 else "movie"
            cards += _card(
                i,
                mt,
                90000 + i,
                f"映像占位标题{i}",
                f"Noise Title {i}",
                f"20{i % 20 + 5} 年 01 月 01 日",
            )
        # 冷门成人条目：精确标题命中《映像》(1975)，热度低被排到第 34 位
        cards += _card(
            100,
            "movie",
            67018,
            "映像",
            "The Image",
            "1975 年 12 月 20 日",
            adult="true",
        )
        # 再追加几条约束总条数
        for i in range(6):
            cards += _card(
                200 + i, "movie", 80000 + i, f"其他映像{i}", "", "2010 年 05 月 01 日"
            )
        return (
            f'<div id="movie_results" class="search_results movie">'
            f'<div class="results flex">{cards}</div></div>'
        ).encode("utf-8")

    def _patch_urlopen(self, html_bytes):
        resp = Mock()
        resp.read.return_value = html_bytes
        return patch("urllib.request.urlopen", return_value=resp)

    def test_web_fallback_surfaces_deep_ranked_exact_title(self, tmdb_client):
        """网页兜底：冷门/成人条目按热度排到 30+ 名时，精确标题匹配必须浮到最前。

        回归场景：`映像 (1975) - 2160p...iso`（电影 TMDB id=67018，成人 flag）。
        API 中文索引（连 include_adult=true）永远搜不到它，只有开启成人偏好的
        网页搜索能命中，但旧逻辑按页序截前 5 条会把它丢掉。
        """
        with self._patch_urlopen(self._fake_page("映像")):
            results = tmdb_client.search_web_fallback("映像", language="zh-CN")

        ids = [r["id"] for r in results]
        assert 67018 in ids, f"深度排名条目未被提取: {ids}"
        # 精确标题匹配需浮到最前，且携带解析出的发布日期/原始名
        assert results[0]["id"] == 67018
        assert results[0]["title"] == "映像"
        assert results[0]["release_date"] == "1975-12-20"
        assert results[0]["original_title"] == "The Image"
        assert results[0]["media_type"] == "movie"

    def test_web_fallback_media_type_filter(self, tmdb_client):
        """网页兜底：指定 movie 后不得混入 tv 卡片。"""
        with self._patch_urlopen(self._fake_page("映像")):
            results = tmdb_client.search_web_fallback(
                "映像", language="zh-CN", media_type="movie"
            )
        assert results
        assert all(r["media_type"] == "movie" for r in results)
        assert any(r["id"] == 67018 for r in results)

    def test_web_fallback_cap(self, tmdb_client):
        """网页兜底：返回条数受 WEB_FALLBACK_MAX_RESULTS 上限约束。"""
        with self._patch_urlopen(self._fake_page("映像")):
            results = tmdb_client.search_web_fallback("映像", language="zh-CN")
        assert len(results) <= 20

    def test_search_video_show(self, tmdb_client):
        """Test search video show."""
        results = tmdb_client.search_video_show("超人")
        # assert len(results) > 0
        # assert results[0]["name"] == "超人"
        # assert results[0]["media_type"] == "tv"
        # assert results[0]["id"] == 1000000
