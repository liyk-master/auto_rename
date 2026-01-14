#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清理重复的特别篇判断patterns
"""


def clean_duplicate_patterns():
    """清理重复的special_patterns"""

    file_path = r"f:\Project\Python\auto_rename\src\video_organizer\core\renamer.py"

    # 读取文件
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 查找special_patterns列表并清理重复
    import re

    # 匹配整个special_patterns列表
    pattern_match = re.search(r"special_patterns = \[(.*?)\]", content, re.DOTALL)

    if pattern_match:
        patterns_content = pattern_match.group(1)

        # 提取所有的pattern行
        pattern_lines = [
            line.strip()
            for line in patterns_content.split("\n")
            if line.strip() and not line.strip().startswith("#")
        ]

        # 去重（保持顺序）
        seen = set()
        unique_patterns = []
        for pattern in pattern_lines:
            if pattern not in seen:
                seen.add(pattern)
                unique_patterns.append(pattern)

        # 重新构建special_patterns列表
        new_patterns_list = "special_patterns = [\n"
        for pattern in unique_patterns:
            # 找到原始行中的注释
            original_line_match = re.search(
                re.escape(pattern) + r".*?#.*", patterns_content, re.DOTALL
            )
            if original_line_match:
                new_patterns_list += (
                    f"                {original_line_match.group().strip()}\n"
                )
            else:
                new_patterns_list += f"                {pattern}\n"
        new_patterns_list += "            ]"

        # 替换原来的special_patterns列表
        new_content = re.sub(
            r"special_patterns = \[.*?\]", new_patterns_list, content, flags=re.DOTALL
        )

        # 写回文件
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        print("✓ 成功清理重复的special_patterns")
        print(f"  - 原始patterns数量: {len(pattern_lines)}")
        print(f"  - 去重后patterns数量: {len(unique_patterns)}")
    else:
        print("✗ 未找到special_patterns列表")


if __name__ == "__main__":
    clean_duplicate_patterns()
