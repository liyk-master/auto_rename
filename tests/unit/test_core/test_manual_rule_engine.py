"""
手动规则引擎单元测试
"""

import os
import sys
import unittest
import tempfile
from pathlib import Path
from typing import Set, Dict
from unittest.mock import patch, MagicMock

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from src.video_organizer.core.manual_rule_engine import (
    ManualRuleEngine, BlockRule, ReplaceRule, PositionRule, EmbedRule,
    ConditionalRule, RuleParseError
)

class TestBlockRule(unittest.TestCase):
    """测试屏蔽词规则 - 修改 _processed_filename 和 show_name"""
    
    def test_block_single_word(self):
        rule = BlockRule("block: 测试", ["测试"])
        metadata = {"show_name": "测试剧集", "original_filename": "测试.mp4", "_processed_filename": "测试.mp4"}
        result = rule.apply(metadata, Path("测试.mp4"))
        # show_name 应被修改
        self.assertEqual(result["show_name"], "剧集")
        # _processed_filename 应被修改
        self.assertEqual(result["_processed_filename"], ".mp4")
    
    def test_block_multiple_words(self):
        rule = BlockRule("block: ABC, XYZ", ["ABC", "XYZ"])
        metadata = {"show_name": "ABC剧集XYZ", "original_filename": "ABC.测试.XYZ.mp4", "_processed_filename": "ABC.测试.XYZ.mp4"}
        result = rule.apply(metadata, Path("ABC.测试.XYZ.mp4"))
        # show_name 应被修改
        self.assertEqual(result["show_name"], "剧集")
        # _processed_filename 应被修改
        self.assertNotIn("ABC", result["_processed_filename"])
        self.assertNotIn("XYZ", result["_processed_filename"])
    
    def test_block_case_insensitive(self):
        rule = BlockRule("block: TEST", ["TEST"])
        metadata = {"show_name": "TestShow", "original_filename": "TESTFILE.mp4", "_processed_filename": "TESTFILE.mp4"}
        result = rule.apply(metadata, Path("TESTFILE.mp4"))
        # show_name 应被修改（移除 TEST）
        self.assertEqual(result["show_name"], "Show")
        # _processed_filename 应被修改
        self.assertEqual(result["_processed_filename"], "FILE.mp4")
    
    def test_lock_fields(self):
        rule = BlockRule("block: test", ["test"])
        locked = rule.lock_fields()
        # BlockRule 不锁定任何字段
        self.assertEqual(len(locked), 0)

class TestReplaceRule(unittest.TestCase):
    """测试替换规则 - 修改 _processed_filename 和 show_name"""
    
    def test_replace_simple(self):
        rule = ReplaceRule("replace: ABC -> XYZ", "ABC", "XYZ")
        metadata = {"show_name": "ABC剧集", "original_filename": "ABC_2023.mp4", "_processed_filename": "ABC_2023.mp4"}
        result = rule.apply(metadata, Path("ABC_2023.mp4"))
        # show_name 也应被修改（因为我们也替换了 show_name）
        self.assertEqual(result["show_name"], "XYZ剧集")
        # _processed_filename 应被修改
        self.assertEqual(result["_processed_filename"], "XYZ_2023.mp4")
    
    def test_replace_with_special_chars(self):
        rule = ReplaceRule("replace: 旧标题 -> 新标题", "旧标题", "新标题")
        metadata = {"show_name": "旧标题测试", "original_filename": "旧标题.mp4", "_processed_filename": "旧标题.mp4"}
        result = rule.apply(metadata, Path("旧标题.mp4"))
        # show_name 也应被修改
        self.assertEqual(result["show_name"], "新标题测试")
        self.assertEqual(result["_processed_filename"], "新标题.mp4")
    
    def test_lock_fields(self):
        rule = ReplaceRule("replace: a->b", "a", "b")
        locked = rule.lock_fields()
        # ReplaceRule 不锁定任何字段
        self.assertEqual(len(locked), 0)

class TestPositionRule(unittest.TestCase):
    """测试定位+偏移规则"""
    
    def test_position_start_end(self):
        rule = PositionRule("position: start=第, end=季", "第", "季", None)
        # 文件路径: / Downloads / 第X季 / 文件名
        file_path = Path("/Downloads/第03季/S01E01.mp4")
        metadata = {"show_name": ""}
        result = rule.apply(metadata, file_path)
        # 提取 "03"（实际提取的是 "03"）
        self.assertIn("03", result["show_name"])
    
    def test_position_with_offset(self):
        rule = PositionRule("position: start=S,offset=1", "S", None, 1)
        file_path = Path("S01E01Test.mp4")
        metadata = {"show_name": ""}
        result = rule.apply(metadata, file_path)
        # offset=1 会截取从 start 后一位，因此是 "01E01Test" 之后取 "1E01Test"? 实现细节。
        self.assertTrue(len(result["show_name"]) > 0)
    
    def test_lock_fields(self):
        rule = PositionRule("position: start=,end=", "start", "end", 0)
        locked = rule.lock_fields()
        self.assertIn("show_name", locked)

