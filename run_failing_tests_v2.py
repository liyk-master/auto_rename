import unittest
import sys
import os
import traceback

sys.path.insert(0, os.path.abspath('.'))

from tests.unit.test_core.test_manual_rule_engine import TestRuleIntegrationWithRenamer

tests_to_run = [
    'test_locked_fields_prevent_regex_override',
    'test_rules_applied_before_regex'
]

suite = unittest.TestSuite()
for test_name in tests_to_run:
    suite.addTest(TestRuleIntegrationWithRenamer(test_name))

runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)

if result.failures:
    print("\n" + "="*80)
    print("FAILURE DETAILS:")
    print("="*80)
    for test, tb in result.failures:
        print(f"\nTest: {test}")
        print(tb)
        # Show last few lines of traceback
        lines = tb.strip().split('\n')
        if lines:
            print("Last lines:", '\n'.join(lines[-5:]))

if result.errors:
    print("\n" + "="*80)
    print("ERROR DETAILS:")
    print("="*80)
    for test, tb in result.errors:
        print(f"\nTest: {test}")
        print(tb)
