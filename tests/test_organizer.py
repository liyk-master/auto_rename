import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.video_organizer.upload.base_organizer import BaseCloudOrganizer
from src.video_organizer.upload.p123_organizer import P123Organizer
from src.video_organizer.upload.yun139_organizer import Yun139Organizer


class FakeOrganizer(BaseCloudOrganizer):
    """用于测试 organize_streaming 的假整理器"""

    def __init__(self, files=None, cancel_after=None, **kwargs):
        super().__init__(**kwargs)
        self.files = files or []
        self.organize_source_id = "source"
        self.organize_target_id = "target"
        self.move_calls = []
        self.rename_calls = []
        self.cancel_after = cancel_after

    def is_available(self):
        return True

    def list_files(self, parent_id, page=1, per_page=100):
        return self.files

    def yield_files_recursive(self, parent_id, max_depth=5):
        for i, f in enumerate(self.files):
            yield f
            if self.cancel_after is not None and (i + 1) >= self.cancel_after:
                self._cancel_flag = True

    def count_video_files(self, parent_id, max_depth=5):
        return sum(1 for f in self.files if f.get("type") != 1)

    def get_file_detail(self, file_id):
        return {"id": file_id}

    def move_file(self, file_id, target_parent_id, new_name=None):
        self.move_calls.append((file_id, target_parent_id, new_name))
        return True

    def rename_file(self, file_id, new_name):
        self.rename_calls.append((file_id, new_name))
        return True

    def create_folder(self, parent_id, name):
        return "folder-id"

    def find_or_create_folder(self, parent_id, name):
        return "folder-id"


