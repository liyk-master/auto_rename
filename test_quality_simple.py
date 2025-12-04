import sys
import os

# 添加src目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from video_organizer.core.renamer import VideoRenamer

def test_quality_tags():
    """简单测试质量标记提取"""
    # 使用假的API密钥
    renamer = VideoRenamer(tmdb_api_key="test_key")
    
    # 测试用例
    filename = '凸变英雄X.2025.S01E02.2160p.WEB-DL.AAC.H264.strm'
    print(f"测试文件名: {filename}")
    
    # 提取质量标记
    quality_tags = renamer._extract_keywords(filename)
    print(f"提取到的质量标记: {quality_tags}")
    
    # 检查是否包含预期标记
    expected_tags = ['2160p', 'WEB-DL', 'AAC', 'H264']
    actual_tags = quality_tags.split('.')
    
    print(f"预期标记: {expected_tags}")
    print(f"实际标记: {actual_tags}")
    
    # 检查是否都被提取到
    for tag in expected_tags:
        if tag in actual_tags:
            print(f"✓ {tag} 被正确提取")
        else:
            print(f"✗ {tag} 未被提取")

if __name__ == "__main__":
    test_quality_tags()
