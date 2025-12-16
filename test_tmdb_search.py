#!/usr/bin/env python3
"""
测试脚本：测试视频的TMDB ID和媒体类型搜索功能
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.video_organizer.core.renamer import VideoRenamer

def test_tmdb_search():
    """测试TMDB搜索功能"""
    # 从环境变量或配置文件获取API密钥
    # 注意：在实际测试中，需要提供有效的TMDB API密钥
    tmdb_api_key = "YOUR_TMDB_API_KEY"  # 替换为你的API密钥
    
    if not tmdb_api_key:
        print("请设置有效的TMDB API密钥")
        return False
    
    try:
        # 创建VideoRenamer实例
        renamer = VideoRenamer(tmdb_api_key=tmdb_api_key)
        
        # 测试用的视频文件名
        test_files = [
            "流浪地球2.2023.1080p.BluRay.x265.10bit.AAC5.1-CMCT.mkv",
            "怪奇物语.S04E01.mkv",
            "鱿鱼游戏.S01E01.mkv",
            "复仇者联盟4：终局之战.2019.BluRay.1080p.x264.DTS-HD.MA.7.1-CHD.mkv"
        ]
        
        print("开始测试TMDB搜索功能...")
        print("=" * 50)
        
        for test_file in test_files:
            print(f"测试文件: {test_file}")
            
            # 模拟文件路径
            file_path = Path(test_file)
            
            # 提取元数据
            metadata = renamer.extract_metadata(file_path)
            
            # 打印结果
            print(f"  媒体类型: {metadata.get('media_type', '未知')}")
            print(f"  TMDB ID: {metadata.get('tmdb_id', '未知')}")
            print(f"  标题: {metadata.get('show_name', '') or metadata.get('title', '')}")
            print(f"  年份: {metadata.get('year', '')}")
            print(f"  类型: {metadata.get('genres', [])}")
            print()
        
        print("=" * 50)
        print("测试完成！")
        return True
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_tmdb_search()