class TestBaseCloudOrganizer(unittest.TestCase):
    def setUp(self):
        self.organizer = BaseCloudOrganizer(tmdb_api_key="test-key")

    def test_get_content_type_movie(self):
        self.assertEqual(self.organizer._get_content_type("movie", "US"), "电影")

    def test_get_content_type_by_country(self):
        cases = {
            "CN": "国漫",
            "HK": "港剧",
            "TW": "台剧",
            "JP": "日番",
            "KR": "韩剧",
            "US": "美剧",
            "GB": "美剧",
            "CA": "美剧",
        }
        for country, expected in cases.items():
            self.assertEqual(
                self.organizer._get_content_type("tv", country), expected, country
            )

    def test_get_content_type_default(self):
        self.assertEqual(self.organizer._get_content_type("tv", "FR"), "电视剧")
        self.assertEqual(self.organizer._get_content_type("tv", ""), "电视剧")

    def test_generate_name_with_season_episode(self):
        name = self.organizer._generate_name(
            "Test Show",
            "2020",
            "123",
            "1",
            "2",
            "{show_name} - {season_episode}",
            original_name="test_show.mkv",
        )
        self.assertEqual(name, "Test Show S01E02.mkv")

    def test_generate_name_with_quality_and_release(self):
        name = self.organizer._generate_name(
            "Test Show",
            "2020",
            "123",
            "1",
            "2",
            "{show_name} - {season_episode}",
            original_name="test_show.mkv",
            quality_tags="1080p",
            release_group="HDTV",
        )
        self.assertEqual(name, "Test Show S01E02 1080p-HDTV.mkv")

    def test_generate_name_strips_invalid_chars(self):
        name = self.organizer._generate_name(
            "Test: Show?",
            "2020",
            "123",
            "1",
            "1",
            "{show_name} - {season_episode}",
            original_name="test.mp4",
        )
        self.assertEqual(name, "Test Show S01E01.mp4")

    def test_generate_name_movie_no_season(self):
        name = self.organizer._generate_name(
            "Movie",
            "2020",
            "1",
            "",
            "",
            "{show_name} - {season_episode}",
            original_name="movie.mp4",
        )
        self.assertEqual(name, "Movie.mp4")

    def test_build_target_path_with_tmdb(self):
        path = self.organizer._build_target_path(
            "Test Show", "2020", "123", "tv", "TV Shows/国漫", "parent"
        )
        self.assertEqual(path["root_folder"], "TV Shows/国漫")
        self.assertEqual(path["folder_name"], "Test Show (2020) {tmdbid=123}")

    def test_build_target_path_without_tmdb(self):
        path = self.organizer._build_target_path(
            "Test Show", "2020", "", "tv", "TV Shows/国漫", "parent"
        )
        self.assertEqual(path["folder_name"], "Test Show (2020)")

    def test_cancel_flag(self):
        self.assertFalse(self.organizer._cancel_flag)
        self.organizer.cancel()
        self.assertTrue(self.organizer._cancel_flag)
        self.organizer.reset_cancel()
        self.assertFalse(self.organizer._cancel_flag)

    def test_recognize_without_tmdb_key(self):
        o = BaseCloudOrganizer(tmdb_api_key=None)
        metadata = o.recognize_file_by_name("some_show_s01e01.mp4")
        self.assertEqual(metadata["show_name"], "")
        self.assertEqual(metadata["category_path"], "TV Shows/电视剧")

    def test_organize_streaming_not_available(self):
        o = FakeOrganizer()

        def not_available():
            return False

        o.is_available = not_available
        result = o.organize_streaming(show_progress=False)
        self.assertEqual(result["success"], 0)
        self.assertEqual(result["failed"], 0)

    def test_organize_streaming_missing_ids(self):
        o = FakeOrganizer()
        o.organize_source_id = ""
        o.organize_target_id = ""
        result = o.organize_streaming(show_progress=False)
        self.assertIn("源目录ID未设置", result["errors"])

    def test_organize_streaming_dry_run(self):
        files = [
            {
                "id": 1,
                "name": "show_s01e01.mkv",
                "type": 0,
                "tmdb_id": "123",
                "show_name": "Show",
                "season": "1",
                "episode": "1",
                "media_type": "tv",
            },
            {
                "id": 2,
                "name": "show_s01e02.mkv",
                "type": 0,
                "tmdb_id": "123",
                "show_name": "Show",
                "season": "1",
                "episode": "2",
                "media_type": "tv",
            },
        ]
        o = FakeOrganizer(files=files, tmdb_api_key="test-key")
        result = o.organize_streaming(dry_run=True, show_progress=False)
        self.assertEqual(result["success"], 2)
        self.assertEqual(result["total"], 2)
        self.assertEqual(o.move_calls, [])

    def test_organize_streaming_skips_non_video_and_folders(self):
        files = [
            {"id": 1, "name": "folder", "type": 1},
            {"id": 2, "name": "readme.txt", "type": 0},
            {
                "id": 3,
                "name": "show_s01e01.mp4",
                "type": 0,
                "tmdb_id": "123",
                "show_name": "Show",
                "season": "1",
                "episode": "1",
                "media_type": "tv",
            },
        ]
        o = FakeOrganizer(files=files, tmdb_api_key="test-key")
        result = o.organize_streaming(show_progress=False)
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(len(o.move_calls), 1)

    def test_organize_streaming_cancel(self):
        files = [
            {
                "id": i,
                "name": f"show_s01e{i:02d}.mp4",
                "type": 0,
                "tmdb_id": "123",
                "show_name": "Show",
                "season": "1",
                "episode": str(i),
                "media_type": "tv",
            }
            for i in range(1, 6)
        ]
        o = FakeOrganizer(files=files, cancel_after=1, tmdb_api_key="test-key")
        result = o.organize_streaming(show_progress=False)
        self.assertTrue(result.get("cancelled"))

    def test_organize_streaming_progress_callback(self):
        files = [
            {
                "id": 1,
                "name": "show_s01e01.mp4",
                "type": 0,
                "tmdb_id": "123",
                "show_name": "Show",
                "season": "1",
                "episode": "1",
                "media_type": "tv",
            }
        ]
        o = FakeOrganizer(files=files, tmdb_api_key="test-key")
        events = []
        o.organize_streaming(show_progress=False, progress_callback=events.append)
        actions = [e["action"] for e in events]
        self.assertIn("organized", actions)

    def test_organize_streaming_unrecognizable_skipped(self):
        files = [
            {
                "id": 1,
                "name": "unknown_noise_file.mp4",
                "type": 0,
            }
        ]
        o = FakeOrganizer(files=files, tmdb_api_key="test-key")

        def not_recognize(name):
            return {
                "name": name,
                "show_name": "",
                "category_path": "TV Shows/电视剧",
            }

        o.recognize_file_by_name = not_recognize
        result = o.organize_streaming(show_progress=False)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["success"], 0)

    def test_organize_streaming_realtime_counts(self):
        files = [
            {
                "id": 1,
                "name": "show_s01e01.mp4",
                "type": 0,
                "tmdb_id": "123",
                "show_name": "Show",
                "season": "1",
                "episode": "1",
                "media_type": "tv",
            },
            {"id": 2, "name": "unknown_noise.mp4", "type": 0},
            {"id": 3, "name": "folder", "type": 1},
        ]
        o = FakeOrganizer(files=files, tmdb_api_key="test-key")

        def not_recognize(name):
            return {
                "name": name,
                "show_name": "",
                "category_path": "TV Shows/电视剧",
            }

        o.recognize_file_by_name = not_recognize
        events = []
        result = o.organize_streaming(
            show_progress=False, progress_callback=events.append
        )
        # 1 成功 + 1 无法识别跳过 + 1 文件夹（不计数）
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["total"], 3)
        # 进度回调中包含实时成败统计
        last = events[-1]
        self.assertIn("success", last)
        self.assertIn("failed", last)
        self.assertIn("skipped", last)
        self.assertEqual(last["success"], result["success"])
        self.assertEqual(last["skipped"], result["skipped"])

    def test_organize_streaming_cancel_midrun(self):
        files = [
            {
                "id": i,
                "name": f"show_s01e{i:02d}.mp4",
                "type": 0,
                "tmdb_id": "123",
                "show_name": "Show",
                "season": "1",
                "episode": str(i),
                "media_type": "tv",
            }
            for i in range(1, 6)
        ]
        o = FakeOrganizer(files=files, tmdb_api_key="test-key")

        def cb(ev):
            if ev["action"] == "recognized":
                o.cancel()

        result = o.organize_streaming(show_progress=False, progress_callback=cb)
        self.assertTrue(result.get("cancelled"))
        self.assertEqual(
            result["success"] + result["failed"] + result["skipped"], result["total"]
        )

    def test_organize_streaming_batch_groups_by_folder(self):
        # 3 个文件分别解析到 2 个不同目标目录，第二阶段应按目录分组各调用一次 move_files
        files = [
            {
                "id": i,
                "name": f"show_s01e{i:02d}.mp4",
                "type": 0,
                "tmdb_id": "123",
                "show_name": "Show",
                "season": "1",
                "episode": str(i),
                "media_type": "tv",
            }
            for i in range(1, 4)
        ]
        o = FakeOrganizer(files=files, tmdb_api_key="test-key")

        def fake_resolve(file_info, target_parent_id, name_format=None):
            fid = str(file_info.get("id"))
            folder = {"1": "folder-a", "2": "folder-a", "3": "folder-b"}[fid]
            return {
                "file_id": file_info.get("id"),
                "target_folder_id": folder,
                "new_name": file_info.get("name"),
            }

        o._resolve_target = fake_resolve
        batch_calls = []

        def record_move_files(file_ids, target_parent_id):
            batch_calls.append((sorted(file_ids), target_parent_id))
            return {"success": len(file_ids), "errors": []}

        o.move_files = record_move_files
        result = o.organize_streaming(show_progress=False)
        self.assertEqual(result["success"], 3)
        self.assertEqual(len(batch_calls), 2)
        # as_completed 完成顺序不定，按目录查找分组结果
        grouped = {folder: ids for ids, folder in batch_calls}
        self.assertEqual(sorted(grouped["folder-a"]), [1, 2])
        self.assertEqual(sorted(grouped["folder-b"]), [3])

    def test_organize_streaming_batch_move_failure_isolates(self):
        files = [
            {
                "id": i,
                "name": f"show_s01e{i:02d}.mp4",
                "type": 0,
                "tmdb_id": "123",
                "show_name": "Show",
                "season": "1",
                "episode": str(i),
                "media_type": "tv",
            }
            for i in range(1, 4)
        ]
        o = FakeOrganizer(files=files, tmdb_api_key="test-key")

        def fail_move_files(file_ids, target_parent_id):
            return {
                "success": 0,
                "errors": [f"移动失败: file_id={fid}" for fid in file_ids],
            }

        o.move_files = fail_move_files
        result = o.organize_streaming(show_progress=False)
        self.assertEqual(result["success"], 0)
        self.assertEqual(result["failed"], 3)
        self.assertEqual(len(result["errors"]), 3)


