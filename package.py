#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
视频文件自动重命名和组织工具 - 打包脚本

使用PyInstaller将Python脚本打包为可执行文件
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent

# 源代码目录
SRC_DIR = PROJECT_ROOT / "src"

# 主要入口文件
MAIN_SCRIPT = str(SRC_DIR / "video_organizer" / "main.py")

# 输出目录
OUTPUT_DIR = PROJECT_ROOT / "dist"

# 临时目录
BUILD_DIR = PROJECT_ROOT / "build"

# 配置文件模板
CONFIG_TEMPLATE = PROJECT_ROOT / "config_template.ini"

# 图标文件（如果有）
ICON_PATH = None  # 可以设置为.ico文件路径


def run_command(command, cwd=None):
    """运行命令并等待其完成"""
    print(f"执行命令: {' '.join(command)}")
    process = subprocess.Popen(
        command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

    stdout, stderr = process.communicate()

    if process.returncode != 0:
        print(f"命令执行失败: {stderr}")
        sys.exit(1)

    if stdout:
        print(stdout)

    return process.returncode


def clean_output_dirs():
    """清理之前的构建和输出目录"""
    print("清理之前的构建文件...")

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
        print(f"删除目录: {BUILD_DIR}")

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
        print(f"删除目录: {OUTPUT_DIR}")


def install_pyinstaller():
    """安装PyInstaller（如果尚未安装）"""
    print("检查PyInstaller...")
    try:
        import PyInstaller

        print(f"已安装PyInstaller版本: {PyInstaller.__version__}")
    except ImportError:
        print("安装PyInstaller...")
        run_command([sys.executable, "-m", "pip", "install", "pyinstaller"])


def build_executable():
    """使用PyInstaller构建可执行文件"""
    print("开始构建可执行文件...")

    # 静态文件目录
    STATIC_SRC = SRC_DIR / "video_organizer" / "web" / "static"

    # 构建PyInstaller命令
    cmd = [
        "pyinstaller",
        "--onefile",  # 打包成单个可执行文件
        "--name",
        "video-organizer",  # 可执行文件名称
        "--paths",
        ".",  # 添加项目根目录到 import 搜索路径
        "--add-data",
        f"{CONFIG_TEMPLATE};.",  # 添加配置模板文件
        "--add-data",
        f"{STATIC_SRC};video_organizer/web/static",  # 添加前端静态文件
        "--hidden-import",
        "configparser",  # 确保包含依赖
        "--hidden-import",
        "requests",
        "--hidden-import",
        "watchdog",
    ]

    # 添加图标（如果有）
    if ICON_PATH and os.path.exists(ICON_PATH):
        cmd.extend(["--icon", ICON_PATH])

    # 添加主要脚本
    cmd.append(MAIN_SCRIPT)

    # 执行构建命令
    run_command(cmd)


def prepare_distribution():
    """准备发布文件"""
    print("准备发布文件...")

    # 确保输出目录存在
    if not OUTPUT_DIR.exists():
        OUTPUT_DIR.mkdir(parents=True)

    # 复制可执行文件到输出目录
    exe_path = PROJECT_ROOT / "dist" / "video-organizer.exe"
    if exe_path.exists():
        shutil.copy2(exe_path, OUTPUT_DIR / "video-organizer.exe")
        print(f"复制可执行文件: {exe_path} -> {OUTPUT_DIR}")
    else:
        print(f"错误: 找不到可执行文件 {exe_path}")
        sys.exit(1)

    # 复制配置模板
    if CONFIG_TEMPLATE.exists():
        shutil.copy2(CONFIG_TEMPLATE, OUTPUT_DIR / "config_template.ini")
        print(f"复制配置模板: {CONFIG_TEMPLATE} -> {OUTPUT_DIR}")

    # 复制README文件
    readme_path = PROJECT_ROOT / "README.md"
    if readme_path.exists():
        shutil.copy2(readme_path, OUTPUT_DIR / "README.md")
        print(f"复制README: {readme_path} -> {OUTPUT_DIR}")


def main():
    """主函数"""
    print("视频文件自动重命名和组织工具 - 打包脚本")
    print("==========================================\n")

    try:
        # 1. 清理输出目录
        clean_output_dirs()

        # 2. 安装PyInstaller（如果需要）
        install_pyinstaller()

        # 3. 构建可执行文件
        build_executable()

        # 4. 准备发布文件
        prepare_distribution()

        print("\n打包完成！")
        print(f"可执行文件位置: {OUTPUT_DIR / 'video-organizer.exe'}")
        print("\n使用说明:")
        print("1. 将配置模板复制为config.ini并进行配置")
        print("2. 运行video-organizer.exe开始使用")

    except Exception as e:
        print(f"打包过程中发生错误: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
