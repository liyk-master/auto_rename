import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

def test_search_sorting():
    """测试搜索结果排序"""
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
        },
        {
            'id': 12345,
            'name': '星期三特别篇',
            'original_name': 'Wednesday Special',
            'media_type': 'tv',
            'popularity': 75.0,
            'first_air_date': '2023-01-01'
        }
    ]
    
    search_term = '星期三'
    
    # 筛选电视剧结果
    tv_results = [result for result in mock_results if result.get('media_type') == 'tv']
    
    # 按得分排序
    sorted_results = sorted(tv_results, key=lambda x: calculate_score(x, search_term), reverse=True)
    
    logger.info(f"搜索词: {search_term}")
    logger.info("排序前结果:")
    for i, result in enumerate(mock_results):
        logger.info(f"  {i+1}. {result['name']} (热度: {result['popularity']}, ID: {result['id']})")
    
    logger.info("排序后结果:")
    for i, result in enumerate(sorted_results):
        logger.info(f"  {i+1}. {result['name']} (热度: {result['popularity']}, ID: {result['id']})")
    
    # 检查结果
    if sorted_results[0]['id'] == 134053 and sorted_results[0]['name'] == '星期三':
        logger.info("✓ 测试通过: 成功将'星期三'排在首位")
        return True
    else:
        logger.error(f"✗ 测试失败: 首位结果是 {sorted_results[0]['name']} (ID: {sorted_results[0]['id']})")
        return False

if __name__ == "__main__":
    test_search_sorting()
