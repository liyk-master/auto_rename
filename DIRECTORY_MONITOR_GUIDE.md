# 目录监控功能使用指南

## 功能概述

目录监控功能允许您监控指定目录中的视频文件，自动进行整理和元数据刮削。与下载器监控不同，目录监控直接监控本地文件系统，适合整理已有的视频文件。

## 配置说明

在 `config.ini` 文件的 `[monitoring]` 配置段中添加以下配置：

```ini
[monitoring]
; 目录监控配置
; enable_directory_monitor: 是否启用目录监控（True/False）
enable_directory_monitor = True
; directory_watch_dir: 要监控的目录路径
directory_watch_dir = F:\Videos\Watch
; directory_output_dir: 整理后的输出目录
directory_output_dir = F:\Videos\Organized
; directory_organize_mode: 整理方式（copy=复制，move=移动）
directory_organize_mode = copy
; directory_scrape_metadata: 是否刮削元数据并保存到文件（True/False）
directory_scrape_metadata = True
; directory_metadata_format: 元数据文件格式（nfo/json/both）
directory_metadata_format = nfo
; directory_polling_interval: 目录监控轮询间隔（秒）
directory_polling_interval = 5
```

## 配置项详解

### enable_directory_monitor
- **类型**: 布尔值
- **默认值**: False
- **说明**: 是否启用目录监控功能。设置为 True 时才会启动目录监控。

### directory_watch_dir
- **类型**: 路径
- **默认值**: 空
- **说明**: 要监控的目录路径。程序会递归扫描此目录及其子目录中的视频文件。

### directory_output_dir
- **类型**: 路径
- **默认值**: 空
- **说明**: 整理后的输出目录。文件会被按照命名规则整理到此目录。

### directory_organize_mode
- **类型**: 字符串
- **可选值**: copy, move
- **默认值**: copy
- **说明**:
  - `copy`: 复制文件到输出目录，保留原文件
  - `move`: 移动文件到输出目录，删除原文件

### directory_scrape_metadata
- **类型**: 布尔值
- **默认值**: True
- **说明**: 是否从 TMDB 下载元数据并保存到文件。

### directory_metadata_format
- **类型**: 字符串
- **可选值**: nfo, json, both
- **默认值**: nfo
- **说明**:
  - `nfo`: 保存为 NFO 格式（兼容 Kodi、Emby、Jellyfin 等）
  - `json`: 保存为 JSON 格式
  - `both`: 同时保存 NFO 和 JSON 格式

### directory_polling_interval
- **类型**: 整数
- **默认值**: 5
- **说明**: 目录监控的轮询间隔（秒）。程序会每隔此时间扫描一次监控目录。

## 使用步骤

1. **配置目录监控**
   - 编辑 `config.ini` 文件
   - 设置 `enable_directory_monitor = True`
   - 配置 `directory_watch_dir` 和 `directory_output_dir`

2. **创建目录**
   - 确保监控目录和输出目录都存在
   - 如果不存在，程序会在启动时自动创建输出目录

3. **放置视频文件**
   - 将需要整理的视频文件放入监控目录
   - 支持的格式：.mp4, .mkv, .avi, .mov, .wmv, .flv, .srt, .ass

4. **启动程序**
   ```bash
   python run_organizer.py
   ```

5. **等待处理**
   - 程序会自动扫描监控目录
   - 检测到新文件后会自动处理
   - 处理后的文件会出现在输出目录

## 工作流程

1. **文件检测**
   - 程序定期扫描监控目录
   - 检测新的视频文件
   - 验证文件是否稳定（文件大小不再变化）

2. **元数据提取**
   - 从文件名提取基本信息（标题、年份、季集等）
   - 从 TMDB 获取完整元数据

3. **文件整理**
   - 根据命名规则生成新路径
   - 创建目标目录
   - 复制或移动文件到目标位置

4. **元数据刮削**
   - 从 TMDB 下载详细信息
   - 生成 NFO 或 JSON 元数据文件
   - 与视频文件保存在同一目录

## 元数据文件格式

### NFO 格式
NFO 格式是标准的媒体库元数据格式，兼容以下软件：
- Kodi
- Emby
- Jellyfin
- Plex（部分支持）

NFO 文件包含以下信息：
- 标题和原始标题
- 年份和首播日期
- 评分
- 剧情简介
- 类型标签
- TMDB ID
- 演员信息
- 季集信息（电视剧）

### JSON 格式
JSON 格式包含完整的原始元数据，适合：
- 自定义处理
- 数据分析
- 备份和恢复

## 注意事项

1. **文件稳定性**
   - 程序会检查文件是否稳定（文件大小不再变化）
   - 正在下载或复制的文件不会被立即处理
   - 默认检查 3 次，每次间隔 1 秒

2. **重复处理**
   - 已处理的文件会被记录，不会重复处理
   - 如果需要重新处理，请删除输出目录中的文件

3. **路径映射**
   - 目录监控不支持路径映射功能
   - 所有路径必须是主机实际路径

4. **性能考虑**
   - 轮询间隔不宜过短，建议 5-10 秒
   - 监控目录中的文件数量不宜过多
   - 大量文件同时处理可能影响性能

## 故障排除

### 文件未被处理
- 检查文件扩展名是否在支持列表中
- 确认文件已完成下载（不是临时文件）
- 查看日志文件，了解详细错误信息

### 元数据刮削失败
- 检查 TMDB API 密钥是否正确
- 确认网络连接正常
- 查看日志文件，了解具体错误

### 文件整理路径错误
- 检查命名规则配置是否正确
- 确认 TMDB 能够识别文件
- 查看日志文件，了解生成的路径

## 示例

### 示例 1：整理电影
```
监控目录: F:\Videos\Watch
输出目录: F:\Videos\Organized

输入文件: F:\Videos\Watch\Avatar.2009.1080p.BluRay.x264.mkv
输出文件: F:\Videos\Organized\Movies\阿凡达 (2009) {tmdbid=19995}\阿凡达 1080p.BluRay.x264.mkv
元数据文件: F:\Videos\Organized\Movies\阿凡达 (2009) {tmdbid=19995}\阿凡达 1080p.BluRay.x264.nfo
```

### 示例 2：整理电视剧
```
监控目录: F:\Videos\Watch
输出目录: F:\Videos\Organized

输入文件: F:\Videos\Watch\Breaking.Bad.S01E01.2008.1080p.BluRay.x264.mkv
输出文件: F:\Videos\Organized\TV Shows\绝命毒师 (2008) {tmdbid=1396}\Season 01\绝命毒师 S01E01 1080p.BluRay.x264.mkv
元数据文件: F:\Videos\Organized\TV Shows\绝命毒师 (2008) {tmdbid=1396}\Season 01\绝命毒师 S01E01 1080p.BluRay.x264.nfo
```

## 与下载器监控的区别

| 特性 | 目录监控 | 下载器监控 |
|------|---------|-----------|
| 监控对象 | 本地文件系统 | 下载器（qBittorrent、Aria2） |
| 触发方式 | 定期轮询 | 下载完成事件 |
| 整理方式 | 复制或移动 | 仅上传 |
| 元数据刮削 | 支持 | 不支持 |
| 适用场景 | 整理已有文件 | 自动处理新下载 |

## 更新日志

### v1.0.0 (2026-01-22)
- 新增目录监控功能
- 支持复制和移动两种整理方式
- 支持 NFO 和 JSON 两种元数据格式
- 支持文件稳定性检测
- 支持递归扫描子目录