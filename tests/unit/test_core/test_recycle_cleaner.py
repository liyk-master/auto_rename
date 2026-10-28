"""网盘回收站定时清理的单元测试

覆盖：
- 时间点解析与调度计算
- Pan123Client 回收站接口（打桩 request，不发真实请求）
- P123RecycleProvider 凭据判断与降级
- RecycleCleaner 清理流程（试运行 / 清空 / 跳过 / 互斥）
- Web 路由处理函数
"""

import threading
from datetime import datetime

import pytest

from video_organizer.core.recycle_cleaner import (
    BaseRecycleProvider,
    P123RecycleProvider,
    RecycleCleaner,
    RecycleStats,
    has_missed_slot,
    list_provider_names,
    next_slot_time,
    parse_time_slots,
)
from video_organizer.core.recycle_cleaner.base import CleanResult, register_provider
from video_organizer.upload.pan123_client import Pan123Client

# ========== 测试用 Provider ==========


class FakeProvider(BaseRecycleProvider):
    """可编排行为的 Provider 桩"""

    name = "fake"
    label = "假网盘"

    def __init__(
        self,
        config=None,
        stats=None,
        clear_result=(True, "ok"),
        available=True,
        raise_on_stats=False,
    ):
        super().__init__(config)
        self._stats = stats or RecycleStats(provider=self.name, count=0, size=0)
        self._clear_result = clear_result
        self._available = available
        self._raise_on_stats = raise_on_stats
        self.clear_calls = 0
        self.stats_calls = 0

    def is_available(self):
        return self._available

    def stats(self, max_items=5000):
        self.stats_calls += 1
        if self._raise_on_stats:
            raise RuntimeError("网络超时")
        if not self._available:
            return RecycleStats(provider=self.name, available=False, error="未配置凭据")
        return self._stats

    def clear(self):
        self.clear_calls += 1
        return self._clear_result


# 注册到全局 Provider 表，以便 Web 路由的 _check_provider 与调度器的过滤逻辑识别
register_provider(FakeProvider)


def make_cleaner(**overrides):
    """构造一个不启动线程的清理器"""
    section = {"enabled": False, "providers": ["fake"], "daily_at": "04:00"}
    section.update(overrides.pop("section", {}))
    cleaner = RecycleCleaner({"recycle_clean": section, "telegram": {}}, **overrides)
    return cleaner


# ========== 时间点解析 ==========


class TestParseTimeSlots:
    def test_single_slot(self):
        assert parse_time_slots("04:00") == [(4, 0)]

    def test_multiple_slots_sorted_and_deduped(self):
        assert parse_time_slots("16:30, 04:00,16:30") == [(4, 0), (16, 30)]

    def test_accepts_list(self):
        assert parse_time_slots(["23:59", "00:00"]) == [(0, 0), (23, 59)]

    def test_missing_minute_defaults_to_zero(self):
        assert parse_time_slots("7") == [(7, 0)]

    @pytest.mark.parametrize("value", ["", None, "bad", "25:00", "04:99", "a,b"])
    def test_invalid_falls_back_to_default(self, value):
        assert parse_time_slots(value) == [(4, 0)]

    def test_partial_invalid_keeps_valid(self):
        assert parse_time_slots("bad,05:30") == [(5, 30)]


class TestNextSlotTime:
    def test_picks_later_slot_today(self):
        now = datetime(2026, 9, 6, 9, 0, 0)
        upcoming, slot = next_slot_time(now, [(4, 0), (16, 0)])
        assert slot == (16, 0)
        assert upcoming == datetime(2026, 9, 6, 16, 0, 0)

    def test_rolls_to_tomorrow(self):
        now = datetime(2026, 9, 6, 23, 0, 0)
        upcoming, slot = next_slot_time(now, [(4, 0), (16, 0)])
        assert slot == (4, 0)
        assert upcoming == datetime(2026, 9, 7, 4, 0, 0)

    def test_exact_slot_time_moves_to_next(self):
        now = datetime(2026, 9, 6, 4, 0, 0)
        upcoming, _ = next_slot_time(now, [(4, 0)])
        assert upcoming == datetime(2026, 9, 7, 4, 0, 0)


