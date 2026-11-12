# AGENTS.md

## 构建/测试/格式化

- **运行全部可用测试（推荐）:** `pytest tests/unit tests/test_emya_models.py tests/test_organizer.py`
  （当前 330 passed / 1 failed）
- **裸跑 `pytest` 会失败:** `tests/integration/test_integration.py` 在收集阶段就 ImportError
  （见「已知问题」），必须先 `--ignore` 或按上面的方式指定路径
- **运行单个测试文件:** `pytest tests/unit/test_core/test_renamer.py`
- **运行单个测试:** `pytest tests/unit/test_core/test_manual_rule_engine.py::TestManualRuleEngine::test_locked_fields_union`
- **格式化:** `black .`（⚠️ 当前 53/76 文件不符合 black，全量格式化会产生巨大 diff，
  只对改动文件执行 `black <file>`）
- **类型检查:** `mypy src/`（⚠️ 基线约 408 errors / 40 files，未纳入 CI 门禁；
  只需保证自己改动的文件不新增错误）
- **Lint:** `flake8 src/`（⚠️ 基线约 3079 处告警，主要是 `W293` 空白行含空格、`E501` 超长；
  同样只关注改动行）
- `pyproject.toml` 已配置 `pythonpath = ["src"]`、`testpaths = ["tests"]`、`addopts = "-v"`
- 依赖安装: `pip install -r requirements.txt`（开发工具在 `requirements-dev.txt`）
- 本地 Python 3.14，但 `requirements.txt` 按 3.9 兼容版本锁定，勿随意升级依赖

## 项目结构要点

所有代码都在 `src/video_organizer/` 包内（不存在顶层 `web/`、`upload/`、`database/` 目录）。

- **入口:**
  - 主入口: `src/video_organizer/main.py` — `main()`
  - 包运行: `python -m src.video_organizer.main [--web/--web-only/--process]`
    或（`pip install -e .` 之后）`python -m video_organizer`（`__main__.py`）
  - CLI 启动器: `run_organizer.py` — 无参数时自动追加 `--web`（监控 + Web 同时启动）
  - 参数定义在 `utils/cli_parser.py`: `--config/--monitor-dir/--show-config/--process/
    --organize-p123/--organize-yun139/--organize-dry-run/--web/--web-only/--web-host/
    --web-port/--web-reload/-v`
- **核心模块** (`src/video_organizer/core/`)：单文件与子包混存，导入前先确认路径
  - `renamer/` — 包，对外只导出 `VideoRenamer`（`from .core.renamer import VideoRenamer`）；
    内含 `renamer.py`（LLM 兜底识别也在此，见 `_parse_filename_with_cache`）、
    `ai_parser.py`（❗空壳，`extract_with_ai()` 只打 warning 不做事）、`category_detector.py`、
    `chinese_utils.py`、`path_builder.py`
  - `file_handler/handler.py` — `VideoFileHandler` 文件处理主循环（原 `core/video_file_handler.py` 已迁移）
  - `monitor/monitor.py` — `FileSystemMonitor` 目录监控
  - `downloader/` — `base.py` + `qbittorrent_monitor.py` + `aria2_monitor.py` + `factory.py`
  - `filename_parser/` — `FilenameParser` 确定性解析器（已替代 GuessIt，guessit 已移除）；
    分层：L2 路径上下文 / L3 紧凑格式 / L4 PT 命名法 / L5 方括号集号 /
    L6 数字标题保护（1917.mkv→movie）/ L7 电影续集号（Spider-Man.2.2014→续集）；
    解析链 = `_extract_with_regex`（显式标记/英文 SxxExx/中文集号）+ FilenameParser（L2-L7），
    猜不到留空交给 TMDB/LLM；格式清单测试 `test_format_matrix.py` 锁分层覆盖；
    ⚙ L2「中文剧名目录 + 数字开头 = 集号」不适用于「`数字.英文标题.年份`」点分
    形态（`三傻大闹宝莱坞/3.ldiots.2009.1080p...` 的 3 是片名 3 Idiots 而非第 3 集，
    误当集号会连带判成 tv 而使后续搜索全部落空；中文副标题点分如
    `狂飙/01.开端.2023.1080p.mp4` 仍提取 episode=1）；
    分层设计见 `core/filename_parser/README.md`
  - `emya/` — emya 媒体库入库（`api.py` / `models.py` / `service.py`）
  - `config_loader.py` — 配置加载/保存/验证（支持 frozen 打包环境路径）
  - `tmdb_client.py` — TMDB API 客户端
  - `manual_rule_engine.py` — 手动规则 DSL 引擎
  - `media_type_resolver.py` — media_type 置信度仲裁（电影/剧集误判修正）
  - `recycle_cleaner/` — 网盘回收站定时清理（`base.py` Provider 抽象 + `providers.py` 各网盘实现
    + `cleaner.py` 每日时间点调度线程）；123云盘删除的文件仍占容量，需 `trash_delete_all` 才释放
    （`fs_trash` 仅移入回收站）；新增网盘只需实现 `BaseRecycleProvider.stats()/clear()` 并
    `@register_provider`
  - `media_tracker_client.py`、`subtitle_handler.py`、`file_mover.py`、`db_manager.py`
