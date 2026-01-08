# GitHub Actions Build

这个项目使用 GitHub Actions 自动构建跨平台可执行文件。

## 构建触发条件

- 推送到 `main` 或 `dev-upload123pan` 分支
- 创建标签 (如 `v1.0.0`)
- 手动触发 (workflow_dispatch)

## GitHub Actions 构建矩阵

| 平台 | 构建工具 | 输出文件 | 兼容性 |
|------|----------|----------|---------|
| Linux (Ubuntu 20.04) | PyInstaller | `VideoOrganizer-ubuntu20-linux` | Ubuntu 20.04+, glibc 2.31+ |
| Linux (Ubuntu 20.04) | Nuitka | `VideoOrganizer-ubuntu20-linux` | Ubuntu 20.04+, glibc 2.31+ |
| Windows | PyInstaller | `VideoOrganizer-ubuntu20-windows.exe` | Windows 10+ |
| macOS | PyInstaller | `VideoOrganizer-ubuntu20-macos` | macOS 10.15+ |

### Legacy版本说明

**由于GitHub Actions环境限制，无法自动构建Ubuntu 18.04兼容版本。**

如需要Ubuntu 18.04兼容版本，请使用本地构建脚本。

## 下载构建产物

1. 进入 GitHub 仓库的 Actions 页面
2. 选择最新的构建任务
3. 在 "Artifacts" 部分下载对应平台的可执行文件

## 发布版本

创建标签并推送会自动创建 GitHub Release：

```bash
git tag v1.0.0
git push origin v1.0.0
```

## 本地构建

如果需要本地构建，可以使用：

```bash
# Linux/macOS
python -m pip install pyinstaller
pyinstaller --onefile --console run_organizer.py

# Windows
pyinstaller --onefile --windowed run_organizer.py
```

## 本地构建 Legacy 版本

对于Ubuntu 18.04及更老系统的兼容版本，需要在有Ubuntu 18.04的机器上本地构建。

### 前提条件
- Ubuntu 18.04 或更高版本
- 网络连接（用于下载Python 3.12）
- sudo权限

### 构建步骤

1. **克隆仓库**
```bash
git clone https://github.com/liyk-master/auto_rename.git
cd auto_rename
```

2. **运行构建脚本**
```bash
chmod +x build_legacy.sh
./build_legacy.sh
```

3. **获取可执行文件**
构建完成后，可执行文件位于 `dist/VideoOrganizer-ubuntu18-linux`

4. **发布到远程服务器**
```bash
# 复制到远程服务器
scp dist/VideoOrganizer-ubuntu18-linux user@remote-server:/path/to/destination/

# 或先打包
tar -czf videoorganizer.tar.gz -C release .
scp videoorganizer.tar.gz user@remote-server:/path/to/destination/
```

### 使用Docker构建（推荐）

如果你在Ubuntu 20.04+上，但需要构建Ubuntu 18.04兼容版本，可以使用Docker：

```bash
# 构建Docker镜像
docker build -f Dockerfile.legacy -t video-organizer-legacy .

# 提取可执行文件
docker run --rm -v $(pwd):/output video-organizer-legacy cp dist/VideoOrganizer-legacy-linux /output/
```

## 兼容性说明

### Linux版本选择
- **VideoOrganizer-ubuntu20-linux**: 适用于Ubuntu 20.04及以上，需要glibc 2.31+
- **VideoOrganizer-ubuntu18-linux**（本地构建）: 适用于Ubuntu 18.04及以上，需要glibc 2.27+

### 检查你的glibc版本
```bash
ldd --version
# 第一行显示: ldd (Ubuntu GLIBC 2.xx) ...
```

### 版本兼容性
- 如果你的系统是 Ubuntu 20.04+ → 使用 github actions 的 ubuntu20 版本
- 如果你的系统是 Ubuntu 18.04 → 使用本地构建的 ubuntu18 版本
- 如果你的系统是 Ubuntu 16.04 或更老 → 可能无法运行

### Nuitka vs PyInstaller
- **Nuitka**: 性能更好，启动更快，体积略大
- **PyInstaller**: 兼容性更好，更稳定