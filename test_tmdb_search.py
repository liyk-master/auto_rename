#!/usr/bin/env python3
"""
测试脚本：测试视频的TMDB ID和媒体类型搜索功能
"""

import sys
import os
import json
from pathlib import Path
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.video_organizer.core.renamer import VideoRenamer
from src.video_organizer.core.tmdb_client import TMDBClient

def test_tmdb_search():
    """测试TMDB搜索功能"""
    # 从配置文件获取API密钥
    import configparser
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')
    tmdb_api_key = config.get('tmdb', 'api_key', fallback='')
    
    if not tmdb_api_key:
        print("请设置有效的TMDB API密钥")
        return False
    
    try:
        # 创建VideoRenamer实例
        renamer = VideoRenamer(None, None, None, None)
        
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

def test_magician_search():
    """专门测试'魔術師庫諾看得見一切'的搜索功能"""
    print("\n\n=== 专门测试'魔術師庫諾看得見一切'搜索 ===")
    
    # 从配置文件获取API密钥
    import configparser
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')
    tmdb_api_key = config.get('tmdb', 'api_key', fallback='')
    
    if not tmdb_api_key:
        print("请设置有效的TMDB API密钥")
        return False
    
    # 1. 直接测试TMDB客户端
    print("\n1. 直接测试TMDB客户端:")
    tmdb_client = TMDBClient(tmdb_api_key)
    
    search_term = "魔術師庫諾看得見一切"
    
    # 测试电视剧搜索
    tv_results = tmdb_client.search_tv(search_term, language='zh-CN')
    if tv_results and tv_results.get('results'):
        print(f"   ✓ search_tv找到 {len(tv_results['results'])} 个结果")
        for result in tv_results['results'][:2]:
            print(f"   - {result.get('name')} (ID: {result.get('id')}, 原始名称: {result.get('original_name')})")
    else:
        print(f"   ✗ search_tv未找到结果: {tv_results}")
    
    # 测试通用搜索
    multi_results = tmdb_client.search_video_show(search_term, language='zh-CN')
    if multi_results:
        print(f"   ✓ search_video_show找到 {len(multi_results)} 个结果")
        for result in multi_results[:2]:
            print(f"   - {result.get('name') or result.get('title')} (ID: {result.get('id')}, 类型: {result.get('media_type')})")
    else:
        print(f"   ✗ search_video_show未找到结果: {multi_results}")
    
    # 2. 测试VideoRenamer的搜索功能
    print("\n2. 测试VideoRenamer搜索:")
    # 正确初始化VideoRenamer，传递tmdb_api_key
    renamer = VideoRenamer(tmdb_api_key=tmdb_api_key)
    
    # 清除缓存
    renamer._search_cache.clear()
    print(f"   ✓ 缓存已清除")
    
    # 模拟元数据
    metadata = {
        'show_name': '魔術師庫諾看得見一切',
        'media_type': 'tv',
        'original_filename': '[ANi] 魔術師庫諾看得見一切 - 02 [1080P][Baha][WEB-DL][AAC AVC][CHT].mp4',
        'season': 1,
        'episode': 2
    }
    
    # 测试_prepare_search_term
    prepared_term = renamer._prepare_search_term(metadata['show_name'])
    print(f"   原始搜索词: '{metadata['show_name']}'")
    print(f"   优化后搜索词: '{prepared_term}'")
    
    # 手动调用搜索方法
    print(f"\n3. 手动测试搜索流程:")
    
    # 检查缓存
    cache_key = (prepared_term, metadata['media_type'], None)
    print(f"   缓存键: {cache_key}")
    
    # 测试_search_with_language
    search_results = renamer._search_with_language(prepared_term, metadata['media_type'], None, 'zh-CN')
    if search_results:
        print(f"   ✓ _search_with_language找到 {len(search_results)} 个结果")
        for result in search_results[:2]:
            print(f"   - {result.get('name')} (ID: {result.get('id')}, 原始名称: {result.get('original_name')})")
            print(f"     匹配名称: {result.get('name')}, 搜索词: {prepared_term}")
            print(f"     相似度: {calculate_similarity(result.get('name', ''), prepared_term)}")
    else:
        print(f"   ✗ _search_with_language未找到结果")
    
    # 测试_enrich_with_tmdb
    print(f"\n4. 测试完整的_enrich_with_tmdb流程:")
    try:
        enriched_metadata = renamer._enrich_with_tmdb(metadata)
        print(f"   ✓ _enrich_with_tmdb完成")
        print(f"   结果: {json.dumps(enriched_metadata, ensure_ascii=False, indent=2)}")
    except Exception as e:
        print(f"   ✗ _enrich_with_tmdb失败: {e}")
        import traceback
        traceback.print_exc()
    
    return True

def calculate_similarity(str1, str2):
    """简单计算两个字符串的相似度"""
    import difflib
    return difflib.SequenceMatcher(None, str1, str2).ratio()

if __name__ == "__main__":
    # 运行基础测试
    test_tmdb_search()
    
    # 运行专门测试
    test_magician_search()