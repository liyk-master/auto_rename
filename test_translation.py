import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.video_organizer.core.renamer import VideoRenamer


def test_translation_function():
    """测试翻译功能"""
    # 创建重命名器实例
    renamer = VideoRenamer(
        tmdb_api_key="test_key",
        ai_service_url=None,
        watch_path=None
    )
    
    # 测试用例：翻译字典中存在的中文
    test_cases = [
        ("怪奇物语", "Stranger Things"),
        ("权力的游戏", "Game of Thrones"),
        ("鱿鱼游戏", "Squid Game"),
        ("流浪地球", "The Wandering Earth"),
        ("山海情", "Minning Town"),
        ("奔跑吧兄弟", "Running Man"),
        ("小猪佩奇", "Peppa Pig"),
        ("海贼王", "One Piece"),
        ("斗罗大陆", "Soul Land"),
        ("舌尖上的中国", "A Bite of China"),
        # 测试用例：翻译字典中不存在的中文
        ("未知剧集", "未知剧集"),
        # 测试用例：中英文混合
        ("怪奇物语 第四季", "Stranger Things 第四季")
    ]
    
    print("开始测试翻译功能...")
    for i, (chinese, expected_english) in enumerate(test_cases, 1):
        translated = renamer._translate_to_english(chinese)
        status = "✓" if translated == expected_english else "✗"
        print(f"测试用例 {i}: {status}")
        print(f"  中文: {chinese}")
        print(f"  预期英文: {expected_english}")
        print(f"  实际英文: {translated}")
        print()


def test_search_with_translation():
    """测试带翻译的搜索功能"""
    # 创建重命名器实例
    renamer = VideoRenamer(
        tmdb_api_key="test_key",
        ai_service_url=None,
        watch_path=None
    )
    
    # 模拟TMDB客户端的搜索方法
    def mock_search_tv(query, year=None, language=None):
        print(f"模拟搜索电视剧: query='{query}', year={year}, language={language}")
        # 模拟返回结果
        return {
            "results": [
                {
                    "id": 66732,
                    "name": "Stranger Things",
                    "media_type": "tv",
                    "first_air_date": "2016-07-15",
                    "popularity": 100.0
                }
            ]
        }
    
    # 替换tmdb_client的search_tv方法
    original_search_tv = renamer.tmdb_client.search_tv
    renamer.tmdb_client.search_tv = mock_search_tv
    
    try:
        # 测试用例：中文搜索词 + 英文语言
        search_term = "怪奇物语"
        media_type_hint = "tv"
        year = "2016"
        language = "en-US"
        
        print("开始测试带翻译的搜索功能...")
        print(f"测试用例: 中文搜索词 '{search_term}' + 英文语言 '{language}'")
        
        results = renamer._search_with_language(search_term, media_type_hint, year, language)
        
        print(f"搜索结果数量: {len(results)}")
        if results:
            print(f"搜索结果: {results[0]['name']} (ID: {results[0]['id']})")
        print()
    finally:
        # 恢复原始方法
        renamer.tmdb_client.search_tv = original_search_tv