- **工具模块** (`src/video_organizer/utils/`):
  - `cache.py` — `ThreadSafeLRUCache`：带容量上限的线程安全 LRU 容器，
    `get_or_create()` 提供 single-flight 并发合并；
    `VideoRenamer` 的全部缓存（`_tmdb_cache` / `_search_cache` / `_type_resolve_cache` /
    `_season_year_boost_cache` / `_llm_parse_cache` / `_tmdb_name_to_id`）均基于它，
    超限自动淘汰最久未使用条目，多 worker 并发读写原子；
    ⚙ 这些缓存是 **VideoRenamer 的类属性（进程级共享）**：同一进程内多个实例
    （监控 handler / Web 手动验证 / 网盘整理 / emya 入库）共享同一份缓存，
    否则 `/api/manual/validate` 这类每请求 new 实例的路径会各自请求 TMDB/LLM；
    测试通过 `tests/conftest.py` 的 autouse fixture 隔离共享缓存
  - `llm_translator.py` — 多 Provider LLM 翻译/识别，负载均衡（round_robin/random/failover/weighted）；
    自动检测 `finish_reason=length` 截断并把 `max_tokens` 翻倍到 `max_tokens_cap` 重试；
    识别 JSON 支持 `tmdb_corrected_title` 纠正片名
  - `cli_parser.py`、`cli_output.py`、`config_loader.py`、`logging_setup.py`、
    `logging_utils.py`、`path_manager.py`
- **Web 后端** (`src/video_organizer/web/`):
  - `app.py` — FastAPI 应用创建 `create_app()`，统一挂 `/api/*` 前缀
  - `auth.py` — HMAC-SHA256 令牌（非标准 JWT，默认 7 天过期，服务重启全部失效）
    + PBKDF2 密码哈希 + `X-API-Key` 认证（sha256 哈希存库）
  - `routers/` — `auth.py`, `apikeys.py`, `config.py`, `tasks.py`, `logs.py`,
    `manual.py`, `downloaders.py`, `strm.py`, `organize.py`, `recycle.py`；
    `strm.py` 的 123 秒传代理会先建临时文件再取直链，**所有提前返回路径**都必须走
    `_p123_trash_temp()` 清理（已重试一次并校 code），否则文件残留在网盘目录里；
    秒传响应的两个 FileId 语义不同（见 `_p123_collect_trash_ids` 注释）：取直链要
    按 `_p123_download_id_candidates()` 的候选顺序逐个试（`Info.FileId` 真实条目
    优先、顶层会话 id 兜底），线上出现过顶层 id 直接 `code=5066 文件不存在`
  - `services/state.py` — `StateManager` 单例
  - `static/` — 原生 JS 前端（`index.html`, `app.js`, `ui.js`, `api.js`, `app.css`）
- **上传/整理模块** (`src/video_organizer/upload/`):
  - `base.py` — 上传基类（进度追踪、断点续传、Telegram 通知）
  - 字幕上传（`p123_uploader.py` / `yun139_uploader.py` 的 `upload_subtitles`）统一走
    `core/subtitle_handler.py` 的 `is_hls_segment_subtitle()` / `plan_subtitle_uploads()`：
    ⚙ m3u8/HLS 下载会留下几十上百个 `playlist1.vtt`、`segment3.vtt` 分片（内容带
    `X-TIMESTAMP-MAP`），旧逻辑把它们当字幕、且无语言标识时全部重命名成同一个
    `<视频名>.srt` 逐个上传（互相覆盖、进度像卡死）。现在按文件名模式 + VTT 内容头
    识别分片直接跳过，并按目标名去重（优先与视频同名者、其次体积大的）；
    `file_handler/handler.py:_process_subtitle_file` 同样不再把分片改名成本地视频字幕
  - `emos_uploader.py` — emos 上传 + 重复资源识别
  - `cloud189_uploader.py` / `cloud189_client.py` — 天翼云盘
  - `p123_uploader.py` / `p123_client.py` / `pan123_client.py` — 123 云盘（`pan123_client.py` 是
    原生驱动，除 `fs_trash` 外另有 `recycle_list/iter_recycle/recycle_stats/recycle_delete/recycle_clear`）；
    ⚠️ `Pan123Client.request()` 接口报错时只记日志**不抛异常**（仅返回带非 0 code 的 body），
    所以删除/移动类调用必须自己检查 `resp["code"]`，否则会静默失败
  - `yun139_uploader.py` / `yun139_client.py` — 139 移动云盘
  - `media_tracker_uploader.py` — Media Tracker
  - `base_organizer.py` + `p123_organizer.py` + `yun139_organizer.py` — 网盘整理（`--organize-*`）；
    `base_organizer` 复用同一个 `VideoRenamer` 实例（懒加载 + 双重检查锁），
    整理路径的 TMDB/LLM 缓存跨文件共享，不会逐文件重建
