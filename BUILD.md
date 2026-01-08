# GitHub Actions Build

这个项目使用 GitHub Actions 自动构建跨平台可执行文件。

## 构建触发条件

- 推送到 `main` 或 `dev-upload123pan` 分支
- 创建标签 (如 `v1.0.0`)
- 手动触发 (workflow_dispatch)

## 构建矩阵

| 平台 | 构建工具 | 输出文件 |
|------|----------|----------|
| Linux | PyInstaller | `VideoOrganizer-linux` |
| Linux | Nuitka | `VideoOrganizer-linux` |
| Windows | PyInstaller | `VideoOrganizer-windows.exe` |
| macOS | PyInstaller | `VideoOrganizer-macos` |
| Linux (Legacy) | PyInstaller | `VideoOrganizer-legacy-linux` |

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

- **标准版本**: 适用于现代 Linux 发行版
- **Legacy 版本**: 基于 Ubuntu 18.04，兼容老系统
- **Nuitka 版本**: 性能更好，体积更小