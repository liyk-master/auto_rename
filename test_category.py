import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.video_organizer.core.renamer import VideoRenamer


def test_category_determination():
    """测试分类功能"""
    # 创建重命名器实例
    renamer = VideoRenamer(
        tmdb_api_key="test_key",
        ai_service_url=None,
        watch_path=None
    )
    
    # 测试用例：动画电影
    animation_movie_metadata = {
        "media_type": "movie",
        "original_language": "en",
        "origin_country": ["US"],
        "genres": ["Animation", "Adventure", "Comedy"],
        "original_title": "Toy Story"
    }
    
    # 测试用例：华语电影
    chinese_movie_metadata = {
        "media_type": "movie",
        "original_language": "zh",
        "origin_country": ["CN"],
        "genres": ["Drama", "Romance"],
        "original_title": "流浪地球"
    }
    
    # 测试用例：外语电影
    foreign_movie_metadata = {
        "media_type": "movie",
        "original_language": "ja",
        "origin_country": ["JP"],
        "genres": ["Drama", "Thriller"],
        "original_title": "Parasite"
    }
    
    # 测试用例：国产剧
    chinese_tv_metadata = {
        "media_type": "tv",
        "original_language": "zh",
        "origin_country": ["CN"],
        "genres": ["Drama", "Romance"],
        "original_show_name": "山海情"
    }
    
    # 测试用例：欧美剧
    western_tv_metadata = {
        "media_type": "tv",
        "original_language": "en",
        "origin_country": ["US"],
        "genres": ["Drama", "Fantasy"],
        "original_show_name": "Game of Thrones"
    }
    
    # 测试用例：日韩剧
    asian_tv_metadata = {
        "media_type": "tv",
        "original_language": "ko",
        "origin_country": ["KR"],
        "genres": ["Drama", "Thriller"],
        "original_show_name": "鱿鱼游戏"
    }
    
    # 测试用例：纪录片
    documentary_tv_metadata = {
        "media_type": "tv",
        "original_language": "zh",
        "origin_country": ["CN"],
        "genres": ["Documentary", "纪录片"],
        "original_show_name": "舌尖上的中国"
    }
    
    # 测试用例：综艺
    variety_tv_metadata = {
        "media_type": "tv",
        "original_language": "zh",
        "origin_country": ["CN"],
        "genres": ["Variety", "综艺"],
        "original_show_name": "奔跑吧兄弟"
    }
    
    # 测试用例：儿童
    kids_tv_metadata = {
        "media_type": "tv",
        "original_language": "zh",
        "origin_country": ["CN"],
        "genres": ["Kids", "儿童"],
        "original_show_name": "小猪佩奇"
    }
    
    # 测试用例：日番
    anime_tv_metadata = {
        "media_type": "tv",
        "original_language": "ja",
        "origin_country": ["JP"],
        "genres": ["Animation", "动画"],
        "original_show_name": "海贼王"
    }
    
    # 测试用例：国漫
    chinese_anime_tv_metadata = {
        "media_type": "tv",
        "original_language": "zh",
        "origin_country": ["CN"],
        "genres": ["Animation", "动画"],
        "original_show_name": "斗罗大陆"
    }
    
    # 测试用例：未分类
    unclassified_tv_metadata = {
        "media_type": "tv",
        "original_language": "fr",
        "origin_country": ["FR"],
        "genres": ["Drama"],
        "original_show_name": "French Drama"
    }
    
    # 执行测试
    test_cases = [
        (animation_movie_metadata, "Movies/动画电影"),
        (chinese_movie_metadata, "Movies/华语电影"),
        (foreign_movie_metadata, "Movies/外语电影"),
        (chinese_tv_metadata, "TV Shows/国产剧"),
        (western_tv_metadata, "TV Shows/欧美剧"),
        (asian_tv_metadata, "TV Shows/日韩剧"),
        (documentary_tv_metadata, "TV Shows/纪录片"),
        (variety_tv_metadata, "TV Shows/综艺"),
        (kids_tv_metadata, "TV Shows/儿童"),
        (anime_tv_metadata, "TV Shows/日番"),
        (chinese_anime_tv_metadata, "TV Shows/国漫"),
        (unclassified_tv_metadata, "TV Shows/未分类")
    ]
    
    print("开始测试分类功能...")
    for i, (metadata, expected_category) in enumerate(test_cases, 1):
        result = renamer._determine_category(metadata)
        status = "✓" if result == expected_category else "✗"
        print(f"测试用例 {i}: {status}")
        print(f"  元数据: {metadata.get('original_title', metadata.get('original_show_name'))} ({metadata.get('media_type')})")
        print(f"  预期分类: {expected_category}")
        print(f"  实际分类: {result}")
        print()


if __name__ == "__main__":
    test_category_determination()
