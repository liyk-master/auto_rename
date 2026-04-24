import sys
import os
sys.path.insert(0, '.')

# 设置日志
import logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 直接调用 extract_metadata 并捕获异常
from src.video_organizer.core.renamer import VideoRenamer
from pathlib import Path
import traceback

# 创建配置
config = {
    "manual_rules": {
        "enabled": True,
        "normalize_symbols": True,
        "rules": [
            {"rule": "replace: 测试 -> 实际", "enabled": True},
            {"rule": "block: 广告"},
            {"rule": "{[tmdbid=12345;type=tv]}", "enabled": True},
        ]
    },
    "tmdb": {"api_key": "dummy", "language": "zh-CN"},
    "guessit": {"enabled": False},
}

# 模拟 TMDBClient
from unittest.mock import patch, MagicMock
with patch('src.video_organizer.core.tmdb_client.TMDBClient') as mock_tmdb:
    mock_tmdb.return_value = MagicMock()
    renamer = VideoRenamer(tmdb_api_key="dummy", config=config)

# 创建一个临时文件
import tempfile
temp_dir = tempfile.mkdtemp()
file_path = Path(temp_dir) / "视频.mp4"
file_path.write_text("dummy")

print(f"Testing extract_metadata on {file_path}")
try:
    metadata = renamer.extract_metadata(file_path)
    print("Metadata:", metadata)
except Exception as e:
    print("Exception occurred:", e)
    traceback.print_exc()
    # 写入文件
    with open('direct_traceback.txt', 'w', encoding='utf-8') as f:
        f.write(traceback.format_exc())
    print("Traceback written to direct_traceback.txt")

# 清理
import shutil
shutil.rmtree(temp_dir)