class TestHasMissedSlot:
    def test_no_previous_run_and_slot_passed(self):
        assert has_missed_slot(datetime(2026, 9, 6, 9, 0), [(4, 0)], None) is True

    def test_no_previous_run_and_slot_future(self):
        assert has_missed_slot(datetime(2026, 9, 6, 3, 0), [(4, 0)], None) is False

    def test_already_ran_today(self):
        last = datetime(2026, 9, 6, 4, 5)
        assert has_missed_slot(datetime(2026, 9, 6, 9, 0), [(4, 0)], last) is False

    def test_ran_yesterday_counts_as_missed(self):
        last = datetime(2026, 9, 5, 4, 5)
        assert has_missed_slot(datetime(2026, 9, 6, 9, 0), [(4, 0)], last) is True

    def test_earlier_slot_already_covered_by_later_run(self):
        last = datetime(2026, 9, 6, 5, 0)
        assert (
            has_missed_slot(datetime(2026, 9, 6, 9, 0), [(4, 0), (16, 0)], last)
            is False
        )

    def test_multiple_slots_only_later_one_missed(self):
        last = datetime(2026, 9, 6, 5, 0)
        assert (
            has_missed_slot(datetime(2026, 9, 6, 18, 0), [(4, 0), (16, 0)], last)
            is True
        )


# ========== Pan123Client 回收站接口 ==========


class StubClient(Pan123Client):
    """跳过 token 文件加载并记录请求的 Pan123Client"""

    def __init__(self, responses=None):
        self.token = "t"
        self.username = ""
        self.password = ""
        self.expire = 0
        self.token_file = ""
        self._auth_lock = threading.Lock()
        self.responses = responses or {}
        self.calls = []

    def ensure_auth(self):
        return None

    def request(self, url, method="POST", json_data=None, params=None, **kwargs):
        self.calls.append(
            {
                "url": url,
                "method": method,
                "json": json_data,
                "params": params,
                **kwargs,
            }
        )
        key = url.rsplit("/b/api", 1)[-1]
        return self.responses.get(key, {"code": 0, "message": "ok", "data": {}})


