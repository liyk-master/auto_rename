"""洗码（Hash Wash）模块单元测试。

覆盖：
- 开关控制（enabled=False 时完全不动文件）
- copy 模式：原文件字节不变、副本哈希变化、清理后副本消失
- inplace 模式：原文件被追加、重复洗码幂等（不会越洗越大）
- 异常回落：洗码失败/空间不足时仍返回原路径，不抛异常
"""

import hashlib
import shutil
from pathlib import Path

import pytest

from src.video_organizer.core.hash_washer import HashWasher, WashResult


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture()
def video_file(tmp_path: Path) -> Path:
    """伪视频文件（内容随机，保证与任何网盘已有条目不同）"""
    source = tmp_path / "downloads" / "Show.S01E01.1080p.mkv"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"\x1a\x45\xdf\xa3" + b"payload" * 20000)
    return source


class TestDisabledByDefault:
    def test_disabled_returns_original_path(self, video_file):
        washer = HashWasher({"enabled": False})
        result = washer.wash(str(video_file))

        assert result.washed is False
        assert result.upload_path == str(video_file)
        assert result.is_temp is False
        assert result.mode == "none"

    def test_empty_config_is_disabled(self, video_file):
        """没配 [hash_wash] 时默认关闭，不能悄悄改用户文件"""
        washer = HashWasher({})
        assert washer.enabled is False
        assert washer.wash(str(video_file)).washed is False

    def test_disabled_does_not_touch_file(self, video_file):
        before = _digest(video_file)
        size_before = video_file.stat().st_size

        HashWasher({}).wash(str(video_file))

        assert _digest(video_file) == before
        assert video_file.stat().st_size == size_before


class TestCopyMode:
    def test_original_untouched_and_copy_hash_differs(self, video_file, tmp_path):
        temp_dir = tmp_path / "wash"
        washer = HashWasher(
            {
                "enabled": True,
                "mode": "copy",
                "min_bytes": 64,
                "max_bytes": 256,
                "temp_dir": str(temp_dir),
            }
        )
        original_digest = _digest(video_file)
        original_size = video_file.stat().st_size

        result = washer.wash(str(video_file))

        assert result.washed is True
        assert result.is_temp is True
        assert result.mode == "copy"

        upload = Path(result.upload_path)
        assert upload.exists()
        assert upload.parent == temp_dir
        # 哈希与大小都变了（网盘秒传按哈希判重）
        assert _digest(upload) != original_digest
        assert upload.stat().st_size > original_size
        assert 64 <= upload.stat().st_size - original_size <= 256
        # 前缀内容与原文件完全一致（只是尾部追加垃圾字节，不影响播放）
        assert upload.read_bytes()[:original_size] == video_file.read_bytes()

        # 原文件一个字节都不动（PT 保种安全）
        assert _digest(video_file) == original_digest
        assert video_file.stat().st_size == original_size

    def test_cleanup_removes_copy_keeps_original(self, video_file, tmp_path):
        washer = HashWasher(
            {"enabled": True, "mode": "copy", "temp_dir": str(tmp_path / "wash")}
        )
        result = washer.wash(str(video_file))
        upload = Path(result.upload_path)
        assert upload.exists()

        washer.cleanup(result)

        assert not upload.exists()
        assert video_file.exists()

    def test_cleanup_is_noop_for_original_result(self, video_file):
        washer = HashWasher({"enabled": False})
        result = washer.wash(str(video_file))

        washer.cleanup(result)  # 不应删除原文件
        washer.cleanup(None)

        assert video_file.exists()

    def test_keep_washed_retains_copy(self, video_file, tmp_path):
        washer = HashWasher(
            {
                "enabled": True,
                "mode": "copy",
                "temp_dir": str(tmp_path / "wash"),
                "keep_washed": True,
            }
        )
        result = washer.wash(str(video_file))

        washer.cleanup(result)

        assert Path(result.upload_path).exists()

    def test_same_basename_from_different_dirs_not_clobbered(self, tmp_path):
        """两个不同目录的同名文件并发洗码时，副本不能互相覆盖"""
        a = tmp_path / "dir_a" / "same.mkv"
        b = tmp_path / "dir_b" / "same.mkv"
        for path, payload in ((a, b"AAA"), (b, b"BBB")):
            path.parent.mkdir(parents=True)
            path.write_bytes(payload * 1000)

        washer = HashWasher(
            {"enabled": True, "mode": "copy", "temp_dir": str(tmp_path / "wash")}
        )
        first = washer.wash(str(a))
        second = washer.wash(str(b))

        assert first.upload_path != second.upload_path
        assert Path(first.upload_path).exists()
        assert Path(second.upload_path).exists()
        assert Path(second.upload_path).read_bytes().startswith(b"BBB")

    def test_missing_file_falls_back_to_original(self, tmp_path):
        washer = HashWasher(
            {"enabled": True, "mode": "copy", "temp_dir": str(tmp_path / "wash")}
        )
        result = washer.wash(str(tmp_path / "nope.mkv"))

        assert result.washed is False
        assert result.upload_path == str(tmp_path / "nope.mkv")

    def test_zero_max_bytes_still_changes_hash(self, video_file, tmp_path):
        """min/max 配成 0 时至少追加 1 字节，仍达到洗码目的"""
        washer = HashWasher(
            {
                "enabled": True,
                "mode": "copy",
                "min_bytes": 0,
                "max_bytes": 0,
                "temp_dir": str(tmp_path / "wash"),
            }
        )
        before = _digest(video_file)

        result = washer.wash(str(video_file))

        assert result.washed is True
        assert _digest(Path(result.upload_path)) != before

    def test_two_washes_produce_different_hashes(self, video_file, tmp_path):
        """每次洗码用新的随机尾部，重复上传同一文件得到不同哈希"""
        washer = HashWasher(
            {"enabled": True, "mode": "copy", "temp_dir": str(tmp_path / "wash")}
        )
        first = Path(washer.wash(str(video_file)).upload_path).read_bytes()
        second = Path(washer.wash(str(video_file)).upload_path).read_bytes()

        assert hashlib.sha256(first).hexdigest() != hashlib.sha256(second).hexdigest()


