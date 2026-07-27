"""
路径生成工具 — 根据元数据和命名规则生成组织路径
"""

import re
import logging
from pathlib import Path
from typing import Dict, Optional, Union

from jinja2 import Template

logger = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """Sanitize a string to be safe for use as a filename."""
    if not name:
        return ""
    name = re.sub(r"[<>:/\\|?*]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def handle_file_conflict(file_path: Path) -> Path:
    """
    处理文件冲突，当文件存在时发出警告但保留原始文件名

    Args:
        file_path: 原始文件路径

    Returns:
        Path: 原始文件路径

    Raises:
        FileExistsError: 当文件已存在时抛出异常
    """
    if file_path.exists():
        logger.warning(f"文件已存在，无法覆盖: {file_path}")
        raise FileExistsError(f"文件已存在，无法覆盖: {file_path}")
    return file_path


def safe_int(val, default=1):
    if not val:
        return default
    if isinstance(val, int):
        return val
    if str(val).isdigit():
        return int(val)
    return val


def _is_special_file(original_path: Optional[Path]) -> bool:
    """检查是否是 OVA/特别篇文件"""
    if not original_path or not original_path.name:
        return False
    special_patterns = [
        r"\bOVA\b", r"\bOVA0?1\b", r"\bOVA0?2\b", r"\bOVA0?3\b",
        r"\bOVA0?4\b", r"\bOVA0?5\b", r"\bOVA0?6\b", r"\bOVA0?7\b",
        r"\bOVA0?8\b", r"\bOVA0?9\b", r"\bOVA10\b",
        r"(?<!\w)SP(?!\w)", r"(?<=\[)Special(?=\])",
        r"\bSpecial\s*(?:Episode|EP|Ep)\b", r"\bSpecial\s*\d+\b",
        r"\bSpecial\b(?=\s*\.\w+$)", r"特别篇", r"番外篇",
    ]
    filename_upper = original_path.name.upper()
    for pattern in special_patterns:
        if re.search(pattern, filename_upper, re.IGNORECASE):
            return True
    return False


def generate_new_path(
    metadata: Dict,
    naming_rules: Dict[str, str],
    determine_category_fn,
    sanitize_fn,
    rule_type: Optional[str] = None,
    original_path: Optional[Union[str, Path]] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    根据元数据和指定的命名规则生成新的组织路径。

    Args:
        metadata: 包含视频元数据的字典
        naming_rules: 命名规则字典
        determine_category_fn: 分类检测函数
        sanitize_fn: 文件名清洗函数
        rule_type: 命名规则类型 (tv_show, movie, anime, simple)
        original_path: 原始文件路径
        output_dir: 输出目录，用于检测文件冲突

    Returns:
        Path: 生成的新路径
    """
    if original_path and isinstance(original_path, str):
        original_path = Path(original_path)

    media_type = metadata.get("media_type")
    if rule_type is None:
        if media_type == "movie":
            rule_type = "movie"
        elif media_type == "tv" or (metadata.get("season") and metadata.get("episode")):
            rule_type = "tv_show"
        else:
            rule_type = "simple"

    template = naming_rules.get(rule_type, naming_rules["simple"])

    is_special = _is_special_file(original_path)
    if is_special:
        season = 0
    else:
        season = safe_int(metadata.get("season", 1))

    episode = safe_int(metadata.get("episode", 1))

    s_str = f"{season:02d}" if isinstance(season, int) else str(season)
    e_str = f"{episode:02d}" if isinstance(episode, int) else str(episode)

    year = metadata.get("year", "")
    tmdb_id = metadata.get("tmdb_id", "")

    year_suffix = f" ({year})" if year and year != "" else ""
    year_bracket_suffix = f" [{year}]" if year and year != "" else ""
    year_dot_suffix = f".{year}" if year and year != "" else ""

    tmdbid_suffix = f" {{tmdbid={tmdb_id}}}" if tmdb_id else ""
    tmdbid_bracket_suffix = f" [{tmdb_id}]" if tmdb_id else ""
    tmdbid_dot_suffix = f".{tmdb_id}" if tmdb_id else ""
    tmdbid_raw = tmdb_id if tmdb_id else ""

    en_title_suffix = f".{metadata.get('en_title')}" if metadata.get("en_title") else ""
    web_source = f".{metadata.get('web_source')}" if metadata.get("web_source") else ""
    edition = f".{metadata.get('edition')}" if metadata.get("edition") else ""
    part = f".{metadata.get('part')}" if metadata.get("part") else ""
    video_format = f"{metadata.get('video_format')}" if metadata.get("video_format") else ""
    video_codec = f".{metadata.get('video_codec')}" if metadata.get("video_codec") else ""
    audio_codec = f".{metadata.get('audio_codec')}" if metadata.get("audio_codec") else ""
    customization = f".{metadata.get('customization')}" if metadata.get("customization") else ""
    customization_suffix = f"-{metadata.get('customization')}" if metadata.get("customization") else ""
    release_group = f"-{metadata.get('release_group')}" if metadata.get("release_group") else ""
    release_group_suffix = f"-{metadata.get('release_group')}" if metadata.get("release_group") else ""

    season_episode = f"S{s_str}E{e_str}"

    format_vars = {
        "title": sanitize_fn(
            metadata.get("title") or metadata.get("original_title") or metadata.get("show_name", "Unknown Title")
        ),
        "year": metadata.get("year", ""),
        "year_suffix": year_suffix,
        "year_bracket_suffix": year_bracket_suffix,
        "year_dot_suffix": year_dot_suffix,
        "tmdbid_suffix": tmdbid_suffix,
        "tmdbid_bracket_suffix": tmdbid_bracket_suffix,
        "tmdbid_dot_suffix": tmdbid_dot_suffix,
        "tmdb_id": tmdb_id,
        "tmdbid_raw": tmdbid_raw,
        "en_title_suffix": en_title_suffix,
        "web_source": web_source,
        "edition": edition,
        "part": part,
        "video_format": video_format,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "customization": customization,
        "customization_suffix": customization_suffix,
        "release_group": release_group,
        "release_group_suffix": release_group_suffix,
        "season_episode": season_episode,
        "show_name": sanitize_fn(
            metadata.get("show_name", metadata.get("original_show_name", "Unknown Show"))
        ),
        "season": season,
        "episode": episode,
        "episode_name": sanitize_fn(metadata.get("episode_name", "")),
        "movie_name": sanitize_fn(
            metadata.get("title") or metadata.get("original_title") or metadata.get("show_name", "Unknown Movie")
        ),
        "anime_name": sanitize_fn(
            metadata.get("show_name", metadata.get("original_show_name", "Unknown Anime"))
        ),
        "season_name": f"Season {s_str}",
        "quality_tags": metadata.get("quality_tags", ""),
        "quality_tags_suffix": (
            f" {metadata.get('quality_tags', '')}" if metadata.get("quality_tags", "") else ""
        ),
    }

    try:
        file_ext = ""
        if original_path and original_path.suffix:
            file_ext = original_path.suffix
        elif metadata.get("extension"):
            file_ext = metadata.get("extension")
            if file_ext and not file_ext.startswith("."):
                file_ext = "." + file_ext

        if "{{" in template and "}}" in template:
            jinja_template = Template(template)
            jinja_vars = {
                "title": format_vars["show_name"] if format_vars.get("show_name") else format_vars.get("movie_name", "Unknown Title"),
                "year": year,
                "tmdbid": tmdb_id,
                "season": season,
                "episode": episode,
                "season_episode": format_vars["season_episode"],
                "videoFormat": format_vars.get("video_format", ""),
                "webSource": metadata.get("web_source", ""),
                "edition": metadata.get("edition", ""),
                "videoCodec": metadata.get("video_codec", ""),
                "audioCodec": metadata.get("audio_codec", ""),
                "customization": metadata.get("customization", ""),
                "releaseGroup": metadata.get("release_group", ""),
                "fileExt": file_ext,
                "quality_tags": format_vars["quality_tags"],
                "quality_tags_suffix": format_vars["quality_tags_suffix"],
                "show_name": format_vars["show_name"],
                "movie_name": format_vars["movie_name"],
                "episode_name": format_vars["episode_name"],
            }
            path_str = jinja_template.render(**jinja_vars)
        else:
            processed_template = template
            if not year:
                processed_template = processed_template.replace(" ({year})", "")
                processed_template = processed_template.replace("({year})", "")

            tmdbid_placeholder = "__TMDBID_PLACEHOLDER__"
            if tmdb_id:
                processed_template = processed_template.replace("{tmdbid=tmdbid}", tmdbid_placeholder)
            else:
                processed_template = processed_template.replace(" {tmdbid=tmdbid}", "")
                processed_template = processed_template.replace("{tmdbid=tmdbid}", "")

            path_str = processed_template.format(**format_vars)

            if tmdb_id:
                tmdbid_str = f"{{tmdbid={tmdb_id}}}"
                path_str = path_str.replace(tmdbid_placeholder, tmdbid_str)

        if file_ext and not path_str.lower().endswith(file_ext.lower()):
            path_str = path_str + file_ext

        path = Path(path_str)

        category_path = determine_category_fn(metadata)
        base_category = "TV Shows" if media_type == "tv" else "Movies"

        if path.parts and path.parts[0] == base_category:
            full_path = Path(category_path) / Path(*path.parts[1:])
        else:
            full_path = Path(category_path) / path

        if output_dir:
            full_output_path = output_dir / full_path
            full_path = handle_file_conflict(full_output_path)

        logger.info(f"generate_new_path output: {full_path}")
        return full_path
    except KeyError as e:
        logger.error(f"Naming template missing required variable: {e}. Using default path structure.")
        if not metadata.get("show_name"):
            raise ValueError("Cannot generate path without show name")

        show_name = sanitize_fn(metadata["show_name"])
        season = metadata.get("season", "1")
        episode = metadata.get("episode", "1")
        episode_name = sanitize_fn(metadata.get("episode_name", ""))

        season_str = f"Season {int(season):02d}" if str(season).isdigit() else f"Season {season}"
        episode_str = f"E{int(episode):02d}" if str(episode).isdigit() else f"E{episode}"

        filename_parts = [show_name, f"S{int(season):02d}{episode_str}"]
        if episode_name:
            filename_parts.append(episode_name)

        filename = " - ".join(filename_parts)
        if original_path and original_path.suffix:
            filename += original_path.suffix

        return Path(f"{filename}")