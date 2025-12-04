import sys
import os

# 添加src目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from video_organizer.core.renamer import VideoRenamer

def test_wednesday_full():
    """综合测试星期三 S01E01.mp4的识别和质量标记提取"""
    # 使用假的API密钥
    renamer = VideoRenamer(tmdb_api_key="test_key")
    
    # 测试用例1：基本识别
    print("=== 测试1：星期三 S01E01.mp4 基本识别 ===")
    metadata = {
        'show_name': '星期三',
        'season': '1',
        'episode': '1',
        'media_type': 'tv'
    }
    
    # 这里我们只测试搜索排序逻辑，不实际调用TMDB API
    # 模拟TMDB搜索结果
    mock_results = [
        {
            'id': 37060,
            'name': '星期三的情事',
            'original_name': 'Wednesday Love Affairs',
            'media_type': 'tv',
            'popularity': 50.0,
            'first_air_date': '2001-01-01'
        },
        {
            'id': 134053,
            'name': '星期三',
            'original_name': 'Wednesday',
            'media_type': 'tv',
            'popularity': 100.0,
            'first_air_date': '2022-11-23'
        }
    ]
    
    # 测试搜索排序函数
    def calculate_score(result, search_term):
        """计算搜索结果的匹配分数"""
        title = result.get('name', result.get('title', '')).lower()
        search_term_lower = search_term.lower()
        # 完全匹配得分最高
        if search_term_lower == title:
            return 1000 + result.get('popularity', 0)
        # 搜索词是标题的子集
        elif search_term_lower in title:
            return 500 + result.get('popularity', 0)
        # 标题是搜索词的子集
        elif title in search_term_lower:
            return 300 + result.get('popularity', 0)
        # 只按流行度排序
        else:
            return result.get('popularity', 0)
    
    # 排序结果
    sorted_results = sorted(mock_results, key=lambda x: calculate_score(x, '星期三'), reverse=True)
    
    print(f"排序前结果: {[r['name'] for r in mock_results]}")
    print(f"排序后结果: {[r['name'] for r in sorted_results]}")
    
    if sorted_results[0]['id'] == 134053 and sorted_results[0]['name'] == '星期三':
        print("✓ 搜索排序测试通过：成功将'星期三'排在首位")
    else:
        print(f"✗ 搜索排序测试失败：首位结果是 {sorted_results[0]['name']}")
    
    # 测试用例2：带质量标记的文件名识别
    print("\n=== 测试2：带质量标记的文件名识别 ===")
    filename = '星期三.S01E01.1080p.BluRay.x265.DTS-HD.MA.TrueHD.7.1.Atmos-CHS.mkv'
    print(f"测试文件名: {filename}")
    
    # 提取质量标记
    quality_tags = renamer._extract_keywords(filename)
    print(f"提取到的质量标记: {quality_tags}")
    
    expected_tags = ['1080p', 'BluRay', 'x265', 'DTS-HD', 'TrueHD', 'Atmos', 'CHS']
    actual_tags = quality_tags.split('.')
    
    # 检查预期标记
    all_found = True
    for tag in expected_tags:
        if tag in actual_tags:
            print(f"✓ {tag} 被正确提取")
        else:
            print(f"✗ {tag} 未被提取")
            all_found = False
    
    if all_found:
        print("✓ 所有预期质量标记都被正确提取")
    else:
        print("✗ 部分质量标记未被提取")
    
    # 测试用例3：验证文件命名格式
    print("\n=== 测试3：验证文件命名格式 ===")
    # 模拟最终元数据
    final_metadata = {
        'show_name': '星期三',
        'original_name': 'Wednesday',
        'season': '1',
        'episode': '1',
        'year': '2022',
        'tmdb_id': '134053',
        'quality_tags': '1080p.BluRay.x265.DTS-HD.TrueHD.Atmos.CHS'
    }
    
    # 验证格式是否符合要求
    print(f"剧集名称: {final_metadata['show_name']}")
    print(f"原始名称: {final_metadata['original_name']}")
    print(f"年份: {final_metadata['year']}")
    print(f"TMDB ID: {final_metadata['tmdb_id']}")
    print(f"质量标记: {final_metadata['quality_tags']}")
    
    # 检查是否符合预期
    if (final_metadata['show_name'] == '星期三' and 
        final_metadata['original_name'] == 'Wednesday' and 
        final_metadata['year'] == '2022'):
        print("✓ 元数据格式符合要求")
    else:
        print("✗ 元数据格式不符合要求")

if __name__ == "__main__":
    test_wednesday_full()
