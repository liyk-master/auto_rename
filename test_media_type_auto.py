import sys
import os

# 添加src目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from video_organizer.core.renamer import VideoRenamer

def test_media_type_auto_detection():
    """测试自动检测剧集信息并设置media_type"""
    print("=== 测试自动媒体类型检测 ===")
    
    renamer = VideoRenamer(tmdb_api_key="test_key")
    
    # 测试用例：包含剧集信息的文件名
    test_cases = [
        '星期三 S01E01.mp4',
        '怪奇物语.S04E01.2160p.NF.WEB-DL.DDP5.1.x265.双语-字慕组.mp4',
        '权力的游戏.S08E06.1080p.BluRay.REMUX.AVC.DTS-HD.MA.7.1-CHS-ENG.mkv',
        '山海情 第1季第1集.mp4'
    ]
    
    for filename in test_cases:
        print(f"\n测试文件名: {filename}")
        
        # 提取元数据
        metadata = renamer._extract_with_regex(filename)
        
        print(f"提取到的元数据: {metadata}")
        
        # 检查是否检测到剧集信息
        has_episode_info = metadata.get('season') or metadata.get('episode')
        print(f"是否检测到剧集信息: {'是' if has_episode_info else '否'}")
        
        # 检查media_type是否正确设置
        media_type = metadata.get('media_type')
        print(f"自动设置的media_type: {media_type}")
        
        if has_episode_info:
            if media_type == 'tv':
                print("✓ 正确：检测到剧集信息，media_type设置为tv")
            else:
                print(f"✗ 错误：检测到剧集信息，但media_type设置为{media_type}")
        else:
            print("- 未检测到剧集信息，不检查media_type")

if __name__ == "__main__":
    test_media_type_auto_detection()
