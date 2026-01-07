# 123云盘上传优化指南

## 📊 当前配置

### 超时设置
| 函数 | 连接超时 | 读取超时 | 说明 |
|------|---------|---------|------|
| `_upload_single_chunk` | 180秒 | 900秒 | 分片上传（预加载） |
| `_upload_single_chunk_lazy` | 180秒 | 900秒 | 分片上传（懒加载） |
| `_upload_small_file` | - | 600秒 | 小文件上传 |

### 重试机制
- **最大重试次数**：8次
- **初始退避时间**：1秒
- **退避策略**：指数退避 + 随机抖动
- **重试间隔**：1秒、2秒、4秒、8秒、16秒、32秒、64秒、128秒

### 并发设置
- **默认并发线程**：2个
- **动态调整**：min(max_workers, total_parts, CPU核心数+2)
- **分片大小**：200MB（由服务器返回）

## ⚠️ 当前问题分析

### 实际上传速度
```
上传速度: 203 kB/s
文件大小: 934 MB
分片数量: 28 个
每个分片: ~33.4 MB
单个分片上传时间: ~165 秒
```

### 超时计算
- **当前读取超时**: 900秒
- **实际需要时间**: 165秒
- **安全系数**: 900 / 165 = 5.4倍 ✅

## 🔧 优化建议

### 1. 网络优化（最重要）

#### 检查网络状况
```python
# 测试上传速度
import requests
import time

def test_upload_speed():
    """测试到123云盘的上传速度"""
    url = "https://m12.123624.com/ping"  # 测试URL
    start = time.time()
    response = requests.get(url, timeout=10)
    elapsed = time.time() - start
    print(f"网络延迟: {elapsed:.2f}秒")
```

#### 网络优化建议
- ✅ **使用有线网络**而非WiFi
- ✅ **避免网络高峰期**上传
- ✅ **关闭其他占用带宽的程序**
- ✅ **检查路由器/网络设备**是否正常
- ✅ **考虑使用VPN**（如果网络环境受限）

### 2. 并发线程调整

#### 当前配置
```python
# p123do.py 第336行
max_workers: int = 2  # 默认值
```

#### 调整建议

**网络速度 < 500 KB/s**
```python
max_workers = 1  # 单线程，避免竞争
```

**网络速度 500 KB/s - 2 MB/s**
```python
max_workers = 2  # 当前默认值
```

**网络速度 > 2 MB/s**
```python
max_workers = 4  # 增加并发
```

**网络速度 > 5 MB/s**
```python
max_workers = 8  # 高并发
```

#### 如何修改
在调用上传函数时传入参数：
```python
from src.video_organizer.upload.p123do import upload_file

result = upload_file(
    client=client,
    file_path="path/to/file.mp4",
    parent_id=123456,
    max_workers=1  # 根据网络速度调整
)
```

### 3. 超时时间调整（已优化）

当前超时设置已经非常宽松：
- **读取超时**: 900秒（15分钟）
- **连接超时**: 180秒（3分钟）

对于203KB/s的网络速度，上传33.4MB分片需要165秒，900秒超时有5.4倍安全系数。

**如果仍然超时，可以进一步增加**：
```python
timeout=(180, 1200)  # 读取超时20分钟
```

### 4. 分片大小调整

当前分片大小由服务器返回，通常为200MB。如果网络很慢，可以尝试：
- **联系123云盘客服**询问是否可以调整分片大小
- **使用其他上传方式**（如Web端上传）

## 📈 监控上传进度

### 关键日志信息

```
[INFO] 使用 X 个线程并发上传 Y 个分片
[INFO] 分片 N 上传成功，已完成 A/B
[ERROR] 分片 N 网络连接失败: ...
[INFO] 分片 N 将在 X 秒后重试
```

### 进度条信息
```
上传 仙帝归来 S01E02 4K.HEVC.mp4:   4%|▏   | 33.6M/934M [02:45<1:14:00, 203kB/s]
```

关注：
- **上传速度**（如203kB/s）- 如果持续低于100KB/s，考虑网络问题
- **剩余时间**（如1:14:00）- 估算完成时间
- **进度百分比**（如4%）- 确认正在上传

## 🚨 故障排查

### 问题1: 频繁超时
**症状**:
```
[ERROR] 分片 N 网络连接失败: ('Connection aborted.', TimeoutError('The write operation timed out'))
```

**解决方案**:
1. 检查网络连接稳定性
2. 降低并发线程数（max_workers=1）
3. 增加超时时间（已优化到900秒）
4. 避免网络高峰期上传

### 问题2: 上传速度极慢
**症状**:
```
上传速度: < 100 kB/s
```

**解决方案**:
1. 检查网络带宽
2. 关闭其他占用带宽的程序
3. 尝试使用有线网络
4. 考虑更换网络环境

### 问题3: 重试次数过多
**症状**:
```
[WARNING] 分片 N 上传失败 (8/8): ...
[ERROR] 分片 N 上传失败，已达到最大重试次数
```

**解决方案**:
1. 检查网络是否断开
2. 检查123云盘服务是否正常
3. 尝试重新启动上传程序
4. 联系123云盘客服

## 📝 配置示例

### 慢速网络配置（< 500 KB/s）
```python
result = upload_file(
    client=client,
    file_path="path/to/file.mp4",
    parent_id=123456,
    max_workers=1  # 单线程
)
```

### 中速网络配置（500 KB/s - 2 MB/s）
```python
result = upload_file(
    client=client,
    file_path="path/to/file.mp4",
    parent_id=123456,
    max_workers=2  # 双线程（默认）
)
```

### 快速网络配置（> 2 MB/s）
```python
result = upload_file(
    client=client,
    file_path="path/to/file.mp4",
    parent_id=123456,
    max_workers=4  # 四线程
)
```

## 🎯 最佳实践

1. **首次上传测试**: 先上传小文件（<100MB）测试网络
2. **监控上传速度**: 持续观察上传速度，如果突然下降，检查网络
3. **合理设置并发**: 根据实际网络速度调整max_workers
4. **避免高峰期**: 在网络使用较少的时间段上传
5. **保持网络稳定**: 上传过程中避免切换网络或关闭路由器

## 📞 获取帮助

如果以上优化仍然无法解决问题，可以：
1. 查看完整的上传日志
2. 测试网络速度和延迟
3. 联系123云盘客服
4. 尝试使用其他上传方式（Web端、客户端）

## 🔗 相关文件

- `src/video_organizer/upload/p123do.py` - 上传核心逻辑
- `src/video_organizer/upload/upload_p123.py` - 上传器封装
- `test_p123_upload.py` - 上传测试脚本
- `test_p123_quick.py` - 快速测试脚本
