#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试 GuessItParser 预处理功能"""

import sys
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from video_organizer.core.guessit_parser import GuessItParser

# 测试用例：各种常见的视频文件命名格式
TEST_CASES = [
    # 标准英文格式
    ("Game.of.Thrones.S01E01.mkv", "标准英文 S01E01"),
    ("Game.of.Thrones.S01E01E02.mkv", "连集 S01E01E02"),
    ("Breaking.Bad.S05E16.1080p.mkv", "带质量标签"),
    ("The.Walking.Dead.S03E04.720p.WEB-DL.mkv", "完整质量标签"),
    
    # 标准数字格式
    ("Show.Name.1x01.mkv", "1x01 格式"),
    ("Show.Name.1x01x02.mkv", "1x01x02 连集"),
    
    # 简单数字格式
    ("/剧名/EP01.mkv", "EP01 格式"),
    ("/剧名/E01.mkv", "E01 格式"),
    ("/剧名/01.mkv", "纯数字"),
    ("/剧名/001.mkv", "三位数字"),
    
    # 中文格式
    ("/剧名/第1集.mkv", "第N集"),
    ("/剧名/第01集.mkv", "第0N集"),
    ("/剧名/第一集.mkv", "中文数字集"),
    ("/剧名/第1话.mkv", "第N话"),
    ("/剧名/第01话.mkv", "第0N话"),
    ("/剧名/第1話.mkv", "繁体話"),
    
    # 带季的中文格式
    ("/剧名/第一季/第1集.mkv", "第一季/第N集"),
    ("/剧名/第二季/第1集.mkv", "第二季/第N集"),
    ("/剧名/Season 1/第1集.mkv", "Season 1/第N集"),
    ("/剧名/S01/第1集.mkv", "S01/第N集"),
    
    # 特殊格式
    ("/剧名/第1-2集.mkv", "连集 第1-2集"),
    ("/剧名/第01-02话.mkv", "连集 第01-02话"),
    ("[字幕组]剧名 - 01.mkv", "字幕组格式"),
    ("【字幕组】剧名 第1集.mkv", "中文括号字幕组"),
    
    # 电影格式
    ("Movie.Name.2023.1080p.mkv", "电影 带年份"),
    ("电影名.2023.mkv", "中文电影"),
    ("Movie.Name.2023.2160p.UHD.BluRay.mkv", "电影 4K"),
    
    # 日剧/动漫格式
    ("/动漫名/01.mkv", "动漫纯数字"),
    ("/动漫名/第1話.mkv", "日式 第N話"),
    ("[SubGroup] Anime Name - 01 [1080p].mkv", "动漫完整格式"),
    
    # 特殊情况
    ("/盗妖行（2026）/第1集.strm", "带年份目录/第N集"),
    ("/盗妖行（2026）/EP01.strm", "带年份目录/EPN"),
    ("/Show Name (2023)/Episode 01.mkv", "英文目录 Episode"),
    
    # 混合格式
    ("剧名.S01E01.1080p.mkv", "中文剧名 S01E01"),
    ("剧名.S01EP01.mkv", "中文剧名 S01EP01"),
]

def main():
    print("=" * 80)
    print("GuessItParser 预处理功能测试")
    print("=" * 80)
    
    parser = GuessItParser(enabled=True)
    
    success = []
    failed = []
    
    for filename, desc in TEST_CASES:
        print(f"\n【{desc}】")
        print(f"  输入: {filename}")
        
        result = parser.parse(filename)
        print(f"  结果: show_name={result.get('show_name')}, season={result.get('season')}, episode={result.get('episode')}, year={result.get('year')}")
        
        # 判断是否成功识别
        has_title = result.get('show_name') is not None
        has_episode = result.get('episode') is not None
        is_movie = result.get('media_type') == 'movie'
        
        # 特殊判断：如果文件名包含"集"、"话"等，期望识别出 episode
        need_episode = any(x in filename for x in ['集', '话', '話', 'EP', 'E0', '/0', 'x0'])
        
        if has_title:
            if need_episode and not has_episode:
                failed.append((filename, desc, result, "缺少集数"))
                print(f"  状态: ❌ 未识别集数")
            elif is_movie and not result.get('year'):
                # 电影没有年份也可以接受
                success.append((filename, desc, result))
                print(f"  状态: ✅ 电影识别成功")
            else:
                success.append((filename, desc, result))
                print(f"  状态: ✅ 识别成功")
        else:
            failed.append((filename, desc, result, "缺少标题"))
            print(f"  状态: ❌ 未识别标题")
    
    print("\n" + "=" * 80)
    print(f"测试结果: 成功 {len(success)} / 失败 {len(failed)}")
    print("=" * 80)
    
    if failed:
        print("\n【仍需处理的格式】")
        for filename, desc, result, reason in failed:
            print(f"  - {desc}: {filename}")
            print(f"    原因: {reason}")
            print(f"    结果: show_name={result.get('show_name')}, episode={result.get('episode')}")

if __name__ == "__main__":
    main()