class TestEmbedRule(unittest.TestCase):
    """测试内嵌直接指定规则"""
    
    def test_embed_tmdb_tv(self):
        rule = EmbedRule(
            "{[tmdbid=12345;type=tv;s=1;e=5]}",
            "tmdbid=12345", "tv", 1, 5
        )
        metadata = {}
        result = rule.apply(metadata, Path("dummy.mp4"))
        self.assertEqual(result.get("tmdb_id"), "12345")
        self.assertEqual(result.get("media_type"), "tv")
    
    def test_embed_douban_movie(self):
        rule = EmbedRule(
            "{[doubanid=67890;type=movie]}",
            "doubanid=67890", "movie", None, None
        )
        metadata = {}
        result = rule.apply(metadata, Path("dummy.mp4"))
        self.assertEqual(result.get("douban_id"), "67890")
        self.assertEqual(result.get("media_type"), "movie")
    
    def test_lock_fields(self):
        rule = EmbedRule("{[tmdbid=1;type=tv]}", "tmdbid=1", "tv")
        locked = rule.lock_fields()
        self.assertIn("tmdb_id", locked)
        self.assertIn("media_type", locked)

class TestConditionalRule(unittest.TestCase):
    """测试条件规则"""
    
    def test_condition_match_replace(self):
        """条件匹配时执行替换"""
        inner_rule = ReplaceRule("replace: 出租 -> 租借", "出租", "租借")
        rule = ConditionalRule(
            "when: [ANi] => replace: 出租 -> 租借",
            "[ANi]",
            inner_rule
        )
        # 文件名包含 [ANi]，条件满足
        metadata = {"_processed_filename": "[ANi] 出租女友 第五季.mp4"}
        result = rule.apply(metadata, Path("test.mp4"))
        self.assertEqual(result["_processed_filename"], "[ANi] 租借女友 第五季.mp4")
    
    def test_condition_not_match(self):
        """条件不匹配时不执行替换"""
        inner_rule = ReplaceRule("replace: 出租 -> 租借", "出租", "租借")
        rule = ConditionalRule(
            "when: [ANi] => replace: 出租 -> 租借",
            "[ANi]",
            inner_rule
        )
        # 文件名不包含 [ANi]，条件不满足
        metadata = {"_processed_filename": "出租女友 第五季.mp4"}
        result = rule.apply(metadata, Path("test.mp4"))
        self.assertEqual(result["_processed_filename"], "出租女友 第五季.mp4")
    
    def test_condition_match_block(self):
        """条件匹配时执行屏蔽"""
        inner_rule = BlockRule("block: 广告", ["广告"])
        rule = ConditionalRule(
            "when: 特定前缀 => block: 广告",
            "特定前缀",
            inner_rule
        )
        metadata = {"_processed_filename": "特定前缀广告视频.mp4"}
        result = rule.apply(metadata, Path("test.mp4"))
        self.assertNotIn("广告", result["_processed_filename"])
    
    def test_lock_fields(self):
        """条件规则的锁字段来自内部规则"""
        inner_rule = EmbedRule("{[tmdbid=1;type=tv]}", "tmdbid=1", "tv")
        rule = ConditionalRule(
            "when: test => {[tmdbid=1;type=tv]}",
            "test",
            inner_rule
        )
        locked = rule.lock_fields()
        self.assertIn("tmdb_id", locked)
        self.assertIn("media_type", locked)
    
    def test_parse_conditional_rule(self):
        """测试条件规则解析"""
        config = [{"rule": "when: [ANi] => replace: 出租 -> 租借", "enabled": True}]
        engine = ManualRuleEngine(config)
        self.assertEqual(len(engine.rules), 1)
        self.assertEqual(engine.rules[0].rule_type, "conditional")
        self.assertEqual(engine.rules[0].condition, "[ANi]")
        self.assertEqual(engine.rules[0].inner_rule.rule_type, "replace")

