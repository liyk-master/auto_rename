# Video Organizer - 项目上下文文档

## 项目概述

**Video Organizer** 是一个强大的 Python 视频文件自动重命名和组织工具。它能够自动识别、重命名和组织视频文件，支持从 TMDB/Emos 获取元数据，智能分类电视剧、电影和动漫，并根据用户自定义规则进行重命名和整理。

### 核心功能

- 🔄 **自动监控文件夹** - 实时检测新添加的视频文件（支持事件监听和轮询两种模式）
- 📚 **智能分类** - 自动识别电视剧、电影、动漫等类型
- 🌐 **元数据获取** - 从 TMDB、Emos API 获取节目信息和剧集标题
- 🧠 **LLM 翻译支持** - 支持使用智谱 AI 进行标题翻译
- 🎯 **GuessIt 增强识别** - 专业文件名解析库，提高识别准确率
- ✏️ **自定义命名规则** - 灵活的 Jinja2 模板配置文件命名格式
- 📁 **自动组织** - 根据类型和系列将文件移动到指定目录
- ☁️ **多云盘支持** - EMOS、123 网盘、天翼云盘、中国移动云盘 (139 云盘)
- 📥 **下载器监控** - 支持 qBittorrent 等下载器，自动清理已完成任务
- 🌐 **Web 管理后台** - FastAPI + Uvicorn 提供的 Web 界面
- 📺 **Emya 数据库集成** - 支持视频入库到 Emya 媒体库
- 📱 **Telegram 通知** - 上传进度推送

## 项目结构

```
auto_rename/
├── src/video_organizer/          # 主源代码目录
│   ├── main.py                   # 主入口文件
│   ├── __main__.py               # 模块运行入口
│   ├── core/                     # 核心业务逻辑
│   │   ├── config_loader.py      # 配置加载器
│   │   ├── filesystem_monitor.py # 文件系统监控器
│   │   ├── video_file_handler.py # 视频文件处理器
│   │   ├── renamer.py            # 重命名逻辑
│   │   ├── tmdb_client.py        # TMDB API 客户端
│   │   ├── emya_service.py       # Emya 数据库服务
│   │   ├── emya_api.py           # Emya API 封装
│   │   ├── emya_models.py        # Emya 数据模型
│   │   ├── db_manager.py         # 数据库管理器
│   │   ├── downloader_monitor.py # 下载器监控器
│   │   ├── file_mover.py         # 文件移动器
│   │   ├── guessit_parser.py     # GuessIt 解析器
│   │   └── subtitle_handler.py   # 字幕处理器
│   ├── utils/                    # 工具模块
│   │   ├── cli_parser.py         # 命令行参数解析
│   │   ├── cli_output.py         # 命令行输出工具
│   │   ├── logging_utils.py      # 日志工具
│   │   ├── logging_setup.py      # 日志设置
│   │   ├── path_manager.py       # 路径管理器
│   │   └── llm_translator.py     # LLM 翻译工具
│   ├── upload/                   # 上传相关模块
│   │   ├── p123_organizer.py     # 123 网盘整理
│   │   ├── cloud189_uploader.py  # 天翼云盘上传
│   │   └── yun139_uploader.py    # 139 云盘上传
│   ├── web/                      # Web 服务
│   │   ├── app.py                # FastAPI 应用
│   │   ├── routers/              # API 路由
│   │   ├── services/             # Web 服务
│   │   └── static/               # 静态资源
│   └── data/                     # 数据文件
├── tests/                        # 测试代码
│   ├── unit/                     # 单元测试
│   └── integration/              # 集成测试
├── config_template.ini           # 配置文件模板
├── requirements.txt              # 依赖列表
├── pyproject.toml                # 项目配置 (pytest)
├── setup.py                      # 安装脚本
├── docker-compose.yml            # Docker Compose 配置
├── Dockerfile.run                # 运行模式 Dockerfile
└── run_organizer.py              # 运行脚本
```

## 技术栈

### 核心依赖
| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | 3.9+ | 运行环境 |
| requests | >=2.28.0 | HTTP 请求 |
| watchdog | >=3.0.0 | 文件系统监控 |
| configparser | >=5.3.0 | 配置文件解析 |
| colorama | >=0.4.6 | 控制台颜色输出 |
| jinja2 | >=3.0.0 | 模板引擎 |
| tqdm | >=4.60.0 | 进度条 |
| guessit | >=3.8.0 | 视频文件名识别 |
| httpx | >=0.24.0 | 现代化 HTTP 客户端 |

### Web 服务依赖
| 依赖 | 版本 | 用途 |
|------|------|------|
| fastapi | >=0.100.0 | Web 框架 |
| uvicorn | >=0.23.0 | ASGI 服务器 |

### 数据库依赖
| 依赖 | 版本 | 用途 |
|------|------|------|
| SQLAlchemy | >=2.0.0 | ORM 框架 |
| PyMySQL | >=1.1.0 | MySQL 驱动 |

