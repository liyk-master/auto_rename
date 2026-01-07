#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手动清理重复的特别篇判断patterns
"""

def clean_duplicate_patterns_manual():
    """手动清理重复的special_patterns"""
    
    file_path = r"f:\Project\Python\auto_rename\src\video_organizer\core\renamer.py"
    
    # 读取文件
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # 查找并清理重复的patterns
    new_lines = []
    in_special_patterns = False
    patterns_seen = set()
    patterns_cleaned = False
    
    for i, line in enumerate(lines):
        # 检测是否进入special_patterns列表
        if 'special_patterns = [' in line:
            in_special_patterns = True
            new_lines.append(line)
            continue
        
        # 如果在special_patterns列表中
        if in_special_patterns:
            # 检测是否到达列表末尾
            if ']' in line and not any(keyword in line for keyword in ['OVA', 'SP', 'Special', '特别篇', '番外篇']):
                in_special_patterns = False
                new_lines.append(line)
                continue
            
            # 提取pattern内容（去掉引号和逗号）
            stripped = line.strip()
            if stripped.startswith("r'") or stripped.startswith('r"'):
                pattern = stripped.split('#')[0].strip().rstrip(',').rstrip()
                
                # 检查是否重复
                if pattern in patterns_seen:
                    patterns_cleaned = True
                    continue
                else:
                    patterns_seen.add(pattern)
                    new_lines.append(line)
                    continue
            elif stripped.startswith('#'):
                # 保留注释行
                new_lines.append(line)
                continue
            else:
                # 空行或其他内容
                new_lines.append(line)
                continue
        
        # 其他行保持不变
        new_lines.append(line)
    
    # 写回文件
    if patterns_cleaned:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print("✓ 成功清理重复的special_patterns")
    else:
        print("✗ 未发现重复的patterns")

if __name__ == "__main__":
    clean_duplicate_patterns_manual()
