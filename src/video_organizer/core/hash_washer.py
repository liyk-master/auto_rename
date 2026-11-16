"""
洗码（Hash Wash）模块

网盘（123/139/天翼）上传前都会先算文件哈希做「秒传/去重」：
同一个种子下载来的文件哈希与网盘上已有的条目完全一致，于是被秒传成
**别人那一份**的引用。洗码就是在上传前轻微改动文件内容，使哈希变化，
从而强制走真实上传、得到一份独立的文件。

实现方式：在文件**尾部追加若干随机字节**。
- MKV/MP4/TS 等容器的解析在结构结束后即停止，尾部多余字节不影响播放；
- 不改变时长/画质，不需要 ffmpeg，速度取决于磁盘拷贝带宽。

两种落地模式（`[hash_wash] mode`）：
- `copy`（默认，安全）：把原文件流式拷到临时目录并追加随机字节，上传副本，
  上传结束删除副本，**原文件一个字节都不动**（PT 做种/校验场景必须用这个）。
- `inplace`（省空间）：直接在原文件尾部追加随机字节。适合「上传完就删」的
  下载器流程，但会破坏下载器的完整性校验（qBittorrent 重新校验会报损坏），
  玩 PT 保种的目录不要用。

⚙ 重试幂等：`inplace` 模式下同一个文件可能被反复重试上传，若不记录状态每次
都会再追加一段，文件越洗越大。`data/hash_wash/state.json` 记录
「路径 -> 洗码后大小」，当前大小与记录一致时跳过（视为已洗）。
"""

import json
import logging
import os
import random
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# 默认临时目录（相对 cwd，与 data/139_rapid 同级，均已 gitignore）
DEFAULT_TEMP_DIR = "data/hash_wash"

# 默认追加的随机字节范围（1KB ~ 64KB）
DEFAULT_MIN_BYTES = 1024
DEFAULT_MAX_BYTES = 64 * 1024

# 洗码状态文件名（inplace 幂等用）
STATE_FILENAME = "state.json"


def _to_bool(value: Any, default: bool = False) -> bool:
    """配置值转 bool（configparser 读出来可能是字符串）"""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("true", "1", "yes", "on", "y")


def _to_int(value: Any, default: int) -> int:
    """配置值转 int，非法时回落默认值"""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


class WashResult:
    """一次洗码的结果

    Attributes:
        original_path: 原始文件路径（字幕扫描等逻辑仍应使用它）
        upload_path: 实际用于上传的路径；未洗码时等于 original_path
        washed: 是否真的改动了内容（哈希已变化）
        is_temp: upload_path 是否为临时副本，需要在上传后清理
        mode: 生效的模式 copy / inplace / none
        message: 供日志展示的说明
    """

    def __init__(
        self,
        original_path: str,
        upload_path: Optional[str] = None,
        washed: bool = False,
        is_temp: bool = False,
        mode: str = "none",
        message: str = "",
    ):
        self.original_path = str(original_path)
        self.upload_path = str(upload_path) if upload_path else str(original_path)
        self.washed = washed
        self.is_temp = is_temp
        self.mode = mode
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (
            f"WashResult(original={self.original_path!r}, upload={self.upload_path!r}, "
            f"washed={self.washed}, is_temp={self.is_temp}, mode={self.mode!r})"
        )