- **数据库** (`src/video_organizer/database/`): SQLAlchemy（`models.py`, `operations.py`,
  `config_operations.py`, `session.py`），用于 emya 入库、API Key、配置持久化
- **运行时目录:** `data/`（缓存、139_rapid）、`logs/`、`strm/`、`cas/`（均被 gitignore）

## 配置

- `config.ini`（实际，gitignore）/ `config_template.ini`（模板，首次运行自动生成），
  两者 section 结构保持一致
- 查找顺序（`core/config_loader.py: get_default_config_path()`）:
  frozen 环境用 exe 同级目录；否则 **cwd 下 `config.ini` → 项目根 `config.ini` → 包内 `config.ini`**。
  注意「配置文件为空」不等于「不可用」，真实密钥常在项目根 `config.ini`
- 主要 section: `[monitoring]` `[naming]` `[tmdb]` `[llm_fallback]` `[llm_provider_1..3]`
  `[guessit]` `[parser]` `[emos]` `[emos_recognition]` `[processing]` `[logging]` `[telegram]`
  `[emya_db]` `[yun139]` `[media_tracker]` `[p123]` `[recycle_clean]`；`[downloader.aria2]` / `[downloader.qbittorrent]` 模板中注释示例
- **回收站清理配置** (`[recycle_clean]`，默认 `enabled = False`):
  - `providers` — 逗号分隔（当前仅 `p123`）、`daily_at` — `HH:MM`，可配多个如 `04:00,16:00`
  - `catch_up_on_start` — 启动时补跑错过的时间点、`run_on_start` — 启动后立即跑一次（调试）
  - `notify_telegram` — 结果推 `[telegram]`、`max_items` — 统计时最多遍历的条目数
  - 策略固定为「清空回收站」（不可恢复），未做按天数/个数删除；调度器在 `main.py:
    initialize_recycle_cleaner()` 创建并 `set_cleaner()` 注册为全局单例，未启用时也注册（供 Web 手动触发）
