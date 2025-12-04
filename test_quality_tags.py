import os
import sys
import logging
from video_organizer.core.renamer import VideoRenamer

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_quality_tags_extraction():
    """测试质量标记提取"""
    # 创建renamer实例
    renamer = VideoRenamer()
    
    # 测试用例
    test_cases = [
        '凸变英雄X.2025.S01E02.2160p.WEB-DL.AAC.H264.strm',
        '星期三.S01E01.1080p.BluRay.x265.DTS-HD.MA.TrueHD.7.1.Atmos-CHS.mkv',
        '怪奇物语.S04E01.2160p.NF.WEB-DL.DDP5.1.x265.双语-字慕组.mp4',
        '权力的游戏.S08E06.1080p.BluRay.REMUX.AVC.DTS-HD.MA.7.1-CHS-ENG.mkv'
    ]
    
    for filename in test_cases:
        logger.info(f"\n测试文件名: {filename}")
        
        # 提取质量标记
        quality_tags = renamer._extract_keywords(filename)
        
        logger.info(f"提取到的质量标记: {quality_tags}")
        
        # 验证是否包含预期的标记
        expected_tags = {
            '凸变英雄X.2025.S01E02.2160p.WEB-DL.AAC.H264.strm': ['2160p', 'WEB-DL', 'AAC', 'H264'],
            '星期三.S01E01.1080p.BluRay.x265.DTS-HD.MA.TrueHD.7.1.Atmos-CHS.mkv': ['1080p', 'BluRay', 'x265', 'DTS-HD', 'TrueHD', 'Atmos', 'CHS'],
            '怪奇物语.S04E01.2160p.NF.WEB-DL.DDP5.1.x265.双语-字慕组.mp4': ['2160p', 'WEB-DL', 'x265', '双语'],
            '权力的游戏.S08E06.1080p.BluRay.REMUX.AVC.DTS-HD.MA.7.1-CHS-ENG.mkv': ['1080p', 'BluRay', 'AVC', 'DTS-HD', 'CHS', 'ENG']
        }
        
        expected = expected_tags[filename]
        actual = quality_tags.split('.')
        
        # 检查预期标记是否都被提取到
        missing_tags = [tag for tag in expected if tag not in actual]
        if missing_tags:
            logger.error(f"✗ 缺少预期标记: {missing_tags}")
        else:
            logger.info(f"✓ 所有预期标记都被提取到")

if __name__ == "__main__":
    test_quality_tags_extraction()
