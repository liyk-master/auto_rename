"""
Emos 三方识别功能演示脚本
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.video_organizer.core.emos_client import EmosClient


def demo_emos_recognition():
    """演示 Emos 三方识别功能"""

    print("=" * 80)
    print("Emos 三方识别功能演示")
    print("=" * 80)

    # 创建 Emos 客户端
    client = EmosClient(
        api_url="https://emos.prlo.de/api/recognize",
        timeout=30,
        enabled=True
    )

    # 测试用例
    test_files = [
        "唐朝诡事录 S01E01.mp4",
        "流浪地球2 (2023).mkv",
        "葬送的芙莉莲 S01E01.mp4",
        "海贼王 EP1080.mp4",
    ]

    print("\n开始识别测试文件...\n")

    for filename in test_files:
        print(f"📁 文件名: {filename}")
        print("-" * 80)

        # 调用识别接口
        response = client.recognize(filename)

        if response:
            # 解析媒体信息
            media_info = client.parse_media_info(response)

            # 显示识别结果
            print(f"✅ 识别成功")
            print(f"   标题: {media_info.get('title', 'N/A')}")
            print(f"   英文名: {media_info.get('original_title', 'N/A')}")
            print(f"   类型: {media_info.get('type', 'N/A')}")
            print(f"   年份: {media_info.get('year', 'N/A')}")
            print(f"   季数: {media_info.get('season', 'N/A')}")
            print(f"   集数: {media_info.get('episode', 'N/A')}")
            print(f"   季集格式: {media_info.get('season_episode', 'N/A')}")
            print(f"   单集标题: {media_info.get('episode_title', 'N/A')}")
            print(f"   清晰度: {media_info.get('resource_pix', 'N/A')}")
            print(f"   制作组: {media_info.get('resource_team', 'N/A')}")
            print(f"   视频编码: {media_info.get('video_encode', 'N/A')}")
            print(f"   音频编码: {media_info.get('audio_encode', 'N/A')}")

            # 判断识别结果是否可信
            is_confident = client.is_confident(response)
            print(f"   可信度: {'高' if is_confident else '低'}")
        else:
            print(f"❌ 识别失败")

        print()

    print("=" * 80)
    print("演示完成")
    print("=" * 80)


if __name__ == "__main__":
    demo_emos_recognition()