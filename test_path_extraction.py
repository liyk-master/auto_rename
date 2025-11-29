#!/usr/bin/env python3
"""
测试路径提取功能
"""

from pathlib import Path
from src.video_organizer.core.renamer import VideoRenamer

def test_path_extraction():
    # 模拟watch_path和文件路径
    watch_path = Path("/mnt/media/test")
    file_path = Path("/mnt/media/test/权力的游戏/01.mp4")
    
    # 创建renamer实例
    renamer = VideoRenamer(
        tmdb_api_key="test_key",
        ai_service_url="http://test.com",
        watch_path=watch_path
    )
    
    # 计算相对路径
    try:
        metadata = renamer._extract_with_regex("权力的游戏 - S01E01.mp4")
        print(metadata)
        exit()
        relative_path = file_path.relative_to(watch_path)
        print(f"文件路径: {file_path}")
        print(f"监控路径: {watch_path}")
        print(f"相对路径: {relative_path}")
        
        # 使用相对路径的第一级目录名称作为视频名称
        if len(relative_path.parts) > 1:
            video_name = relative_path.parts[0]  # 第一级目录名称
        else:
            video_name = file_path.stem  # 如果文件直接在watch_path下，使用文件名
        print(f"提取的视频名称: {video_name}")
    except ValueError as e:
        print(f"错误: {e}")

if __name__ == "__main__":
    test_path_extraction()