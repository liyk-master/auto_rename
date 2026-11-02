"""「分段短篇 / 剧场版拆段」的 Part N 处理

背景（线上实例）：
    Grotesqqque.YOROSHIKU.Girl.Part.2.2026.NF.WEB-DL.x264.AAC.mkv

- `YOROSHIKU Girl` 是**分段名**，TMDB 里只有总条目 GROTESQQQUE (2026, id=1313587)
  → 整串搜索必然 0 条，必须剥掉分段名 / `Part 2` 才能命中
- `Part 2` 是这一段的唯一身份，输出文件名必须保留，否则同一总条目的多段
  会生成同名文件互相覆盖

覆盖点：
- `extract_part_label()`：从文件名提取 `Part N`
- `segment_part_search_candidates()`：搜索词剥离候选
- `inject_part_suffix()`：把 `Part N` 注入命名模板的文件名部分
- `VideoRenamer.generate_new_path()`：端到端文件名后缀（目录不受影响）
"""

import pytest

from video_organizer.core.renamer import VideoRenamer
from video_organizer.core.renamer.part_marker import (
    extract_part_label,
    inject_part_suffix,
    segment_part_search_candidates,
)

MOVIE_TEMPLATE = (
    "Movies/{show_name} ({year}) {tmdbid=tmdbid}/"
    "{show_name} {quality_tags}{release_group_suffix}"
)


class TestExtractPartLabel:
    def test_dotted_part(self):
        assert (
            extract_part_label(
                "Grotesqqque.YOROSHIKU.Girl.Part.2.2026.NF.WEB-DL.x264.AAC.mkv"
            )
            == "Part 2"
        )

    def test_part_without_dot(self):
        assert extract_part_label("Some Movie Part 3 2024 1080p.mkv") == "Part 3"

    def test_pt_abbreviation(self):
        assert extract_part_label("Some.Movie.Pt.3.2024.mkv") == "Part 3"

    def test_roman_numeral(self):
        assert extract_part_label("Back.To.The.Future.Part.II.1989.mkv") == "Part II"

    def test_full_path_argument(self):
        assert extract_part_label("/media/Movies/X.Part.4.2020.mkv") == "Part 4"

    @pytest.mark.parametrize(
        "filename",
        [
            "The.Matrix.1999.1080p.mkv",
            "My.Partner.2020.1080p.mkv",  # "Partner" 不是 Part N
            "Some.Partial.Movie.2021.mkv",
            "Part.of.the.Crowd.1990.mkv",  # Part 后面没有编号
            "",
        ],
    )
    def test_no_marker(self, filename):
        assert extract_part_label(filename) == ""


class TestSegmentPartSearchCandidates:
    def test_progressive_strip(self):
        """去掉 Part N 后逐词丢尾部词，直到总片名"""
        assert segment_part_search_candidates("Grotesqqque YOROSHIKU Girl Part 2") == [
            "Grotesqqque YOROSHIKU Girl",
            "Grotesqqque YOROSHIKU",
            "Grotesqqque",
        ]

    def test_part_immediately_after_title(self):
        assert segment_part_search_candidates("Some Movie Part 2") == [
            "Some Movie",
            "Some",
        ]

    def test_no_marker_returns_empty(self):
        """没有 Part/Pt 标记时不做尾部截断，避免普通 0 结果标题被误配"""
        assert segment_part_search_candidates("Blade Runner 2049") == []
        assert segment_part_search_candidates("") == []

    def test_single_word_title_with_part(self):
        assert segment_part_search_candidates("Grotesqqque Part 2") == ["Grotesqqque"]

    def test_candidate_cap(self):
        term = "A B C D E F G Part 9"
        assert len(segment_part_search_candidates(term)) <= 4