- **LLM 兜底识别配置** (`[llm_fallback]`):
  - `enabled`、`max_concurrent` — 真正发 LLM 请求的并发槽数
  - `llm_wait_timeout` — 默认 60（秒），同时用作「排队等并发槽」与「等待在途同类请求」的上限
  - 兜底只在 TMDB 主搜索 + cleaned_name + 截断 + 父目录名四种策略全部失败后才触发
  - ⚙ **截断不做数字季号截断**——`晚酌的流派5：夏篇`、电影续作
    `终结者2：审判日` 等一律按原名搜索，宁可识别失败走 LLM，也不允许截成第一部
    （`tests/test_renamer_llm_cache.py::TestNoAggressiveTruncation` 覆盖该约束）
  - ⚙ **按年份反推季号**：文件名无季号但有目录年份时（如
    `死神 千年血战篇 -祸进谭（2026）更新至7集/01.mp4`、
    `一念永恒 完结季（2026）/第3集 4K.mkv`），识别成功后用目录年份
    （`entry_year`，识别过程中 year 会被 TMDB 首播年份覆盖，反推必须用入口值）
    反查 TMDB 剧集季列表的 `air_date`，恰一个季匹配则采用（`_infer_season_from_year`），
    否则默认第 1 季（`_ensure_season` 统一兜底，所有识别路径共用）；
    解析器给裸集号文件名补的默认 season=1 不被信任——
    无显式季标记（S01/第1季/Season 1）且带目录年份时也允许反推覆盖
    （`_has_explicit_season`，`TestDefaultSeasonNotTrusted` 覆盖）
  - ⚙ **同名「电视剧/动漫」双条目按集号容量判定**：TMDB 常有同名双条目
    （《凡人修仙传》2020 动画 206 集 / 2025 真人剧 30 集），目录年份 2025 触发的
    季年份加分会把 `S01E194` 选进只更新到 30 集的真人剧。识别时在年份/热度
    打分前用 `_filter_candidates_by_episode_capacity()` 剔除集数容不下文件集号的
    tv 候选（有显式季标记看该季集数，否则看总集数）。⚠️ **只做 tv 候选之间的
    消歧**：只有一个 tv 候选或没有任何 tv 候选能容纳集号时不剔除（TMDB 对在播剧
    常只收录很少集数，如《真男人》S02 仅收录 1 集而文件是 S02E05）——否则唯一
    标题精确匹配的 tv 会出局、退化成同名 movie；movie 等非 tv 候选也不受益。
    容量未知（详情缺失/集数 0）不剔除；`_tv_episode_capacity_cache` 按 tmdb_id
    缓存容量，失败结果不缓存（`tests/unit/test_core/test_episode_capacity.py` 覆盖）
  - ⚙ **电影续集号不回吞**：`The.Amazing.Spider-Man.2.2014…` 的续集号 2
    由 native L7 合并回搜索词（`The Amazing Spider Man 2`）；
    同时 `has_exact_match` 对标题做连字符/下划线归一化（`Spider-Man` == `Spider Man`），
    否则 TMDB 收录名带连字符永远匹配不上、退化为按人气选错条目；
    movie 搜索命中后立即落 `tmdb_id`（不依赖 external_ids）
    （`TestMovieSequel` 覆盖）
  - ⚙ **TMDB 搜索带 single-flight + 空结果短时缓存**：`_search_with_language()` 对
    同 (搜索词, 类型, 年份, 语言) 的并发调用只发一次真实请求；空结果缓存
    `_SEARCH_EMPTY_TTL`（600s），避免识别失败的搜索词被多文件反复重试打爆限速；
    `search_web_fallback` 也走进程级全局限速器（`_global_rate_limiter`）
  - ⚙ **0 条结果必须补做跨语言搜索**（`_cross_language_search()`）：TMDB 索引按语言
    分片，条目可能只以原名收录，指定 zh-CN/en-US 时就是搜不到。旧代码
    `if primary_results:` 的 else 分支在 0 命中时只打了句「第一次搜索结果充足(0个)，
    跳过跨语言搜索」就放弃（措辞与语义都反了），白丢一次补搜机会。现在 0 命中
    也会跑 `language=None` 搜索（再掉 `search_video_show(language=None)` 兜底），
    但**只采纳完全匹配+年份守卫的结果**：对脏搜索词跨语言常返回一堆子串噪音，
    直接当候选会让 `results` 非空、后面的备选策略（cleaned_name/截断/分段剥离/
    父目录/LLM）全部被跳过（`TestZeroResultCrossLanguage` 正反两向覆盖）
  - ⚙ **名称缓存键必须带年份**（`_name_id_cache_key`）：key 是
    `名称_类型_年份`（年份缺失时是 `名称_类型_`，只在文件与目录都抽不到年份时
    才查询）。旧 key 只有 `名称_类型`，同名不同版本必互相污染——射雕英雄传在
    TMDB 有 1976/1983/1988/1994/2003/2008/2017 多个独立条目，识别过一次
    2017 版（id=69530）后，`射雕英雄传 (2003)/…S01E11.mkv` 的每一集都直接命中
    缓存被链到 2017 条目（集数容量校验救不了：各版本集数都装得下 E11）。
    现在 2003 文件走 `射雕英雄传_tv_2003` 必 miss → 搜索按年份裁决到 id=31929，
    两个年份的映射并存（`TestSameNameDifferentYearCacheSeparation` 正反+无年份+
    键格式四向覆盖）
  - ⚙ **名称缓存（`_tmdb_name_to_id`）命中后必须过集数容量校验**：它是
    `VideoRenamer` 类属性（进程级共享），key 里虽有年份，但同一年份下同名的
    不同条目仍然存在——
    同名不同条目会互相污染。线上实例：《大主宰》TMDB 双条目（2019 年
    id=102008 仅 12 集 Ended / 2023 年番 id=226045 共 104 集 Returning），
    缓存被 102008 污染后 `大主宰（2023）/98 4K.mkv` 的 E98 直接链到 12 集条目，
    目录年份 2023 还被首播年份 2019 覆盖。现在缓存来源的 id 用
    `_entry_can_hold_episode()` 判容量（集号硬约束，同
    `_filter_candidates_by_episode_capacity` 语义），装不下 → 判缓存污染、
    `pop` 该缓存项 + 清除 tmdb_id → 回落搜索重新裁决，识别成功后再把正确 id
    写回缓存（自愈）。容量未知不拦（在播剧 TMDB 常只收录少量集）；文件名硬
    标记 `[tmdbid=…]` 是用户显式锁定，不做此校验
    （`TestNameCacheEpisodeCapacity` 覆盖）
  - ⚙ **网页兜底不得伪装浏览器 UA**（`tmdb_client.TMDB_WEB_USER_AGENTS`）：
    www.themoviedb.org 在 Cloudflare 后面且开了浏览器完整性校验（BIC）——UA 写
    `Chrome/120.0.0.0` 但 TLS 指纹不是 Chrome（urllib/requests 必然如此）会被丢到
    JS 挑战页，返回 `403 Just a moment...`（与 IP、登录态无关，带 preferences
    cookie 也没用；`Mozilla/5.0 (compatible; …)` 同样被拦）。实测非浏览器 UA
    （`video-organizer/1.0 (+url)` / `curl/8.5.0`）返回 200 + 正常结果卡，故按
    候选列表逐个试，403/429 换下一个 UA。**不要把这里改回浏览器 UA**
    （`TestWebFallbackUserAgent` 锁定）
  - ⚙ **分段短篇「Part N」**（`part_marker.py`）：剧场版拆段发行时 PT 命名是
    `X.分段名.Part.2.2026…`（`Grotesqqque.YOROSHIKU.Girl.Part.2.2026.NF…`），
    分段名不是 TMDB 条目、只有总条目（GROTESQQQUE 2026 / id=1313587）——
    ① 搜索：所有 API 策略 0 结果后，「备选策略1.7」按
    `segment_part_search_candidates()` 依次试「去掉 Part N」+「逐词丢尾部词」
    （`Grotesqqque YOROSHIKU Girl` → `Grotesqqque YOROSHIKU` → `Grotesqqque`），
    **只接受完全匹配+年份守卫**，且仅在搜索词带 `Part/Pt + 编号` 时触发
    （普通 0 结果标题不做尾部截断，防误配）；② 命名：`metadata["part"]` 由
    `extract_part_label()` 填充，`inject_part_suffix()` 把它插进命名模板的
    **文件名部分**（目录不动）→ `GROTESQQUE (2026) {tmdbid=1313587}/`
    `GROTESQQUE Part 2 1080p….mkv`；模板引用 `{part}`/`{part_suffix}` 时不自动插入，
    片名本身已含该标记（Mockingjay Part 1）时不重复；⚠️ 日番 TV 的 `Part N` 是
    分割期（cour）标记而非分段名（进击的巨人 Final Season Part 1/2/3、呪術廻戦
    渋谷事変 等），TMDB 常把同一 IP 按 Part 拆成多个独立 TV 条目，剥离会链错
    兄弟条目——策略搜索只在 `media_type_hint != "tv"` 且无 season/episode 证据时
    触发（`TestTvPartMarkerProtection` 双向覆盖），命名注入只对 movie/simple
    模板生效
    （`tests/unit/test_core/test_part_marker.py` 覆盖）
  - ⚙ **tmdbid 标记文件的跨类型回退必须验证标题相关性**（`_alt_title_related`）：
    文件名自带 `[tmdbid-318051]` 时直接按 ID 取详情（跳过搜索），当前类型 404
    时跨类型回退（tv→movie / movie→tv）。旧逻辑只验证「回退类型能否取到详情」
    不验证标题——错误/陈旧 id 会把毫不相干的条目硬塞进来（[tmdbid-318051]
    实为 2009 电影 Homero Manzi，与「寒蝉鸣泣之时·礼」无关，tv 404 后回退
    movie 把剧集识别成电影并改判 media_type）。现在回退前校验标题相关性
    （归一化后相同/包含/字符重叠 ≥ 0.5），无关 → 判坏 ID 清除，交由搜索路径
    （`TestTmdbIdCrossTypeFallback` 覆盖，双向回退 + 坏 ID 清除均测）
  - ⚙ 同一目录的多集（如 `剧名（2026）/01.mp4`、`02.mp4`）只调一次 LLM：
    `renamer._parse_filename_with_cache()` 按「父目录 + 原始剧名」缓存并做 single-flight
    并发合并（等待者不占并发槽）；纠正后的剧名会作为「搜索别名」写入
    `_tmdb_cache` / `_tmdb_name_to_id`，否则下一集仍按未纠正名查找而永远 miss
  - ⚙ **media_type 未知时兜底搜索照常发出**：`_search_with_language()` 在
    `media_type_hint` 为空时改走通用 `search_video_show`（早期版本直接
    `return []`）。cleaned_name / 父目录名 / 截断 / LLM 四个兜底全复用该方法，
    而它们恰恰最常发生在类型判不出来时（纯英文文件名 + 中文目录名，如
    `影视/西西里的美丽传说/Melina.2000.UNCUT...`），否则父目录名兜底与 LLM 兜底
    静默失效、识别必然失败；也让「同名多版本」能被父目录中文名纠正
    （`傲慢与偏见/Pride.And.Prejudice.2005` 由 1995 剧集改为 2005 电影 4348）
    （`test_renamer.py::TestUnknownMediaTypeParentDirFallback` 覆盖）
  - ⚙ **片名以年份样数字开头时年份取后一个**：`2001 A Space Odyssey 1968 USA
    BluRay Remux ...` 的首个 2001 属于片名本体（TMDB 收录名
    `2001: A Space Odyssey`），取 2001 会把标题砍成 `A Space Odyssey`/父目录的
    `太空漫游`，且所有搜索都带 year=2001 → 年份噪音过滤把整批候选判为噪音
    （`TestLeadingTitleYear` 覆盖；`2012.mkv` 这类只有一个年份的不受影响）
  - ⚙ **无有效扩展名的条目不识别**：后缀不是「`.` + 字母数字」时
    （139 秒传/网盘清单里的 0 字节说明文本或目录名，如
    `影视/双子杀手/1.本片可做为设备测试片使用`——注意 `Path().suffix` 会把整个
    中文串当后缀，看似「有后缀」）直接返回 `{}`，否则会被 L2 当集号、
    误配成父目录电影的第 1/2 集（`TestNonVideoEntrySkipped` 覆盖）
  - ⚙ **文件名只有年份时父目录剧名必须覆盖伪剧名**：`八仙！/2026.2160p.60fps.
    HQ.WEB-DL.H265…iso` 的正则抽出的 show_name 是纯数字 `2026`，
    `is_invalid_name` 会正确触发父目录查找，但填值时只对
    `is_fragment / is_season_episode_only` 强制覆盖、漏了 `is_invalid_name`，
    于是 show_name 留着 `2026` → 拿年份当片名搜 TMDB（96 条同名结果）→
    误配成一部叫「2026」的剧（id=327781）。现在 `is_invalid_name` 一并强制
    覆盖，用父目录 `八仙！` 搜到 movie 1633056；分类目录（`电影`/`Movies`/
    `剧集`）已由 `_is_garbage_show_candidate` 判垃圾，不会顶掉 `1917`/`2012`
    这类叫年份的真片名（`TestBareYearShowNameParentFallback` 正反覆盖）
  - ⚙ **父目录兜底禁止拿垃圾目录当剧名**（ACG 秒传高发）：
    - 季节目录带修饰词（`第一季 蓝光原盘REMUX 内封…字幕 年糕`、`S01 4K`、
      `Season 2 2025`）不是剧名，`_is_garbage_show_candidate` 对
      `^(第[一二三四五六七八九十百千\d]+季|SEASON\s*\d+|S\d{1,2}(?:E\d+)?)`
      开头的目录一律判垃圾；否则会被当 show_name 填进 metadata，主搜索
      拿「第一季」类词汇导出 90 条任意剧按人气误配（实测胆大党→土豆逗严肃
      科普/魔法使莎莉，`TestJunkParentDirNotUsedAsShowName` 覆盖）
    - 目录名末尾的冗余词「系列」剥离后再用（`胆大党系列`→`胆大党`，TMDB
      搜「胆大党系列」命中率为 0；`进击的巨人系列`→`进击的巨人`）
    - `番剧/新番/日漫/国漫/美漫/港漫` 补进分类词表（fragment_keywords +
      garbage 判定）：无剧名的英文文件名（正则收不出 show_name）向上兜底到
      分类层后会拿「番剧」当搜索词，返回热门电影随手误配（实测辉夜姬物语被
      配成 The Jogger / 名侦探柯南）
    - 截断搜索词不允许截成纯季节词（`第一季`/`S01`/`Season 1`），与
      「不做数字季号截断」配套
  - ⚙ **电影目录硬规则让位于显式剧集证据**：`_tv_candidate_inadmissible`
    此前对路径含「电影/Movies」目录段的文件**无条件剔除 tv 候选**（电影目录
    即电影语义），但用户可能把剧集放进「电影/H/」等首字母分类目录
    （`影视库/电影/H/黑礁 Black Lagoon (2006)/Season 1/黑礁.Black.Lagoon.
    S01E04.2006…mkv`）——S01E04 是比目录语义更强的 tv 证据，旧逻辑把
    主搜索 tv 候选剔空导致识别失败。现在先过 `_tv_candidate_admissible`
    （SxxExx/第N集/Season 标记、Season 1/第X季 布局目录），有剧集证据才
    放行；无证据仍按「电影目录 = 电影语义」排除（宁失败不误配）
    （`TestMovieDirAllowsExplicitTvEvidence` 正反两向覆盖）
  - ⚙ **「中文剧名.数字」点分形态提取集号**（`遮天.186.4K.mkv`、
    `火影忍者.115[www.xxx].mkv.iso`）：国产剧/国漫常用「剧名.集号」命名，
    旧逻辑把点分数字混进 show_name（`遮天 186`）且 cleaned_name 又把数字剥掉
    → media_type 落回 movie，搜「遮天 186」失败后兜底搜「遮天」电影池错配成
    「遮蔽的天空」(1990)。`_extract_with_regex` 在正则链前基于原始文件名
    提取集号（`^中文\.(\d{2,10})(?![0-9pPkK])`），安全约束：1 位数字不提取
    （电影续集号 `复仇者联盟.2.2015`）、4 位年份形状（1850-2035）不提取
    （`让子弹飞.2010`）、后随 p/P/k/K 分辨率不提取（`特工迷阵.1080p`）；
    年份范围外的 4 位数仍是集号（`海贼王.1045`）
    （`TestChineseTitleDotNumberEpisode` 覆盖；顺带修好火影 220 条
    `.mkv.iso` 镜像被误配成剧场版的问题）
  - LLM 只贡献剧名级信息（show_name / tmdb_corrected_title / year / media_type），
    episode/season 一律由文件名解析决定，不取 LLM 的猜测
