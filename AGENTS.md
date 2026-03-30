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
