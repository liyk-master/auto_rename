import unittest
import sys
import os

sys.path.insert(0, os.path.abspath('.'))

from tests.unit.test_core.test_manual_rule_engine import TestRuleIntegrationWithRenamer

suite = unittest.TestSuite()
suite.addTest(TestRuleIntegrationWithRenamer('test_locked_fields_prevent_regex_override'))
runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)

# 输出结果到文件
with open('test_run_result.txt', 'w', encoding='utf-8') as f:
    f.write(f"Tests run: {result.testsRun}, Failures: {len(result.failures)}, Errors: {len(result.errors)}\n")
    if result.failures:
        f.write("\nFailures:\n")
        for test, trace in result.failures:
            f.write(f"{test}:\n{trace}\n")
    if result.errors:
        f.write("\nErrors:\n")
        for test, trace in result.errors:
            f.write(f"{test}:\n{trace}\n")
