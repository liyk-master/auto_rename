#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试 guessit_parser 预处理功能"""

import sys
import re
from pathlib import Path

try:
    from guessit import guessit
except ImportError:
    print("guessit 未安装，请先安装: pip install guessit")
    exit(1)

def preprocess_chinese_filename(filename: str) -> str:
    """预处理中文文件名"""
    path = Path(filename)
    stem = path.stem
    
    # 检查是否是纯中文格式
    chinese_episode_patterns = [
        r'^第\d+集$',
        r'^第\d+话$',
        r'^第\d+話$',
        r'^[Ee][Pp]?\d+$',
        r'^\d+$',
    ]
    
    is_pure_episode = any(re.match(p, stem) for p in chinese_episode_patterns)
    
    if is_pure_episode:
        parent = path.parent
        if parent and parent.name:
            parent_name = parent.name
            # 清理父目录名中的年份
            clean_parent = re.sub(r'[（\(]\d{4}[）\)]', '', parent_name)
            clean_parent = re.sub(r'\s*\d{4}\s*$', '', clean_parent)
            clean_parent = clean_parent.strip()
            
            if clean_parent:
                new_filename = f"{clean_parent} - {stem}{path.suffix}"
                return new_filename
    
    return filename

print("="*60)
print("GuessIt 预处理测试")
print("="*60)

tests = [
    "/盗妖行（2026）/第1集.strm",
    "/盗妖行（2026）/第1集.mp4",
    "/path/to/盗妖行（2026）/第1集.strm",
    "/剧名/第01话.mkv",
    "/剧名/EP01.mkv",
]

for path in tests:
    print(f"\n原始输入: {path}")
    
    # 预处理
    preprocessed = preprocess_chinese_filename(path)
    print(f"预处理后: {preprocessed}")
    
    # guessit 解析
    result = guessit(preprocessed)
    print(f"解析结果:")
    print(f"  title: {result.get('title')}")
    print(f"  episode: {result.get('episode')}")
    print(f"  season: {result.get('season')}")
    print(f"  type: {result.get('type')}")

print("\n" + "="*60)