class TestInplaceMode:
    def test_appends_bytes_to_original(self, video_file):
        washer = HashWasher(
            {"enabled": True, "mode": "inplace", "min_bytes": 8, "max_bytes": 32}
        )
        before = video_file.read_bytes()
        original_digest = hashlib.sha256(before).hexdigest()

        result = washer.wash(str(video_file))

        assert result.washed is True
        assert result.is_temp is False
        assert result.upload_path == str(video_file)
        after = video_file.read_bytes()
        assert after[: len(before)] == before
        assert 8 <= len(after) - len(before) <= 32
        assert hashlib.sha256(after).hexdigest() != original_digest

    def test_repeat_wash_is_idempotent(self, video_file, tmp_path):
        """重试上传时不能每次都再追加一段，否则文件越洗越大"""
        washer = HashWasher(
            {
                "enabled": True,
                "mode": "inplace",
                "temp_dir": str(tmp_path / "wash"),
            }
        )
        original_size = video_file.stat().st_size

        first = washer.wash(str(video_file))
        size_after_first = video_file.stat().st_size
        second = washer.wash(str(video_file))

        assert first.washed is True
        assert second.washed is False
        assert video_file.stat().st_size == size_after_first
        assert size_after_first > original_size

    def test_modified_file_gets_washed_again(self, video_file, tmp_path):
        """记录的大小与当前大小不一致（文件被重新下载）→ 重新洗码"""
        washer = HashWasher(
            {"enabled": True, "mode": "inplace", "temp_dir": str(tmp_path / "wash")}
        )
        washer.wash(str(video_file))
        size_washed = video_file.stat().st_size

        # 模拟下载器重新写入原始文件（回到洗码前）
        with video_file.open("r+b") as f:
            f.truncate(size_washed - 100)

        result = washer.wash(str(video_file))

        assert result.washed is True
        assert video_file.stat().st_size > size_washed - 100

    def test_state_survives_new_instance(self, video_file, tmp_path):
        """进程重启后仍能识别已洗过的文件（状态落盘）"""
        temp_dir = tmp_path / "wash"
        first_washer = HashWasher(
            {"enabled": True, "mode": "inplace", "temp_dir": str(temp_dir)}
        )
        first_washer.wash(str(video_file))
        size_after = video_file.stat().st_size
        assert (temp_dir / "state.json").exists()

        second_washer = HashWasher(
            {"enabled": True, "mode": "inplace", "temp_dir": str(temp_dir)}
        )
        result = second_washer.wash(str(video_file))

        assert result.washed is False
        assert video_file.stat().st_size == size_after

    def test_corrupt_state_file_is_ignored(self, video_file, tmp_path):
        temp_dir = tmp_path / "wash"
        temp_dir.mkdir(parents=True)
        (temp_dir / "state.json").write_text("{ not json", encoding="utf-8")

        washer = HashWasher(
            {"enabled": True, "mode": "inplace", "temp_dir": str(temp_dir)}
        )
        result = washer.wash(str(video_file))

        assert result.washed is True


