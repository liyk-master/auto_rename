import os
import sys
import logging

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from video_organizer.core.renamer import VideoRenamer

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_wednesday_identification():
    """测试星期三 S01E01.mp4的识别"""
    # 创建测试元数据
    metadata = {
        'show_name': '星期三',
        'season': '1',
        'episode': '1',
        'media_type': 'tv'
    }
    
    # 创建renamer实例
    renamer = VideoRenamer()
    
    # 调用TMDB搜索
    result = renamer._enrich_with_tmdb(metadata)
    
    logger.info(f"识别结果: {result}")
    
    # 检查结果
    if result.get('show_name') == '星期三' and result.get('original_name') == 'Wednesday':
        logger.info("✓ 测试通过: 成功识别为'星期三' (Wednesday)")
        return True
    else:
        logger.error(f"✗ 测试失败: 识别为 {result.get('show_name')} ({result.get('original_name')})")
        return False

if __name__ == "__main__":
    test_wednesday_identification()
