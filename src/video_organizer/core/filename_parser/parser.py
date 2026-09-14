"""确定性文件名解析器 —— 渐进替代 GuessIt。

分层规则引擎，命中即返回（不累加猜错风险）。核心原则：**宁可留空，不要乱猜**。

当前已实现：
- L2 路径上下文：中文剧名目录 + 裸数字文件（``斗破丨苍穹/210 4K.mkv``）→ episode
- L3 紧凑格式：中文标题 + 末尾 1-3 位数字（``入青云01.mp4``）→ episode
- L4 PT 命名法：``[中文].English.2024.2160p...`` → 中文标题 / 年份
- L5 方括号集号：``[剧名][13-25][...]/[剧名][25][...]`` → show_name / episode
- L6 数字标题保护：4 位纯数字无中文目录（``1917.mkv``）→ movie（不拆季集）

后续层（L1 显式标记等）逐步从 renamer._extract_with_regex 和 guessit_parser
补丁中迁移进来。分层设计见 README.md。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 文件名主干末尾常见的质量/编码/来源标签（剥离后剩余部分若为纯数字，则视为集号）
_QUALITY_SUFFIX_RE = re.compile(
    r"\s*(?:4[kK]|2160p|1080p|720p|480p|360p|UHD|FHD|HD|HDR10?\+?|DV|"
    r"H\.?26[45]|HEVC|AVC|WEB-?DL|WEBRip|BluRay|BDRip|DVDRip|REMUX|"
    r"AAC\d*|AC3|EAC3|DTS[-.]?[\w.]*|TrueHD(?:\.[\w]+)*|Atmos|FLAC|"
    r"10bit|8bit|60fps|30fps)(?:[_\-\s]*(?:V\d+|Rev|Repack|Proper))?\s*$",
    re.IGNORECASE,
)


class FilenameParser:
    """确定性文件名解析器（分层规则引擎）。"""

    def parse(self, filename: str) -> Dict[str, Any]:
        """解析文件名，返回确定性识别出的字段（未识别字段不出现在结果中）。

        命中任一规则即返回；无规则命中返回空字典，调用方回退到 GuessIt/TMDB/LLM。
        """
        path = Path(filename)
        stem = path.stem
        parent = path.parent.name

        # 季目录（Season N / Sxx / 第N季 / Specials）不是剧名，
        # 向上取祖父目录作为剧名上下文（"剧名(2025)/Season 1/05.mkv" → 用祖父剧名）
        effective_parent = parent
        if re.match(
            r"(?i)^(?:Season\s*\d+|S\d+|第\d+季|Specials?|SP\d*)$", parent or ""
        ):
            gparent = path.parent.parent.name
            if gparent and _is_chinese_show_dir(gparent):
                effective_parent = gparent

        # L2 路径上下文：中文剧名目录 + 裸数字集号
        result = self._parse_path_context(stem, effective_parent)
        if result:
            return result

        # L4 PT 命名法：[中文].English.2024.2160p...
        result = self._parse_pt_naming(stem)
        if result:
            return result

        # L5 方括号集号：[剧名][13-25][...]/[剧名][25][...]
        result = self._parse_bracket_episode(path)
        if result:
            return result

        # L5b 单层方括号：[剧名][N][标签]...（剧名在方括号内，regex 会误把扩展名当剧名）
        result = self._parse_bracket_single(path.name)
        if result:
            return result

        # L3 紧凑格式：中文标题 + 末尾数字
        result = self._parse_compact(stem)
        if result:
            return result

        # L6 数字标题保护：4 位纯数字无中文目录 → movie
        result = self._parse_numeric_title(stem, parent)
        if result:
            return result

        # L7 电影续集号：``Title.2.2014...`` → show_name 合并续集号
        result = self._parse_movie_sequel(stem)
        if result:
            return result

        return {}

    # ---- 各层规则 ----

    def _parse_path_context(self, stem: str, parent: str) -> Dict[str, Any]:
        """L2：中文剧名目录 + 裸数字文件名 → episode（国漫年番）。"""
        numeric = _strip_quality_suffix(stem)
        if numeric.isdigit() and _is_chinese_show_dir(parent):
            # 4 位纯数字（19xx/20xx）是电影年份名（"1917 4K.mkv" 的 1917），
            # 不是集号（裸集号至多 4 位非年份）；交给 L6 数字标题保护判 movie
            if re.match(r"^(?:19|20)\d{2}$", numeric):
                return {}
            logger.info(f"L2 路径上下文命中: '{parent}/{stem}' -> episode={numeric}")
            # season 留空，交由 renamer._ensure_season 用目录年份反推或默认第 1 季
            return {"episode": int(numeric), "media_type": "tv"}
        return {}

    def _parse_pt_naming(self, stem: str) -> Dict[str, Any]:
        """L4：PT 命名法 ``[中文标题].English.2024.2160p...``。

        含 SxxExx 视为剧集，否则视为电影。
        """
        m = re.match(r"^\[([\u4e00-\u9fff]+)\]\.(.+?)\.(\d{4})\.", stem)
        if not m:
            return {}
        cn_title, en_title, year = m.group(1), m.group(2), m.group(3)
        # SxxExx 从完整主干搜索（en_title 非贪婪截断在年份前，
        # "[中文].English.2025.S01E22.2160p..." 的 S01E22 在年份之后）
        se = re.search(r"(?i)\bS(\d{1,2})E(\d{1,4})\b", stem)
        if se:
            logger.info(f"L4 PT 命名法命中(剧集): '{stem}' -> {cn_title}")
            return {
                "show_name": cn_title,
                "season": int(se.group(1)),
                "episode": int(se.group(2)),
                "year": int(year),
                "media_type": "tv",
            }
        logger.info(f"L4 PT 命名法命中(电影): '{stem}' -> {cn_title} ({year})")
        return {
            "show_name": cn_title,
            "year": int(year),
            "media_type": "movie",
        }

    def _parse_bracket_episode(self, path: Path) -> Dict[str, Any]:
        """L5：方括号集号 ``[剧名][M-N][...]/[剧名][N][...]``。

        父目录的 ``[M-N]`` 是集号范围（不是 season），文件名 ``[N]`` 是具体集号。
        """
        filename_only = path.name
        parent = path.parent.name
        fm = re.match(r"^\[([^\]]+)\]\s*\[(\d+)\]", filename_only)
        if not fm:
            return {}
        show = fm.group(1).strip()
        episode = int(fm.group(2))
        if not show or show.isdigit():
            return {}
        # 父目录需为 [剧名][范围] 形式，确认 [N] 是集号而非其他标签
        pm = re.match(r"^\[([^\]]+)\]\s*\[(\d+)-(\d+)\]", parent)
        if not pm:
            return {}
        logger.info(f"L5 方括号集号命中: '{filename_only}' -> {show} E{episode}")
        # season 留空，交由 renamer._ensure_season 处理
        return {"show_name": show, "episode": episode, "media_type": "tv"}

    def _parse_bracket_single(self, filename_only: str) -> Dict[str, Any]:
        """L5b：单层方括号 ``[剧名][N][标签]...``（剧名在方括号内）。

        ``[Tonikaku Kawaii][04][BIG5][1080P].mp4`` → show_name + episode。
        排除方括号内是质量标签/扩展名（``[BIG5][01]``）的情况。
        """
        m = re.match(r"^\[([^\]]+)\]\s*\[(\d{1,4})\]", filename_only)
        if not m:
            return {}
        show = m.group(1).strip()
        episode = int(m.group(2))
        if not show or show.isdigit() or _is_quality_or_ext(show):
            return {}
        logger.info(f"L5b 单方括号集号命中: '{filename_only}' -> {show} E{episode}")
        return {"show_name": show, "episode": episode, "media_type": "tv"}

    def _parse_compact(self, stem: str) -> Dict[str, Any]:
        """L3：紧凑格式 中文标题 + 末尾 1-3 位数字（``入青云01.mp4``）→ episode。

        排除末尾 4 位数字（年份/标题如 ``唐探1900``）与音频小数（``5.1``）。
        已有显式季/集标记（S13E04/第N集/EPxx）或标题含点分隔的文件交给 regex，
        紧凑层不碰（否则 ``...H265`` 的 ``265`` 会被当成集号）。
        """
        if _has_explicit_episode_marker(stem):
            return {}
        m = re.match(r"^(.+?)(\d{1,3})$", stem)
        if not m:
            return {}
        title = m.group(1).strip()
        num = m.group(2)
        if not title or title.isdigit():
            return {}
        # 标题需含中文（本项目紧凑格式主要面向中文剧）
        if not re.search(r"[\u4e00-\u9fff]", title):
            return {}
        # 数字前不能是数字或点（排除 "唐探1"+"900" 拆分、音频 "5.1"）
        if re.search(r"[\d.]$", title):
            return {}
        # 标题不含点分隔："剧名.01" 类交由 regex；"...8bit.H265" 的 265 不得当集号
        if "." in title:
            return {}
        logger.info(f"L3 紧凑格式命中: '{stem}' -> {title} E{num}")
        return {
            "show_name": title,
            "episode": int(num),
            "media_type": "tv",
        }

    def _parse_numeric_title(self, stem: str, parent: str) -> Dict[str, Any]:
        """L6：4 位纯数字文件名且无中文目录 → 视为电影标题（如 ``1917.mkv``）。

        避免 GuessIt 把年份范围数字拆成 season+episode（1917 → S19E17）。
        """
        numeric = _strip_quality_suffix(stem)
        if numeric.isdigit() and len(numeric) == 4 and not _is_chinese_show_dir(parent):
            logger.info(f"L6 数字标题保护命中: '{stem}' -> movie '{numeric}'")
            return {"show_name": numeric, "media_type": "movie"}
        return {}

    def _parse_movie_sequel(self, stem: str) -> Dict[str, Any]:
        """L7：电影续集号 ``Title.2.2014...`` → show_name 合并续集号。

        ``The.Amazing.Spider-Man.2.2014...`` 的 ``.2.`` 是续集号（非季号），
        GuessIt 会把它拆成 season，导致搜索“第一部标题”误识别成第一部。
        此规则要求数字后紧跟 4 位年份，且数字前为 ``.``（排除 ``S02`` 季号）。
        """
        m = re.match(r"^(.+?)\.(\d{1,2})\.(\d{4})(?:\.|$)", stem)
        if not m:
            return {}
        title = m.group(1).replace(".", " ").replace("_", " ").strip()
        sequel = m.group(2)
        year = m.group(3)
        if not title or title.isdigit():
            return {}
        logger.info(f"L7 电影续集号合并: '{stem}' -> '{title} {sequel}' ({year})")
        return {
            "show_name": f"{title} {sequel}",
            "year": int(year),
            "media_type": "movie",
        }


def _strip_quality_suffix(stem: str) -> str:
    """剥离文件名主干末尾的质量/编码标签。

    ``210 4K`` -> ``210``；``01`` -> ``01``；``第3集 4K`` -> ``第3集``（不剥离中文集号标记）。
    """
    stripped = _QUALITY_SUFFIX_RE.sub("", stem.strip())
    return stripped.strip()


# 显式季/集标记（S13E04 / 第3集 / EP04）——这些格式由 regex 负责，紧凑层不碰
_EXPLICIT_EPISODE_MARKER_RE = re.compile(
    r"(?i)(?:^|[^a-z0-9])s\d{1,2}e\d{1,4}(?:[^a-z0-9]|$)"
    r"|第\d{1,4}[集话話]"
    r"|(?:^|[^a-z0-9])ep\d{1,4}(?:[^a-z0-9]|$)"
)


def _has_explicit_episode_marker(text: str) -> bool:
    """文件名是否含显式季/集标记（S13E04/第3集/EP04）。"""
    return bool(_EXPLICIT_EPISODE_MARKER_RE.search(text))


def _is_chinese_show_dir(name: str) -> bool:
    """父目录是否像中文剧名目录。

    要求含中文且非纯数字，避免把英文目录（TV Shows）或年份目录下的电影标题数字
    （如 ``1917.mkv``）误判为集号；顶层分类目录（电影/动漫/电视剧/剧集等）
    不是剧名目录（``100 4K.mkv`` 在电影目录下的 100 是电影名，不是集号）。
    """
    if not name or name.isdigit():
        return False
    if not re.search(r"[\u4e00-\u9fff]", name):
        return False
    # 顶层分类目录词：不是具体的剧名
    return name.strip() not in {
        "电影",
        "MOVIE",
        "MOVIES",
        "FILM",
        "FILMS",
        "动漫",
        "动画",
        "ANIME",
        "电视剧",
        "剧集",
        "TV",
        "TVS",
        "TVSHOWS",
        "综艺",
        "纪录片",
        "音乐",
        "演唱会",
        "日番",
        "国产",
        "影视",
        "影视资源",
        "影视库",
        "媒体",
        "媒体库",
        "资源",
        "网盘",
        "备份",
    }


# 方括号内常见的质量标签/扩展名，不能当作剧名
_QUALITY_OR_EXT_TOKENS = {
    "BIG5",
    "GB",
    "CHS",
    "CHT",
    "简体",
    "繁体",
    "720P",
    "1080P",
    "2160P",
    "4K",
    "HEVC",
    "AVC",
    "AAC",
    "AC3",
    "FLAC",
    "MP4",
    "MKV",
    "AVI",
    "WEB",
    "WEB-DL",
    "REMUX",
    "HDR",
    "DV",
    "BD",
}


def _is_quality_or_ext(text: str) -> bool:
    """方括号内文本是否为质量标签/扩展名（而非剧名）。"""
    return text.upper() in _QUALITY_OR_EXT_TOKENS
