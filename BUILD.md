# GitHub Actions Build

这个项目使用 GitHub Actions 自动构建跨平台可执行文件。

## 构建触发条件

- 推送到 `main` 或 `dev-upload123pan` 分支
- 创建标签 (如 `v1.0.0`)
- 手动触发 (workflow_dispatch)

## GitHub Actions 构建矩阵

| 平台 | 构建工具 | 输出文件 | Python版本 | 兼容性 |
|------|----------|----------|------------|---------|
| Linux (Ubuntu 20.04) | PyInstaller | `VideoOrganizer-ubuntu20-linux` | 3.9 | Ubuntu 20.04+, glibc 2.31+ |
| Linux (Ubuntu 20.04) | Nuitka | `VideoOrganizer-ubuntu20-linux` | 3.9 | Ubuntu 20.04+, glibc 2.31+ |
| Windows | PyInstaller | `VideoOrganizer-ubuntu20-windows.exe` | 3.9 | Windows 10+ |
| macOS | PyInstaller | `VideoOrganizer-ubuntu20-macos` | 3.9 | macOS 10.15+ |
| Linux (Ubuntu 18.04) | PyInstaller | `VideoOrganizer-ubuntu18-linux` | 3.9 | Ubuntu 18.04+, glibc 2.27+ |

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

## 兼容性说明

### Linux版本选择
- **VideoOrganizer-ubuntu18-linux**: 适用于Ubuntu 18.04及以上，需要glibc 2.27+ (你的服务器)
- **VideoOrganizer-ubuntu20-linux**: 适用于Ubuntu 20.04及以上，需要glibc 2.31+

### 检查你的glibc版本
```bash
ldd --version
# 第一行显示: ldd (Ubuntu GLIBC 2.xx) ...
```

### 版本兼容性
- 如果你的系统是 Ubuntu 18.04 → 使用 github actions 的 ubuntu18 版本
- 如果你的系统是 Ubuntu 20.04+ → 使用 github actions 的 ubuntu20 版本
- 如果你的系统是 Ubuntu 16.04 或更老 → 可能无法运行

### Python版本说明
为了兼容老系统，所有版本都使用Python 3.9构建，而不是3.12。
- 移除了需要Python 3.12的依赖包（如p123client）
- 确保在Ubuntu 18.04+系统上正常运行

### Nuitka vs PyInstaller
- **Nuitka**: 性能更好，启动更快，体积略大
- **PyInstaller**: 兼容性更好，更稳定