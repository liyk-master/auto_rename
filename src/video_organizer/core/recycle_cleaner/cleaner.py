"""回收站定时清理调度器

设计要点：
- 单条 daemon 线程 + ``threading.Event`` 等待，停止时最多 1 秒内退出
- 支持多个每日时间点（``daily_at = 04:00,16:00``）
- 服务启动时若当天时间点已过且当天未跑过，可补跑一次（``catch_up_on_start``）
- 手动触发与定时触发共用一把非阻塞锁，避免并发清空
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from .base import (
    BaseRecycleProvider,
    CleanResult,
    RecycleStats,
    create_provider,
    format_size,
    list_provider_names,
)

logger = logging.getLogger(__name__)

__all__ = [
    "RecycleCleaner",
    "parse_time_slots",
    "next_slot_time",
    "has_missed_slot",
    "get_cleaner",
    "set_cleaner",
]

DEFAULT_DAILY_AT = "04:00"
#: 单次等待的分片，保证 stop() 响应及时
_TICK = 1.0
#: 保留的历史记录条数
_HISTORY_LIMIT = 20


# ========== 时间工具（独立函数便于单测） ==========


def _parse_slot(item: Any) -> Optional[Tuple[int, int]]:
    """解析单个 ``HH:MM``，非法返回 None"""
    parts = str(item).strip().split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (IndexError, TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return (hour, minute)


def parse_time_slots(
    value: Any, default: str = DEFAULT_DAILY_AT
) -> List[Tuple[int, int]]:
    """解析 ``HH:MM`` 列表（逗号分隔），非法项忽略，全部非法时回落到默认值

    >>> parse_time_slots("04:00, 16:30 ")
    [(4, 0), (16, 30)]
    """
    if isinstance(value, (list, tuple)):
        raw_items: List[Any] = list(value)
    else:
        raw_items = [v for v in str(value or "").split(",") if v.strip()]

    slots: List[Tuple[int, int]] = []
    for item in raw_items:
        parsed = _parse_slot(item)
        if parsed is None:
            logger.warning(f"回收站清理时间点格式非法，已忽略: {item!r}（应为 HH:MM）")
            continue
        slots.append(parsed)

    if not slots:
        fallback = _parse_slot(default) or (4, 0)
        logger.warning(
            f"回收站清理时间点未配置或全部非法，使用默认 {fallback[0]:02d}:{fallback[1]:02d}"
        )
        slots = [fallback]
    # 去重并按时间排序
    return sorted(set(slots)) or [(4, 0)]


def next_slot_time(
    now: datetime, slots: List[Tuple[int, int]]
) -> Tuple[datetime, Tuple[int, int]]:
    """返回今天或明天最近的一个执行时间点"""
    candidates = []
    for hour, minute in slots:
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        candidates.append((candidate, (hour, minute)))
    best, best_slot = min(candidates, key=lambda pair: pair[0])
    return best, best_slot


def has_missed_slot(
    now: datetime,
    slots: List[Tuple[int, int]],
    last_run_at: Optional[datetime],
) -> bool:
    """判断今天是否有「已过但上次执行在其之前」的时间点（用于启动补跑）

    按时间点逐个比较，因此配置多个时间点时，只要有一个被错过就会补跑。
    """
    for hour, minute in slots:
        slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if slot > now:
            continue
        if last_run_at is None or slot > last_run_at:
            return True
    return False


# ========== 调度器 ==========


class RecycleCleaner:
    """回收站定时清理器"""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        provider_names: Optional[List[str]] = None,
        telegram_config: Optional[Dict[str, Any]] = None,
        provider_factory: Optional[Callable[[str], BaseRecycleProvider]] = None,
    ) -> None:
        config = config or {}
        section = config.get("recycle_clean", {}) or {}
        self.section = section

        self.enabled = bool(section.get("enabled", False))
        self.notify_telegram = bool(section.get("notify_telegram", True))
        self.catch_up_on_start = bool(section.get("catch_up_on_start", True))
        self.run_on_start = bool(section.get("run_on_start", False))
        try:
            self.max_items = int(section.get("max_items", 5000) or 5000)
        except (TypeError, ValueError):
            self.max_items = 5000

        raw_providers = provider_names
        if raw_providers is None:
            raw_providers = section.get("providers", ["p123"])
        if isinstance(raw_providers, str):
            raw_providers = [p.strip() for p in raw_providers.split(",") if p.strip()]
        self.provider_names: List[str] = list(raw_providers or []) or ["p123"]

        self.daily_at = str(
            section.get("daily_at", DEFAULT_DAILY_AT) or DEFAULT_DAILY_AT
        )
        self.slots = parse_time_slots(self.daily_at)

        self.telegram_config = (
            telegram_config
            if telegram_config is not None
            else config.get("telegram", {})
        )
        self._provider_factory = provider_factory or (
            lambda name: create_provider(name, self._config)
        )

        self._providers: Dict[str, BaseRecycleProvider] = {}
        self._config: Dict[str, Any] = config
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()

        self.running = False
        self.last_run_at: Optional[datetime] = None
        self.next_run_at: Optional[datetime] = None
        #: 最近一次已执行的定时时间点（精确到分钟），防止执行窗口内重复触发
        self._last_fired_slot: Optional[datetime] = None
        self.last_results: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []
        self._config_fp = self._credentials_fingerprint(config)

    # ----- Provider -----

    def _get_provider(self, name: str) -> BaseRecycleProvider:
        provider = self._providers.get(name)
        if provider is None:
            provider = self._provider_factory(name)
            self._providers[name] = provider
        return provider

    def use_provider(self, name: str, provider: BaseRecycleProvider) -> None:
        """注入 Provider 实例（Web 端复用已登录客户端、单元测试打桩）"""
        self._providers[name] = provider
        if name not in self.provider_names:
            self.provider_names.append(name)

    def stats_for(self, name: str, max_items: Optional[int] = None) -> RecycleStats:
        """查询指定网盘的回收站统计（供 Web 端实时展示）"""
        return self._get_provider(name).stats(
            max_items=max_items if max_items else self.max_items
        )

    # ----- 配置热更新 -----

    @staticmethod
    def _credentials_fingerprint(config: Dict[str, Any]) -> str:
        """对各网盘的凭据 section 算指纹，凭据变化时丢弃已缓存的 Provider"""
        import hashlib
        import json

        relevant = {name: config.get(name) for name in ("p123", "yun139", "cloud189")}
        raw = json.dumps(relevant, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def apply_config(self, config: Dict[str, Any]) -> None:
        """用最新配置刷新调度参数（Web 端修改配置后无需重启）"""
        config = config or {}
        self._config = config
        section = config.get("recycle_clean", {}) or {}
        self.section = section
        self.enabled = bool(section.get("enabled", False))
        self.notify_telegram = bool(section.get("notify_telegram", True))
        self.catch_up_on_start = bool(section.get("catch_up_on_start", True))
        self.run_on_start = bool(section.get("run_on_start", False))
        try:
            self.max_items = int(section.get("max_items", 5000) or 5000)
        except (TypeError, ValueError):
            self.max_items = 5000

        raw_providers = section.get("providers", ["p123"])
        if isinstance(raw_providers, str):
            raw_providers = [p.strip() for p in raw_providers.split(",") if p.strip()]
        self.provider_names = [n for n in (raw_providers or []) if n] or ["p123"]

        self.daily_at = str(
            section.get("daily_at", DEFAULT_DAILY_AT) or DEFAULT_DAILY_AT
        )
        self.slots = parse_time_slots(self.daily_at)
        self.telegram_config = config.get("telegram", {}) or {}

        fingerprint = self._credentials_fingerprint(config)
        if fingerprint != self._config_fp:
            self._config_fp = fingerprint
            # 凭据变了，丢弃缓存的 Provider（下次按新配置重建）
            self._providers = {}

        # 开关变化时同步线程状态
        if self.enabled and not self.is_alive:
            self.start()
        elif not self.enabled and self.is_alive:
            self.stop()

    # ----- 生命周期 -----

    def start(self) -> bool:
        """启动定时线程，返回是否真正启动"""
        if not self.enabled:
            logger.info("回收站定时清理未启用（[recycle_clean] enabled = false）")
            return False
        if self._thread and self._thread.is_alive():
            return True
        unknown = [n for n in self.provider_names if n not in list_provider_names()]
        if unknown:
            logger.warning(f"忽略未注册的回收站 Provider: {unknown}")
            self.provider_names = [
                n for n in self.provider_names if n in list_provider_names()
            ]
        if not self.provider_names:
            logger.warning("回收站清理没有可用的 Provider，跳过启动")
            return False

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="RecycleCleaner", daemon=True
        )
        self._thread.start()
        logger.info(
            "回收站定时清理已启动: providers=%s, 时间点=%s",
            ",".join(self.provider_names),
            ",".join(self._fmt_slot(s) for s in self.slots),
        )
        return True

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        logger.info("回收站定时清理已停止")

    @property
    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ----- 线程主循环 -----

    def _loop(self) -> None:
        now = datetime.now()

        if self.run_on_start:
            logger.info("回收站清理：run_on_start 已开启，启动后立即执行一次")
            self.clean_all(reason="on_start")
            # 启动已实际执行过本时间点窗口则记账，避免紧接着重复触发
            self._mark_slot_fired(now)
        elif self.catch_up_on_start and has_missed_slot(
            now, self.slots, self.last_run_at
        ):
            logger.info("回收站清理：今天的时间点已过且未执行，补跑一次")
            self.clean_all(reason="catch_up")
            self._mark_slot_fired(now)

        while not self._stop.is_set():
            now = datetime.now()

            # 执行窗口：本日时间点起 60 秒内触发。
            # 不能只靠 next_slot_time + wait：线程从 wait 醒来时通常已过
            # 04:00:00.000，next_slot_time 会把时间点推到明天，导致当天永远错过。
            slot_dt = self._current_slot_dt(now)
            if slot_dt is not None:
                if self._last_fired_slot != slot_dt:
                    self._last_fired_slot = slot_dt
                    self.clean_all(
                        reason=f"scheduled:{self._fmt_slot((slot_dt.hour, slot_dt.minute))}"
                    )
                if self._stop.wait(_TICK * 5):
                    break
                continue

            upcoming, slot = next_slot_time(now, self.slots)
            with self._state_lock:
                self.next_run_at = upcoming
            wait_seconds = (upcoming - now).total_seconds()
            if wait_seconds > 0:
                if self._stop.wait(min(wait_seconds, _TICK * 30)):
                    break

    def _current_slot_dt(self, now: datetime) -> Optional[datetime]:
        """当前是否落在某个时间点的执行窗口内（时间点起 60 秒），是则返回该时间点"""
        for hour, minute in self.slots:
            slot_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if slot_dt <= now < slot_dt + timedelta(minutes=1):
                return slot_dt
        return None

    def _mark_slot_fired(self, now: datetime) -> None:
        """启动补跑/立即执行后，若恰好落在执行窗口内则记账，避免同一窗口重复触发"""
        slot_dt = self._current_slot_dt(now)
        if slot_dt is not None:
            self._last_fired_slot = slot_dt

    @staticmethod
    def _fmt_slot(slot: Tuple[int, int]) -> str:
        return f"{slot[0]:02d}:{slot[1]:02d}"

    # ----- 执行 -----

    def clean_all(
        self,
        providers: Optional[List[str]] = None,
        dry_run: bool = False,
        reason: str = "manual",
    ) -> List[Dict[str, Any]]:
        """清理所有（或指定）网盘的回收站

        Args:
            providers: 要清理的网盘列表，默认取配置
            dry_run: 只统计不清理
            reason: 触发来源，写入日志与历史
        """
        names = providers or self.provider_names
        if not self._run_lock.acquire(blocking=False):
            logger.warning("已有回收站清理任务在运行，本次请求被忽略")
            return [
                CleanResult(
                    provider=",".join(names),
                    skipped=True,
                    message="已有清理任务在运行",
                ).to_dict()
            ]
        self.running = True
        started = datetime.now()
        results: List[Dict[str, Any]] = []
        try:
            for name in names:
                results.append(self._clean_one(name, dry_run=dry_run).to_dict())
            self.last_run_at = started
            self.last_results = results
            self.history.insert(
                0,
                {
                    "started_at": started.isoformat(timespec="seconds"),
                    "reason": reason,
                    "dry_run": dry_run,
                    "results": results,
                },
            )
            del self.history[_HISTORY_LIMIT:]
            self._notify(results, reason=reason, dry_run=dry_run)
        except Exception as exc:  # 防止线程因意外异常退出
            logger.exception(f"回收站清理流程异常: {exc}")
        finally:
            self.running = False
            self._run_lock.release()
        return results

    def clean_one(
        self, name: str, dry_run: bool = False, reason: str = "manual"
    ) -> Dict[str, Any]:
        """清理单个网盘（供 Web 手动触发），与定时任务互斥"""
        if not self._run_lock.acquire(blocking=False):
            logger.warning("已有回收站清理任务在运行，本次请求被忽略")
            return CleanResult(
                provider=name, skipped=True, message="已有清理任务在运行"
            ).to_dict()
        self.running = True
        started = datetime.now()
        try:
            result = self._clean_one(name, dry_run=dry_run)
            self.last_run_at = started
            self.last_results = [result.to_dict()]
            self.history.insert(
                0,
                {
                    "started_at": started.isoformat(timespec="seconds"),
                    "reason": reason,
                    "dry_run": dry_run,
                    "results": [result.to_dict()],
                },
            )
            del self.history[_HISTORY_LIMIT:]
            self._notify([result.to_dict()], reason=reason, dry_run=dry_run)
            return result.to_dict()
        finally:
            self.running = False
            self._run_lock.release()

    def _clean_one(self, name: str, dry_run: bool = False) -> CleanResult:
        started_at = datetime.now().isoformat(timespec="seconds")
        try:
            provider = self._get_provider(name)
        except ValueError as exc:
            return CleanResult(
                provider=name,
                message=str(exc),
                started_at=started_at,
                finished_at=started_at,
            )

        stats: RecycleStats
        try:
            stats = provider.stats(max_items=self.max_items)
        except Exception as exc:  # 单个 Provider 异常不能弄挂调度线程
            logger.warning(f"[{name}] 回收站统计异常: {exc}")
            return CleanResult(
                provider=name,
                skipped=True,
                dry_run=dry_run,
                message=f"读取回收站失败: {exc}",
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
        if not stats.available:
            logger.info(f"[{name}] 回收站跳过: {stats.error}")
            return CleanResult(
                provider=name,
                skipped=True,
                dry_run=dry_run,
                message=stats.error or "未配置",
                started_at=started_at,
                finished_at=started_at,
                details=stats.to_dict(),
            )
        if stats.error and stats.count == 0:
            logger.warning(f"[{name}] 回收站统计失败: {stats.error}")
            return CleanResult(
                provider=name,
                skipped=True,
                dry_run=dry_run,
                message=f"读取回收站失败: {stats.error}",
                started_at=started_at,
                finished_at=started_at,
                details=stats.to_dict(),
            )
        if stats.count == 0:
            logger.info(f"[{name}] 回收站为空，无需清理")
            return CleanResult(
                provider=name,
                success=True,
                skipped=True,
                dry_run=dry_run,
                message="回收站为空",
                started_at=started_at,
                finished_at=started_at,
                details=stats.to_dict(),
            )

        preview = f"{stats.count} 个文件 / {format_size(stats.size)}"
        if dry_run:
            logger.info(f"[{name}] 试运行：将清空回收站（{preview}）")
            return CleanResult(
                provider=name,
                success=True,
                dry_run=True,
                count=stats.count,
                size=stats.size,
                message=f"试运行：将清空 {preview}",
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                details=stats.to_dict(),
            )

        try:
            ok, message = provider.clear()
        except Exception as exc:
            logger.exception(f"[{name}] 清空回收站异常: {exc}")
            ok, message = False, f"清空异常: {exc}"
        finished_at = datetime.now().isoformat(timespec="seconds")
        logger.info(
            f"[{name}] 清空回收站 {'成功' if ok else '失败'}: {preview} -> {message}"
        )
        return CleanResult(
            provider=name,
            success=ok,
            count=stats.count,
            size=stats.size,
            message=message if not ok else f"已提交清空 {preview}（{message}）",
            started_at=started_at,
            finished_at=finished_at,
            details=stats.to_dict(),
        )

    # ----- 状态与通知 -----

    def get_status(self) -> Dict[str, Any]:
        with self._state_lock:
            next_run = self.next_run_at
        return {
            "enabled": self.enabled,
            "providers": list(self.provider_names),
            "daily_at": [self._fmt_slot(s) for s in self.slots],
            "catch_up_on_start": self.catch_up_on_start,
            "run_on_start": self.run_on_start,
            "notify_telegram": self.notify_telegram,
            "max_items": self.max_items,
            "thread_alive": self.is_alive,
            "running": self.running,
            "next_run_at": next_run.isoformat(timespec="seconds") if next_run else "",
            "last_run_at": (
                self.last_run_at.isoformat(timespec="seconds")
                if self.last_run_at
                else ""
            ),
            "last_results": self.last_results,
            "history": self.history,
            "registered_providers": list_provider_names(),
        }

    def _notify(
        self, results: List[Dict[str, Any]], reason: str, dry_run: bool
    ) -> None:
        if not self.notify_telegram:
            return
        bot_token = str(self.telegram_config.get("bot_token", "") or "").strip()
        chat_id = str(self.telegram_config.get("chat_id", "") or "").strip()
        if not bot_token or not chat_id:
            return

        lines = ["🧹 网盘回收站清理" + ("（试运行）" if dry_run else "")]
        for item in results:
            flag = (
                "✅" if item.get("success") else ("⏭️" if item.get("skipped") else "❌")
            )
            lines.append(
                f"{flag} {item.get('provider')}: {item.get('message') or '无变更'}"
            )
        lines.append(f"来源: {reason}")
        self._send_telegram(bot_token, chat_id, "\n".join(lines))

    @staticmethod
    def _send_telegram(bot_token: str, chat_id: str, text: str) -> None:
        try:
            requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=15,
            )
        except Exception as exc:
            logger.warning(f"回收站清理通知发送失败: {exc}")


# ========== 全局单例（供 Web 层取用） ==========

_cleaner: Optional[RecycleCleaner] = None
_cleaner_lock = threading.Lock()


def get_cleaner() -> Optional[RecycleCleaner]:
    """获取当前进程的清理器（未初始化时返回 None）"""
    return _cleaner


def set_cleaner(cleaner: Optional[RecycleCleaner]) -> None:
    global _cleaner
    with _cleaner_lock:
        _cleaner = cleaner
