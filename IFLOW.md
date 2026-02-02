# Video Organizer - 项目上下文文档

## 项目概述

Video Organizer 是一个强大的视频文件自动重命名和组织工具，使用 Python 3.9+ 开发。该工具能够自动识别、重命名和组织视频文件，支持从 TMDB 获取元数据，智能分类电视剧、电影和动漫，并可根据用户自定义规则进行重命名和整理。

### 核心特性
- 🔄 自动监控文件夹，实时检测新视频文件
- 📚 智能分类电视剧、电影、动漫等类型
- 🌐 从 TMDB 获取准确的节目信息和剧集标题
- ✏️ 支持自定义命名规则
- 📁 自动组织文件到指定目录
- 🎛️ 友好的命令行界面
- 🔍 批量处理模式
- 🔧 支持下载器监控和任务清理
- ☁️ 支持 123 网盘整理功能

### 项目架构
```
src/
└── video_organizer/
    ├── main.py              # 主入口文件
    ├── core/                # 核心功能模块
    │   ├── config_loader.py      # 配置加载器
    │   ├── downloader_monitor.py # 下载器监控
    │   ├── file_mover.py         # 文件移动器
    │   ├── filesystem_monitor.py # 文件系统监控
    │   ├── renamer.py            # 重命名逻辑
    │   ├── tmdb_client.py        # TMDB API 客户端
    │   └── video_file_handler.py # 视频文件处理器
    ├── utils/               # 工具模块
    ├── upload/              # 上传相关模块
    └── data/                # 数据文件
```

## 技术栈

### 核心依赖
- **Python**: 3.9+ (推荐 3.12)
- **requests**: HTTP 请求库
- **watchdog**: 文件系统监控
- **configparser**: 配置文件解析
- **colorama**: 控制台输出颜色
- **jinja2**: 模板引擎
- **tqdm**: 进度条显示
- **httpx**: 现代化 HTTP 客户端
- **p123client**: 123 网盘 API (可选，需要 Python 3.12)

### 开发依赖
- **pytest**: 测试框架
- **pytest-cov**: 测试覆盖率
- **pyinstaller**: 打包工具
- **nuitka**: Python 编译器

### 构建工具
- **setuptools**: 包管理
- **wheel**: 分发格式

## 构建和运行

### 安装依赖
```bash
# 安装所有依赖
pip install -r requirements.txt

# 或使用 pip 安装（开发模式）
pip install -e .
```

### 运行方式

#### 1. 直接运行
```bash
# 使用 Python 运行主模块
python -m video_organizer

# 或使用入口点
video-organizer

# 或使用运行脚本
python run_organizer.py
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

#### 3. 命令行选项
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

# 123网盘整理模式
video-organizer --organize-p123 --organize-dry-run
```

### 测试
```bash
# 运行所有测试
python run_tests.py

# 或使用 pytest
pytest

# 运行特定测试
pytest tests/unit/test_config_loader.py

# 查看覆盖率
pytest --cov=src/video_organizer
```

### 打包

#### 使用 PyInstaller
```bash
# 打包为可执行文件
pyinstaller --onefile --name video-organizer src/video_organizer/main.py
```

#### 使用 Nuitka
```bash
# 编译为二进制文件
python -m nuitka --standalone --onefile src/video_organizer/main.py
```

## 配置文件

配置文件默认为 `config.ini`，首次运行时会自动创建。主要配置项：

```ini
[monitoring]
watch_dir = ""              # 监控目录
output_dir = ""             # 输出目录
supported_extensions = .mp4,.mkv,.avi,.wmv,.mov
poll_interval = 1           # 轮询间隔（秒）
use_polling = false         # 是否使用轮询模式
polling_interval = 5        # 轮询模式扫描间隔（秒）

[naming_rules]
tv_show = "{title} - S{season:02d}E{episode:02d} - {episode_title}"
movie = "{title} ({year})"
anime = "{title} - {episode}"
simple = "{title}"

[tmdb]
api_key = ""                # TMDB API 密钥
language = "zh-CN"
region = " "CN"
retry_count = 3
timeout = 30

[logging]
level = "INFO"
file = "video_organizer.log"
max_bytes = 10485760
backup_count = 5

[emos]
# Emos 相关配置

[p123]
token = ""
organize_source_id = 0
organize_target_id = 0
max_workers = 2

[telegram]
# Telegram 通知配置

[llm_translation]
# LLM 翻译配置
```