class TestPan123RecycleApi:
    def test_recycle_list_params(self):
        client = StubClient()
        client.recycle_list(limit=50, next_cursor=123)
        params = client.calls[0]["params"]
        assert client.calls[0]["url"].endswith("/file/list/new")
        assert params["trashed"] == "true"
        assert params["event"] == "recycleListFile"
        assert params["next"] == "123"
        assert params["limit"] == "50"
        # 123 接口 desc 会返回空列表，必须固定 asc
        assert params["orderDirection"] == "asc"

    def test_normal_fs_list_still_excludes_trash(self):
        client = StubClient()
        client.fs_list({"parentFileId": 0})
        assert client.calls[0]["params"]["trashed"] == "false"
        assert client.calls[0]["params"]["event"] == "homeListFile"

    def test_iter_recycle_follows_cursor(self):
        client = StubClient(
            {
                "/file/list/new": {
                    "code": 0,
                    "data": {
                        "Next": "-1",
                        "InfoList": [
                            {"FileId": 1, "Size": 10},
                            {"FileId": 2, "Size": 20},
                        ],
                    },
                }
            }
        )
        items = list(client.iter_recycle())
        assert [i["FileId"] for i in items] == [1, 2]

    def test_iter_recycle_paginates_until_next_minus_one(self):
        pages = [
            {"Next": "100", "InfoList": [{"FileId": 1, "Size": 1}]},
            {"Next": "200", "InfoList": [{"FileId": 2, "Size": 2}]},
            {"Next": "-1", "InfoList": [{"FileId": 3, "Size": 3}]},
        ]
        client = StubClient()
        calls = {"n": 0}

        def fake_request(url, method="POST", json_data=None, params=None, **kwargs):
            page = pages[calls["n"]]
            calls["n"] += 1
            return {"code": 0, "data": page}

        client.request = fake_request
        stats = client.recycle_stats()
        assert stats["count"] == 3
        assert stats["size"] == 6
        assert calls["n"] == 3

    def test_recycle_stats_reads_file_size_alias(self):
        client = StubClient(
            {
                "/file/list/new": {
                    "code": 0,
                    "data": {
                        "Next": "-1",
                        "InfoList": [{"FileId": 1, "FileSize": 4096}],
                    },
                }
            }
        )
        assert client.recycle_stats() == {"count": 1, "size": 4096, "truncated": False}

    def test_recycle_stats_respects_max_items(self):
        client = StubClient(
            {
                "/file/list/new": {
                    "code": 0,
                    "data": {
                        "Next": "999",
                        "InfoList": [{"FileId": i, "Size": 1} for i in range(5)],
                    },
                }
            }
        )
        stats = client.recycle_stats(max_items=5)
        assert stats["count"] == 5
        assert stats["truncated"] is True

    def test_iter_recycle_raises_on_error_code(self):
        """回收站列表失败必须抛错传播，不能静默当作「回收站为空」"""
        client = StubClient({"/file/list/new": {"code": 401, "message": "token 过期"}})
        with pytest.raises(RuntimeError, match="token 过期"):
            list(client.iter_recycle())

    def test_is_token_expired_detects_not_logged_in(self):
        """「未登录」等非 401 措辞也应判定为凭据失效，触发自动重登"""
        from video_organizer.upload.pan123_client import _is_token_expired

        assert _is_token_expired(0, "未登录") is True
        assert _is_token_expired(0, "请先登录") is True
        assert _is_token_expired(0, "未登陆") is True
        assert _is_token_expired(0, "登录已失效") is True
        assert _is_token_expired(0, "token 已过期") is True
        assert _is_token_expired(0, "文件不存在") is False
        assert _is_token_expired(401, "whatever") is True

    def test_recycle_clear_payload(self):
        client = StubClient({"/file/trash_delete_all": {"code": 0, "message": "ok"}})
        resp = client.recycle_clear()
        assert resp["code"] == 0
        assert client.calls[0]["url"].endswith("/file/trash_delete_all")
        assert client.calls[0]["method"] == "POST"
        assert client.calls[0]["json"] == {"event": "recycleClear"}

    def test_recycle_delete_payload(self):
        client = StubClient({"/file/delete": {"code": 0, "message": "ok"}})
        client.recycle_delete([11, 22])
        assert client.calls[0]["url"].endswith("/file/delete")
        assert client.calls[0]["json"] == {
            "fileIdList": [{"FileId": 11}, {"FileId": 22}],
            "event": "recycleDelete",
        }

    def test_recycle_restore_uses_trash_endpoint(self):
        client = StubClient({"/file/trash": {"code": 0, "message": "ok"}})
        client.recycle_restore(7)
        payload = client.calls[0]["json"]
        assert payload["event"] == "recycleRestore"
        assert payload["operation"] is False
        assert payload["fileTrashInfoList"] == [{"FileId": 7}]


# ========== P123RecycleProvider ==========


