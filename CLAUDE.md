# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application (monitor mode)
python -m video_organizer

# Run with web admin UI (--web flag)
python -m video_organizer --web

# Run all tests
pytest

# Run a single test file
pytest tests/unit/test_core/test_renamer.py -v

# Run tests with coverage
pytest --cov
```

## Architecture Overview

This is a video file auto-rename and organization tool. The entry point is `src/video_organizer/main.py` (`python -m video_organizer`). A legacy `main.py.tmp` exists at the root but is not the active entry point.

### Core Processing Pipeline

1. **`FileSystemMonitor`** (`core/filesystem_monitor.py`) — Orchestrator. Watches a directory (via polling or downloader API) and dispatches new files to `VideoFileHandler`.
2. **`DownloaderMonitor`** (`core/downloader_monitor.py`) — Abstract base with `Aria2Monitor` and `qBittorrentMonitor` implementations. Polls downloader APIs for completed downloads and fires a callback into `FileSystemMonitor`.
3. **`VideoFileHandler`** (`core/video_file_handler.py`) — Processes individual files: resolves path mappings, calls `VideoRenamer`, moves/copies files, triggers uploads.
4. **`VideoRenamer`** (`core/renamer.py`) — Extracts metadata from filenames using `GuessItParser` (guessit library) with regex fallback, queries `TMDBClient` to enrich with show/movie info, and generates the final output path using Jinja2 templates from naming rules.
5. **`TMDBClient`** (`core/tmdb_client.py`) — Wraps the TMDB API. Supports both JWT Bearer tokens (starts with `eyJ`) and regular API keys. Routes through a proxy at `proxy1.liyk001.eu.org`.

### Web Admin Backend

`web/app.py` creates a FastAPI app mounted at `/`. Routers under `web/routers/` expose REST APIs at `/api/*` for config management, task monitoring, logs, manual file processing, and downloader status. A `StateManager` singleton (`web/services/state.py`) holds shared references to the running `VideoFileHandler` and config.

When `--web` is passed, the main process starts both `FileSystemMonitor` (in a thread) and `uvicorn` (serving the FastAPI app).

### Upload Integrations

`upload/` contains uploaders for multiple cloud services: Emos, 123Pan (`p123`), 天翼云 (`cloud189`), and 139云 (`yun139`). Upload targets are configured via `processing.upload_targets` in config.

### Configuration

Config is an INI file at `src/video_organizer/data/config.ini`, loaded by `core/config_loader.py`. Key sections:
- `[monitoring]` — `watch_path`, `processed_path`, polling settings, `path_mappings` (maps downloader container paths to host paths)
- `[naming]` — Jinja2-style format strings for `tv_show_format`, `movie_format`, `anime_format`, `simple_format`
- `[api]` — `tmdb_api_key`, `ai_service_url` (LLM for translation)
- `[processing]` — `supported_extensions`, `upload_targets`, copy/delete behavior
- `[emos]`, `[p123]`, `[cloud189]`, `[yun139]` — Per-service upload credentials

### Content Type Detection

`VideoRenamer` has a `DEFAULT_RELEASE_GROUP_MAPPING` dict that maps known fansub/release group names to content types (`anime`, `drama`, `movie`). This is used to bias TMDB searches toward the correct content type when guessit cannot determine it from the filename alone.

### Test Layout

Tests live in `tests/unit/test_core/` and `tests/integration/`. `pythonpath = ["src"]` is set in `pyproject.toml` so imports use `from video_organizer.core...` (not `src.video_organizer...`). The `src/video_organizer/main.py` module itself uses relative imports; only root-level scripts use the `src.` prefix.


## 语言规范
- 所有对话和文档都使用中文
- 文档使用 markdown 格式