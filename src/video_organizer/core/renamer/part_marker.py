"""
「分段短篇 / 剧场版拆段」命名标记处理（Part N）

剧场版按段发行时，PT 命名常写成：

    Grotesqqque.YOROSHIKU.Girl.Part.2.2026.NF.WEB-DL.x264.AAC.mkv

- ``YOROSHIKU Girl`` 是**分段名**，TMDB 里只有总条目（GROTESQQQUE 2026，
  id=1313587）→ 整串搜索必然 0 条，必须剥掉分段名 / ``Part N`` 才能命中
- 但 ``Part 2`` 是这一段的唯一身份，输出文件名必须保留，否则同一总条目的
  多段会生成同名文件（互相覆盖 / 冲突）

本模块只放纯函数，``renamer.py``（搜索兜底 + 命名）与 ``path_builder.py``
（命名）共用，避免 import 循环。
"""

import re
from pathlib import Path
from typing import List

PART_MARKER_RE = re.compile(
    r"(?i)(?:^|[.\s_\-\[\(])(?:part|pt)\.?\s*(\d{1,2}|[IVX]{1,5})(?=[.\s_\-\)\]]|$)"
)


def extract_part_label(filename: str) -> str:
    """从文件名提取「分段编号」标记，返回可写入文件名的后缀（如 ``Part 2``）

    剧场版拆段发行时 PT 命名常写成
    ``Grotesqqque.YOROSHIKU.Girl.Part.2.2026.NF.WEB-DL.x264.AAC.mkv``：
    「YOROSHIKU Girl」是**分段名**，TMDB 里只有总条目（GROTESQQQUE 2026，
    id=1313587），所以搜索时必须剥掉分段名/``Part N``；但输出文件名必须
    保留 ``Part 2``，否则同一个总条目的多段会生成同名文件互相覆盖/冲突。

    Args:
        filename: 文件名或完整路径

    Returns:
        ``Part N`` 字符串；无标记时返回空串
    """
    if not filename:
        return ""
    stem = Path(str(filename)).stem
    match = PART_MARKER_RE.search(stem)
    if not match:
        return ""
    return f"Part {match.group(1)}"


def segment_part_search_candidates(search_term: str) -> List[str]:
    """从「分段短篇」搜索词生成剥离候选（越靠后越激进）

    ``'Grotesqqque YOROSHIKU Girl Part 2'``
      → ``['Grotesqqque YOROSHIKU Girl', 'Grotesqqque YOROSHIKU', 'Grotesqqque']``

    只处理带 ``Part N`` / ``Pt.N`` 标记的搜索词（由调用点判定），避免对普通
    0 结果标题做尾部截断造成误配；调用方还必须用完全匹配+年份守卫验过才采纳。

    Args:
        search_term: 已清洗的搜索词

    Returns:
        去重后的搜索词候选（最多 4 个），无可用候选时返回空列表
    """
    term = (search_term or "").strip()
    if not term:
        return []

    candidates: List[str] = []
    base = term
    match = PART_MARKER_RE.search(term)
    if not match:
        # 无 Part/Pt 标记 → 不做任何截断（普通 0 结果标题不走这条策略）
        return []
    # “... Part N” 前面的整段（标题 + 分段名）
    base = term[: match.start()].strip(" .-_")
    if base and base != term:
        candidates.append(base)

    # 逐词丢弃尾部词：分段名一般跟在总片名后面
    words = base.split()
    while len(words) > 1:
        words.pop()
        candidate = " ".join(words).strip(" .-_")
        if len(candidate) >= 2 and candidate not in candidates:
            candidates.append(candidate)

    return candidates[:4]


def inject_part_suffix(template: str, part_label: str, title_text: str = "") -> str:
    """把 ``Part N`` 注入命名模板的**文件名部分**（目录部分不动）

    默认命名模板（``Movies/{show_name} ({year}) .../{show_name} {quality_tags}``）
    没有 ``{part}`` 占位符，用户不改模板也应该拿到 ``GROTESQQQUE Part 2 1080p...mkv``：
    同一总条目的多段共用目录、文件名区分。因此这里在模板最后一个 ``/``
    之后、首个标题占位符后插入后缀。

    Args:
        template: 命名模板字符串
        part_label: ``Part N``（空串则不处理）
        title_text: 最终片名（已含同样标记时不注入，避免“Part 1 Part 1”）

    Returns:
        注入后的模板（无需注入时原样返回）
    """
    if not template or not part_label:
        return template
    # 模板自己处理了位置（{part} / {part_suffix} / {{ part }}）就别插手
    if re.search(r"\{\{?\s*part", template):
        return template
    # TMDB 收录名本身已带 Part N（The.Hunger.Games.Mockingjay.Part.1）
    if title_text and part_label.lower() in str(title_text).lower():
        return template

    head, sep, file_part = template.rpartition("/")
    for placeholder in (
        # str.format 风格
        "{show_name}",
        "{movie_name}",
        "{title}",
        "{anime_name}",
        # jinja2 风格（模板含 {{ }} 时走 jinja 渲染分支）
        "{{ show_name }}",
        "{{ movie_name }}",
        "{{ title }}",
        "{{show_name}}",
        "{{movie_name}}",
        "{{title}}",
    ):
        if placeholder not in file_part:
            continue
        # 年分紧跟标题时把后缀放到年份后面，读起来更自然：
        #   "{show_name} ({year}) {quality_tags}" → "{show_name} ({year}) Part 2 ..."
        # 否则（默认模板）直接跟在标题后面。
        # 两种写法：括号形式 " ({year})" / 紧凑形式 "{year_suffix}"（允许多空格分隔）
        year_token = (
            r"(?:\{(?:year|year_suffix|year_bracket_suffix)\}|"
            r"\{\{\s*(?:year|year_suffix|year_bracket_suffix)\s*\}\})"
        )
        year_group = re.search(
            re.escape(placeholder)
            + r"(?:\s*\(\s*"
            + year_token
            + r"\s*\)|\s*"
            + year_token
            + r")",
            file_part,
        )
        if year_group:
            insert_at = year_group.end()
            return (
                f"{head}{sep}{file_part[:insert_at]} {part_label}"
                f"{file_part[insert_at:]}"
            )
        file_part = file_part.replace(placeholder, f"{placeholder} {part_label}", 1)
        break
    else:
        return template
    return f"{head}{sep}{file_part}"
