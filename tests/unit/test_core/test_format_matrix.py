"""格式清单全表回归测试（对应 core/filename_parser/README.md 第 2 节）。

锁定 native `FilenameParser` 各层对格式清单的覆盖。英文 SxxExx（A 组）与
中文显式集号（B 组 `第N集`）由 renamer 的 `_extract_with_regex` 负责，
见 `test_renamer.py`。
"""

from video_organizer.core.filename_parser import FilenameParser


def _parse(filename):
    return FilenameParser().parse(filename)


class TestFormatMatrix:
    # C 组：方括号字幕组
    def test_C1_bracket_range_parent(self):
        """父目录 [13-25] 是集号范围（非 season），native L5 提取具体集号。"""
        md = _parse(
            "[Solo Leveling][13-25][BIG5][720P]/[Solo Leveling][25][BIG5][720P].mp4"
        )
        assert md["show_name"] == "Solo Leveling"
        assert md["episode"] == 25

    def test_C2_bracket_single(self):
        """[剧名][N][标签]（剧名在方括号内），native L5b 提取。"""
        md = _parse("[剧名][01][BIG5][1080P].mkv")
        assert md["show_name"] == "剧名"
        assert md["episode"] == 1

    # D 组：裸数字集号
    def test_D1_numeric_with_quality(self):
        md = _parse("斗破丨苍穹/210 4K.mkv")
        assert md["episode"] == 210
        assert md["media_type"] == "tv"

    def test_D2_numeric_in_year_dir(self):
        md = _parse("剧名（2026）/01.mp4")
        assert md["episode"] == 1

    # E 组：PT 命名法
    def test_E1_pt_naming_movie(self):
        md = _parse("[第二十条].Article.20.2024.60FPS.2160p.WEB-DL.HEVC.mkv")
        assert md["show_name"] == "第二十条"
        assert md["media_type"] == "movie"
        assert md["year"] == 2024

    # F 组：紧凑格式
    def test_F1_compact_show_episode(self):
        md = _parse("入青云01.mp4")
        assert md["show_name"] == "入青云"
        assert md["episode"] == 1

    # G 组：数字标题电影（不得误拆成季集）
    def test_G1_731_movie_not_parsed(self):
        """731 是 3 位数字，native 不妄下结论（留空交给 regex/TMDB）。"""
        assert _parse("731.1080p.mkv") == {}

    def test_G1_1917_movie(self):
        md = _parse("1917.mkv")
        assert md["show_name"] == "1917"
        assert md["media_type"] == "movie"

    def test_G2_sequel_number(self):
        md = _parse("The.Amazing.Spider-Man.2.2014.2160p.BluRay.REMUX.HEVC.mkv")
        assert md["show_name"] == "The Amazing Spider-Man 2"
        assert md["media_type"] == "movie"

    # 电影标题数字（4 位在中文标题末尾）不得误判
    def test_tang_tan_1900_not_episode(self):
        assert _parse("唐探1900.mkv") == {}
