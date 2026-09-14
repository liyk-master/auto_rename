# 确定性文件名解析器（替代 GuessIt）设计

> 分支：`feat/native-filename-parser`
> 状态：Phase 0/1 进行中

## 1. 动机

GuessIt 为英文/西式文件名设计，对中文国漫/国产剧/字幕组命名先天不足。项目为此在
`core/guessit_parser/parser.py`（1778 行）堆了大量补丁，补丁之间互相冲突：

- 「场景1」想把纯数字文件名当集号（`01.mp4` → episode=1）
- 「场景2」又把 `210 4K.mkv` 判成电影《731》式标题，清空 season/episode
- 结果：`斗破丨苍穹/210 4K.mkv` → `S01E01`（210 被丢弃）

核心原则：**宁可留空，不要乱猜**。只填有显式证据的字段，猜不到交给 TMDB/LLM。

## 2. 格式清单（Phase 0 盘点）

| # | 输入示例 | show_name | season | episode | year | 类型 | 现状 |
|---|---|---|---|---|---|---|---|
| A1 | `Game.of.Thrones.S01E01.1080p...` | Game Of Thrones | 1 | 1 | — | tv | regex ✓ |
| A2 | `Breaking Bad - s05e16 - Felina.mp4` | Breaking Bad | 5 | 16 | — | tv | regex ✓ |
| A3 | `The Office Season 3 Episode 22.avi` | The Office | 3 | 22 | — | tv | regex ✓ |
| B1 | `一念永恒 完结季（2026）/第3集 4K.mkv` | 一念永恒 | 4(反推) | 3 | 2026 | tv | 已修（反推季号） |
| B2 | `死神 千年血战篇 -祸进谭（2026）更新至7集/01.mp4` | 死神 千年血战篇 | 4(反推) | 1 | 2026 | tv | 已修（反推季号） |
| C1 | `[Solo Leveling][13-25][BIG5]/[Solo][25].mp4` | Solo Leveling | 1 | 25 | — | tv | parser 补丁 ✓ |
| C2 | `[字幕组]剧名[01][BIG5][1080P].mkv` | 剧名 | 1 | 1 | — | tv | parser 补丁 ✓ |
| D1 | `斗破丨苍穹/210 4K.mkv` | 斗破苍穹 | ? | **210** | — | tv | **❌ 当前失败** |
| D2 | `剧名（2026）/01.mp4` | 剧名 | 反推 | 1 | 2026 | tv | 已修 |
| E1 | `[第二十条].Article.20.2024.60FPS.2160p...` | 第二十条 | — | — | 2024 | movie | PT 补丁 ✓ |
| F1 | `入青云01.mp4` | 入青云 | 1 | 1 | — | tv | 紧凑格式 ✓ |
| G1 | `1917.mkv` / `731.1080p.mkv` | 1917 / 731 | — | — | — | movie | 需防误判 |
| G2 | `The.Amazing.Spider-Man.2.2014...` | The Amazing Spider-Man 2 | — | — | 2014 | movie | 已修（续集号合并） |

**D1 是当前唯一已知失败项**：裸数字集号 + 质量标签，guessit 拆成 S02E10 后被
「场景2」补丁判成电影清空。

## 3. 分层规则引擎设计

新模块 `core/filename_parser/`，分层匹配，每层独立可测，**命中即返回**（不累加猜错风险）。

| 层 | 规则 | 覆盖格式 | 优先级 |
|---|---|---|---|
| L2 | 路径上下文 | 剧名目录 + 裸数字文件 → 集号 | 高 |
| L4 | PT 命名法 | `[中文].English.2024.2160p` | 高 |
| L5 | 方括号集号 | `[剧名][13-25]/[剧名][25]` | 高 |
| L3 | 紧凑格式 | `入青云01`、`剧名E03` | 中 |
| L6 | 数字标题保护 | `1917.mkv`（4 位数字）→ movie | 中 |
| L7 | 电影续集号 | `Spider-Man.2.2014` → 合并续集号 | 低 |
| L1 | 显式标记（待迁移） | `SxxExx`、`第N集/话`、`EPxx` | 最高 |
| L5b | 质量标签剥离 + 标题归一化（待迁移） | 通用后处理 | 低 |

## 4. 渐进迁移计划

- [x] Phase 0：格式清单（本文档第 2 节）
- [x] Phase 1：`FilenameParser` 骨架 + L2（路径上下文），接入 renamer（native 命中跳过 guessit）
- [x] Phase 1b：扩展 L3（紧凑格式）/ L4（PT 命名法）/ L5（方括号集号）/ L6（数字标题保护）
- [x] Phase 2：格式清单全表测试（`tests/unit/test_core/test_format_matrix.py`）；
      8 绿锁定当前正确行为，4 xfailed 记录 regex/guessit 旧世界缺陷（C1/E1/F1/G1-1917），
      native 端到端测试已覆盖对应新世界修复（`test_filename_parser.py`）
- [~] Phase 3：native 命中即跳过 GuessIt；GuessIt 未命中时降级为纯兜底已实现
      （`_has_explicit_season/episode_marker`：无显式季/集标记不采纳 GuessIt 的 season/episode）
- [x] Phase 4：A/B 对比测试（`test_parser_backend.py`）+ 配置开关 `parser.backend`
      （native/guessit/hybrid，默认 hybrid；见 config_template.ini `[parser]`）
- [x] Phase 5：移除 guessit——renamer 不再 import/调用；`requirements.txt` 删 guessit；
      删除 `guessit_parser/` 模块与旧世界测试；`parser.backend` 仅 native 有效
      （guessit/hybrid 静默回退 native）

## 5. 现状

解析链已完全确定化：`renamer._extract_with_regex`（显式标记/英文 SxxExx/中文集号）
+ `FilenameParser`（L2-L7 路径上下文/紧凑/PT/方括号/数字标题/续集号），
无外部解析依赖。猜不到的字段留空交给 TMDB/LLM 兜底。
