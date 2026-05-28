# Project knowledge

This file gives Codebuff context about your project: goals, commands, conventions, and gotchas.

## Quickstart
- **Install:** `pip install -r requirements.txt`
- **Dev install:** `pip install -e .`
- **Run:** `python run_organizer.py` or `python -m video_organizer`
- **Run with web UI:** `python -m video_organizer --web`
- **Test (pytest):** `pytest` (runs from `pyproject.toml` config)
- **Test (unittest):** `python run_tests.py`
- **Single test (pytest):** `pytest tests/test_renamer.py::TestVideoRenamer::test_xxx -v`
- **Single test (unittest):** `python run_single_test.py` or `python run_one_test.py`
- **Type check:** `mypy src/`
- **Lint:** `flake8 src/`
- **Format:** `black .`
- **Build PyInstaller:** `pyinstaller --onefile --name video-organizer src/video_organizer/main.py`
- **Build Nuitka:** `python -m nuitka --standalone --onefile src/video_organizer/main.py`
- **Debug:** `python debug_test.py` / `python run_debug.bat` (Windows)
- **Verify LLM:** `python verify_llm.py`
- **Active branch:** `feature/llm-tmdb-fallback`

## Architecture

### Core Pipeline
`FileSystemMonitor` (orchestrator) → `VideoFileHandler` (per-file processor) → `VideoRenamer` (metadata extraction + TMDB lookup) → cloud upload

### Directory Layout
```
src/video_organizer/
├── main.py                # Entry point (argparse, init, dispatch)
├── __main__.py            # `python -m video_organizer` entry
├── core/                  # Core business logic
│   ├── filesystem_monitor.py  # Dir watching (polling + event), retry loop
│   ├── video_file_handler.py  # File processing orchestration, upload queue
│   ├── renamer.py             # Metadata extraction, TMDB search, naming rules
│   ├── config_loader.py       # INI config loading
│   ├── downloader_monitor.py  # Aria2/qBittorrent download monitoring
│   ├── tmdb_client.py         # TMDB API (JWT or API key, proxy support)
│   ├── guessit_parser.py      # Enhanced filename parsing via guessit lib
│   ├── manual_rule_engine.py  # User-defined manual rules engine
│   ├── file_mover.py          # File move/copy operations
│   ├── subtitle_handler.py    # Subtitle file handling
│   ├── emya_service.py        # Emya media library database service
│   ├── emya_api.py            # Emya API wrapper
│   ├── emya_models.py         # Emya data models (SQLAlchemy)
│   └── db_manager.py          # Database connection pool manager
├── upload/                # Cloud upload integrations
│   ├── upload_emos.py         # Emos cloud uploader
│   ├── upload_p123.py         # 123Pan uploader
│   ├── upload_cloud189.py     # 天翼云 uploader
│   ├── upload_yun139.py       # 139云 uploader
│   ├── p123_organizer.py      # 123Pan organization mode
│   ├── p123do.py              # 123Pan direct operations
│   ├── yun139.py              # 139 cloud operations
│   └── cloud189_upload.py     # 天翼云 operations
├── utils/                 # Utilities
│   ├── cli_parser.py          # Command-line argument parsing
│   ├── cli_output.py          # Console output formatting (colorama)
│   ├── logging_setup.py       # Logging configuration
│   ├── logging_utils.py       # Logging helper utilities
│   ├── config_loader.py       # Config loading (separate from core)
│   ├── path_manager.py        # Path mapping (Docker/host paths)
│   └── llm_translator.py      # LLM-based title translation (智谱/DeepSeek/OpenAI)
├── web/                   # FastAPI admin UI
│   ├── app.py                 # FastAPI app, uvicorn server
│   ├── routers/               # REST API routes: config, downloaders, logs, manual, tasks
│   ├── services/state.py      # StateManager singleton
│   └── static/                # Frontend: index.html, app.js
tests/
├── test_renamer.py            # Renamer unit tests
├── test_config_loader.py      # Config loader tests
├── test_emya_models.py        # Emya model tests
├── test_tmdb_client.py        # TMDB client tests
└── unit/test_core/            # Additional unit tests
```

### Config Sections (config.ini)
- `[monitoring]` — watch_dir, output_dir, polling, path_mappings, directory_monitor settings
- `[naming]` — Jinja2 format strings: tv_show_format, movie_format, anime_format, simple_format
- `[tmdb]` — api_key (JWT or API key), language, region, retry_count, timeout
- `[llm_fallback]` — LLM fallback enabled/max_concurrent
- `[llm_provider_1/2/3]` — Multiple providers (GLM, DeepSeek, OpenAI) with weighted round-robin
- `[guessit]` — enabled, prefer_guessit
- `[emos]` — auth_token, base_url, file_storage, chunk_size_mb
- `[emos_recognition]` — Emos recognition API (enabled, api_url, timeout, priority)
- `[processing]` — upload_targets (emos/p123/cloud189/yun139/both/all), delete_after_upload, max_upload_workers
- `[emya_db]` — Database for Emya media library (host, port, user, password, database)
- `[telegram]` — Bot notifications: bot_token, chat_id, channel_chat_id
- `[downloader.aria2]` / `[downloader.qbittorrent]` — Downloader monitors
- `[cloud189]` — 天翼云 credentials, family_id, strm_server
- `[yun139]` — 139云 authorization, cloud_type, parent_id, strm_server
- `[logging]` — log_level, log_file, console_log, file_log

