#!/usr/bin/env python3
"""
测试脚本：验证配置文件中的命名模板是否正确工作
"""

import os
import sys
from pathlib import Path
import logging

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from src.video_organizer.core.renamer import VideoRenamer
from src.video_organizer.config.config_loader import ConfigLoader

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_config_verification():
    """验证配置文件中的命名模板是否正确工作"""
    try:
        # 加载配置
        config_loader = ConfigLoader()
        config = config_loader.load_config()
        
        logger.info("=== 配置验证测试开始 ===")
        
        # 1. 检查配置文件中的命名模板格式
        logger.info(f"TV Show 命名模板: {config['naming']['tv_show_format']}")
        logger.info(f"Movie 命名模板: {config['naming']['movie_format']}")
        
        # 2. 验证TV Show命名模板格式是否正确
        tv_template = config['naming']['tv_show_format']
        assert "({year})" in tv_template, f"TV Show模板缺少正确的年份格式: {tv_template}"
        assert "{tmdbid=tmdbid}" in tv_template, f"TV Show模板缺少正确的tmdbid格式: {tv_template}"
        logger.info("✓ TV Show命名模板格式正确")
        
        # 3. 验证Movie命名模板格式是否正确
        movie_template = config['naming']['movie_format']
        assert "({year})" in movie_template, f"Movie模板缺少正确的年份格式: {movie_template}"
        assert "{tmdbid=tmdbid}" in movie_template, f"Movie模板缺少正确的tmdbid格式: {movie_template}"
        logger.info("✓ Movie命名模板格式正确")
        
        # 4. 测试VideoRenamer是否能正确解析配置
        tmdb_api_key = config['tmdb']['api_key']
        renamer = VideoRenamer(tmdb_api_key)
        
        # 更新命名规则
        naming_rules = {
            'tv_show': config['naming']['tv_show_format'],
            'movie': config['naming']['movie_format'],
            'anime': config['naming']['anime_format'],
            'simple': config['naming']['simple_format']
        }
        renamer.set_naming_rules(naming_rules)
        logger.info("✓ 成功更新命名规则")
        
        # 5. 模拟元数据测试命名生成
        test_metadata = {
            'media_type': 'tv',
            'show_name': '怪奇物语',
            'season': 1,
            'episode': 1,
            'year': '2016',
            'tmdb_id': '1402',
            'quality_tags': 'WEB-DL.1080p.x264.AAC',
            'extension': '.mp4'
        }
        
        # 生成新路径
        new_path = renamer.generate_new_path(test_metadata, rule_type='tv_show')
        logger.info(f"生成的TV Show路径: {new_path}")
        
        # 验证生成的路径是否包含预期内容
        assert "怪奇物语" in str(new_path), f"生成的路径缺少剧集名称: {new_path}"
        assert "(2016)" in str(new_path), f"生成的路径缺少年份: {new_path}"
        assert "{tmdbid=1402}" in str(new_path), f"生成的路径缺少tmdbid: {new_path}"
        assert "Season 01" in str(new_path), f"生成的路径缺少季号: {new_path}"
        logger.info("✓ 成功生成包含年份和tmdbid的TV Show路径")
        
        logger.info("=== 配置验证测试完成，所有测试通过！ ===")
        return True
        
    except Exception as e:
        logger.error(f"配置验证测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_config_verification()
    sys.exit(0 if success else 1)
