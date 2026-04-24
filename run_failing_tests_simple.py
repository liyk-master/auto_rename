import unittest
import sys
import os

sys.path.insert(0, os.path.abspath('.'))

from tests.unit.test_core.test_manual_rule_engine import TestRuleIntegrationWithRenamer

tests_to_run = [
    'test_locked_fields_prevent_regex_override',
    'test_rules_applied_before_regex'
]

suite = unittest.TestSuite()
for test_name in tests_to_run:
    suite.addTest(TestRuleIntegrationWithRenamer(test_name))

with open('detailed_test_output.txt', 'w', encoding='utf-8') as f:
    runner = unittest.TextTestRunner(verbosity=2, stream=f)
    result = runner.run(suite)

print(f"Tests run: {result.testsRun}, Failures: {len(result.failures)}, Errors: {len(result.errors)}")
print("Detailed output written to detailed_test_output.txt")