class TestP123RecycleProvider:
    def test_registered(self):
        assert "p123" in list_provider_names()

    def test_available_with_token(self):
        provider = P123RecycleProvider({"p123": {"token": "abc"}})
        assert provider.is_available() is True

    def test_available_with_username_password(self):
        provider = P123RecycleProvider({"p123": {"username": "u", "password": "p"}})
        assert provider.is_available() is True

    def test_not_available_without_credentials(self):
        provider = P123RecycleProvider(
            {"p123": {"token": "", "username": "", "password": ""}}
        )
        assert provider.is_available() is False

    def test_inline_comment_stripped_from_credentials(self):
        provider = P123RecycleProvider({"p123": {"token": "abc# 注释"}})
        assert provider._credentials()[0] == "abc"

    def test_stats_uses_injected_client(self):
        client = StubClient(
            {
                "/file/list/new": {
                    "code": 0,
                    "data": {
                        "Next": "-1",
                        "InfoList": [
                            {"FileId": 1, "Size": 1024},
                            {"FileId": 2, "Size": 2048},
                        ],
                    },
                }
            }
        )
        provider = P123RecycleProvider({}, client=client)
        stats = provider.stats()
        assert stats.count == 2
        assert stats.size == 3072
        assert stats.size_text == "3.00 KB"
        assert stats.error == ""

    def test_stats_reports_error_instead_of_raising(self):
        class Boom:
            def recycle_stats(self, max_items=5000):
                raise RuntimeError("连接被重置")

        provider = P123RecycleProvider({"p123": {"token": "t"}}, client=Boom())
        stats = provider.stats()
        assert stats.available is True
        assert stats.count == 0
        assert "连接被重置" in stats.error

    def test_clear_success(self):
        client = StubClient({"/file/trash_delete_all": {"code": 0, "message": "ok"}})
        provider = P123RecycleProvider({}, client=client)
        assert provider.clear() == (True, "ok")

    def test_clear_treats_async_code_7301_as_success(self):
        """7301 是 123 的异步成功码（已清空，空间稍后释放），不能计为失败"""
        client = StubClient(
            {
                "/file/trash_delete_all": {
                    "code": 7301,
                    "message": "已清空，系统释放空间需要一段时间，请稍后查看",
                }
            }
        )
        provider = P123RecycleProvider({}, client=client)
        ok, message = provider.clear()
        assert ok is True
        assert "已清空" in message

    def test_recycle_clear_passes_7301_as_ok_code(self):
        """client 层也要把 7301 当成功，否则 request() 会误记 error 日志"""
        client = StubClient(
            {"/file/trash_delete_all": {"code": 7301, "message": "已清空"}}
        )
        resp = client.recycle_clear()
        assert client.calls[0]["ok_codes"] == (0, 200, 7301)
        assert resp["code"] == 7301

    def test_recycle_delete_passes_7301_as_ok_code(self):
        client = StubClient({"/file/delete": {"code": 7301, "message": "已删除"}})
        client.recycle_delete([1])
        assert client.calls[0]["ok_codes"] == (0, 200, 7301)

    def test_clear_failure_returns_message(self):
        client = StubClient(
            {"/file/trash_delete_all": {"code": 500, "message": "服务端异常"}}
        )
        provider = P123RecycleProvider({}, client=client)
        ok, message = provider.clear()
        assert ok is False
        assert "服务端异常" in message

    def test_clear_without_credentials(self):
        provider = P123RecycleProvider({"p123": {}})
        ok, message = provider.clear()
        assert ok is False
        assert "未配置" in message


# ========== RecycleCleaner 清理流程 ==========


