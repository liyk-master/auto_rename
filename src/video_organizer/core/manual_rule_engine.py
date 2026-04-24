"""
手动规则 DSL 引擎，用于 TMDB 重名/错判干预。

支持五种语法：
1. 屏蔽词：block: 词1,词2
2. 替换：replace: 原词 -> 新词
3. 定位+偏移：position: start=值,end=值,offset=值
4. 组合（内嵌直接指定）：{[tmdbid/doubanid=...;type=...;s=...;e=...]}
5. 条件规则：when: 条件 => 规则（仅当文件名匹配条件时才执行规则）

字段锁定机制：规则设置的字段会被锁定，防止后续流程覆盖。
"""

import re
import logging
from typing import Dict, List, Optional, Set, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# DSL 语法正则表达式
BLOCK_PATTERN = re.compile(r"^block\s*:\s*(.+)$", re.IGNORECASE)
REPLACE_PATTERN = re.compile(r"^replace\s*:\s*(.+)\s*->\s*(.+)$", re.IGNORECASE)
POSITION_PATTERN = re.compile(r"^position\s*:\s*(.+)$", re.IGNORECASE)
EMBED_PATTERN = re.compile(
    r"\{\[(?P<type>tmdbid|doubanid)=(?P<id>\d+);type=(?P<media_type>tv|movie)(?:;s=(?P<start>\d+))?(?:;e=(?P<end>\d+))?(?:\]\})",
    re.IGNORECASE,
)
# 条件规则: when: 条件 => 规则
CONDITIONAL_PATTERN = re.compile(r"^when\s*:\s*(.+?)\s*=>\s*(.+)$", re.IGNORECASE)


class RuleParseError(Exception):
    """规则解析错误"""
    pass


class ManualRule:
    """表示一条手动规则"""

    def __init__(self, raw_rule: str, rule_type: str):
        self.raw_rule = raw_rule
        self.rule_type = rule_type  # 'block', 'replace', 'position', 'embed', 'conditional'
        self.enabled = True

    def apply(self, metadata: Dict, file_path: Path, normalize_symbols: bool = False) -> Dict:
        """应用规则到元数据"""
        raise NotImplementedError

    def lock_fields(self) -> Set[str]:
        """返回此规则会锁定的字段列表"""
        return set()


class BlockRule(ManualRule):
    """屏蔽词规则 - 修改 _processed_filename 和 show_name"""

    def __init__(self, raw_rule: str, words: List[str]):
        super().__init__(raw_rule, 'block')
        self.words = [w.strip() for w in words if w.strip()]

    def apply(self, metadata: Dict, file_path: Path, normalize_symbols: bool = False) -> Dict:
        if not self.words:
            return metadata

        # 处理 _processed_filename
        processed = metadata.get('_processed_filename', '')
        if processed:
            for word in self.words:
                pattern = re.escape(word)
                processed = re.sub(pattern, '', processed, flags=re.IGNORECASE)
            processed = re.sub(r'\s+', ' ', processed).strip()
            metadata['_processed_filename'] = processed

        # 同时处理 show_name（如果存在）
        show_name = metadata.get('show_name', '')
        if show_name:
            original_show = show_name
            for word in self.words:
                pattern = re.escape(word)
                show_name = re.sub(pattern, '', show_name, flags=re.IGNORECASE)
            show_name = re.sub(r'\s+', ' ', show_name).strip()
            if show_name != original_show:
                metadata['show_name'] = show_name
                logger.debug(f"BlockRule 移除 show_name 中的词: {original_show} -> {show_name}")

        return metadata

    def lock_fields(self) -> Set[str]:
        return set()