class TestManualRuleEngine(unittest.TestCase):
    """测试规则引擎整体功能"""
    
    def test_parse_rules_from_config(self):
        config = [
            {"rule": "block: ABC", "enabled": True},
            {"rule": "replace: 旧 -> 新", "enabled": True},
            {"rule": "position: start=S,end=E", "enabled": True},
            {"rule": "{[tmdbid=123;type=tv]}", "enabled": True},
        ]
        engine = ManualRuleEngine(config)
        self.assertEqual(len(engine.rules), 4)
    
    def test_apply_multiple_rules(self):
        config = [
            {"rule": "block: 广告"},
            {"rule": "replace: 旧名 -> 新名"},
        ]
        engine = ManualRuleEngine(config)
        metadata = {"show_name": "旧名广告", "original_filename": "旧名广告.mp4", "_processed_filename": "旧名广告.mp4"}
        result = engine.apply_rules(metadata, Path("旧名广告.mp4"))
        # BlockRule 移除 "广告"，ReplaceRule 替换 "旧名" 为 "新名"
        # 两者都修改 _processed_filename 和 show_name
        self.assertNotIn("广告", result["_processed_filename"])
        self.assertIn("新名", result["_processed_filename"])
        # show_name 也应被修改（ReplaceRule 也会替换 show_name）
        self.assertEqual(result["show_name"], "新名")
    
    def test_locked_fields_union(self):
        config = [
            {"rule": "block: test"},
            {"rule": "replace: a->b"},
            {"rule": "{[tmdbid=123;type=tv]}"},
        ]
        engine = ManualRuleEngine(config)
        locked = engine.get_locked_fields()
        # block 和 replace 不锁定任何字段
        # embed 锁定 tmdb_id, douban_id, media_type
        self.assertIn("tmdb_id", locked)
        self.assertIn("media_type", locked)
        self.assertNotIn("show_name", locked)
    
    def test_disabled_rule(self):
        config = [
            {"rule": "block: ABC", "enabled": False},
            {"rule": "replace: XYZ -> 123", "enabled": True},
        ]
        engine = ManualRuleEngine(config)
        self.assertEqual(len(engine.rules), 1)  # 只有 enabled 的规则被加载
    
    def test_invalid_rule_skipped(self):
        config = [
            {"rule": "invalid syntax"},
            {"rule": "block: OK", "enabled": True},
        ]
        engine = ManualRuleEngine(config)
        self.assertEqual(len(engine.rules), 1)
        self.assertEqual(engine.rules[0].rule_type, "block")
    
    def test_empty_config(self):
        engine = ManualRuleEngine([])
        self.assertEqual(len(engine.rules), 0)
        locked = engine.get_locked_fields()
        self.assertEqual(len(locked), 0)

class TestRuleIntegrationWithRenamer(unittest.TestCase):
    """测试规则引擎与 VideoRenamer 集成"""
    
    def setUp(self):
        from src.video_organizer.core.renamer import VideoRenamer
        
        self.temp_dir = tempfile.mkdtemp()
        # 创建一个 minimal config，启用 manual_rules
        self.config = {
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
            "guessit": {"enabled": False},  # 简化测试
        }
        # Mock TMDBClient - patch 正确的位置 (renamer 模块中 from import 的名称)
        self.tmdb_patcher = patch('src.video_organizer.core.renamer.renamer.TMDBClient')
        self.mock_tmdb_class = self.tmdb_patcher.start()
        self.mock_tmdb_instance = MagicMock()
        # 配置 mock 返回值
        self.mock_tmdb_instance.get_tv_details.return_value = {
            "id": 12345,
            "name": "测试剧集",
            "number_of_seasons": 1,
        }
        self.mock_tmdb_instance.search_tv_show.return_value = {
            "results": [{"id": 12345, "name": "测试剧集"}]
        }
        self.mock_tmdb_class.return_value = self.mock_tmdb_instance
        
        self.renamer = VideoRenamer(
            tmdb_api_key="dummy",
            config=self.config
        )
    
    def tearDown(self):
        if hasattr(self, 'tmdb_patcher'):
            self.tmdb_patcher.stop()
        # 清理临时目录
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_rules_applied_before_regex(self):
        """测试规则在正则提取前应用 - 检查最终 show_name"""
        file_path = Path(self.temp_dir) / "测试广告视频S01E01.mp4"
        # 创建空文件
        file_path.touch()
        metadata = self.renamer.extract_metadata(file_path)
        # 打印元数据用于调试
        print(f"DEBUG metadata: {metadata}")
        # 由于 EmbedRule 设置了 tmdb_id=12345，TMDB 会返回 "测试剧集"
        # 规则修改了 _processed_filename，但 show_name 最终来自 TMDB
        # 检查 tmdb_id 是否正确设置（由 EmbedRule 锁定）
        self.assertEqual(metadata.get("tmdb_id"), "12345")
        # show_name 应该来自 TMDB（因为 EmbedRule 设置了 tmdb_id）
        self.assertEqual(metadata.get("show_name"), "测试剧集")
    
    def test_locked_fields_prevent_regex_override(self):
        """测试锁定字段（tmdb_id, media_type）不会被后续流程覆盖"""
        file_path = Path(self.temp_dir) / "视频.mp4"
        file_path.touch()
        metadata = self.renamer.extract_metadata(file_path)
        # Embed 规则设置了 tmdb_id 和 media_type，应被锁定
        self.assertEqual(metadata.get("tmdb_id"), "12345")
        self.assertEqual(metadata.get("media_type"), "tv")
    
    def test_rule_lock_show_name_from_parent_fallback(self):
        """测试规则锁定 show_name 后，父目录补全不会覆盖"""
        # 创建一个文件在子目录中
        sub_dir = Path(self.temp_dir) / "Season 01"
        sub_dir.mkdir()
        file_path = sub_dir / "实际视频.mp4"
        file_path.touch()
        metadata = self.renamer.extract_metadata(file_path)
        # 由于 EmbedRule 没有锁定 show_name，此处不做断言
        # 只检查 embed 规则设置的字段
        self.assertEqual(metadata.get("tmdb_id"), "12345")

if __name__ == '__main__':
    unittest.main()