- **LLM Provider 配置** (`[llm_provider_N]`):
  - `api_url`, `api_key`, `model`, `name` — 基本连接参数；
    ⚙ `api_key` 可空：内网/网关类 Provider（如 139 云盘）常不校验 token，
    空 key 时 `_call_api` 自动省略 Authorization 头，`_init_providers` 与
    `LLMProvider.__post_init__` 均不再因空 key 过滤/禁用 Provider
  - `max_tokens` — 最大输出 token（默认 4096，推理模型需更大预算）
  - `max_tokens_cap` — 截断时自动翻倍上限（默认 16384）
  - `timeout`, `max_retries`, `weight`, `enabled` — 控制参数
  - 策略默认 `round_robin`，由代码传入 `llm_config["strategy"]`，config.ini 暂无该键

## 代码约定

- 使用 `pathlib.Path`，禁用字符串路径
- 使用 `from typing import Dict, List, Optional, Union`
- 绝对导入: `from src.video_organizer.core.renamer import VideoRenamer`
- 异常用 `try/except` + 日志 `logger = logging.getLogger(__name__)`
- 文档和注释使用中文
- ⚠️ 控制台输出中文在 Windows 下易乱码，脚本内读文件显式 `encoding="utf-8"`

## Docker

- 正式镜像: `Dockerfile` — 无 ENTRYPOINT，`CMD ["python","run_organizer.py","--web",
  "--web-host","0.0.0.0","--web-port","8080"]`（监控 + Web），带 `/api/health` healthcheck，
  非 root `appuser` 运行，`config_template.ini` 拷为 `/app/config.ini`
