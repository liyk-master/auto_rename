#!/bin/bash
# PyInstaller 打包脚本 - Alpine/musl libc 版本

set -e  # 遇到错误时退出

echo "================================"
echo "  VideoOrganizer 打包脚本 (PyInstaller + Alpine)"
echo "================================"
echo ""

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

# 构建可执行文件 - 使用 PyInstaller
build_executable() {
    echo "开始构建可执行文件 (PyInstaller)..."
    echo ""
    
    # 检查入口文件
    if [ ! -f "run_organizer.py" ]; then
        echo "错误: 未找到 run_organizer.py"
        exit 1
    fi
    
    # 使用 PyInstaller 的 collect_data_files 自动收集数据文件
    # 创建临时 spec 文件以支持更复杂的数据收集
    cat > VideoOrganizer.spec << 'EOF'
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

# 收集 babelfish 和 guessit 的数据文件
datas = [('config.ini', '.')]
datas += collect_data_files('babelfish')
datas += collect_data_files('guessit')

a = Analysis(
    ['run_organizer.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'src.video_organizer',
        'babelfish',
        'guessit',
    ],
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
    
    echo "创建 spec 文件完成，开始构建..."
    
    # 使用 spec 文件构建
    pyinstaller \
        --noconfirm \
        --clean \
        VideoOrganizer.spec
    
    if [ $? -eq 0 ]; then
        echo ""
        echo "✅ 构建成功！"
        
        # 显示文件信息
        echo ""
        echo "生成的文件:"
        ls -lh dist/
        
        echo ""
        echo "动态依赖检查:"
        if [ "$OS" = "linux" ]; then
            # Alpine 构建的可执行文件使用 musl libc
            ldd dist/VideoOrganizer 2>/dev/null | head -10 || echo "无法检查依赖"
        fi
    else
        echo ""
        echo "❌ 构建失败！"
        exit 1
    fi
}

# 显示构建结果
show_result() {
    echo ""
    echo "================================"
    echo "  构建完成"
    echo "================================"
    echo ""
    
    echo "说明:"
    echo "- Alpine/musl libc 构建版本"
    echo "- 兼容大多数 Linux 发行版，包括旧系统"
    echo "- 输出目录: dist/"
    echo ""
    
    echo "使用方法:"
    echo "1. 将 dist/VideoOrganizer 复制到目标服务器"
    echo "2. 添加执行权限: chmod +x VideoOrganizer"
    echo "3. 运行: ./VideoOrganizer"
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