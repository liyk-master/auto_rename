# 视频文件自动重命名和组织工具

![版本](https://img.shields.io/badge/version-1.0.0-blue.svg)
![Python版本](https://img.shields.io/badge/python-3.8%2B-green.svg)
![操作系统](https://img.shields.io/badge/OS-Windows%20%7C%20Linux%20%7C%20macOS-blue.svg)

一个强大的自动化工具，可以自动识别、重命名和组织您的视频文件。该工具支持从TMDB获取元数据，智能分类电视剧、电影和动漫，并根据用户自定义的规则进行重命名和整理。

## 🚀 功能特性

### 核心功能
- 🔄 **自动监控文件夹**，实时检测新添加的视频文件
- 📚 **智能分类** 电视剧、电影、动漫等不同类型的视频
- 🌐 **元数据获取** 从TMDB获取准确的节目信息和剧集标题
- ✏️ **自定义命名规则** 灵活配置文件命名格式
- 📁 **自动组织** 根据类型和系列将文件移动到指定目录

### 高级功能
- 🎛️ **友好的命令行界面**，支持丰富的命令选项
- 📝 **详细的日志记录**，便于排查问题
- 🔄 **优雅的错误处理** 和重试机制
- 🔍 **批量处理模式**，支持手动处理指定文件
- 🔧 **配置文件管理**，支持自定义所有设置

## 📋 系统要求

- **Python**: 3.8 或更高版本
- **操作系统**: Windows, Linux, macOS
- **依赖项**: requests, watchdog

## 📦 安装

### 方法1: 使用pip安装（推荐）

```bash
# 从源码安装
pip install -e .

# 或直接运行
python -m video_organizer
```

### 方法2: 直接运行

```bash
# 安装依赖
pip install -r requirements.txt

# 运行程序
python src/video_organizer/main.py
```

## 🛠️ 配置

### 配置文件

首次运行时，程序会在当前目录创建默认配置文件 `config.ini`。您可以修改此文件来自定义程序行为：

```ini
[monitoring]
watch_dir = ""  # 要监控的目录
output_dir = ""  # 输出目录
supported_extensions = .mp4,.mkv,.avi,.wmv,.mov
poll_interval = 1  # 轮询间隔（秒）
use_polling = false  # 是否使用轮询模式
polling_interval = 5  # 轮询间隔（秒）

[naming_rules]
tv_show = "{title} - S{season:02d}E{episode:02d} - {episode_title}"
movie = "{title} ({year})"
anime = "{title} - {episode}"
simple = "{title}"

[tmdb]
api_key = ""  # 您的TMDB API密钥
language = "zh-CN"
region = "CN"
retry_count = 3
timeout = 30

[logging]
level = "INFO"  # 日志级别: DEBUG, INFO, WARNING, ERROR
file = "video_organizer.log"  # 日志文件
max_bytes = 10485760  # 最大文件大小（10MB）
backup_count = 5  # 保留的日志文件数量
```

### 命令行选项

```
用法: video-organizer [选项]

选项:
  -h, --help            显示此帮助信息并退出
  -v, --version         显示版本信息并退出
  -c CONFIG, --config CONFIG
                        指定配置文件路径
  -l {DEBUG,INFO,WARNING,ERROR}, --log-level {DEBUG,INFO,WARNING,ERROR}
                        设置日志级别
  -w WATCH_DIR, --watch-dir WATCH_DIR
                        监控目录（覆盖配置文件）
  -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                        输出目录（覆盖配置文件）
  -p POLL_INTERVAL, --poll-interval POLL_INTERVAL
                        事件轮询间隔（秒）
  --use-polling         使用轮询模式而非事件监听
  --polling-interval POLLING_INTERVAL
                        轮询模式下的扫描间隔（秒）
  -s, --show-config     显示当前配置信息
  -f FILE, --process FILE
                        强制处理指定文件而非启动监控
```

## 🎯 使用示例

### 1. 基本使用

启动默认监控：

```bash
video-organizer
```

### 2. 自定义监控目录

```bash
video-organizer --watch-dir "D:\Downloads" --output-dir "D:\Videos"
```

### 3. 手动处理特定文件

```bash
video-organizer --process "D:\Downloads\some_video.mp4"
```

### 4. 查看当前配置

```bash
video-organizer --show-config
```

### 5. 使用自定义配置文件

```bash
video-organizer --config "D:\custom_config.ini"
```

### 6. 启用详细日志

```bash
video-organizer --log-level DEBUG
```

## 📝 支持的文件命名模板变量

在配置文件中，您可以使用以下变量来自定义文件命名格式：

### 电视剧变量
- `{title}` - 剧集标题
- `{season}` - 季数
- `{episode}` - 集数
- `{episode_title}` - 单集标题

### 电影变量
- `{title}` - 电影标题
- `{year}` - 上映年份

### 动画变量
- `{title}` - 动画标题
- `{episode}` - 集数

## 🔄 自动分类机制

程序会尝试通过以下方式确定视频类型：

1. **文件名分析**：检查文件名中的模式（如 "S01E02" 表示电视剧）
2. **元数据匹配**：使用TMDB API搜索匹配的电视剧或电影
3. **回退机制**：无法分类时使用简单命名格式

## 📊 日志和错误处理

- **日志文件** 默认保存在当前目录的 `video_organizer.log`
- **错误重试** 机制自动处理临时网络问题
- **详细的错误信息** 帮助您快速定位问题

## 🔧 故障排除

### 常见问题

1. **无法监控文件夹**
   - 检查路径是否正确
   - 确保有足够的权限
   - 对于网络共享目录，尝试启用 `use_polling` 选项

2. **元数据匹配失败**
   - 确保TMDB API密钥正确配置
   - 检查文件名是否包含足够的信息用于匹配
   - 查看日志文件了解详细错误信息

3. **文件未移动到预期位置**
   - 检查输出目录权限
   - 验证命名规则配置是否正确
   - 查看日志了解分类和移动过程

## 🤝 贡献

欢迎提交问题和建议！如果您想参与开发，请遵循以下步骤：

1. Fork 本仓库
2. 创建您的功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交您的更改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 开启一个 Pull Request

## 📜 许可证

本项目采用 MIT 许可证 - 详情请查看 LICENSE 文件

## 📧 联系

如有任何问题或建议，请随时联系项目维护者。

---

*Happy organizing!* 🎬