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
    
    # 使用 pyinstaller 构建
    pyinstaller \
        --noconfirm \
        --onefile \
        --console \
        --name "VideoOrganizer" \
        --clean \
        --hidden-import=src.video_organizer \
        --add-data "config.ini:." \
        run_organizer.py
    
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
