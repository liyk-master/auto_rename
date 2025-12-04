#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试脚本：验证文件移动和完整性检查修复
"""

import sys
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

# 导入修改后的类
from video_organizer.core.file_mover import FileMover


def test_file_mover_with_nonexistent_file():
    """测试移动不存在的文件"""
    print("测试1: 移动不存在的文件...")
    
    try:
        # 创建临时目录
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # 创建FileMover实例
            file_mover = FileMover(temp_path)
            
            # 创建不存在的文件路径
            nonexistent_file = temp_path / "nonexistent_file.mp4"
            
            # 尝试移动不存在的文件，应该抛出FileNotFoundError
            file_mover.move_file(nonexistent_file, Path("test_dir/nonexistent_file.mp4"))
            
            print("✗ 测试失败：移动不存在的文件没有抛出预期的异常")
            return False
            
    except FileNotFoundError as e:
        print(f"✓ 测试通过：正确抛出了FileNotFoundError: {e}")
    except Exception as e:
        print(f"✗ 测试失败：抛出了错误的异常类型: {type(e).__name__}: {e}")
        return False
    
    return True


def test_file_mover_with_directory():
    """测试移动目录而不是文件"""
    print("\n测试2: 移动目录而不是文件...")
    
    try:
        # 创建临时目录
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # 创建一个测试目录
            test_dir = temp_path / "test_directory"
            test_dir.mkdir()
            
            # 创建FileMover实例
            file_mover = FileMover(temp_path)
            
            # 尝试移动目录，应该抛出IsADirectoryError
            file_mover.move_file(test_dir, Path("test_dir/test_directory"))
            
            print("✗ 测试失败：移动目录没有抛出预期的异常")
            return False
            
    except IsADirectoryError as e:
        print(f"✓ 测试通过：正确抛出了IsADirectoryError: {e}")
    except Exception as e:
        print(f"✗ 测试失败：抛出了错误的异常类型: {type(e).__name__}: {e}")
        return False
    
    return True


def test_file_mover_with_valid_file():
    """测试移动有效的文件"""
    print("\n测试3: 移动有效的文件...")
    
    try:
        # 创建临时目录
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # 创建一个测试文件
            source_file = temp_path / "test_file.mp4"
            source_file.write_text("test content")
            
            # 创建FileMover实例
            file_mover = FileMover(temp_path)
            
            # 移动文件
            dest_relative = Path("test_dir/test_file.mp4")
            final_path = file_mover.move_file(source_file, dest_relative)
            
            # 检查文件是否已移动
            dest_path = temp_path / dest_relative
            if dest_path.exists():
                print(f"✓ 测试通过：文件已成功移动到: {final_path}")
            else:
                print(f"✗ 测试失败：文件未移动到预期位置: {dest_path}")
                return False
            
            # 检查源文件是否已删除
            if not source_file.exists():
                print("✓ 测试通过：源文件已成功删除")
            else:
                print(f"✗ 测试失败：源文件未删除: {source_file}")
                return False
            
    except Exception as e:
        print(f"✗ 测试失败：移动文件时发生错误: {e}")
        return False
    
    return True


def test_file_integrity_check():
    """测试文件完整性检查"""
    print("\n测试4: 文件完整性检查...")
    
    try:
        # 创建临时目录
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # 导入FileSystemMonitor类
            from video_organizer.core.filesystem_monitor import FileSystemMonitor
            
            # 创建FileSystemMonitor实例（使用测试API密钥）
            monitor = FileSystemMonitor(
                str(temp_path), 
                str(temp_path / "processed"),
                "test_api_key"
            )
            
            # 创建一个测试文件
            test_file = temp_path / "test_file.mp4"
            test_file.write_text("test content")
            
            # 测试_is_file_complete方法
            result = monitor._is_file_complete(test_file, check_interval=0.1, max_checks=2)
            if result:
                print("✓ 测试通过：文件完整性检查通过")
            else:
                print("✗ 测试失败：文件完整性检查未通过")
                return False
            
            # 测试大小为0的文件
            empty_file = temp_path / "empty_file.mp4"
            empty_file.write_text("")
            result = monitor._is_file_complete(empty_file)
            if not result:
                print("✓ 测试通过：大小为0的文件被正确识别")
            else:
                print("✗ 测试失败：大小为0的文件未被正确识别")
                return False
            
            # 测试不存在的文件
            nonexistent_file = temp_path / "nonexistent_file.mp4"
            result = monitor._is_file_complete(nonexistent_file)
            if not result:
                print("✓ 测试通过：不存在的文件被正确识别")
            else:
                print("✗ 测试失败：不存在的文件未被正确识别")
                return False
            
    except Exception as e:
        print(f"✗ 测试失败：文件完整性检查时发生错误: {e}")
        return False
    
    return True


def test_move_retry_mechanism():
    """测试移动文件的重试机制"""
    print("\n测试5: 移动文件的重试机制...")
    
    try:
        # 创建临时目录
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # 创建一个测试文件
            source_file = temp_path / "test_file.mp4"
            source_file.write_text("test content")
            
            # 模拟shutil.move抛出异常
            with patch('shutil.move') as mock_move:
                # 让前两次调用失败，第三次成功
                mock_move.side_effect = [OSError("模拟移动失败"), OSError("模拟移动失败"), None]
                
                # 创建FileMover实例
                file_mover = FileMover(temp_path)
                
                # 尝试移动文件
                dest_relative = Path("test_dir/test_file.mp4")
                final_path = file_mover.move_file(source_file, dest_relative)
                
                # 检查是否调用了3次
                if mock_move.call_count == 3:
                    print(f"✓ 测试通过：重试机制正常工作，共调用了 {mock_move.call_count} 次")
                else:
                    print(f"✗ 测试失败：重试机制未正常工作，只调用了 {mock_move.call_count} 次")
                    return False
    
    except Exception as e:
        print(f"✗ 测试失败：重试机制测试时发生错误: {e}")
        return False
    
    return True


def main():
    """运行所有测试"""
    print("开始测试文件移动和完整性检查修复...")
    
    tests = [
        test_file_mover_with_nonexistent_file,
        test_file_mover_with_directory,
        test_file_mover_with_valid_file,
        test_file_integrity_check,
        test_move_retry_mechanism
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        if test():
            passed += 1
        else:
            failed += 1
    
    print(f"\n测试结果: 共 {len(tests)} 个测试，{passed} 个通过，{failed} 个失败")
    
    if failed == 0:
        print("✓ 所有测试通过！修改成功解决了文件移动问题。")
        sys.exit(0)
    else:
        print("✗ 有测试失败，需要进一步检查。")
        sys.exit(1)


if __name__ == "__main__":
    main()