class TestRecycleCleanerFlow:
    def test_empty_recycle_skips_clear(self):
        provider = FakeProvider()
        cleaner = make_cleaner()
        cleaner.use_provider("fake", provider)
        result = cleaner.clean_one("fake")
        assert result["skipped"] is True
        assert result["success"] is True
        assert result["message"] == "回收站为空"
        assert provider.clear_calls == 0

    def test_dry_run_does_not_clear(self):
        provider = FakeProvider(
            stats=RecycleStats(provider="fake", count=3, size=3 * 1024**3)
        )
        cleaner = make_cleaner()
        cleaner.use_provider("fake", provider)
        result = cleaner.clean_one("fake", dry_run=True)
        assert result["dry_run"] is True
        assert result["count"] == 3
        assert "3.00 GB" in result["message"]
        assert provider.clear_calls == 0

    def test_clear_called_when_not_dry_run(self):
        provider = FakeProvider(
            stats=RecycleStats(provider="fake", count=5, size=100),
            clear_result=(True, "回收站已清空"),
        )
        cleaner = make_cleaner()
        cleaner.use_provider("fake", provider)
        result = cleaner.clean_one("fake")
        assert provider.clear_calls == 1
        assert result["success"] is True
        assert result["count"] == 5
        assert "回收站已清空" in result["message"]

    def test_clear_failure_marks_unsuccessful(self):
        provider = FakeProvider(
            stats=RecycleStats(provider="fake", count=2, size=1),
            clear_result=(False, "权限不足"),
        )
        cleaner = make_cleaner()
        cleaner.use_provider("fake", provider)
        result = cleaner.clean_one("fake")
        assert result["success"] is False
        assert "权限不足" in result["message"]

    def test_unavailable_provider_skipped(self):
        provider = FakeProvider(available=False)
        cleaner = make_cleaner()
        cleaner.use_provider("fake", provider)
        result = cleaner.clean_one("fake")
        assert result["skipped"] is True
        assert result["success"] is False
        assert "未配置凭据" in result["message"]
        assert provider.clear_calls == 0

    def test_stats_exception_becomes_skip(self):
        provider = FakeProvider(raise_on_stats=True)
        cleaner = make_cleaner()
        cleaner.use_provider("fake", provider)
        result = cleaner.clean_one("fake")
        assert result["skipped"] is True
        assert "读取回收站失败" in result["message"]
        assert provider.clear_calls == 0

    def test_stats_error_result_becomes_skip(self):
        provider = FakeProvider(
            stats=RecycleStats(provider="fake", count=0, size=0, error="连接被重置")
        )
        cleaner = make_cleaner()
        cleaner.use_provider("fake", provider)
        result = cleaner.clean_one("fake")
        assert result["skipped"] is True
        assert "读取回收站失败" in result["message"]

    def test_unknown_provider_reports_error(self):
        cleaner = make_cleaner()
        result = cleaner.clean_one("not-exists")
        assert result["success"] is False
        assert "不支持的网盘类型" in result["message"]

    def test_concurrent_run_is_rejected(self):
        cleaner = make_cleaner()
        cleaner.use_provider("fake", FakeProvider())
        assert cleaner._run_lock.acquire(blocking=False)
        try:
            result = cleaner.clean_one("fake")
            assert result["skipped"] is True
            assert "已有清理任务在运行" in result["message"]
        finally:
            cleaner._run_lock.release()

    def test_history_and_last_results_recorded(self):
        cleaner = make_cleaner()
        cleaner.use_provider("fake", FakeProvider())
        cleaner.clean_one("fake", reason="unit-test")
        status = cleaner.get_status()
        assert status["last_run_at"]
        assert len(status["history"]) == 1
        assert status["history"][0]["reason"] == "unit-test"
        assert status["last_results"][0]["provider"] == "fake"

    def test_clean_all_iterates_all_providers(self):
        cleaner = make_cleaner(provider_names=["fake"])
        cleaner.use_provider("fake", FakeProvider())
        cleaner.use_provider("fake2", FakeProvider())
        results = cleaner.clean_all(providers=["fake", "fake2"])
        assert [r["provider"] for r in results] == ["fake", "fake2"]

    def test_telegram_notify_disabled_makes_no_request(self, monkeypatch):
        called = {"n": 0}

        def fake_post(*args, **kwargs):
            called["n"] += 1

        import video_organizer.core.recycle_cleaner.cleaner as cleaner_module

        monkeypatch.setattr(cleaner_module.requests, "post", fake_post)
        cleaner = make_cleaner(section={"notify_telegram": False})
        cleaner.telegram_config = {"bot_token": "t", "chat_id": "c"}
        cleaner.use_provider("fake", FakeProvider())
        cleaner.clean_one("fake")
        assert called["n"] == 0

    def test_telegram_notify_sends_message(self, monkeypatch):
        sent = {}

        def fake_post(url, json=None, timeout=None):
            sent["url"] = url
            sent["text"] = (json or {}).get("text")

        import video_organizer.core.recycle_cleaner.cleaner as cleaner_module

        monkeypatch.setattr(cleaner_module.requests, "post", fake_post)
        cleaner = make_cleaner()
        cleaner.telegram_config = {"bot_token": "tok", "chat_id": "123"}
        cleaner.use_provider(
            "fake",
            FakeProvider(
                stats=RecycleStats(provider="fake", count=1, size=10),
                clear_result=(True, "ok"),
            ),
        )
        cleaner.clean_one("fake", reason="unit-test")
        assert "bottok" in sent["url"]
        assert "fake" in sent["text"]
        assert "unit-test" in sent["text"]