## Conventions
- **Language:** All docs, code comments, and logs are in **Chinese**.
- **Imports:** stdlib → 3rd-party → project. Use `from video_organizer.core...` (not `src.` prefix) since `pythonpath = ["src"]` in pyproject.toml.
- **Paths:** Always use `pathlib.Path`, never raw strings for file paths.
- **Types:** Use `typing` module (Dict, List, Optional, Union, Set) for type hints.
- **Logging:** Use `logger = logging.getLogger(__name__)` via `logging_setup.py`.
- **Naming:** PascalCase classes, snake_case functions/variables, UPPER_CASE constants.
- **Error handling:** try/except with clear Chinese error messages; CLI output via `cli_output.py` (colorama-based).

## Key Design Details
- **Dual test systems:** Both `pytest` (via pyproject.toml) and `unittest` (via `python run_tests.py`) are supported. Root-level test files use `from src.video_organizer...` while ones under `tests/unit/` use relative-style imports.
- **Monitoring modes:** Polling-based (`use_polling = True`) or event-based (watchdog). Also supports `enable_directory_monitor` for scanning existing files.
- **Downloader integration:** Aria2 (polling/websocket/webhook modes) and qBittorrent via their respective APIs.
- **Path mapping:** Docker containers ↔ host path conversion via `path_mappings` config.
- **Upload targets:** Multiple cloud targets supported simultaneously (emos, p123, cloud189, yun139). Concurrent upload via `max_upload_workers`.
- **TMDB auth:** JWT Bearer tokens (start with `eyJ`) or regular API keys. Routes through proxy at `proxy1.liyk001.eu.org`. TMDBClient tracks `last_request_failed` and `last_request_error` state per request.
- **LLM fallback:** When TMDB/regex can't identify a file, multiple LLM providers (GLM/DeepSeek/OpenAI) can be used with weighted load balancing (round-robin) or failover mode.
- **LLM providers:** Configured via `[llm_provider_1/2/3]` sections with individual `api_url`, `api_key`, `model`, `enabled`, `weight`, `timeout`, `max_retries`.
- **Retry mechanism:** `FileSystemMonitor._retry_loop()` runs in a background thread every 60s. It retries:
  - `_pending_files` - files awaiting completion (e.g. still being written)
  - `_retry_files` - files that failed due to TMDB API errors or upload failures
  - Failed files are tracked in `VideoFileHandler._failed_files` dict with reason strings.
- **Compact filename detection:** `GuessItParser` handles "剧名+集号" compact formats like `入青云01.mp4` or `TonikakuKawaii08.mkv` without relying on LLM.
- **Manual rule engine:** `ManualRuleEngine` tracks `_last_locked_fields` so only fields locked by the last applied rule are returned, not all rules combined.
- **File stability check:** Files aren't processed until size stabilizes (checked 3 times at 1s intervals).

## Gotchas
- **Imports in tests:** `pythonpath = ["src"]` in `pyproject.toml` means pytest imports `from video_organizer.core...`. But `run_organizer.py` uses `sys.path.append("src")` so it imports `from src.video_organizer...`.
- **TMDB proxy:** All TMDB requests go through `proxy1.liyk001.eu.org` — if this proxy is down, TMDB lookups fail.
- **Config paths:** Default config is `config.ini` in project root. The `core/config_loader.py` creates a default if missing.
- **p123client:** Requires Python 3.12; commented out in requirements.txt for 3.9 compatibility.
- **Docker:** Three Dockerfiles: `Dockerfile.run` (Python 3.12 Alpine, direct run), `Dockerfile` (PyInstaller build in Alpine), `Dockerfile.legacy` (Ubuntu 18.04 build).
- **File stability check:** Files aren't processed until size stabilizes (checked 3 times at 1s intervals).
- **Naming variables:** Jinja2 templates use `{show_name}`, `{season}`, `{episode}`, `{episode_name}`, `{quality_tags}`, `{tmdbid=tmdbid}`, `{release_group_suffix}`, `{year}`.
- **Content type detection:** `VideoRenamer.DEFAULT_RELEASE_GROUP_MAPPING` maps fansub/release group names to content types (anime/drama/movie) to bias TMDB searches.
