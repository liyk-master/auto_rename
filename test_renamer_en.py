#!/usr/bin/env python3
"""
测试脚本：调试年份没有被添加到文件夹名称的问题
"""

import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from src.video_organizer.core.renamer import VideoRenamer
from src.video_organizer.core.filesystem_monitor import FileSystemMonitor

def test_year_issue():
    """测试年份是否被正确添加到文件夹名称"""
    try:
        # 创建测试用的VideoRenamer实例
        renamer = VideoRenamer(tmdb_api_key="test_api_key")
        
        # 设置与配置文件中相同的命名规则
        renamer.set_naming_rules({
            'tv_show': '{show_name} ({year}) {tmdbid=tmdbid}/Season {season:02d}/{show_name} {season_episode} {quality_tags}',
            'movie': 'Movies/{title} ({year}) {tmdbid=tmdbid}',
            'anime': 'Anime/{show_name}/{show_name} - {episode:03d}',
            'simple': '{title}'
        })
        
        # 创建测试元数据，包含年份和tmdbid
        test_metadata = {
            'media_type': 'tv',
            'show_name': '怪奇物语',
            'season': 1,
            'episode': 1,
            'year': '2016',
            'tmdb_id': '1455575',
            'quality_tags': '',
            'extension': '.mp4'
        }
        
        print("=== 测试年份添加问题 ===")
        print(f"使用的命名规则: {renamer.naming_rules['tv_show']}")
        print(f"测试元数据: {test_metadata}")
        
        # 生成新路径
        new_path = renamer.generate_new_path(test_metadata, rule_type='tv_show')
        print(f"\n生成的路径: {new_path}")
        
        # 检查路径中是否包含年份
        if "(2016)" in str(new_path):
            print("✅ 路径中包含年份 (2016)")
        else:
            print("❌ 路径中缺少年份 (2016)")
            
            # 调试信息
            print("\n=== 调试信息 ===")
            print(f"year变量: '{test_metadata['year']}'")
            print(f"tmdb_id变量: '{test_metadata['tmdb_id']}'")
            
            # 测试不同的命名规则
            print("\n=== 测试不同命名规则 ===")
            
            # 测试1: 简化版规则，只包含年份
            renamer.set_naming_rules({'tv_show': '{show_name} ({year})/Season {season:02d}/{show_name} {season_episode}'})
            path1 = renamer.generate_new_path(test_metadata, rule_type='tv_show')
            print(f"规则1 - 只包含年份: {path1}")
            
            # 测试2: 使用year_suffix
            renamer.set_naming_rules({'tv_show': '{show_name}{year_suffix}/Season {season:02d}/{show_name} {season_episode}'})
            path2 = renamer.generate_new_path(test_metadata, rule_type='tv_show')
            print(f"规则2 - 使用year_suffix: {path2}")
            
            # 测试3: 手动构建路径
            year_suffix = f" ({test_metadata['year']})" if test_metadata['year'] else ""
            tmdbid_suffix = f" {{tmdbid={test_metadata['tmdb_id']}}}" if test_metadata['tmdb_id'] else ""
            manual_path = f"{test_metadata['show_name']}{year_suffix}{tmdbid_suffix}/Season {test_metadata['season']:02d}/{test_metadata['show_name']} S{test_metadata['season']:02d}E{test_metadata['episode']:02d}"
            print(f"规则3 - 手动构建: {manual_path}")
        
        return True
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_year_issue()