# ========== 生命周期与配置热更新 ==========


class TestRecycleCleanerLifecycle:
    def test_start_returns_false_when_disabled(self):
        cleaner = make_cleaner(provider_names=["fake"])
        cleaner.use_provider("fake", FakeProvider())
        assert cleaner.start() is False
        assert cleaner.is_alive is False

    def test_start_rejects_unregistered_provider(self):
        cleaner = RecycleCleaner(
            {"recycle_clean": {"enabled": True, "providers": ["nope"]}}
        )
        assert cleaner.start() is False

    def test_start_and_stop_thread(self):
        cleaner = RecycleCleaner(
            {
                "recycle_clean": {
                    "enabled": True,
                    "providers": ["fake"],
                    "daily_at": "23:59",
                    "catch_up_on_start": False,
                }
            }
        )
        cleaner.use_provider("fake", FakeProvider())
        try:
            assert cleaner.start() is True
            assert cleaner.is_alive is True
            status = cleaner.get_status()
            assert status["thread_alive"] is True
            assert status["next_run_at"].endswith("23:59:00")
        finally:
            cleaner.stop(timeout=3)
        assert cleaner.is_alive is False

    def test_apply_config_updates_schedule(self):
        cleaner = make_cleaner()
        cleaner.apply_config(
            {
                "recycle_clean": {
                    "enabled": False,
                    "providers": "p123,yun139",
                    "daily_at": "03:15",
                }
            }
        )
        assert cleaner.slots == [(3, 15)]
        assert cleaner.provider_names == ["p123", "yun139"]

    def test_apply_config_drops_provider_on_credential_change(self):
        cleaner = make_cleaner()
        cleaner.use_provider("fake", FakeProvider())
        # 配置未变 → 保留已注入的 Provider（避免重复登录）
        cleaner.apply_config(
            {
                "recycle_clean": {
                    "enabled": False,
                    "providers": ["fake"],
                    "daily_at": "04:00",
                }
            }
        )
        assert "fake" in cleaner._providers
        # 凭据变化 → 丢弃缓存，下次按新配置重建
        cleaner.apply_config(
            {
                "recycle_clean": {
                    "enabled": False,
                    "providers": ["fake"],
                    "daily_at": "04:00",
                },
                "p123": {"token": "new"},
            }
        )
        assert "fake" not in cleaner._providers

    def test_provider_rebuilt_from_fresh_config_after_credential_change(self):
        """凭据变更后重建的 Provider 必须拿到新配置（而非构造时闭包里的旧配置）"""
        seen_configs = []

        class SpyProvider(FakeProvider):
            name = "spy"

            def __init__(self, config=None, **kwargs):
                super().__init__(config, **kwargs)
                seen_configs.append(config)

        register_provider(SpyProvider)
        section = {"enabled": False, "providers": ["spy"], "daily_at": "04:00"}
        cleaner = RecycleCleaner({"recycle_clean": section, "p123": {"token": "old"}})
        cleaner.clean_one("spy")
        cleaner.apply_config({"recycle_clean": section, "p123": {"token": "new"}})
        cleaner.clean_one("spy")

        assert len(seen_configs) == 2
        assert seen_configs[0]["p123"]["token"] == "old"
        assert seen_configs[1]["p123"]["token"] == "new"


# ========== 定时触发执行窗口 ==========