class ReplaceRule(ManualRule):
    """替换规则 - 修改 _processed_filename 和 show_name"""

    def __init__(self, raw_rule: str, old: str, new: str):
        super().__init__(raw_rule, 'replace')
        self.old = old.strip()
        self.new = new.strip()

    def apply(self, metadata: Dict, file_path: Path, normalize_symbols: bool = False) -> Dict:
        if not self.old:
            return metadata

        # 替换 _processed_filename 中的内容
        processed = metadata.get('_processed_filename', '')
        if processed and self.old in processed:
            pattern = re.escape(self.old)
            processed = re.sub(pattern, self.new, processed, flags=re.IGNORECASE)
            processed = re.sub(r'\s+', ' ', processed).strip()
            metadata['_processed_filename'] = processed

        # 同时替换 show_name 中的内容（如果存在）
        show_name = metadata.get('show_name', '')
        if show_name and self.old in show_name:
            pattern = re.escape(self.old)
            new_show_name = re.sub(pattern, self.new, show_name, flags=re.IGNORECASE)
            new_show_name = re.sub(r'\s+', ' ', new_show_name).strip()
            if new_show_name != show_name:
                metadata['show_name'] = new_show_name
                logger.debug(f"ReplaceRule 替换 show_name: {show_name} -> {new_show_name}")

        return metadata

    def lock_fields(self) -> Set[str]:
        return set()


class PositionRule(ManualRule):
    """定位+偏移规则"""

    def __init__(self, raw_rule: str, start: Optional[str] = None, end: Optional[str] = None, offset: Optional[int] = None):
        super().__init__(raw_rule, 'position')
        self.start = start
        self.end = end
        self.offset = offset

    def apply(self, metadata: Dict, file_path: Path, normalize_symbols: bool = False) -> Dict:
        """根据起始和结束字符串定位并提取内容作为剧名"""
        text = metadata.get('_processed_filename', str(file_path))

        start_pos = 0
        end_pos = len(text)

        if self.start:
            match = re.search(re.escape(self.start), text)
            if match:
                start_pos = match.end()
            else:
                return metadata

        if self.end:
            match = re.search(re.escape(self.end), text)
            if match:
                end_pos = match.start()
            else:
                return metadata

        if end_pos > start_pos:
            extracted = text[start_pos:end_pos].strip()
            if extracted:
                extracted = re.sub(r'[\\/]', ' ', extracted)
                extracted = re.sub(r'\.[a-zA-Z0-9]+$', '', extracted)
                metadata['show_name'] = extracted.strip()

        if self.offset:
            current_name = metadata.get('show_name', '')
            if current_name and abs(self.offset) < len(current_name):
                if self.offset > 0:
                    metadata['show_name'] = current_name[self.offset:]
                else:
                    metadata['show_name'] = current_name[:self.offset]

        return metadata

    def lock_fields(self) -> Set[str]:
        return {'show_name'}


class EmbedRule(ManualRule):
    """内嵌直接指定规则"""

    def __init__(self, raw_rule: str, rule_id: str, media_type: str,
                 start_ep: Optional[int] = None, end_ep: Optional[int] = None):
        super().__init__(raw_rule, 'embed')
        self.rule_id = rule_id
        self.media_type = media_type
        self.start_ep = start_ep
        self.end_ep = end_ep

    def apply(self, metadata: Dict, file_path: Path, normalize_symbols: bool = False) -> Dict:
        if '=' in self.rule_id:
            prefix, id_val = self.rule_id.split('=', 1)
            if prefix == 'tmdbid':
                metadata['tmdb_id'] = id_val
            elif prefix == 'doubanid':
                metadata['douban_id'] = id_val

        metadata['media_type'] = self.media_type
        return metadata

    def lock_fields(self) -> Set[str]:
        return {'tmdb_id', 'media_type', 'douban_id'}


class ConditionalRule(ManualRule):
    """条件规则 - 当文件名匹配条件时才执行内部规则"""

    def __init__(self, raw_rule: str, condition: str, inner_rule: ManualRule):
        super().__init__(raw_rule, 'conditional')
        self.condition = condition
        self.inner_rule = inner_rule

    def apply(self, metadata: Dict, file_path: Path, normalize_symbols: bool = False) -> Dict:
        text = metadata.get('_processed_filename', '') or str(file_path)
        if re.search(re.escape(self.condition), text, re.IGNORECASE):
            return self.inner_rule.apply(metadata, file_path, normalize_symbols)
        return metadata

    def lock_fields(self) -> Set[str]:
        return self.inner_rule.lock_fields()