def test_wednesday_search():
    """测试搜索"星期三"的情况，验证第一个结果是电视剧Wednesday"""
    # 创建重命名器实例
    renamer = VideoRenamer(
        tmdb_api_key="test_key",
        ai_service_url=None,
        watch_path=None
    )
    
    # 模拟TMDB客户端的search_tv方法
    def mock_search_tv(query, year=None, language=None):
        print(f"模拟搜索电视剧: query='{query}', year={year}, language={language}")
        # 模拟返回结果
        return {
            "results": [
                {
                    "id": 192477,
                    "name": "Wednesday",
                    "media_type": "tv",
                    "first_air_date": "2022-11-23",
                    "popularity": 85.0
                }
            ]
        }
    
    # 模拟TMDB客户端的search_movie方法
    def mock_search_movie(query, year=None, language=None):
        print(f"模拟搜索电影: query='{query}', year={year}, language={language}")
        # 模拟返回结果
        return {
            "results": [
                {
                    "id": 10283,
                    "title": "十三号星期五8：杰森侵入曼哈顿",
                    "media_type": "movie",
                    "release_date": "1989-07-28",
                    "popularity": 75.0
                }
            ]
        }
    
    # 模拟TMDB客户端的search_video_show方法，返回"星期三"的搜索结果
    def mock_search_video_show(query, year=None, include_adult=False, language=None):
        print(f"模拟搜索视频: query='{query}', year={year}, language={language}")
        # 模拟返回结果，包含电视剧和电影
        return [
            {
                "id": 192477,
                "name": "Wednesday",
                "media_type": "tv",
                "first_air_date": "2022-11-23",
                "popularity": 85.0
            },
            {
                "id": 10283,
                "title": "十三号星期五8：杰森侵入曼哈顿",
                "media_type": "movie",
                "release_date": "1989-07-28",
                "popularity": 75.0
            },
            {
                "id": 123456,
                "title": "How do you like Wednesday?",
                "media_type": "movie",
                "release_date": "2020-01-10",
                "popularity": 65.0
            }
        ]
    
    # 模拟TMDB客户端的get_tv_details方法
    def mock_get_tv_details(tv_id, append_to_response=None):
        print(f"模拟获取电视剧详情: tv_id={tv_id}")
        # 模拟返回结果
        return {
            "id": 192477,
            "name": "Wednesday",
            "original_name": "Wednesday",
            "overview": "星期三·亚当斯聪明、爱挖苦人，内心有点死气沉沉。在调查一起连环杀人案时，她在奈弗莫尔学院结识了新朋友，也遇见了新对手。",
            "vote_average": 8.0,
            "genres": [{"name": "Drama"}, {"name": "Fantasy"}, {"name": "Mystery"}],
            "original_language": "en",
            "origin_country": ["US"],
            "first_air_date": "2022-11-23",
            "last_air_date": "2022-11-23",
            "status": "Returning Series",
            "number_of_seasons": 1,
            "number_of_episodes": 8
        }
    
    # 替换tmdb_client的方法
    original_search_tv = renamer.tmdb_client.search_tv
    original_search_movie = renamer.tmdb_client.search_movie
    original_search_video_show = renamer.tmdb_client.search_video_show
    original_get_tv_details = renamer.tmdb_client.get_tv_details
    
    renamer.tmdb_client.search_tv = mock_search_tv
    renamer.tmdb_client.search_movie = mock_search_movie
    renamer.tmdb_client.search_video_show = mock_search_video_show
    renamer.tmdb_client.get_tv_details = mock_get_tv_details
    
    try:
        # 模拟元数据
        metadata = {
            "show_name": "星期三",
            "media_type": "tv",
            "year": "2022",
            "quality_tags": "",
            "tmdb_id": ""
        }
        
        print("开始测试搜索'星期三'的情况...")
        
        # 调用_enrich_with_tmdb方法，测试搜索结果处理逻辑
        enriched_metadata = renamer._enrich_with_tmdb(metadata)
        
        print(f"搜索结果: {enriched_metadata.get('show_name')}")
        print(f"媒体类型: {enriched_metadata.get('media_type')}")
        print(f"TMDB ID: {enriched_metadata.get('tmdb_id')}")
        print()
        
        # 验证结果是否正确
        assert enriched_metadata.get('media_type') == 'tv', f"预期媒体类型为'tv'，实际为'{enriched_metadata.get('media_type')}'"
        assert enriched_metadata.get('tmdb_id') == 192477, f"预期TMDB ID为192477，实际为'{enriched_metadata.get('tmdb_id')}'"
        print("测试通过！搜索'星期三'的第一个结果是电视剧Wednesday")
    finally:
        # 恢复原始方法
        renamer.tmdb_client.search_tv = original_search_tv
        renamer.tmdb_client.search_movie = original_search_movie
        renamer.tmdb_client.search_video_show = original_search_video_show
        renamer.tmdb_client.get_tv_details = original_get_tv_details


if __name__ == "__main__":
    test_translation_function()
    test_search_with_translation()
    test_wednesday_search()
