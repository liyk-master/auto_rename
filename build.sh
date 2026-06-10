#!/bin/bash
# PyInstaller 打包脚本

set -e  # 遇到错误时退出

echo "================================"
echo "  VideoOrganizer 打包脚本 (PyInstaller)"
echo "================================"
echo ""

APP_NAME="VideoOrganizer"
ENTRY_SCRIPT="run_organizer.py"

# 检测操作系统
detect_os() {
    case "$(uname -s)" in
        Linux*)
            OS="linux"
            ;;
        Darwin*)
            OS="macos"
            ;;
        MINGW*|MSYS*|CYGWIN*)
            OS="windows"
            ;;
        *)
            OS="unknown"
            ;;
    esac
    echo "检测到操作系统: $OS"
}

# 清理构建文件
clean_build() {
    echo "清理之前的构建文件..."

    rm -rf build 2>/dev/null || true
    rm -rf __pycache__ 2>/dev/null || true
    rm -rf dist/* 2>/dev/null || true

    find . -name "*.spec" -delete 2>/dev/null || true
    find . -name "*.pyc" -delete 2>/dev/null || true

    echo "清理完成"
}

# 构建主程序可执行文件
build_main_executable() {
    echo "开始构建主程序可执行文件..."
    echo ""

    if [ ! -f "$ENTRY_SCRIPT" ]; then
        echo "错误: 未找到 $ENTRY_SCRIPT"
        exit 1
    fi

    cat > "${APP_NAME}.spec" << 'EOF'
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 收集 babelfish 和 guessit 的数据文件
datas = [('config.ini', '.')]
datas += [('src/video_organizer/web/static', 'video_organizer/web/static')]
datas += collect_data_files('babelfish')
datas += collect_data_files('guessit')

hiddenimports = [
    'src',
    'src.video_organizer',
    'babelfish',
    'guessit',
    'rebulk',
    'rebulk.rules',
    'rebulk.patterns',
    'rebulk.match',
]
hiddenimports += collect_submodules('babelfish')
hiddenimports += collect_submodules('guessit')
hiddenimports += collect_submodules('rebulk')

a = Analysis(
    ['run_organizer.py'],
    pathex=['.', 'src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VideoOrganizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
EOF

    echo "创建主程序 spec 文件完成，开始构建..."

    pyinstaller \
        --noconfirm \
        --clean \
        "${APP_NAME}.spec"
}

build_executable() {
    build_main_executable

    echo ""
    echo "✅ 构建成功！"

    echo ""
    echo "生成的文件:"
    ls -lh dist/

    echo ""
    echo "动态依赖检查:"
    if [ "$OS" = "linux" ]; then
        ldd "dist/${APP_NAME}" 2>/dev/null | head -10 || echo "无法检查依赖"
    fi
}

# 显示构建结果
show_result() {
    echo ""
    echo "================================"
    echo "  构建完成"
    echo "================================"
    echo ""

    if [ "$OS" = "windows" ]; then
        echo "说明:"
        echo "- 主程序可执行版本"
        echo "- 启动入口: run_organizer.py"
        echo "- 默认启动 Web 管理后台 (端口 8080) + 文件监控"
        echo "- 输出目录: dist/"
        echo ""
        echo "使用方法:"
        echo "1. 双击 dist/${APP_NAME}.exe"
        echo "2. 打开浏览器访问 http://localhost:8080"
    else
        echo "说明:"
        echo "- 主程序可执行版本"
        echo "- 兼容大多数 Linux / macOS 环境"
        echo "- 输出目录: dist/"
        echo ""
        echo "使用方法:"
        echo "1. 将 dist/${APP_NAME} 复制到目标环境"
        echo "2. 添加执行权限: chmod +x ${APP_NAME}"
        echo "3. 运行: ./${APP_NAME}"
    fi
    echo ""
}

# 主函数
main() {
    detect_os
    clean_build
    build_executable
    show_result
}

main
