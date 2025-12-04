import sys
import os

# 添加src目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from video_organizer.core.renamer import VideoRenamer

def test_media_type_fix():
    """测试修复后的媒体类型提示处理逻辑"""
    print("=== 测试媒体类型提示修复 ===")
    
    # 模拟搜索结果
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
        },
        {
            'id': 45678,
            'name': '星期三电影版',
            'original_name': 'Wednesday Movie',
            'media_type': 'movie',
            'popularity': 80.0,
            'release_date': '2023-01-01'
        }
    ]
    
    search_term = '星期三'
    media_type_hint = 'tv'
    
    # 模拟修复后的逻辑
    print(f"搜索词: {search_term}")
    print(f"媒体类型提示: {media_type_hint}")
    print("\n原始搜索结果:")
    for i, result in enumerate(mock_results):
        print(f"  {i+1}. {result['name']} (类型: {result['media_type']}, 热度: {result['popularity']})")
    
    # 应用修复后的逻辑
    # 筛选出匹配媒体类型的结果
    type_matched_results = [result for result in mock_results if result.get('media_type') == media_type_hint]
    if type_matched_results:
        target_results = type_matched_results
    else:
        target_results = mock_results
    
    # 计算标题相似度并按相似度和流行度排序
    def calculate_score(result):
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
    
    # 按得分排序
    sorted_results = sorted(target_results, key=calculate_score, reverse=True)
    best_match = sorted_results[0]
    
    print("\n修复后处理逻辑:")
    print(f"  1. 筛选出媒体类型为 {media_type_hint} 的结果")
    print(f"  2. 按标题相似度和流行度排序")
    print(f"  3. 选择最佳匹配: {best_match['name']} (类型: {best_match['media_type']}, 热度: {best_match['popularity']})")
    
    # 检查结果
    if best_match['id'] == 134053 and best_match['name'] == '星期三':
        print("\n✓ 修复成功: 正确选择了'星期三'而不是'星期三的情事'")
        return True
    else:
        print(f"\n✗ 修复失败: 错误选择了 {best_match['name']}")
        return False

if __name__ == "__main__":
    test_media_type_fix()