class TestP123Organizer(unittest.TestCase):
    def test_is_available_without_token(self):
        o = P123Organizer()
        self.assertFalse(o.is_available())

    def test_is_available_with_token(self):
        o = P123Organizer(token="test-token")
        self.assertTrue(o.is_available())

    def test_is_available_with_credentials_no_token(self):
        o = P123Organizer(username="user", password="pass")
        self.assertTrue(o.is_available())

    def test_is_available_with_username_only(self):
        o = P123Organizer(username="user")
        self.assertFalse(o.is_available())

    def test_list_files(self):
        o = P123Organizer(token="test-token")
        o.client = mock.Mock()
        o.client.fs_list.return_value = {
            "code": 0,
            "data": {
                "InfoList": [
                    {
                        "FileId": "11",
                        "FileName": "folder",
                        "Type": 1,
                        "FileSize": 0,
                    },
                    {
                        "FileId": "12",
                        "FileName": "video.mp4",
                        "Type": 0,
                        "FileSize": 100,
                    },
                ]
            },
        }
        files = o.list_files(0)
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]["id"], "11")
        self.assertEqual(files[0]["type"], 1)
        self.assertEqual(files[1]["name"], "video.mp4")

    def test_list_files_failure(self):
        o = P123Organizer(token="test-token")
        o.client = mock.Mock()
        o.client.fs_list.return_value = {"code": 1, "message": "error"}
        self.assertEqual(o.list_files(0), [])

    def test_move_file_success(self):
        o = P123Organizer(token="test-token")
        o.client = mock.Mock()
        o.client.fs_rename.return_value = {"code": 0}
        o.client.fs_move.return_value = {"code": 0}
        self.assertTrue(o.move_file(1, 2, "new.mkv"))
        o.client.fs_rename.assert_called_once()
        o.client.fs_move.assert_called_once()

    def test_move_file_failure(self):
        o = P123Organizer(token="test-token")
        o.client = mock.Mock()
        o.client.fs_rename.return_value = {"code": 0}
        o.client.fs_move.return_value = {"code": 1, "message": "fail"}
        self.assertFalse(o.move_file(1, 2))

    def test_rename_file_success(self):
        o = P123Organizer(token="test-token")
        o.client = mock.Mock()
        o.client.fs_rename.return_value = {"code": 0}
        self.assertTrue(o.rename_file(1, "new.mkv"))
        o.client.fs_rename.assert_called_once()

    def test_move_files_batch_single_call(self):
        o = P123Organizer(token="test-token")
        o.client = mock.Mock()
        o.client.fs_move.return_value = {"code": 0}
        result = o.move_files([1, 2, 3], 99)
        self.assertEqual(result["success"], 3)
        self.assertEqual(result["errors"], [])
        # 单次 fs_move 调用，携带全部 fileId
        o.client.fs_move.assert_called_once()
        payload = o.client.fs_move.call_args[0][0]
        self.assertEqual(len(payload["fileIdList"]), 3)
        self.assertEqual(payload["parentFileId"], 99)

    def test_move_files_retry_then_fallback_per_file(self):
        o = P123Organizer(token="test-token")
        o.client = mock.Mock()
        # 批量两次都失败，回退逐文件（rename 成功、move 失败）
        o.client.fs_move.return_value = {"code": 1, "message": "fail"}
        o.client.fs_rename.return_value = {"code": 0}
        result = o.move_files([1, 2, 3], 99)
        self.assertEqual(result["success"], 0)
        self.assertEqual(len(result["errors"]), 3)
        # 2 次批量 + 3 次逐文件 = 5 次 fs_move（回退时不重复重命名）
        self.assertEqual(o.client.fs_move.call_count, 5)
        self.assertEqual(o.client.fs_rename.call_count, 0)

    def test_move_files_retry_then_fallback_partial_success(self):
        o = P123Organizer(token="test-token")
        o.client = mock.Mock()
        # 批量失败两次，逐文件移动成功（fs_move 第 3 次起返回成功）
        o.client.fs_move.side_effect = [
            {"code": 1, "message": "fail"},
            {"code": 1, "message": "fail"},
            {"code": 0},
            {"code": 0},
            {"code": 0},
        ]
        o.client.fs_rename.return_value = {"code": 0}
        result = o.move_files([1, 2, 3], 99)
        self.assertEqual(result["success"], 3)
        self.assertEqual(result["errors"], [])

    def test_create_folder(self):
        o = P123Organizer(token="test-token")
        o.client = mock.Mock()
        o.client.fs_mkdir.return_value = {"code": 0, "data": {"Info": {"FileId": 99}}}
        self.assertEqual(o.create_folder(1, "New Folder"), 99)

    def test_find_or_create_folder_existing(self):
        o = P123Organizer(token="test-token")
        o.client = mock.Mock()
        o.client.fs_list.return_value = {
            "code": 0,
            "data": {
                "InfoList": [
                    {"FileId": "7", "FileName": "Existing", "Type": 1, "FileSize": 0}
                ]
            },
        }
        self.assertEqual(o.find_or_create_folder(1, "Existing"), "7")
        o.client.fs_mkdir.assert_not_called()

    def test_find_or_create_folder_creates(self):
        o = P123Organizer(token="test-token")
        o.client = mock.Mock()
        o.client.fs_list.return_value = {"code": 0, "data": {"InfoList": []}}
        o.client.fs_mkdir.return_value = {"code": 0, "data": {"Info": {"FileId": 5}}}
        self.assertEqual(o.find_or_create_folder(1, "Missing"), 5)
        o.client.fs_mkdir.assert_called_once()


