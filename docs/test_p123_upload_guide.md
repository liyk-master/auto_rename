# 123云盘上传测试脚本使用说明

## 📋 概述

提供了两个测试脚本来测试123云盘的上传功能：

1. **test_p123_upload.py** - 完整功能测试脚本
2. **test_p123_quick.py** - 快速测试脚本（最小配置）

---

## 🔑 获取123云盘API Token

1. 登录 [123云盘网页版](https://www.123pan.com/)
2. 进入 **个人中心**
3. 找到 **API Token** 或 **开发者设置**
4. 创建或复制你的Token

---

## 🚀 快速开始（推荐新手）

### 使用 test_p123_quick.py

这是最简单的测试方式，只需配置一个参数：

1. 打开 `test_p123_quick.py`
2. 找到第17行：
   ```python
   P123_TOKEN = "your_p123_token_here"
   ```
3. 将 `your_p123_token_here` 替换为你的123云盘API Token
4. 运行脚本：
   ```bash
   python test_p123_quick.py
   ```

**功能：**
- 自动创建10MB测试文件
- 上传到123云盘根目录
- 上传完成后自动删除测试文件

---

## ⚙️ 完整功能测试

### 使用 test_p123_upload.py

适合需要自定义配置的场景：

#### 1. 基础配置

打开脚本，修改以下配置：

```python
# 123云盘API Token（必须）
P123_TOKEN = "your_p123_token_here"

# 根目录文件夹ID（默认为0）
ROOT_PARENT_ID = 0

# Telegram通知配置（可选）
TELEGRAM_CONFIG = {
    'bot_token': 'your_telegram_bot_token',
    'chat_id': 'your_telegram_chat_id'
}
```

#### 2. 测试文件配置

**方式1：使用真实文件**
```python
TEST_FILE_PATH = r"F:\test\video.mp4"  # 你的文件路径
CREATE_TEST_FILE = False
```

**方式2：自动创建测试文件**
```python
TEST_FILE_PATH = r"F:\test\video.mp4"  # 占位路径
CREATE_TEST_FILE = True
TEST_FILE_SIZE_MB = 10  # 测试文件大小（MB）
```

#### 3. 上传配置

```python
# 上传后的文件名（可选）
RENAME_TO = "My Video.mp4"

# 媒体信息（用于创建文件夹结构）
MEDIA_INFO = {
    'title': 'Test Show',
    'season': 1,
    'episode': 1
}

# 媒体类型
ITEM_TYPE = 'tv'  # 'tv' 或 'movie'

# 自定义文件夹结构
FOLDER_STRUCTURE = ["media", "TV Shows", "Test Show", "Season 01"]
```

#### 4. 运行测试

```bash
python test_p123_upload.py
```

---

## 📂 文件夹结构说明

### 自动创建的文件夹结构

使用 `folder_structure` 参数可以指定上传路径：

```python
FOLDER_STRUCTURE = ["media", "TV Shows", "Show Name", "Season 01"]
```

这会在123云盘中创建：
```
根目录/
└── media/
    └── TV Shows/
        └── Show Name/
            └── Season 01/
                └── 上传的文件.mp4
```

### 兼容旧逻辑

如果不提供 `folder_structure`，会使用 `media_info` 自动创建：

```python
ITEM_TYPE = 'tv'
MEDIA_INFO = {'title': 'Show Name'}
```

会创建：
```
根目录/
└── media/
    └── TV Shows/
        └── Show Name/
            └── 上传的文件.mp4
```

---

## 📊 Telegram通知配置（可选）

如果需要上传进度通知到Telegram：

1. 创建Telegram机器人
   - 在Telegram中找到 [@BotFather](https://t.me/BotFather)
   - 发送 `/newbot` 创建机器人
   - 获取 Bot Token

2. 获取Chat ID
   - 在Telegram中找到 [@userinfobot](https://t.me/userinfobot)
   - 发送任意消息获取你的 Chat ID

3. 配置到脚本：
```python
TELEGRAM_CONFIG = {
    'bot_token': '123456789:ABCdefGHIjklMNOpqrsTUVwxyz',
    'chat_id': '123456789'
}
```

**功能：**
- 实时上传进度条
- 上传速度显示
- 已上传/总大小显示
- 每2秒更新一次进度

---

## 🧪 批量上传测试

取消注释 `test_p123_upload.py` 最后一行：

```python
if __name__ == "__main__":
    test_p123_upload()
    test_multiple_files()  # 取消注释
```

这会：
- 创建3个5MB的测试文件
- 逐个上传到不同文件夹
- 上传完成后自动清理

---

## ⚠️ 常见问题

### 1. ImportError: p123client 未安装

**解决方法：**
```bash
pip install p123client
```

### 2. 上传失败：Token无效

**检查：**
- Token是否正确复制
- Token是否已过期
- 网络连接是否正常

### 3. 创建文件夹失败

**可能原因：**
- 权限不足
- 文件夹名称包含非法字符（已自动清理）
- 网络问题

### 4. 上传速度慢

**建议：**
- 检查网络带宽
- 尝试小文件测试
- 查看123云盘服务器状态

---

## 📝 返回值说明

上传成功返回字典：
```python
{
    'fileid': 123456789,      # 文件ID
    'filename': 'video.mp4',  # 文件名
    'filesize': 10485760      # 文件大小（字节）
}
```

上传失败返回 `None`

---

## 🔧 高级用法

### 自定义进度回调

```python
def my_progress_callback(uploaded, total):
    percent = (uploaded / total) * 100
    print(f"进度: {percent:.1f}%")

# 在 _upload_with_progress 中使用
```

### 重试机制

默认最大重试3次，可修改：
```python
result = p123_upload_file(
    client=self.client,
    file_path=file_path,
    parent_id=parent_id,
    new_name=file_name,
    max_retries=5,  # 修改重试次数
    callback=progress_callback
)
```

---

## 📞 获取帮助

如遇问题，请检查：
1. Python版本 >= 3.7
2. 依赖包已安装：`pip install -r requirements.txt`
3. 123云盘API Token有效
4. 网络连接正常

---

## 📄 相关文件

- `src/video_organizer/upload/upload_p123.py` - 上传器实现
- `src/video_organizer/upload/p123do.py` - 底层上传逻辑
- `src/video_organizer/upload/p123client.py` - 123云盘API客户端

---

## ✅ 测试检查清单

使用测试脚本前，请确认：

- [ ] 已安装 p123client
- [ ] 已配置有效的 P123_TOKEN
- [ ] 测试文件存在或允许自动创建
- [ ] 网络连接正常
- [ ] 有足够的123云盘存储空间
- [ ] （可选）Telegram配置正确

---

**祝测试顺利！** 🎉
