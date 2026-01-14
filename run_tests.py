#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试运行脚本

此脚本用于运行项目中的所有测试，包括单元测试和集成测试。
"""

import os
import sys
import unittest
import argparse
from unittest.runner import TextTestRunner
from unittest import defaultTestLoader
import time
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger("test_runner")


def get_test_suite(test_dir="tests", pattern="test_*.py"):
    """
    获取测试套件

    Args:
        test_dir: 测试目录
        pattern: 测试文件匹配模式

    Returns:
        测试套件对象
    """
    # 获取项目根目录
    root_dir = os.path.abspath(os.path.dirname(__file__))

    # 构建测试目录的完整路径
    test_path = os.path.join(root_dir, test_dir)

    # 确保测试目录存在
    if not os.path.exists(test_path):
        logger.error(f"测试目录不存在: {test_path}")
        sys.exit(1)

    logger.info(f"从目录加载测试: {test_path}")

    # 查找所有测试文件
    test_suite = defaultTestLoader.discover(test_path, pattern=pattern)

    return test_suite


def run_tests(suite, verbosity=2):
    """
    运行测试套件

    Args:
        suite: 测试套件
        verbosity: 输出详细程度

    Returns:
        测试结果
    """
    # 创建测试运行器
    runner = TextTestRunner(verbosity=verbosity)

    # 运行测试并计时
    start_time = time.time()

    try:
        logger.info("开始运行测试...")
        result = runner.run(suite)

        # 计算运行时间
        end_time = time.time()
        run_time = end_time - start_time

        # 输出测试统计信息
        logger.info(f"测试完成，总耗时: {run_time:.2f} 秒")
        logger.info(f"运行测试数: {result.testsRun}")
        logger.info(f"失败测试数: {len(result.failures)}")
        logger.info(f"错误测试数: {len(result.errors)}")
        logger.info(f"跳过测试数: {len(result.skipped)}")

        if result.wasSuccessful():
            logger.info("✅ 所有测试通过！")
        else:
            logger.error("❌ 测试失败！")

        return result

    except Exception as e:
        logger.error(f"运行测试时发生错误: {e}")
        raise


def main():
    """
    主函数
    """
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="运行项目测试")
    parser.add_argument("--test-dir", default="tests", help="测试目录")
    parser.add_argument("--pattern", default="test_*.py", help="测试文件匹配模式")
    parser.add_argument("--verbosity", type=int, default=2, help="输出详细程度 (1-3)")

    args = parser.parse_args()

    try:
        # 获取测试套件
        suite = get_test_suite(args.test_dir, args.pattern)

        # 运行测试
        result = run_tests(suite, args.verbosity)

        # 根据测试结果设置退出码
        sys.exit(0 if result.wasSuccessful() else 1)

    except KeyboardInterrupt:
        logger.info("测试运行被用户中断")
        sys.exit(1)
    except Exception as e:
        logger.error(f"运行测试时发生未预期的错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