## 开发约定

### 代码风格
- 使用 Python 3.9+ 语法特性
- 遵循 PEP 8 代码风格指南
- 使用类型注解（Type Hints）
- 函数和类使用文档字符串（docstring）

### 项目结构约定
- 源代码位于 `src/video_organizer/` 目录
- 核心业务逻辑在 `core/` 子目录
- 工具函数在 `utils/` 子目录
- 测试代码位于 `tests/` 目录
- 单元测试在 `tests/unit/`
- 集成测试在 `tests/integration/`

### 命名规则
- 文件名使用小写字母和下划线：`video_file_handler.py`
- 类名使用大驼峰命名：`VideoFileHandler`
- 函数和变量使用小写字母和下划线：`force_process_file()`
- 常量使用大写字母和下划线：`MAX_RETRIES`

### 日志规范
- 使用项目统一的日志工具：`from .utils.logging_utils import get_logger`
- 日志级别：DEBUG（调试）、INFO（信息）、WARNING（警告）、ERROR（错误）
- 日志消息使用中文，描述清晰

### 错误处理
- 使用 try-except 捕获异常
- 对关键操作进行错误重试
- 提供详细的错误信息
- 使用 CLI 输出工具：`from .utils.cli_output import get_cli_output`

### 测试规范
- 测试文件命名：`test_*.py`
- 测试类命名：`Test*`
- 测试方法命名：`test_*`
- 使用 pytest 框架
- 保持测试独立性和可重复性

## 关键模块说明

### main.py
主入口文件，负责：
- 解析命令行参数
- 加载配置文件
- 初始化日志系统
- 启动文件系统监控器
- 处理强制文件处理模式
- 处理 123 网盘整理模式

### core/config_loader.py
配置加载器，负责：
- 从 INI 文件加载配置
- 验证配置有效性
- 提供默认配置
- 保存配置到文件

### core/filesystem_monitor.py
文件系统监控器，负责：
- 监控指定目录的文件变化
- 支持事件监听和轮询两种模式
- 触发文件处理回调

### core/video_file_handler.py
视频文件处理器，负责：
- 识别视频文件类型
- 从 TMDB 获取元数据
- 应用命名规则
- 移动和重命名文件
- 管理上传队列
- 清理下载器任务

### core/renamer.py
重命名逻辑，负责：
- 解析文件名模式
- 提取季数和集数
- 生成新文件名
- 处理特殊字符和路径

### core/tmdb_client.py
TMDB API 客户端，负责：
- 搜索电视剧和电影
- 获取详细信息
- 处理 API 错误和重试

### core/downloader_monitor.py
下载器监控器，负责：
- 监控下载器任务状态
- 检测下载完成
- 清理已完成的任务

## 常见任务

### 添加新的下载器支持
1. 在 `core/downloader_monitor.py` 中添加新的监控器类
2. 在 `DownloaderMonitorFactory` 中注册新类型
3. 在配置文件中添加下载器配置

### 修改命名规则
编辑 `config.ini` 中的 `[naming_rules]` 部分，支持以下变量：
- `{title}` - 标题
- `{season}` - 季数
- `{episode}` - 集数
- `{episode_title}` - 单集标题
- `{year}` - 年份

### 添加新的文件类型支持
修改 `config.ini` 中的 `supported_extensions` 配置项

### 调试问题
1. 设置日志级别为 DEBUG：`--log-level DEBUG`
2. 查看日志文件：`video_organizer.log`
3. 使用 `--show-config` 查看当前配置
4. 使用 `--process` 测试单个文件处理

## Docker 部署

项目支持 Docker 容器化部署，相关文件：
- `Dockerfile.run` - 直接运行模式的 Dockerfile
- `Dockerfile` - 构建可执行文件的 Dockerfile
- `docker-compose.yml` - Docker Compose 配置

部署步骤：
1. 构建 Docker 镜像
2. 配置 `config.ini` 文件
3. 挂载必要目录（视频目录、配置文件、日志目录）
4. 运行容器

## 版本信息

- **当前版本**: 1.0.0
- **Python 要求**: 3.9+
- **许可证**: MIT

## 相关文档

- `README.md` - 用户使用指南
- `BUILD.md` - 构建和部署文档
- `docs/developer_guide.md` - 开发者指南
- `docs/usage_guide.md` - 使用指南