class TestConfigParsing:
    def test_string_values_from_configparser(self):
        """config.ini 读出来都是字符串，开关/数字必须能正确转换"""
        washer = HashWasher(
            {
                "enabled": "true",
                "mode": "INPLACE",
                "min_bytes": "10",
                "max_bytes": "20",
                "temp_dir": " data/wash ",
                "keep_washed": "False",
            }
        )
        assert washer.enabled is True
        assert washer.mode == "inplace"
        assert washer.min_bytes == 10
        assert washer.max_bytes == 20
        assert washer.temp_dir == Path("data/wash")
        assert washer.keep_washed is False

    def test_min_greater_than_max_is_clamped(self):
        washer = HashWasher({"enabled": True, "min_bytes": 500, "max_bytes": 10})
        assert washer.max_bytes == 500

    def test_invalid_mode_falls_back_to_copy(self):
        assert HashWasher({"mode": "weird"}).mode == "copy"

    def test_invalid_int_falls_back_to_default(self):
        washer = HashWasher({"min_bytes": "abc", "max_bytes": None})
        assert washer.min_bytes == 1024
        assert washer.max_bytes == 65536


class TestFailureFallback:
    def test_wash_failure_does_not_raise(self, video_file, tmp_path, monkeypatch):
        """洗码内部异常不得中断上传流程，回落为上传原文件"""
        washer = HashWasher(
            {"enabled": True, "mode": "copy", "temp_dir": str(tmp_path / "wash")}
        )

        def _boom(*args, **kwargs):
            raise OSError("disk on fire")

        monkeypatch.setattr(shutil, "copyfileobj", _boom)
        result = washer.wash(str(video_file))

        assert isinstance(result, WashResult)
        assert result.washed is False
        assert result.upload_path == str(video_file)
        # 半成品副本必须被清掉
        assert list((tmp_path / "wash").glob("*.mkv")) == []

    def test_insufficient_disk_space_skips_wash(
        self, video_file, tmp_path, monkeypatch
    ):
        """临时目录空间不足时跳过洗码，不能把磁盘写满"""
        washer = HashWasher(
            {"enabled": True, "mode": "copy", "temp_dir": str(tmp_path / "wash")}
        )
        original_size = video_file.stat().st_size

        class _Usage:
            free = original_size // 2

        monkeypatch.setattr(shutil, "disk_usage", lambda _p: _Usage())
        result = washer.wash(str(video_file))

        assert result.washed is False
        assert result.upload_path == str(video_file)
        assert "空间不足" in result.message
        assert video_file.stat().st_size == original_size


class TestConfigDefaults:
    def test_hash_wash_section_in_default_config(self):
        """DEFAULT_CONFIG 必须包含 [hash_wash]，否则 Web 配置页看不到开关"""
        from src.video_organizer.core.config_loader import DEFAULT_CONFIG

        section = DEFAULT_CONFIG.get("hash_wash")
        assert section is not None
        assert section["enabled"] is False
        assert section["mode"] == "copy"

    def test_template_contains_hash_wash_section(self):
        template = Path("config_template.ini").read_text(encoding="utf-8")
        assert "[hash_wash]" in template
        assert (
            "enabled = False" in template.split("[hash_wash]")[1].split("[logging]")[0]
        )