class HashWasher:
    """洗码器：按配置决定是否/如何改动文件内容以规避网盘秒传"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}

        self.enabled = _to_bool(config.get("enabled"), False)
        mode = str(config.get("mode", "copy")).strip().lower()
        self.mode = mode if mode in ("copy", "inplace") else "copy"
        self.min_bytes = max(0, _to_int(config.get("min_bytes"), DEFAULT_MIN_BYTES))
        self.max_bytes = max(
            self.min_bytes, _to_int(config.get("max_bytes"), DEFAULT_MAX_BYTES)
        )
        raw_temp_dir = str(config.get("temp_dir", DEFAULT_TEMP_DIR)).strip()
        self.temp_dir = Path(raw_temp_dir) if raw_temp_dir else Path(DEFAULT_TEMP_DIR)
        self.keep_washed = _to_bool(config.get("keep_washed"), False)

        self._state_lock = threading.Lock()
        self._state_path = self.temp_dir / STATE_FILENAME

    # ====== 对外接口 ======

    def wash(self, file_path: str) -> WashResult:
        """对文件洗码，返回上传应使用的路径

        任何异常都不会向上抛：洗码失败时回落为「上传原文件」，
        宁可被秒传也不要让整条上传流程失败。

        Args:
            file_path: 待上传的本地文件路径

        Returns:
            WashResult；未启用或失败时 upload_path == 原路径
        """
        if not self.enabled:
            return WashResult(file_path, mode="none", message="洗码未启用")

        try:
            source = Path(file_path)
            if not source.is_file():
                logger.warning(f"洗码跳过：文件不存在 {file_path}")
                return WashResult(file_path, mode="none", message="文件不存在")

            if self.mode == "inplace":
                return self._wash_inplace(source)
            return self._wash_copy(source)
        except Exception as e:  # noqa: BLE001 - 洗码失败不得影响上传
            logger.warning(f"洗码失败，将直接上传原文件: {file_path}, 错误: {e}")
            return WashResult(
                file_path, mode="none", message=f"洗码失败已回落原文件: {e}"
            )

    def cleanup(self, result: Optional[WashResult]) -> None:
        """清理洗码产生的临时副本（keep_washed=True 时保留）"""
        if result is None or not result.is_temp:
            return
        if self.keep_washed:
            logger.info(f"按配置保留洗码副本: {result.upload_path}")
            return
        try:
            temp_path = Path(result.upload_path)
            if temp_path.exists():
                temp_path.unlink()
                logger.debug(f"已删除洗码副本: {temp_path}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"删除洗码副本失败: {result.upload_path}, 错误: {e}")

    # ====== 内部实现 ======

    def _random_tail(self) -> bytes:
        """生成随机尾部字节（长度在 [min_bytes, max_bytes] 之间随机）"""
        if self.max_bytes <= 0:
            # 配置成 0 表示不追加内容 —— 仍然洗码：至少写 1 个随机字节
            length = 1
        elif self.min_bytes >= self.max_bytes:
            length = self.max_bytes
        else:
            length = random.randint(self.min_bytes, self.max_bytes)
        return os.urandom(length)

    def _wash_copy(self, source: Path) -> WashResult:
        """copy 模式：拷贝到临时目录 + 尾部追加随机字节，原文件不动"""
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            size = source.stat().st_size
        except OSError as e:
            return WashResult(
                str(source), mode="none", message=f"读取文件信息失败: {e}"
            )

        # 空间预检：副本需要与原文件同样大的空间，不够就别洗（回落原文件）
        try:
            free = shutil.disk_usage(str(self.temp_dir)).free
            if free < size + self.max_bytes + 64 * 1024 * 1024:
                msg = (
                    f"临时目录可用空间不足（需 {size / 1024 / 1024:.0f}MB，"
                    f"剩 {free / 1024 / 1024:.0f}MB），跳过洗码直接上传原文件"
                )
                logger.warning(msg)
                return WashResult(str(source), mode="copy", message=msg)
        except OSError as e:
            logger.warning(f"检查临时目录空间失败（继续尝试洗码）: {e}")

        temp_path = self._unique_temp_path(source)
        start = time.time()
        tail = self._random_tail()

        try:
            with source.open("rb") as fin, temp_path.open("wb") as fout:
                shutil.copyfileobj(fin, fout, length=8 * 1024 * 1024)
                fout.write(tail)
        except Exception:
            # 半成品必须删掉，否则会占满磁盘
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
            raise

        elapsed = time.time() - start
        msg = (
            f"洗码完成（copy，+{len(tail)} 字节，耗时 {elapsed:.1f}s）: "
            f"{temp_path.name}"
        )
        logger.info(msg)
        return WashResult(
            str(source),
            upload_path=str(temp_path),
            washed=True,
            is_temp=True,
            mode="copy",
            message=msg,
        )

    def _unique_temp_path(self, source: Path) -> Path:
        """生成不与现有文件冲突的临时副本路径"""
        candidate = self.temp_dir / source.name
        if not candidate.exists():
            return candidate
        stem, suffix = source.stem, source.suffix
        for index in range(1, 1000):
            candidate = self.temp_dir / f"{stem}.{index}{suffix}"
            if not candidate.exists():
                return candidate
        # 极端情况：用时间戳兜底
        return self.temp_dir / f"{stem}.{int(time.time() * 1000)}{suffix}"

    def _wash_inplace(self, source: Path) -> WashResult:
        """inplace 模式：直接在原文件尾部追加随机字节（会破坏下载器校验）"""
        key = str(source)
        state = self._load_state()
        try:
            current_size = source.stat().st_size
        except OSError as e:
            return WashResult(key, mode="none", message=f"读取文件信息失败: {e}")

        recorded = state.get(key)
        if isinstance(recorded, int) and recorded == current_size:
            msg = "文件已洗过码（大小与记录一致），跳过重复洗码"
            logger.info(msg)
            return WashResult(key, mode="inplace", message=msg)

        tail = self._random_tail()
        start = time.time()
        with source.open("ab") as f:
            f.write(tail)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # 某些文件系统（网络盘）不支持 fsync，忽略即可
                pass

        try:
            new_size = source.stat().st_size
        except OSError:
            new_size = current_size + len(tail)

        with self._state_lock:
            state[key] = new_size
            # 状态文件会随重试无限增长，顺手剪掉已不存在的条目
            if len(state) > 512:
                state = {
                    path: size for path, size in state.items() if os.path.exists(path)
                }
                state[key] = new_size
            self._save_state(state)

        elapsed = time.time() - start
        msg = f"洗码完成（inplace，+{len(tail)} 字节，耗时 {elapsed:.1f}s）: {source.name}"
        logger.info(msg)
        return WashResult(key, mode="inplace", washed=True, message=msg)

    def _load_state(self) -> Dict[str, int]:
        """读取 inplace 幂等状态"""
        try:
            if not self._state_path.exists():
                return {}
            with self._state_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"读取洗码状态失败（忽略）: {e}")
            return {}

    def _save_state(self, state: Dict[str, int]) -> None:
        """写入 inplace 幂等状态"""
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            with self._state_path.open("w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"保存洗码状态失败（忽略）: {e}")