- 轻量镜像: `Dockerfile.run` — 默认 `python run_organizer.py`，无 healthcheck；
  ⚙ **基础镜像是 `python:3.12-slim` 多阶段（不是 alpine）**：alpine 是 musl，依赖无预编译
  wheel 就得现场编译，必须先 `apk add build-base gcc`，国内源上 600s+；slim 直接吃
  manylinux wheel。`COPY` 只拿 `src/` + `run_organizer.py` + `config_template.ini`，
  pip 层用 `RUN --mount=type=cache,target=/root/.cache/pip`（需 BuildKit），
  支持 `build.args` 的 `APT_MIRROR` / `PIP_INDEX` 与预定义代理参数 `HTTP_PROXY`/`HTTPS_PROXY`
- 遗留镜像: `Dockerfile.legacy`
- `docker-compose.yml` 三个 service: `video-organizer`、`video-organizer-web-only`
  （需 `--profile web-only`，命令覆盖为 `--web-only`）、`video-organizer-dev`（同样只挂
  `./src`，改完代码 `restart`；⚠️ 没用 `--web-reload`：`uvicorn.run(app, reload=True)`
  传的是 app 对象而不是 import string，reload 子进程会跑不起来，`--web-only` 分支同此限制）
- ⚙ **改代码不用重建镜像**：绑挂 `./src:/app/src`（**不要加 `:ro`**，数据库在
  `src/video_organizer/data/video_organizer.db` 要写），改完 `docker compose restart` 即可；
  只有 `requirements.txt` / Dockerfile 变了才 `docker compose build`