class ManualRuleEngine:
    """手动规则引擎"""

    def __init__(self, rules_config: List[Dict], enabled: bool = True, normalize_symbols: bool = True):
        self.enabled = enabled
        self.normalize_symbols = normalize_symbols
        self.rules: List[ManualRule] = []

        if enabled:
            self._parse_rules(rules_config)

        logger.info(f"ManualRuleEngine: enabled={enabled}, rules count={len(self.rules)}")

    def _parse_rules(self, rules_config: List[Dict]) -> None:
        for rule_conf in rules_config:
            if not isinstance(rule_conf, dict):
                continue

            raw_rule = rule_conf.get('rule', '').strip()
            if not raw_rule:
                continue

            try:
                rule = self._parse_single_rule(raw_rule)
                if rule:
                    rule.enabled = rule_conf.get('enabled', True)
                    if rule.enabled:
                        self.rules.append(rule)
            except Exception as e:
                logger.warning(f"解析规则失败: '{raw_rule}': {e}")

    def _parse_single_rule(self, raw_rule: str) -> Optional[ManualRule]:
        # 条件规则
        conditional_match = CONDITIONAL_PATTERN.match(raw_rule)
        if conditional_match:
            condition = conditional_match.group(1).strip()
            rule_text = conditional_match.group(2).strip()
            inner_rule = self._parse_single_rule(rule_text)
            if inner_rule:
                return ConditionalRule(raw_rule, condition, inner_rule)
            return None

        # 内嵌格式
        embed_match = EMBED_PATTERN.search(raw_rule)
        if embed_match:
            rule_id = embed_match.group('type') + '=' + embed_match.group('id')
            media_type = embed_match.group('media_type')
            start_ep = int(embed_match.group('start')) if embed_match.group('start') else None
            end_ep = int(embed_match.group('end')) if embed_match.group('end') else None
            return EmbedRule(raw_rule, rule_id, media_type, start_ep, end_ep)

        # 屏蔽词
        block_match = BLOCK_PATTERN.match(raw_rule)
        if block_match:
            words = [w.strip() for w in block_match.group(1).split(',')]
            return BlockRule(raw_rule, words)

        # 替换
        replace_match = REPLACE_PATTERN.match(raw_rule)
        if replace_match:
            old_word = replace_match.group(1)
            new_word = replace_match.group(2)
            return ReplaceRule(raw_rule, old_word, new_word)

        # 定位
        position_match = POSITION_PATTERN.match(raw_rule)
        if position_match:
            params_str = position_match.group(1)
            params = {}
            for pair in params_str.split(','):
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    params[k.strip().lower()] = v.strip()

            start = params.get('start')
            end = params.get('end')
            offset = None
            if 'offset' in params:
                try:
                    offset = int(params['offset'])
                except ValueError:
                    pass

            return PositionRule(raw_rule, start, end, offset)

        logger.warning(f"无法识别规则格式: {raw_rule}")
        return None

    def apply_rules(self, metadata: Dict, file_path: Path) -> Dict:
        if not self.enabled:
            return metadata

        for rule in self.rules:
            if not rule.enabled:
                continue

            try:
                logger.debug(f"应用规则 [{rule.rule_type}]: {rule.raw_rule}")
                metadata = rule.apply(metadata, file_path, self.normalize_symbols)
            except Exception as e:
                logger.error(f"应用规则失败 [{rule.rule_type}]: {e}")

        return metadata

    def get_locked_fields(self) -> Set[str]:
        locked = set()
        for rule in self.rules:
            if rule.enabled:
                locked.update(rule.lock_fields())
        return locked