class TestYun139Organizer(unittest.TestCase):
    def _available(self):
        o = Yun139Organizer(authorization="")
        o.authorization = "dummy-auth"
        o.client = mock.Mock()
        return o

    def test_is_available_without_auth(self):
        o = Yun139Organizer(authorization="")
        self.assertFalse(o.is_available())

    def test_to_dict(self):
        from src.video_organizer.upload.yun139_client import FileInfo

        fi = FileInfo(
            id="1",
            name="v.mp4",
            size=10,
            is_folder=False,
            created_time=None,
            modified_time=None,
        )
        d = Yun139Organizer(authorization="")._to_dict(fi, "/")
        self.assertEqual(d["id"], "1")
        self.assertEqual(d["type"], 0)
        self.assertEqual(d["name"], "v.mp4")

    def test_list_files(self):
        from src.video_organizer.upload.yun139_client import FileInfo

        o = self._available()
        o.client.list_files.return_value = [
            FileInfo(
                id="1",
                name="dir",
                size=0,
                is_folder=True,
                created_time=None,
                modified_time=None,
            ),
            FileInfo(
                id="2",
                name="movie.mp4",
                size=50,
                is_folder=False,
                created_time=None,
                modified_time=None,
            ),
        ]
        files = o.list_files("/")
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]["type"], 1)
        self.assertEqual(files[1]["type"], 0)

    def test_move_file_success(self):
        o = self._available()
        o._file_info_map["1"] = {
            "id": "1",
            "name": "movie.mp4",
            "size": 10,
            "type": 0,
        }
        self.assertTrue(o.move_file("1", "target", "new.mp4"))
        o.client.rename.assert_called_once()
        o.client.move.assert_called_once()

    def test_move_file_raises(self):
        o = self._available()
        o._file_info_map["1"] = {
            "id": "1",
            "name": "movie.mp4",
            "size": 10,
            "type": 0,
        }
        o.client.move.side_effect = Exception("boom")
        self.assertFalse(o.move_file("1", "target"))

    def test_create_folder(self):
        from src.video_organizer.upload.yun139_client import FileInfo

        o = self._available()
        o.client.mkdir.return_value = True
        o.client.list_files.return_value = [
            FileInfo(
                id="f1",
                name="New",
                size=0,
                is_folder=True,
                created_time=None,
                modified_time=None,
            )
        ]
        self.assertEqual(o.create_folder("/", "New"), "f1")

    def test_find_or_create_folder_existing(self):
        from src.video_organizer.upload.yun139_client import FileInfo

        o = self._available()
        o.client.list_files.return_value = [
            FileInfo(
                id="d1",
                name="Existing",
                size=0,
                is_folder=True,
                created_time=None,
                modified_time=None,
            )
        ]
        self.assertEqual(o.find_or_create_folder("/", "Existing"), "d1")
        o.client.mkdir.assert_not_called()

    def test_count_video_files(self):
        from src.video_organizer.upload.yun139_client import FileInfo

        o = self._available()
        o.client.list_files.return_value = [
            FileInfo(
                id="1",
                name="a.mp4",
                size=1,
                is_folder=False,
                created_time=None,
                modified_time=None,
            ),
            FileInfo(
                id="2",
                name="b.mp4",
                size=1,
                is_folder=False,
                created_time=None,
                modified_time=None,
            ),
        ]
        self.assertEqual(o.count_video_files("/"), 2)


class TestOrganizeConfig(unittest.TestCase):
    def test_yun139_organize_keys_in_default_config(self):
        from src.video_organizer.core.config_loader import DEFAULT_CONFIG

        yun139 = DEFAULT_CONFIG.get("yun139", {})
        self.assertIn("organize_source_id", yun139)
        self.assertIn("organize_target_id", yun139)

    def test_template_contains_organize_keys(self):
        from pathlib import Path

        template = Path(__file__).parent.parent / "config_template.ini"
        content = template.read_text(encoding="utf-8")
        self.assertIn("organize_source_id", content)
        self.assertIn("organize_target_id", content)


if __name__ == "__main__":
    unittest.main()
