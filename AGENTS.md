# AGENTS.md

## 构建/测试/格式化

- **运行全部测试:** `pytest`
- **运行单个测试文件:** `pytest tests/test_renamer.py`
- **运行单个测试:** `pytest tests/test_renamer.py::TestVideoRenamer::test_extract_metadata_basic`
- **格式化:** `black .`
- **类型检查:** `mypy src/`
- **Lint:** `flake8 src/`
- `pyproject.toml` 已配置 `pythonpath = ["src"]`，测试会自动识别包路径

## 项目结构要点

- **入口:**
  - 主入口: `src/video_organizer/main.py` — `main()`
  - 包运行: `python -m src.video_organizer.main [--web/--web-only/--process]`
  - CLI 启动器: `run_organizer.py` — 无参数时自动追加 `--web`（同时启动监控 + Web）
- **核心模块** (`src/video_organizer/core/`):
  - `renamer.py` — 文件识别/重命名核心
  - `config_loader.py` — 配置加载/保存/验证（支持 frozen 打包环境路径）
  - `video_file_handler.py` — 文件处理主循环
  - `filesystem_monitor.py` — 目录/下载器监控
  - `tmdb_client.py` — TMDB API 客户端
  - `manual_rule_engine.py` — 手动规则 DSL 引擎
  - `guessit_parser.py` — GuessIt 集成 + 中文文件名预处理
- **Web 后端** (`web/`):
  - `app.py` — FastAPI 应用创建，`create_app()`
  - `auth.py` — HMAC-SHA256 令牌认证（非标准 JWT），服务重启所有 token 失效
  - `routers/` — `config.py`, `tasks.py`, `logs.py`, `manual.py`, `auth.py`, `downloaders.py`, `strm.py`
  - `services/state.py` — `StateManager` 单例
- **上传模块** (`upload/`): `yun139.py`/`upload_yun139.py`, `cloud189_upload.py`, `p123do.py`
- **数据库** (`database/`): SQLAlchemy，用于 emya 入库和 DB 配置
- **配置文件:** `config.ini`（实际）、`config_template.ini`（模板），首次运行自动生成
- **打包:** `build.sh` — PyInstaller 构建，spec 内嵌生成

## 代码约定

- 使用 `pathlib.Path`，禁用字符串路径
- 使用 `from typing import Dict, List, Optional, Union`
- 绝对导入: `from src.video_organizer.core.renamer import VideoRenamer`
- 异常用 `try/except` + 日志 `logger = logging.getLogger(__name__)`
- 文档和注释使用中文

## Docker

- 正式镜像: `Dockerfile`（ENTRYPOINT + CMD `--web-only`）
- 轻量镜像: `Dockerfile.run`（默认 `python run_organizer.py`，无 healthcheck）
- `docker-compose.yml` 有 `video-organizer` 和 `video-organizer-dev` 两个 service

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
python -c "import sys; sys.path.insert(0,'src'); from pathlib import Path; p=Path('logs'); [print(f.read_text()[:2000]) for f in sorted(p.glob('*.log'))[-3:]]"
```

## Web API 快速参考

- Web 服务默认 `0.0.0.0:8080`（`--web-port` 可改）
- 认证: `POST /api/auth/login` → `access_token`，后续 `Authorization: Bearer <token>`
- `POST /api/manual/validate` — 文件名识别验证（传 `{"file_path": "..."}`）
- `GET /api/auth/first-run-credentials` — 首次运行随机密码
- `/api/auth/`、`/static/`、`/api/health` 无需认证
- WebSocket: `/api/tasks/ws/progress`, `/api/tasks/ws/dashboard`, `/api/logs/ws/{filename}`
