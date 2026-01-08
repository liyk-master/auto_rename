#!/bin/bash
# Legacy Linux构建脚本 - 适用于Ubuntu 18.04+
# 在有Ubuntu 18.04的机器上本地构建

set -e

echo "================================"
echo "  VideoOrganizer Legacy构建脚本"
echo "  目标: Ubuntu 18.04+ (glibc 2.27+)"
echo "================================"
echo ""

# 检查操作系统
check_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "检测到系统: $PRETTY_NAME"
    else
        echo "错误: 无法检测操作系统"
        exit 1
    fi
}

# 检查并安装Python 3.12
install_python() {
    echo "检查Python版本..."
    
    if command -v python3.12 &> /dev/null; then
        echo "✓ Python 3.12 已安装"
        python3.12 --version
    else
        echo "安装Python 3.12..."
        sudo apt-get update
        sudo apt-get install -y software-properties-common wget build-essential
        sudo add-apt-repository ppa:deadsnakes/ppa
        sudo apt-get update
        sudo apt-get install -y python3.12 python3.12-dev python3.12-venv python3-pip
        
        # 创建软链接
        if [ ! -L /usr/bin/python ]; then
            sudo ln -sf /usr/bin/python3.12 /usr/bin/python
        fi
        
        echo "✓ Python 3.12 安装完成"
        python --version
    fi
}

# 安装系统依赖
install_system_deps() {
    echo "安装系统依赖..."
    sudo apt-get install -y build-essential patchelf wget git
    echo "✓ 系统依赖安装完成"
}

# 安装Python依赖
install_python_deps() {
    echo "安装Python依赖..."
    
    python -m pip install --upgrade pip
    pip install pyinstaller>=6.0.0
    pip install -r requirements.txt
    
    echo "✓ Python依赖安装完成"
}

# 构建可执行文件
build_executable() {
    echo "开始构建可执行文件..."
    echo ""
    
    # 清理之前的构建
    rm -rf build dist __pycache__ *.spec 2>/dev/null || true
    
    # 构建可执行文件
    pyinstaller \
        --noconfirm \
        --onefile \
        --console \
        --name "VideoOrganizer-ubuntu18-linux" \
        --clean \
        --hidden-import=src.video_organizer \
        run_organizer.py
    
    if [ $? -eq 0 ]; then
        echo ""
        echo "✅ 构建成功！"
        
        # 显示文件信息
        echo ""
        echo "生成的文件:"
        ls -lh dist/
        
        echo ""
        echo "依赖检查:"
        ldd dist/VideoOrganizer-ubuntu18-linux | head -10
        
        echo ""
        echo "文件类型:"
        file dist/VideoOrganizer-ubuntu18-linux
        
    else
        echo ""
        echo "❌ 构建失败！"
        exit 1
    fi
}

# 创建发布包
create_package() {
    echo ""
    echo "创建发布包..."
    
    mkdir -p release
    cp dist/VideoOrganizer-ubuntu18-linux release/
    
    # 如果有README或配置文件也复制过去
    [ -f README.md ] && cp README.md release/
    [ -f BUILD.md ] && cp BUILD.md release/
    
    cd release
    tar -czf VideoOrganizer-ubuntu18-linux.tar.gz VideoOrganizer-ubuntu18-linux README.md BUILD.md 2>/dev/null || tar -czf VideoOrganizer-ubuntu18-linux.tar.gz VideoOrganizer-ubuntu18-linux
    cd ..
    
    echo "✓ 发布包创建完成: release/VideoOrganizer-ubuntu18-linux.tar.gz"
}

# 显示使用说明
show_usage() {
    echo ""
    echo "================================"
    echo "  构建完成"
    echo "================================"
    echo ""
    
    echo "可执行文件: dist/VideoOrganizer-ubuntu18-linux"
    echo "发布包: release/VideoOrganizer-ubuntu18-linux.tar.gz"
    echo ""
    
    echo "使用方法:"
    echo "1. 在目标服务器上解压:"
    echo "   tar -xzf VideoOrganizer-ubuntu18-linux.tar.gz"
    echo ""
    echo "2. 添加执行权限:"
    echo "   chmod +x VideoOrganizer-ubuntu18-linux"
    echo ""
    echo "3. 运行:"
    echo "   ./VideoOrganizer-ubuntu18-linux"
    echo ""
    
    echo "兼容性说明:"
    echo "- 适用于 Ubuntu 18.04 及以上版本"
    echo "- 需要 glibc 2.27 或更高版本"
    echo "- 使用命令 'ldd --version' 检查版本"
    echo ""
}

# 主函数
main() {
    check_os
    install_python
    install_system_deps
    install_python_deps
    build_executable
    create_package
    show_usage
}

main