class TestInjectPartSuffix:
    def test_injects_into_file_part_only(self):
        out = inject_part_suffix(MOVIE_TEMPLATE, "Part 2", "GROTESQQQUE")
        # 目录部分不动，文件名部分插入后缀
        assert out == (
            "Movies/{show_name} ({year}) {tmdbid=tmdbid}/"
            "{show_name} Part 2 {quality_tags}{release_group_suffix}"
        )

    def test_skips_when_template_has_part_placeholder(self):
        template = "Movies/{show_name} ({year})/{show_name}{part_suffix} {quality_tags}"
        assert inject_part_suffix(template, "Part 2", "X") == template

    def test_skips_jinja_part_placeholder(self):
        template = (
            "Movies/{{ show_name }} ({{ year }})/{{ show_name }}{{ part_suffix }}.mkv"
        )
        assert inject_part_suffix(template, "Part 2", "X") == template

    def test_part_goes_after_trailing_year(self):
        """文件名里年份紧跟标题时，Part N 放在年份后："片名 (2026) Part 2"""
        template = "Movies/{show_name} ({year})/{show_name} ({year}) {quality_tags}"
        assert inject_part_suffix(template, "Part 2", "X") == (
            "Movies/{show_name} ({year})/{show_name} ({year}) Part 2 {quality_tags}"
        )

    def test_part_goes_after_year_suffix_var(self):
        template = "{movie_name}{year_suffix}/{movie_name}{year_suffix} {quality_tags}"
        assert inject_part_suffix(template, "Part 2", "X") == (
            "{movie_name}{year_suffix}/{movie_name}{year_suffix} Part 2 {quality_tags}"
        )

    def test_skips_when_title_already_contains_part(self):
        """The.Hunger.Games.Mockingjay.Part.1 → TMDB 名已含 Part 1，不能重复"""
        out = inject_part_suffix(
            MOVIE_TEMPLATE, "Part 1", "The Hunger Games: Mockingjay, Part 1"
        )
        assert out == MOVIE_TEMPLATE

    def test_no_label_leaves_template(self):
        assert inject_part_suffix(MOVIE_TEMPLATE, "", "X") == MOVIE_TEMPLATE

    def test_template_without_title_placeholder(self):
        template = "Movies/{year}/fixed-name.mkv"
        assert inject_part_suffix(template, "Part 2", "X") == template

    def test_jinja_title_placeholder(self):
        template = "Movies/{{ show_name }} ({{ year }})/{{ show_name }}.mkv"
        assert inject_part_suffix(template, "Part 2", "X") == (
            "Movies/{{ show_name }} ({{ year }})/{{ show_name }} Part 2.mkv"
        )


class TestPartNaming:
    """generate_new_path：Part N 只影响文件名，不影响目录"""

    @pytest.fixture
    def renamer(self):
        return VideoRenamer(
            "",  # 空 key → 不建 TMDB 客户端，离线可跑
            naming_rules={
                "movie": MOVIE_TEMPLATE,
                "tv_show": (
                    "{show_name} ({year})/Season {season:02d}/"
                    "{show_name} {season_episode}"
                ),
                "anime": "Anime/{show_name}/{show_name} - {episode:03d}",
                "simple": "{title}",
            },
        )

    def _metadata(self, **overrides):
        metadata = {
            "media_type": "movie",
            "show_name": "GROTESQQUE",
            "title": "GROTESQQUE",
            "year": 2026,
            "tmdb_id": 1313587,
            "quality_tags": "1080p.WEB-DL.AAC",
            "part": "Part 2",
        }
        metadata.update(overrides)
        return metadata

    def test_movie_filename_gets_part_suffix(self, renamer):
        path = renamer.generate_new_path(self._metadata(), original_path="x.mkv")
        assert "GROTESQQUE Part 2 1080p.WEB-DL.AAC" in path.name
        # 目录（含 tmdbid 标记）不重复 Part
        assert "Part" not in str(path.parent)

    def test_movie_filename_without_part(self, renamer):
        path = renamer.generate_new_path(self._metadata(part=""), original_path="x.mkv")
        assert path.name.startswith("GROTESQQUE 1080p")

    def test_tv_rule_is_not_injected(self, renamer):
        """剧集模板没有分段语义，不注入"""
        path = renamer.generate_new_path(
            self._metadata(
                media_type="tv", show_name="Some Show", title="Some Show", episode=3
            ),
            original_path="x.mkv",
        )
        assert "Part" not in path.name

    def test_user_template_can_control_position(self, renamer):
        renamer.set_naming_rules(
            {
                "movie": "Movies/{show_name} ({year})/{show_name}{part_suffix} {quality_tags}"
            }
        )
        path = renamer.generate_new_path(self._metadata(), original_path="x.mkv")
        assert path.name == "GROTESQQUE Part 2 1080p.WEB-DL.AAC.mkv"

    def test_extract_metadata_sets_part(self, renamer):
        """真实文件名 → metadata["part"]（TMDB 客户端未初始化，离线可测）"""
        metadata = renamer.extract_metadata(
            r"E:\media\Grotesqqque.YOROSHIKU.Girl.Part.2.2026.NF.WEB-DL.x264.AAC.mkv"
        )
        assert metadata.get("part") == "Part 2"

    def test_extract_metadata_without_part(self, renamer):
        metadata = renamer.extract_metadata(r"E:\media\The.Matrix.1999.1080p.mkv")
        assert not metadata.get("part")