### 开发/打包依赖
| 依赖 | 版本 | 用途 |
|------|------|------|
| pytest | >=7.0.0 | 测试框架 |
| pytest-cov | >=4.0.0 | 测试覆盖率 |
| pyinstaller | >=5.0.0 | 打包工具 |
| nuitka | >=1.0.0 | Python 编译器 |
| setuptools | >=60.0.0 | 包管理 |

## 构建和运行

### 安装依赖

```bash
# 安装所有依赖
pip install -r requirements.txt

# 开发模式安装（可编辑）
pip install -e .
```

### 运行方式

#### 1. 直接运行（开发模式）
```bash
# 使用 Python 模块运行
python -m video_organizer

# 使用运行脚本
python run_organizer.py

# 使用入口点（安装后）
video-organizer
```

#### 2. Docker 运行
```bash
# 使用 Docker Compose
docker-compose up -d

# 查看日志
docker-compose logs -f video-organizer

# 停止
docker-compose down
```

#### 3. 构建可执行文件
```bash
# 使用 PyInstaller
pyinstaller --onefile --name video-organizer src/video_organizer/main.py

# 使用 Nuitka
python -m nuitka --standalone --onefile src/video_organizer/main.py
```

### 命令行选项

```bash
# 显示帮助
video-organizer --help

# 显示版本
video-organizer --version

# 指定配置文件
video-organizer --config custom_config.ini

# 自定义监控目录
video-organizer --watch-dir "D:\Downloads" --output-dir "D:\Videos"

# 强制处理指定文件
video-organizer --process "D:\Downloads\video.mp4"

# 显示当前配置
video-organizer --show-config

# 设置日志级别
video-organizer --log-level DEBUG

# 使用轮询模式
video-organizer --use-polling --polling-interval 5

# 123 网盘整理模式
video-organizer --organize-p123 --organize-dry-run

# 仅启动 Web 管理后台
video-organizer --web-only --web-host 0.0.0.0 --web-port 8080

# 同时启动监控和 Web 服务
video-organizer --web
```

### 测试

```bash
# 运行所有测试
python run_tests.py

# 或使用 pytest
pytest

# 运行特定测试文件
pytest tests/test_renamer.py

# 运行特定测试
pytest tests/test_renamer.py::TestVideoRenamer::test_extract_metadata_basic

# 查看测试覆盖率
pytest --cov=src/video_organizer

# 详细输出
pytest -v
```

### 代码质量检查

```bash
# 格式化代码
black .

# 类型检查
mypy src/

# Linting
flake8 src/
```

## 配置文件

配置文件默认为 `config.ini`，首次运行时会自动创建。主要配置段落：

### [monitoring] - 监控配置
```ini
[monitoring]
watch_dir = ""                    # 监控目录
output_dir = ""                   # 输出目录
supported_extensions = .mp4,.mkv,.avi,.mov,.wmv,.flv
poll_interval = 1                 # 轮询间隔（秒）
use_polling = false               # 是否使用轮询模式
polling_interval = 5              # 轮询模式扫描间隔（秒）
path_mappings =                   # 路径映射（下载器路径 -> 主机路径）
```

### [naming] - 命名规则
```ini
[naming]
tv_show_format = {show_name} ({year}) {tmdbid=tmdbid}/Season {season:02d}/{show_name} {season_episode} {quality_tags}
movie_format = Movies/{show_name} ({year}) {tmdbid=tmdbid}/{show_name} {quality_tags}
anime_format = Anime/{show_name}/{show_name} - {episode:02d}
simple_format = {title}
```

### [tmdb] - TMDB API 配置
```ini
[tmdb]
api_key = ""                      # TMDB API 密钥
language = zh-CN
region = CN
retry_count = 3
timeout = 30
```

### [llm_translation] - LLM 翻译配置
```ini
[llm_translation]
api_url = https://open.bigmodel.cn/api/paas/v4/chat/completions
api_key = ""
model = GLM-4.5-Flash
enabled = False
```

### [guessit] - GuessIt 增强识别
```ini
[guessit]
enabled = True                    # 是否启用 GuessIt
prefer_guessit = False            # 是否优先使用 GuessIt 结果
```

### [processing] - 处理配置
```ini
[processing]
upload_targets = emos             # 上传目标：emos, p123, cloud189, yun139
delete_after_upload = True
max_upload_workers = 3            # 并发上传线程数
```

### [downloader.*] - 下载器配置
```ini
[downloader.qbittorrent]
type = qbittorrent
rpc_url = http://192.168.1.16:8091/api/v2
username = admin
password = 123456
```

### [emya_db] - Emya 数据库配置
```ini
[emya_db]
enabled = False
host = localhost
port = 3306
user = root
password = ""
database = emya
default_user_id = 1
default_tv_library = 电视剧
default_movie_library = 电影
```

## 开发约定

### 代码风格
- 遵循 PEP 8 代码风格指南
- 使用 Python 3.9+ 语法特性
- 使用类型注解（`typing` 模块：`Dict`, `List`, `Optional`, `Union`）
- 所有公共函数/方法添加文档字符串（docstring）
- 使用 `pathlib.Path` 处理文件路径，而非字符串
- 使用 `logger = logging.getLogger(__name__)` 进行日志记录
- 异常处理使用 try-except，提供清晰的错误信息