- 配置挂载在 `./data/config.ini:/app/config.ini`；线上机器另有 `docker-compose.yml.tmp`
  （Dockerfile.run + `./src` 挂载 + 构建代理），`.dockerignore` 必须继续排除
  `logs/ data/ strm/ build/ dist/ .git/`（历史上 logs/ 就有 292MB，直接拖慢上下文）

## 已知问题

1. **`pytest` 收集失败（阻塞全量测试）**
   `tests/integration/test_integration.py:14` 仍 `from src.video_organizer.core.video_file_handler
   import VideoFileHandler`，该模块已迁移到 `core/file_handler/handler.py` → ImportError，
   整个测试会话被中断。临时绕过：`--ignore=tests/integration/test_integration.py`。
2. **`tests/` 根目录下的旧测试与当前 API 不匹配（12 failed）**
   - `tests/test_tmdb_client.py`（8 个）— `TMDBClient.__init__()` 已无 `language` 参数
   - `tests/test_config_loader.py`（2 个）— `config_to_dict` 不再输出 `monitored_dir` 键
   - `tests/test_renamer.py::test_extract_movie_pattern` — `original_filename` 现在返回完整路径
   - 与 `tests/unit/test_core/` 下的同名新测试重复，需要决定删除还是修
3. **`tests/unit/test_core/test_manual_rule_engine.py::TestManualRuleEngine::test_locked_fields_union` 失败**
   原因：`get_locked_fields()` 依赖 `apply()` 被调用后累积结果，而测试直接构造引擎后查询，
   从未调用 `apply()`，导致返回空集合。这是测试与实现语义分歧，需要决定改实现
   （静态推导 lock_fields）还是改测试。
