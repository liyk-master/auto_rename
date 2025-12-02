#!/usr/bin/env python3
"""
测试脚本：验证命名模板是否能正确生成包含年份和tmdbid的文件名
"""

import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from src.video_organizer.core.renamer import VideoRenamer

def test_template_verification():
    """验证命名模板是否能正确生成包含年份和tmdbid的文件名"""
    try:
        # 创建一个简单的测试用例，不需要真实的TMDB API密钥
        renamer = VideoRenamer(tmdb_api_key="test_api_key")
        
        # 更新命名规则，使用我们修改后的格式
        renamer.set_naming_rules({
            'tv_show': '{show_name} ({year}) {tmdbid=tmdbid}/Season {season:02d}/{show_name} {season_episode} {quality_tags}',
            'movie': 'Movies/{title} ({year}) {tmdbid=tmdbid}',
            'anime': 'Anime/{show_name}/{show_name} - {episode:03d}',
            'simple': '{title}'
        })
        
        print("=== 命名模板验证测试开始 ===")
        print("使用的TV Show模板：{show_name} ({year}) {tmdbid=tmdbid}/Season {season:02d}/{show_name} {season_episode} {quality_tags}")
        
        # 测试电视剧命名模板
        tv_metadata = {
            'media_type': 'tv',
            'show_name': '怪奇物语',
            'season': 1,
            'episode': 1,
            'year': '2016',
            'tmdb_id': '1402',
            'quality_tags': 'WEB-DL.1080p.x264.AAC',
            'extension': '.mp4'
        }
        
        tv_path = renamer.generate_new_path(tv_metadata, rule_type='tv_show')
        print(f"生成的TV路径: {tv_path}")
        
        # 验证结果
        assert "怪奇物语" in str(tv_path), f"生成的路径缺少剧集名称: {tv_path}"
        assert "(2016)" in str(tv_path), f"生成的路径缺少年份: {tv_path}"
        assert "{tmdbid=1402}" in str(tv_path), f"生成的路径缺少tmdbid: {tv_path}"
        assert "Season 01" in str(tv_path), f"生成的路径缺少季号: {tv_path}"
        print("✓ TV Show模板测试通过")
        
        # 测试电影命名模板
        movie_metadata = {
            'media_type': 'movie',
            'title': '肖申克的救赎',
            'year': '1994',
            'tmdb_id': '278',
            'quality_tags': 'BluRay.1080p.x264.AAC',
            'extension': '.mp4'
        }
        
        movie_path = renamer.generate_new_path(movie_metadata, rule_type='movie')
        print(f"生成的Movie路径: {movie_path}")
        
        # 验证结果
        assert "肖申克的救赎" in str(movie_path), f"生成的路径缺少电影名称: {movie_path}"
        assert "(1994)" in str(movie_path), f"生成的路径缺少年份: {movie_path}"
        assert "{tmdbid=278}" in str(movie_path), f"生成的路径缺少tmdbid: {movie_path}"
        print("✓ Movie模板测试通过")
        
        # 测试无tmdbid的情况
        tv_metadata_no_tmdbid = tv_metadata.copy()
        tv_metadata_no_tmdbid['tmdb_id'] = ''
        tv_path_no_tmdbid = renamer.generate_new_path(tv_metadata_no_tmdbid, rule_type='tv_show')
        print(f"生成的TV路径(无tmdbid): {tv_path_no_tmdbid}")
        assert "{tmdbid=" not in str(tv_path_no_tmdbid), f"无tmdbid时不应该包含tmdbid: {tv_path_no_tmdbid}"
        print("✓ 无tmdbid情况测试通过")
        
        # 测试无年份的情况
        tv_metadata_no_year = tv_metadata.copy()
        tv_metadata_no_year['year'] = ''
        tv_path_no_year = renamer.generate_new_path(tv_metadata_no_year, rule_type='tv_show')
        print(f"生成的TV路径(无年份): {tv_path_no_year}")
        assert "()" not in str(tv_path_no_year), f"无年份时不应该包含空括号: {tv_path_no_year}"
        print("✓ 无年份情况测试通过")
        
        print("\n=== 所有测试通过！命名模板能正确生成包含年份和tmdbid的文件名 ===")
        return True
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_template_verification()
    sys.exit(0 if success else 1)