class TestRecycleCleanerLoopWindow:
    """覆盖修复：线程在时间点后醒来也必须触发，不能把当天的时间点推到明天"""

    def test_window_opens_exactly_at_slot(self):
        cleaner = make_cleaner()
        assert cleaner._current_slot_dt(datetime(2026, 9, 30, 4, 0, 0, 0)) == datetime(
            2026, 9, 30, 4, 0
        )

    def test_window_covers_post_slot_wake(self):
        """旧实现：04:00:00.000 之后醒来会被 next_slot_time 推到明天而永远错过"""
        cleaner = make_cleaner()
        assert cleaner._current_slot_dt(
            datetime(2026, 9, 30, 4, 0, 0, 500000)
        ) == datetime(2026, 9, 30, 4, 0)
        assert cleaner._current_slot_dt(datetime(2026, 9, 30, 4, 0, 59)) == datetime(
            2026, 9, 30, 4, 0
        )

    def test_window_closed_after_one_minute(self):
        cleaner = make_cleaner()
        assert cleaner._current_slot_dt(datetime(2026, 9, 30, 4, 1, 0)) is None
        assert cleaner._current_slot_dt(datetime(2026, 9, 30, 3, 59, 59)) is None

    def test_multiple_slots_each_have_own_window(self):
        cleaner = make_cleaner(section={"daily_at": "04:00,16:30"})
        assert cleaner._current_slot_dt(datetime(2026, 9, 30, 16, 30, 20)) == datetime(
            2026, 9, 30, 16, 30
        )
        assert cleaner._current_slot_dt(datetime(2026, 9, 30, 16, 29, 59)) is None

    def test_fire_within_window_and_no_double_fire(self):
        """窗口内触发一次后，同一窗口不得重复触发"""
        cleaner = make_cleaner()
        provider = FakeProvider(
            stats=RecycleStats(provider="fake", count=1, size=10),
            clear_result=(True, "ok"),
        )
        cleaner.use_provider("fake", provider)
        slot_dt = datetime(2026, 9, 30, 4, 0)
        assert cleaner._last_fired_slot is None

        # 模拟线程在 04:00:00.500 醒来（旧实现此时已错过当天）
        if cleaner._current_slot_dt(datetime(2026, 9, 30, 4, 0, 0, 500000)) == slot_dt:
            if cleaner._last_fired_slot != slot_dt:
                cleaner._last_fired_slot = slot_dt
                cleaner.clean_all(reason="scheduled:04:00")
        assert provider.clear_calls == 1

        # 同一窗口内再次醒来 → 不再触发
        if cleaner._current_slot_dt(datetime(2026, 9, 30, 4, 0, 30)) == slot_dt:
            if cleaner._last_fired_slot != slot_dt:
                cleaner._last_fired_slot = slot_dt
                cleaner.clean_all(reason="scheduled:04:00")
        assert provider.clear_calls == 1

    def test_mark_slot_fired_after_catch_up(self):
        """启动补跑若落在窗口内，需记账避免紧接着重复触发"""
        cleaner = make_cleaner()
        now = datetime(2026, 9, 30, 4, 0, 20)
        cleaner._mark_slot_fired(now)
        assert cleaner._last_fired_slot == datetime(2026, 9, 30, 4, 0)
        # 不在窗口内则不记账，不影响后续定时触发
        cleaner._mark_slot_fired(datetime(2026, 9, 30, 10, 0))
        assert cleaner._last_fired_slot == datetime(2026, 9, 30, 4, 0)

    def test_apply_config_can_disable_running_thread(self):
        cleaner = RecycleCleaner(
            {
                "recycle_clean": {
                    "enabled": True,
                    "providers": ["fake"],
                    "daily_at": "23:59",
                    "catch_up_on_start": False,
                }
            }
        )
        cleaner.use_provider("fake", FakeProvider())
        assert cleaner.start() is True
        try:
            cleaner.apply_config(
                {
                    "recycle_clean": {
                        "enabled": False,
                        "providers": ["fake"],
                        "daily_at": "23:59",
                        "catch_up_on_start": False,
                    }
                }
            )
            assert cleaner.enabled is False
            assert cleaner.is_alive is False
        finally:
            cleaner.stop(timeout=3)


# ========== 配置默认值 ==========


