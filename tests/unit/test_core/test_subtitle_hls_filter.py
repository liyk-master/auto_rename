"""
Tests for HLS/DASH 分片字幕识别与字幕上传去重。

背景：用 m3u8/HLS 方式下载剧集后，目录里会留下几十上百个 playlistN.vtt
分片。旧逻辑把它们全部当字幕，重命名成同一个 <视频名>.srt 逐个上传，
远端文件互相覆盖、进度看起来像卡死。
"""

from pathlib import Path

from video_organizer.core.subtitle_handler import (
    SubtitleHandler,
    is_hls_segment_subtitle,
    plan_subtitle_uploads,
)


VIDEO_NAME = "青之箱 (2024) S02E04 NF.WebRip.H265-Feibanyama.mkv"
VIDEO_STEM = "青之箱 (2024) S02E04 NF.WebRip.H265-Feibanyama"


def _write(path: Path, content: str = "1\n00:00:01,000 --> 00:00:02,000\nhi\n") -> Path:
    path.write_text(content, encoding="utf-8")
    return path


class TestIsHlsSegmentSubtitle:
    """按文件名/内容识别 HLS 分片"""

    def test_playlist_segments_detected(self, tmp_path):
        for name in ("playlist1.vtt", "playlist33.vtt", "segment12.vtt",
                     "chunk_07.vtt", "index5.vtt", "part10.srt"):
            assert is_hls_segment_subtitle(tmp_path / name) is True, name

    def test_real_subtitles_not_detected(self, tmp_path):
        for name in (
            f"{VIDEO_STEM}.srt",
            f"{VIDEO_STEM}.zh.srt",
            "English.srt",
            "Movie.2019.1080p.BluRay.eng.ass",
            "player.srt",  # 以 playlist 开头但不是分片
        ):
            assert is_hls_segment_subtitle(_write(tmp_path / name)) is False, name

    def test_vtt_with_timestamp_map_detected_by_content(self, tmp_path):
        """HLS 打包的 WebVTT 片段带 X-TIMESTAMP-MAP，即使文件名正常也要跳过"""
        path = tmp_path / "subtitle.vtt"
        path.write_text(
            "WEBVTT\nX-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000\n\n"
            "00:00:01.000 --> 00:00:02.000\nhi\n",
            encoding="utf-8",
        )
        assert is_hls_segment_subtitle(path) is True

    def test_plain_vtt_kept(self, tmp_path):
        path = tmp_path / "subtitle.vtt"
        path.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhi\n", encoding="utf-8")
        assert is_hls_segment_subtitle(path) is False

    def test_missing_file_does_not_raise(self, tmp_path):
        assert is_hls_segment_subtitle(tmp_path / "playlist9.vtt") is True
        assert is_hls_segment_subtitle(tmp_path / "not-there.vtt") is False


class TestPlanSubtitleUploads:
    """上传计划：剔除分片 + 目标名去重"""

    def test_hls_segments_filtered_out(self, tmp_path):
        video = tmp_path / VIDEO_NAME
        _write(video, "x" * 1000)
        _write(tmp_path / f"{VIDEO_STEM}.srt", "1\n" * 500)
        for i in range(1, 40):
            _write(tmp_path / f"playlist{i}.vtt", "WEBVTT\n\n")

        files = [f for f in sorted(tmp_path.iterdir()) if f.suffix.lower() != ".mkv"]
        plans, junk, dup = plan_subtitle_uploads(
            files,
            VIDEO_NAME,
            lambda f: f"{Path(f).stem}.srt" if Path(f).suffix.lower() != ".srt" else f.name,
        )

        assert [p.name for p, _ in plans] == [f"{VIDEO_STEM}.srt"]
        assert len(junk) == 39
        assert dup == []

    def test_duplicate_target_name_keeps_best(self, tmp_path):
        """两个无语言标识的字幕会撞同一个目标名，只保留体积更大的那个"""
        small = _write(tmp_path / "a.srt", "1\n")
        big = _write(tmp_path / "b.srt", "2\n" * 2000)

        plans, junk, dup = plan_subtitle_uploads(
            [small, big], VIDEO_NAME, lambda f: f"{VIDEO_STEM}.srt"
        )

        assert [(p.name, t) for p, t in plans] == [("b.srt", f"{VIDEO_STEM}.srt")]
        assert junk == []
        assert [p.name for p in dup] == ["a.srt"]

    def test_video_stem_match_wins_over_size(self, tmp_path):
        """与视频同名的字幕优先，即使体积更小"""
        exact = _write(tmp_path / f"{VIDEO_STEM}.srt", "1\n")
        other = _write(tmp_path / "huge.srt", "2\n" * 5000)

        plans, _, dup = plan_subtitle_uploads(
            [other, exact], VIDEO_NAME, lambda f: f"{VIDEO_STEM}.srt"
        )

        assert [(p.name, t) for p, t in plans] == [(f"{VIDEO_STEM}.srt", f"{VIDEO_STEM}.srt")]
        assert [p.name for p in dup] == ["huge.srt"]

    def test_distinct_language_targets_all_kept(self, tmp_path):
        zh = _write(tmp_path / "Movie.zh.srt", "1\n")
        en = _write(tmp_path / "Movie.en.srt", "1\n")

        plans, junk, dup = plan_subtitle_uploads(
            [zh, en],
            "Movie.mkv",
            lambda f: f"Movie.{Path(f).stem.split('.')[-1]}.srt",
        )

        assert [t for _, t in plans] == ["Movie.zh.srt", "Movie.en.srt"]
        assert (junk, dup) == ([], [])

    def test_no_subtitles(self, tmp_path):
        plans, junk, dup = plan_subtitle_uploads([], VIDEO_NAME, lambda f: f.name)
        assert (plans, junk, dup) == ([], [], [])


class TestSubtitleHandlerSkipsHlsSegments:
    """SubtitleHandler 不应把分片当作视频字幕处理"""

    def test_process_subtitle_file_skips_segment(self, tmp_path):
        handler = SubtitleHandler()
        video = _write(tmp_path / "Show.S01E01.mkv", "x")
        segment = _write(tmp_path / "playlist12.vtt", "WEBVTT\n\n")

        result = handler.process_subtitle_file(segment, tmp_path)

        assert result is None
        assert segment.exists()
        assert video.exists()
