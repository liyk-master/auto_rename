#!/usr/bin/env python3
"""
测试脚本：全面测试年份添加问题
"""

import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from src.video_organizer.core.renamer import VideoRenamer

def test_year_issue():
    """全面测试年份是否被正确添加到文件夹名称"""
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
        
        # 测试1: 有年份和tmdbid的情况
        test_metadata1 = {
            'media_type': 'tv',
            'show_name': '怪奇物语',
            'season': 1,
            'episode': 1,
            'year': '2016',
            'tmdb_id': '1455575',
            'quality_tags': '',
            'extension': '.mp4'
        }
        
        # 测试2: 没有年份但有tmdbid的情况
        test_metadata2 = {
            'media_type': 'tv',
            'show_name': '怪奇物语',
            'season': 1,
            'episode': 1,
            'year': '',  # 空年份
            'tmdb_id': '1455575',
            'quality_tags': '',
            'extension': '.mp4'
        }
        
        # 测试3: 没有年份和tmdbid的情况
        test_metadata3 = {
            'media_type': 'tv',
            'show_name': '怪奇物语',
            'season': 1,
            'episode': 1,
            'year': '',  # 空年份
            'tmdb_id': '',  # 空tmdbid
            'quality_tags': '',
            'extension': '.mp4'
        }
        
        # 测试4: 年份为None的情况
        test_metadata4 = {
            'media_type': 'tv',
            'show_name': '怪奇物语',
            'season': 1,
            'episode': 1,
            'year': None,  # None年份
            'tmdb_id': '1455575',
            'quality_tags': '',
            'extension': '.mp4'
        }
        
        print("=== 测试年份添加问题 ===")
        print(f"使用的命名规则: {renamer.naming_rules['tv_show']}")
        
        # 测试1
        print("\n=== 测试1: 有年份和tmdbid ===")
        new_path1 = renamer.generate_new_path(test_metadata1, rule_type='tv_show')
        print(f"生成的路径: {new_path1}")
        if "(2016)" in str(new_path1):
            print("✅ 路径中包含年份 (2016)")
        else:
            print("❌ 路径中缺少年份 (2016)")
        
        # 测试2
        print("\n=== 测试2: 没有年份但有tmdbid ===")
        new_path2 = renamer.generate_new_path(test_metadata2, rule_type='tv_show')
        print(f"生成的路径: {new_path2}")
        if "()" in str(new_path2):
            print("❌ 路径中包含空括号 ()")
        else:
            print("✅ 路径中不包含空括号")
        
        # 测试3
        print("\n=== 测试3: 没有年份和tmdbid ===")
        new_path3 = renamer.generate_new_path(test_metadata3, rule_type='tv_show')
        print(f"生成的路径: {new_path3}")
        if "()" in str(new_path3):
            print("❌ 路径中包含空括号 ()")
        else:
            print("✅ 路径中不包含空括号")
        
        # 测试4
        print("\n=== 测试4: 年份为None ===")
        new_path4 = renamer.generate_new_path(test_metadata4, rule_type='tv_show')
        print(f"生成的路径: {new_path4}")
        if "()" in str(new_path4):
            print("❌ 路径中包含空括号 ()")
        else:
            print("✅ 路径中不包含空括号")
        
        # 测试5: 使用Jinja2模板
        print("\n=== 测试5: 使用Jinja2模板 ===")
        jinja_template = "{{show_name}}{% if year %} ({{year}}){% endif %}{% if tmdbid %} {tmdbid={{tmdbid}}}{% endif %}/Season {{(season|string).zfill(2)}}/{{show_name}} {{season_episode}}"
        renamer.set_naming_rules({'tv_show': jinja_template})
        print(f"使用的Jinja2模板: {jinja_template}")
        new_path5 = renamer.generate_new_path(test_metadata1, rule_type='tv_show')
        print(f"生成的路径: {new_path5}")
        if "(2016)" in str(new_path5):
            print("✅ 路径中包含年份 (2016)")
        else:
            print("❌ 路径中缺少年份 (2016)")
        
        return True
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_year_issue()
