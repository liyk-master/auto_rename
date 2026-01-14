import os
import unittest
from pathlib import Path
import tempfile

# 添加项目根目录到Python路径
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.video_organizer.core.config_loader import (
    load_config,
    _config_to_dict,
    save_default_config,
)


class TestConfigLoader(unittest.TestCase):

    def setUp(self):
        """
        创建临时配置文件用于测试
        """
        # 创建临时目录
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp_dir)

        # 创建临时配置文件
        self.temp_config_path = os.path.join(self.temp_dir, "test_config.ini")

    def tearDown(self):
        """
        清理测试环境
        """
        # 如果测试文件存在则删除
        if os.path.exists(self.temp_config_path):
            os.remove(self.temp_config_path)

    def test_load_config_default(self):
        """
        测试加载默认配置
        """
        # 确保配置文件不存在
        if os.path.exists(self.temp_config_path):
            os.remove(self.temp_config_path)

        # 加载配置（应该生成默认配置）
        config = load_config(self.temp_config_path)

        # 验证基本配置是否存在
        self.assertIsNotNone(config)
        self.assertIn("monitoring", config)
        self.assertIn("naming_rules", config)

    def test_load_config_with_content(self):
        """
        测试加载带有内容的配置文件
        """
        # 创建测试配置文件
        config_content = """[monitoring]
# 监控目录
monitored_dir = C:\\Downloads\\Videos

# 输出目录
output_dir = D:\\Media\\Videos

# 支持的视频扩展名
supported_extensions = .mp4, .mkv, .avi, .mov, .wmv, .flv

# 轮询间隔（秒）
polling_interval = 10

# 是否递归监控子目录
recursive = true

[naming]
tv_show_format = TV/{show_name}/Season {season:02d}/{show_name} - S{season:02d}E{episode:02d} - {episode_name}
movie_format = Movies/{movie_name} ({year})/{movie_name} ({year})
anime_format = Anime/{anime_name}/Season {season:02d}/{anime_name} - S{season:02d}E{episode:02d}
simple_format = Unsorted/{filename}

[tmdb]
api_key = test_api_key
language = zh-CN
region = CN
"""

        with open(self.temp_config_path, "w", encoding="utf-8") as f:
            f.write(config_content)

        # 加载配置
        config = load_config(self.temp_config_path)

        # 验证配置是否正确加载
        self.assertEqual(config.get("monitored_dir"), "C:\\Downloads\\Videos")
        self.assertEqual(config.get("output_dir"), "D:\\Media\\Videos")

        # 验证命名规则
        naming_rules = config.get("naming_rules", {})
        self.assertEqual(
            naming_rules.get("tv_show"),
            "TV/{show_name}/Season {season:02d}/{show_name} - S{season:02d}E{episode:02d} - {episode_name}",
        )

        # 验证TMDB配置
        self.assertEqual(config.get("tmdb_config", {}).get("api_key"), "test_api_key")

    def test_config_to_dict(self):
        """
        测试配置对象转换为字典
        """
        from configparser import ConfigParser

        # 创建测试配置对象
        config = ConfigParser()
        config["monitoring"] = {
            "monitored_dir": "C:\\Downloads\\Videos",
            "output_dir": "D:\\Media\\Videos",
            "supported_extensions": ".mp4, .mkv",
            "polling_interval": "10",
            "recursive": "true",
        }

        config["naming"] = {
            "tv_show_format": "TV/{show_name}/Season {season:02d}/{show_name} - S{season:02d}E{episode:02d}",
            "movie_format": "Movies/{movie_name} ({year})/{movie_name} ({year})",
        }

        # 转换为字典
        config_dict = _config_to_dict(config)

        # 验证转换结果
        self.assertEqual(config_dict["monitored_dir"], "C:\\Downloads\\Videos")
        self.assertEqual(config_dict["output_dir"], "D:\\Media\\Videos")
        self.assertEqual(config_dict["supported_extensions"], [".mp4", ".mkv"])
        self.assertEqual(config_dict["polling_interval"], 10)
        self.assertEqual(config_dict["recursive"], True)

        # 验证命名规则
        self.assertEqual(
            config_dict["naming_rules"]["tv_show"],
            "TV/{show_name}/Season {season:02d}/{show_name} - S{season:02d}E{episode:02d}",
        )

    def test_save_default_config(self):
        """
        测试保存默认配置
        """
        # 保存默认配置
        save_default_config(self.temp_config_path)

        # 验证文件是否存在
        self.assertTrue(os.path.exists(self.temp_config_path))

        # 验证文件内容
        with open(self.temp_config_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 检查是否包含必要的配置节
        self.assertIn("[monitoring]", content)
        self.assertIn("[naming]", content)
        self.assertIn("[tmdb]", content)


if __name__ == "__main__":
    unittest.main()
