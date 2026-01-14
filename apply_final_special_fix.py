#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
应用最终优化的特别篇判断逻辑到 renamer.py
"""

import re


def apply_final_fix():
    """应用最终优化的特别篇判断逻辑"""

    file_path = r"f:\Project\Python\auto_rename\src\video_organizer\core\renamer.py"

    # 读取文件
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 查找并替换特别篇判断逻辑
    old_pattern = r"""        # 检查是否是OVA/特别篇，如果是则设置为Season 0
        is_special = False
        if original_path and original_path\.name:
            # 检查文件名是否包含特别篇标识（使用正则表达式精确匹配，避免部分匹配）
            special_patterns = \[
                r'\\\\bOVA\\\\b',  # 匹配独立的OVA
                r'\\\\bSP\\\\b',  # 匹配独立的SP
                r'\\\\bSpecial\\\\b',  # 匹配独立的Special
                r'特别篇',  # 中文关键词
                r'番外篇',  # 中文关键词
                r'\\\\bOVA0\?1\\\\b',  # 匹配OVA01或OVA1
                r'\\\\bOVA0\?2\\\\b',  # 匹配OVA02或OVA2
                r'\\\\bOVA0\?3\\\\b',  # 匹配OVA03或OVA3
                r'\\\\bOVA0\?4\\\\b',  # 匹配OVA04或OVA4
                r'\\\\bOVA0\?5\\\\b',  # 匹配OVA05或OVA5
                r'\\\\bOVA0\?6\\\\b',  # 匹配OVA06或OVA6
                r'\\\\bOVA0\?7\\\\b',  # 匹配OVA07或OVA7
                r'\\\\bOVA0\?8\\\\b',  # 匹配OVA08或OVA8
                r'\\\\bOVA0\?9\\\\b',  # 匹配OVA09或OVA9
                r'\\\\bOVA10\\\\b',  # 匹配OVA10
            \]
            filename_upper = original_path\.name\.upper\(\)
            for pattern in special_patterns:
                if re\.search\(pattern, filename_upper, re\.IGNORECASE\):
                    is_special = True
                    break"""

    new_pattern = r"""        # 检查是否是OVA/特别篇，如果是则设置为Season 0
        is_special = False
        if original_path and original_path.name:
            # 检查文件名是否包含特别篇标识（使用正则表达式精确匹配，避免部分匹配）
            special_patterns = [
                r'\\bOVA\\b',  # 匹配独立的OVA
                r'\\bOVA0?1\\b', r'\\bOVA0?2\\b', r'\\bOVA0?3\\b', r'\\bOVA0?4\\b', r'\\bOVA0?5\\b',
                r'\\bOVA0?6\\b', r'\\bOVA0?7\\b', r'\\bOVA0?8\\b', r'\\bOVA0?9\\b', r'\\bOVA10\\b',
                r'(?<!\\w)SP(?!\\w)',  # 匹配独立的SP，排除SPY等词
                r'(?<=\\[)Special(?=\\])',  # [Special] 格式
                r'\\bSpecial\\s*(?:Episode|EP|Ep)\\b',  # Special Episode 格式
                r'\\bSpecial\\s*\\d+\\b',  # Special 01 格式
                r'\\bSpecial\\b(?=\\s*\\.\\w+$)',  # Special.mkv 格式（在文件名末尾）
                r'特别篇',  # 中文关键词
                r'番外篇',  # 中文关键词
            ]
            filename_upper = original_path.name.upper()
            for pattern in special_patterns:
                if re.search(pattern, filename_upper, re.IGNORECASE):
                    is_special = True
                    break"""

    # 执行替换
    if re.search(old_pattern, content, re.DOTALL):
        new_content = re.sub(old_pattern, new_pattern, content, flags=re.DOTALL)

        # 写回文件
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        print("✓ 成功应用最终优化的特别篇判断逻辑")
        print("  - 使用正则表达式进行精确匹配")
        print("  - 避免了 'SPY' 被误判为 'SP' 的问题")
        print("  - 避免了 'Special Mission Force' 等剧名被误判的问题")
        print("  - 只在特定上下文中匹配 'Special' 关键词")
    else:
        print("✗ 未找到目标代码，可能文件已被修改或已应用最新版本")


if __name__ == "__main__":
    apply_final_fix()