### 命名规则
- **文件名**: 小写字母 + 下划线，如 `video_file_handler.py`
- **类名**: 大驼峰命名 (PascalCase)，如 `VideoFileHandler`
- **函数/变量**: 小写字母 + 下划线 (snake_case)，如 `force_process_file()`
- **常量**: 大写字母 + 下划线，如 `MAX_RETRIES`

### 导入顺序
1. 标准库导入
2. 第三方库导入
3. 项目内部导入（使用绝对导入）

```python
# 示例
import os
import logging
from typing import Dict, List, Optional

import requests
from pathlib import Path

from src.video_organizer.core.renamer import VideoRenamer
from src.video_organizer.utils.logging_utils import get_logger
```

### 日志规范
- 使用项目统一日志工具：`from .utils.logging_utils import get_logger`
- 日志级别：DEBUG（调试）、INFO（信息）、WARNING（警告）、ERROR（错误）
- 日志消息使用中文，描述清晰

### 测试规范
- 测试文件命名：`test_*.py`
- 测试类命名：`Test*`
- 测试方法命名：`test_*`
- 使用 pytest 框架
- 保持测试独立性和可重复性

## 关键模块说明

### main.py - 主入口
- 解析命令行参数
- 加载配置文件
- 初始化日志系统
- 启动文件系统监控器
- 处理特殊模式（文件处理、网盘整理、Web 服务）

### core/config_loader.py - 配置加载器
- 从 INI 文件加载配置
- 验证配置有效性
- 提供默认配置
- 保存配置到文件

### core/filesystem_monitor.py - 文件系统监控器
- 监控指定目录的文件变化
- 支持事件监听和轮询两种模式
- 触发文件处理回调
- 管理下载器监控器

### core/video_file_handler.py - 视频文件处理器
- 识别视频文件类型
- 从 TMDB/Emos 获取元数据
- 应用命名规则
- 移动和重命名文件
- 管理上传队列
- 清理下载器任务

### core/renamer.py - 重命名逻辑
- 解析文件名模式
- 提取季数和集数
- 生成新文件名
- 处理特殊字符和路径

### core/tmdb_client.py - TMDB API 客户端
- 搜索电视剧和电影
- 获取详细信息
- 处理 API 错误和重试

### core/downloader_monitor.py - 下载器监控器
- 监控下载器任务状态
- 检测下载完成
- 清理已完成的任务
- 支持多种下载器类型（qBittorrent 等）

### utils/path_manager.py - 路径管理器
- 处理路径映射
- 统一路径转换逻辑

### web/app.py - Web 应用
- FastAPI 应用入口
- 提供 REST API
- 管理后台界面

## 常见任务

### 添加新的下载器支持
1. 在 `core/downloader_monitor.py` 中添加新的监控器类
2. 在 `DownloaderMonitorFactory` 中注册新类型
3. 在配置文件中添加下载器配置

### 修改命名规则
编辑 `config.ini` 中的 `[naming]` 部分，支持以下变量：
- `{title}` / `{show_name}` / `{movie_name}` - 标题
- `{season}` - 季数
- `{episode}` - 集数
- `{episode_name}` / `{episode_title}` - 单集标题
- `{year}` / `{year_suffix}` - 年份
- `{quality_tags}` - 质量标签
- `{release_group_suffix}` - 发布组后缀
- `{tmdbid=tmdbid}` - TMDB ID

### 添加新的云盘支持
1. 在 `upload/` 目录创建新的上传器模块
2. 在 `core/video_file_handler.py` 中集成
3. 在配置文件中添加对应配置段落

### 调试问题
1. 设置日志级别为 DEBUG：`--log-level DEBUG`
2. 查看日志文件：`video_organizer.log`
3. 使用 `--show-config` 查看当前配置
4. 使用 `--process` 测试单个文件处理

## Docker 部署

### 构建镜像
```bash
docker build -f Dockerfile.run -t video-organizer .
```

### 运行容器
```bash
docker run -d \
  --name video-organizer \
  -v /path/to/your/videos:/app/videos \
  -v $(pwd)/config.ini:/app/config.ini:ro \
  video-organizer
```

### 挂载目录说明
```bash
# 视频目录 - 必填
-v /your/video/path:/app/videos

# 配置文件 - 可选
-v $(pwd)/config.ini:/app/config.ini:ro

# 日志目录 - 可选
-v $(pwd)/logs:/app/logs
```

## 版本信息

- **当前版本**: 1.0.0
- **Python 要求**: 3.9+
- **许可证**: MIT

## 相关文档

- `README.md` - 用户使用指南
- `BUILD.md` - 构建和部署文档
- `IFLOW.md` - 项目上下文和架构文档
- `AGENTS.md` - AI 助手开发指南
- `DIRECTORY_MONITOR_GUIDE.md` - 目录监控指南
