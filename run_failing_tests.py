#!/usr/bin/env python
import sys
import os
import traceback

# Add project root to path
sys.path.insert(0, os.path.abspath('.'))

# Import test class
from tests.unit.test_core.test_manual_rule_engine import TestRuleIntegrationWithRenamer

# Run each failing test individually and capture detailed output
tests_to_run = [
    'test_locked_fields_prevent_regex_override',
    'test_rules_applied_before_regex'
]

suite = unittest.TestSuite()
for test_name in tests_to_run:
    suite.addTest(TestRuleIntegrationWithRenamer(test_name))

runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)

# If failures, print detailed info
if result.failures:
    print("\n" + "="*80)
    print("FAILURE DETAILS:")
    print("="*80)
    for test, trace in result.failures:
        print(f"\nTest: {test}")
        print(trace)
        # Also extract and print the actual error message and location
        if 'Traceback' in trace:
            lines = trace.split('\n')
            for i, line in enumerate(lines):
                if 'Error' in line or 'Exception' in line:
                    print(f"Error line: {line}")
                    break

if result.errors:
    print("\n" + "="*80)
    print("ERROR DETAILS:")
    print("="*80)
    for test, trace in result.errors:
        print(f"\nTest: {test}")
        print(trace)
