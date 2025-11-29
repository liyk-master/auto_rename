# 视频文件自动重命名和组织工具 - 使用指南

## 📋 目录

- [快速入门](#快速入门)
- [详细配置](#详细配置)
  - [监控配置](#监控配置)
  - [命名规则](#命名规则)
  - [TMDB配置](#tmdb配置)
  - [日志配置](#日志配置)
- [命令行选项](#命令行选项)
- [工作流程](#工作流程)
- [高级功能](#高级功能)
- [故障排除](#故障排除)

## 🚀 快速入门

### 步骤1: 安装

```bash
# 安装依赖
pip install -r requirements.txt

# 或直接从源码安装
pip install -e .
```

### 步骤2: 配置

1. 复制配置模板文件:
   ```bash
   copy config_template.ini config.ini
   ```

2. 编辑 `config.ini`，设置以下必要参数:
   - `watch_dir`: 要监控的文件夹路径
   - `output_dir`: 文件整理后的输出路径
   - `tmdb.api_key`: 您的TMDB API密钥

### 步骤3: 运行

```bash
# 启动监控服务
python src/video_organizer/main.py

# 或（如果已安装）
video-organizer
```

## 🔍 详细配置

### 监控配置

在 `[monitoring]` 部分，您可以配置程序如何监控文件系统：

- **`watch_dir`**: 程序将监控此目录中的新文件。
  ```ini
  watch_dir = "D:\Downloads"
  ```

- **`output_dir`**: 重命名和分类后的文件将移动到此目录。
  ```ini
  output_dir = "D:\Videos"
  ```

- **`supported_extensions`**: 要处理的文件扩展名列表。
  ```ini
  supported_extensions = .mp4,.mkv,.avi,.wmv,.mov
  ```

- **`use_polling`**: 在某些文件系统或网络共享上，事件监听可能不可靠。启用此选项使用轮询模式。
  ```ini
  use_polling = false
  ```

- **`polling_interval`**: 轮询模式下，多久检查一次新文件（秒）。
  ```ini
  polling_interval = 5
  ```

### 命名规则

在 `[naming_rules]` 部分，您可以定义不同类型内容的命名格式：

- **电视剧格式**:
  ```ini
  tv_show = "{title} - S{season:02d}E{episode:02d} - {episode_title}"
  ```
  - `{title}`: 电视剧名称
  - `{season}`: 季数（02d确保两位数格式）
  - `{episode}`: 集数
  - `{episode_title}`: 单集标题

- **电影格式**:
  ```ini
  movie = "{title} ({year})"
  ```
  - `{title}`: 电影名称
  - `{year}`: 上映年份

- **动画格式**:
  ```ini
  anime = "{title} - {episode}"
  ```

- **简单格式** (用于无法识别的文件):
  ```ini
  simple = "{title}"
  ```

### TMDB配置

TMDB配置决定了程序如何与The Movie Database API交互：

- **`api_key`**: 您的TMDB API密钥（必须）。
  ```ini
  api_key = "your_api_key_here"
  ```

- **`language`**: 搜索结果和元数据的语言。
  ```ini
  language = "zh-CN"
  ```

- **`region`**: 影响某些搜索结果的地区设置。
  ```ini
  region = "CN"
  ```

- **`retry_count`**: API请求失败后重试的次数。
  ```ini
  retry_count = 3
  ```

### 日志配置

在 `[logging]` 部分，您可以调整日志行为：

- **`level`**: 日志详细程度 (DEBUG, INFO, WARNING, ERROR)。
  ```ini
  level = "INFO"
  ```

- **`file`**: 日志文件路径。
  ```ini
  file = "video_organizer.log"
  ```

## 🖥️ 命令行选项

程序支持多种命令行选项，可以在运行时覆盖配置文件的设置：

```
可选参数:
  -h, --help            显示帮助信息
  -v, --version         显示版本信息
  -c CONFIG, --config CONFIG
                        指定配置文件路径
  -l {DEBUG,INFO,WARNING,ERROR}, --log-level {DEBUG,INFO,WARNING,ERROR}
                        设置日志级别
  -w WATCH_DIR, --watch-dir WATCH_DIR
                        监控目录（覆盖配置文件）
  -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                        输出目录（覆盖配置文件）
  -p POLL_INTERVAL, --poll-interval POLL_INTERVAL
                        事件轮询间隔
  --use-polling         使用轮询模式
  --polling-interval POLLING_INTERVAL
                        轮询间隔（秒）
  -s, --show-config     显示当前配置
  -f FILE, --process FILE
                        强制处理指定文件
```

## 🔄 工作流程

程序的典型工作流程如下：

1. **监控**: 程序持续监控配置的 `watch_dir` 目录
2. **检测**: 当检测到新文件时，程序分析文件名尝试提取信息
3. **匹配**: 使用提取的信息或文件名在TMDB上搜索匹配项
4. **分类**: 根据匹配结果将文件分类为电视剧、电影或其他
5. **命名**: 应用相应的命名规则生成新文件名
6. **组织**: 将重命名的文件移动到输出目录中的适当子目录

## 💡 高级功能

### 批量处理模式

您可以使用 `--process` 选项手动处理特定文件：

```bash
# 处理单个文件
python src/video_organizer/main.py --process "D:\Downloads\some_file.mp4"

# 或使用通配符（需要通过shell展开）
for %%f in (D:\Downloads\*.mp4) do (
    python src/video_organizer/main.py --process "%%f"
)
```

### 自定义组织规则

程序会根据内容类型自动创建子目录结构：

```
outout_dir/
├── TV Shows/
│   ├── 节目名称1/
│   └── 节目名称2/
├── Movies/
├── Anime/
└── Others/
```

## 🔧 故障排除

### 常见问题

1. **监控不工作**
   - 检查监控目录路径是否正确
   - 确保有足够的权限访问该目录
   - 对于网络共享，尝试启用 `use_polling = true`

2. **TMDB匹配失败**
   - 检查文件名是否包含足够的识别信息
   - 确保API密钥正确配置
   - 查看日志文件了解详细错误

3. **文件未移动**
   - 检查输出目录权限
   - 确认文件名中不包含非法字符
   - 查看日志中的错误信息

### 查看日志

详细的日志信息可以帮助您排查问题：

```bash
# 查看最新日志
cat video_organizer.log

# 或在Windows上
type video_organizer.log
```

### 启用调试日志

对于更详细的问题排查，启用DEBUG级别日志：

```bash
python src/video_organizer/main.py --log-level DEBUG
```

## 📝 注意事项

- 程序会保留原始文件的扩展名
- 重命名和移动操作是不可逆的，请确保您有原始文件的备份
- TMDB API使用有限制，请合理使用程序以避免超出API限制
- 处理大文件可能需要一些时间，请耐心等待

---

祝您使用愉快！如有任何问题，请查看README.md中的联系信息。