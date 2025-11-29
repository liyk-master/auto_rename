# 视频文件自动重命名和组织工具 - 开发者指南

## 📋 目录

- [项目架构](#项目架构)
- [代码结构](#代码结构)
- [核心模块](#核心模块)
- [API参考](#api参考)
- [测试](#测试)
- [贡献指南](#贡献指南)

## 🏗️ 项目架构

项目采用模块化设计，遵循以下架构原则：

- **关注点分离**: 不同功能划分为独立模块
- **可扩展性**: 易于添加新功能和修改现有功能
- **测试友好**: 模块间低耦合，便于单元测试
- **错误处理**: 统一的错误处理和日志记录机制

## 📁 代码结构

```
video-organizer/
├── src/
│   └── video_organizer/
│       ├── __init__.py
│       ├── main.py            # 主入口
│       ├── core/              # 核心功能模块
│       │   ├── __init__.py
│       │   ├── config_loader.py  # 配置加载
│       │   ├── file_system_monitor.py  # 文件监控
│       │   ├── video_file_handler.py  # 文件处理
│       │   ├── tmdb_client.py  # TMDB API客户端
│       │   └── video_renamer.py  # 视频重命名逻辑
│       └── utils/             # 工具函数
│           ├── __init__.py
│           ├── logging_utils.py  # 日志工具
│           ├── cli_parser.py  # 命令行解析
│           └── cli_output.py  # 命令行输出
├── tests/                    # 测试文件
│   ├── __init__.py
│   ├── test_config_loader.py
│   ├── test_tmdb_client.py
│   ├── test_renamer.py
│   └── integration/
│       └── test_integration.py
├── docs/                     # 文档
├── config_template.ini       # 配置模板
├── setup.py                  # 包安装配置
├── requirements.txt          # 依赖列表
└── run_tests.py              # 测试运行脚本
```

## 🔍 核心模块

### 1. 配置加载器 (config_loader.py)

负责从配置文件加载和验证配置。

**主要功能**:
- 读取和解析INI配置文件
- 验证必要的配置项
- 提供默认配置值
- 支持配置保存功能

### 2. 文件系统监控器 (file_system_monitor.py)

监控指定目录的文件系统变化。

**主要功能**:
- 支持事件监听和轮询两种监控模式
- 过滤和处理相关文件类型
- 触发文件处理流程
- 优雅地启动和停止监控服务

### 3. 视频文件处理器 (video_file_handler.py)

处理检测到的视频文件，协调重命名和移动操作。

**主要功能**:
- 初始化TMDB客户端和视频重命名器
- 处理单个文件
- 队列管理和错误重试
- 维护处理状态

### 4. TMDB客户端 (tmdb_client.py)

与The Movie Database API交互获取元数据。

**主要功能**:
- 搜索电视剧和电影
- 获取剧集信息和详情
- 错误处理和重试机制
- 缓存支持

### 5. 视频重命名器 (video_renamer.py)

实现视频文件的重命名逻辑。

**主要功能**:
- 解析文件名提取信息
- 应用命名规则
- 处理特殊情况和冲突
- 生成最终文件路径

## 📚 API参考

### 1. 配置加载器 API

```python
# 加载配置文件
def load_config(config_path: str) -> dict:
    """从指定路径加载配置文件"""

# 保存默认配置
def save_default_config(config_path: str) -> None:
    """创建默认配置文件"""

# 验证配置
def validate_config(config: dict) -> None:
    """验证配置的有效性，抛出异常如果无效"""
```

### 2. 文件系统监控器 API

```python
class FileSystemMonitor:
    def __init__(self, watch_dir, event_handler, **kwargs):
        """初始化监控器"""
        
    def start(self):
        """启动监控服务"""
        
    def stop(self):
        """停止监控服务"""
        
    def _on_file_created(self, event):
        """处理文件创建事件"""
```

### 3. 视频文件处理器 API

```python
class VideoFileHandler:
    def __init__(self, output_dir, supported_extensions, naming_rules, tmdb_config):
        """初始化文件处理器"""
        
    def on_created(self, file_path):
        """处理新创建的文件"""
        
    def force_process_file(self, file_path):
        """强制处理指定文件"""
        
    def _process_file_internal(self, file_path):
        """内部处理文件的逻辑"""
```

### 4. TMDB客户端 API

```python
class TMDBClient:
    def __init__(self, api_key, language="zh-CN", region="CN", **kwargs):
        """初始化TMDB客户端"""
        
    def search_tv_show(self, query, **kwargs):
        """搜索电视剧"""
        
    def search_movie(self, query, **kwargs):
        """搜索电影"""
        
    def get_tv_season_details(self, tv_id, season_number, **kwargs):
        """获取电视剧季信息"""
        
    def get_movie_details(self, movie_id, **kwargs):
        """获取电影详情"""
```

## 🧪 测试

### 运行测试

```bash
# 使用测试运行脚本
python run_tests.py

# 或直接使用pytest
pytest

# 查看测试覆盖率
pytest --cov=src/video_organizer
```

### 测试结构

- **单元测试**: 测试单个组件的功能
- **集成测试**: 测试多个组件协同工作
- **模拟**: 使用mock模拟外部依赖

### 编写新测试

1. 在 `tests/` 目录下创建新的测试文件
2. 遵循现有的测试模式和命名约定
3. 使用模拟对象隔离外部依赖
4. 确保测试覆盖正常和异常情况

## 🤝 贡献指南

### 提交更改

1. 创建功能分支:
   ```bash
   git checkout -b feature/amazing-feature
   ```

2. 进行更改并编写测试

3. 运行测试确保一切正常:
   ```bash
   python run_tests.py
   ```

4. 提交更改:
   ```bash
   git commit -m "Add amazing feature"
   ```

5. 推送到远程分支:
   ```bash
   git push origin feature/amazing-feature
   ```

6. 创建Pull Request

### 代码规范

- 遵循PEP 8规范
- 使用类型注解
- 添加详细的函数和类文档
- 确保测试覆盖率
- 避免代码重复

### 添加新功能

1. 在适当的模块中实现新功能
2. 更新相关文档
3. 添加测试用例
4. 更新配置模板（如果需要）

### 报告问题

请在GitHub Issues中报告问题，包括:
- 问题描述
- 复现步骤
- 预期行为
- 实际行为
- 环境信息（操作系统、Python版本等）
- 相关日志（如果有）

## 🔧 开发提示

- 使用 `--log-level DEBUG` 获取详细日志
- 利用 `--process` 选项测试单个文件处理
- 使用模拟对象测试API交互
- 在修改配置加载器时，确保验证所有必要的配置项
- 添加新的文件类型时，更新支持的扩展名配置