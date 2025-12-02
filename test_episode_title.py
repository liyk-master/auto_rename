from pathlib import Path
from src.video_organizer.core.renamer import VideoRenamer

# 创建一个测试实例（不需要实际的API密钥，因为我们只测试正则表达式提取）
# 使用包含 {quality_tags} 的自定义命名规则
custom_naming_rules = {
    "tv_show": "{show_name}/Season {season:02d}/{show_name} {season_episode} {quality_tags}",
    "movie": "{movie_name}{year_suffix}/{movie_name}{year_suffix} {quality_tags}",
    "anime": "{anime_name}/{season_name}/{anime_name} - S{season:02d}E{episode:02d} {quality_tags}",
    "simple": "{title} {quality_tags}"
}
renamer = VideoRenamer(tmdb_api_key="test_key", naming_rules=custom_naming_rules)

# 测试用例：包含剧集标题的文件名
test_files = [
    "唐朝诡事录 S01E01 - 长安红茶.mkv",
    "权力的游戏 Season 8 Episode 3 - The Long Night.mkv",
    "大明王朝1566 - 第1季第2集 - 御前会议.mkv",
    "海贼王 第1000集 - 草帽一伙的誓言.mkv",
    "Breaking Bad - S05E16 - Felina.mkv",
    "黑盒子 S01E01 1080p.Netflix.WEB-DL.H264.AAC.strm",
    "唐朝诡事录 - S01E01 - Chang'an Black Tea (1).mp4"  # 包含(1)后缀的测试用例
]

print("测试剧集标题提取：")
print("=" * 50)

for test_file in test_files:
    print(f"\n测试文件名: {test_file}")
    metadata = renamer._extract_with_regex(test_file)
    
    # 打印提取的元数据
    print(f"  剧集名称: {metadata.get('show_name', '未提取')}")
    print(f"  季号: {metadata.get('season', '未提取')}")
    print(f"  集号: {metadata.get('episode', '未提取')}")
    print(f"  剧集标题: {metadata.get('episode_name', '未提取')}")
    print(f"  提取的关键词: {metadata.get('quality_tags', '未提取')}")

print("\n" + "=" * 50)
print("测试命名规则应用：")
print("=" * 50)

# 测试命名规则应用
test_metadata = {
    'show_name': '黑盒子',
    'season': '1',
    'episode': '1',
    'quality_tags': '1080p.Netflix.WEB-DL.H264.AAC',
    'media_type': 'tv'
}

# 使用默认的tv_show命名规则
new_path = renamer.generate_new_path(test_metadata)
print(f"\n测试命名规则应用：")
print(f"  元数据: {test_metadata}")
print(f"  生成的路径: {new_path}")

print("\n" + "=" * 50)
print("测试完成！")