4. `black` / `mypy` / `flake8` 均无干净基线（见上），仓库无 CI 门禁；
   `.github/workflows/build.yml` 只做打包构建。

## 调试

### 启动测试服务器（避免卡住）
```powershell
$p = Start-Process -WindowStyle Hidden -PassThru -FilePath "python" -ArgumentList "-m", "src.video_organizer.main", "--web-only", "--web-port", "8095"; Write-Output $p.Id
```

### 停止测试服务器
```powershell
Get-Process -Id (Get-NetTCPConnection -LocalPort 8095 -ErrorAction SilentlyContinue).OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force
```

### 查看日志
```powershell
python -c "import sys; sys.path.insert(0,'src'); from pathlib import Path; p=Path('logs'); [print(f.read_text(encoding='utf-8')[:2000]) for f in sorted(p.glob('*.log'))[-3:]]"
```

## Web API 快速参考

- Web 服务默认 `0.0.0.0:8080`（`--web-port` / `--web-host` 可改）
- 认证两种方式：
  - `POST /api/auth/login` → `access_token`，后续 `Authorization: Bearer <token>`
    （Bearer 校验失败时还会回退尝试把它当 API Key）
  - `X-API-Key: <key>`（`/api/apikeys` 增删改查，哈希存库）
- 免认证路径前缀（`web/auth.py: PUBLIC_PATHS`）: `/api/auth/`、`/static/`、
  `/api/health`、`/api/tasks/ws/`、`/api/logs/ws/`
- `POST /api/manual/validate` — 文件名识别验证（传 `{"file_path": "..."}`），
  详见 `docs/api-manual-validate.md`
- `GET /api/auth/first-run-credentials` — 首次运行随机密码
- 其他路由前缀: `/api/config`、`/api/tasks`、`/api/logs`、`/api/manual`、
  `/api/downloaders`、`/api/organize/{provider}/status|files|count|run|cancel|progress`；
  STRM 代理路由无 `/api` 前缀
- 回收站清理: `GET /api/recycle/status`、`GET /api/recycle/{provider}/stats`、
  `POST /api/recycle/{provider}/run`（body `{"dry_run": bool}`）；前端入口在「网盘整理」页底部卡片，
  配置项在「配置管理 → 回收站清理」
- WebSocket: `/api/tasks/ws/progress`, `/api/tasks/ws/dashboard`, `/api/logs/ws/{filename}`

## 其他文档

- `docs/API.md`、`docs/developer_guide.md`、`docs/usage_guide.md`
- `README.md`（功能说明）、`DOCKER.md` / `DOCKER_QUICKSTART.md`、`BUILD.md`
- ⚠️ `CLAUDE.md` / `IFLOW.md` / `QWEN.md` 是同类 agent 说明书的历史副本，内容已过时；
  改架构说明时以本文件为准并同步它们，或先确认是否可删
