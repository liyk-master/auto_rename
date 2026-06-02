# AGENTS.md

## Build/Lint/Test Commands

- **Run all tests:** `pytest` or `python run_tests.py`
- **Run single test file:** `pytest tests/test_renamer.py`
- **Run single test:** `pytest tests/test_renamer.py::TestVideoRenamer::test_extract_metadata_basic`
- **Format code:** `black .`
- **Type checking:** `mypy src/`
- **Linting:** `flake8 src/`

## Code Style Guidelines

- Use type hints from `typing` module (Dict, List, Optional, Union)
- Add docstrings to all public functions/methods
- Use `pathlib.Path` for file paths, not string paths
- Use `logger = logging.getLogger(__name__)` for logging
- Handle exceptions with try/except and proper error messages
- Organize imports: stdlib first, then third-party, then project imports
- Use PascalCase for classes, snake_case for functions/variables
- Use absolute imports from package root (e.g., `from src.video_organizer.core.renamer import VideoRenamer`)

## 语言规范
- 所有对话和文档都使用中文
- 文档使用 markdown 格式

## 调试

### 启动测试服务器（避免卡住）
```powershell
# 正确方式：使用 -WindowStyle Hidden，不要用 -NoNewWindow
$p = Start-Process -WindowStyle Hidden -PassThru -FilePath "python" -ArgumentList "-m", "src.video_organizer.main", "--web-only", "--web-port", "8095"; Write-Output $p.Id
```

### 停止测试服务器
```powershell
Get-Process -Id (Get-NetTCPConnection -LocalPort 8095 -ErrorAction SilentlyContinue).OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force
```

### 查看日志
```powershell
python -c "import sys; sys.path.insert(0,'src'); from pathlib import Path; p=Path('logs'); [print(f.read_text()[:2000]) for f in sorted(p.glob('*.log'))[-3:]]"