class TestConfigDefaults:
    def test_default_config_contains_recycle_clean(self):
        from video_organizer.core.config_loader import DEFAULT_CONFIG

        section = DEFAULT_CONFIG["recycle_clean"]
        assert section["enabled"] is False
        assert section["providers"] == ["p123"]
        assert section["daily_at"] == "04:00"
        assert section["max_items"] == 5000

    def test_template_file_has_recycle_clean_section(self):
        import configparser
        from pathlib import Path

        path = Path(__file__).resolve().parents[3] / "config_template.ini"
        parser = configparser.ConfigParser()
        parser.read(path, encoding="utf-8")
        assert "recycle_clean" in parser.sections()
        assert parser["recycle_clean"].getboolean("enabled") is False
        assert parser["recycle_clean"]["daily_at"] == "04:00"


# ========== Web 路由 ==========


class TestRecycleRouter:
    def setup_method(self):
        from video_organizer.core.recycle_cleaner import get_cleaner, set_cleaner
        from video_organizer.web.services.state import get_state_manager

        self._previous_cleaner = get_cleaner()
        set_cleaner(None)
        self.state = get_state_manager()
        self._previous_config = self.state.get_config()
        self.state.set_config(
            {
                "recycle_clean": {
                    "enabled": False,
                    "providers": ["fake"],
                    "daily_at": "04:00",
                },
                "p123": {"token": "abc"},
                "telegram": {},
            }
        )

    def teardown_method(self):
        from video_organizer.core.recycle_cleaner import set_cleaner

        set_cleaner(self._previous_cleaner)
        self.state.set_config(self._previous_config)

    def test_status_lists_providers(self):
        from video_organizer.web.routers.recycle import recycle_status

        payload = recycle_status()
        assert payload["success"] is True
        names = [p["name"] for p in payload["providers"]]
        assert "p123" in names
        assert payload["cleaner"]["daily_at"] == ["04:00"]

    def test_unknown_provider_rejected(self):
        from fastapi import HTTPException
        from video_organizer.web.routers.recycle import recycle_stats

        with pytest.raises(HTTPException) as exc:
            recycle_stats("nope")
        assert exc.value.status_code == 400

    def test_run_uses_injected_provider(self):
        from video_organizer.web.routers.recycle import _get_cleaner, recycle_run
        from video_organizer.web.routers.recycle import RunRequest

        cleaner = _get_cleaner()
        provider = FakeProvider(
            stats=RecycleStats(provider="fake", count=4, size=4096),
            clear_result=(True, "回收站已清空"),
        )
        cleaner.use_provider("fake", provider)

        response = recycle_run("fake", RunRequest(dry_run=False))
        assert response["success"] is True
        assert response["result"]["count"] == 4
        assert provider.clear_calls == 1

    def test_run_dry_run_via_router(self):
        from video_organizer.web.routers.recycle import _get_cleaner, recycle_run
        from video_organizer.web.routers.recycle import RunRequest

        cleaner = _get_cleaner()
        provider = FakeProvider(stats=RecycleStats(provider="fake", count=9, size=1))
        cleaner.use_provider("fake", provider)

        response = recycle_run("fake", RunRequest(dry_run=True))
        assert response["result"]["dry_run"] is True
        assert provider.clear_calls == 0

    def test_stats_endpoint_reports_error_for_unavailable(self):
        from video_organizer.web.routers.recycle import _get_cleaner, recycle_stats

        cleaner = _get_cleaner()
        cleaner.use_provider("fake", FakeProvider(available=False))
        response = recycle_stats("fake")
        assert response["success"] is False
        assert response["stats"]["available"] is False


# ========== 结果模型 ==========


class TestCleanResult:
    def test_to_dict_includes_size_text(self):
        result = CleanResult(provider="p123", count=1, size=1536, success=True)
        payload = result.to_dict()
        assert payload["size_text"] == "1.50 KB"
        assert payload["success"] is True

    def test_format_size_units(self):
        from video_organizer.core.recycle_cleaner import format_size

        assert format_size(0) == "0 B"
        assert format_size(999) == "999 B"
        assert format_size(1024) == "1.00 KB"
        assert format_size(1024**4) == "1.00 TB"
