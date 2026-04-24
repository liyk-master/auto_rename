import unittest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath('.'))

from tests.unit.test_core.test_manual_rule_engine import TestRuleIntegrationWithRenamer

suite = unittest.TestLoader().loadTestsFromName('test_locked_fields_prevent_regex_override', TestRuleIntegrationWithRenamer)
runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)

# Print any errors
if result.errors or result.failures:
    print("\n=== Errors and Failures ===")
    for test, trace in result.errors + result.failures:
        print(f"Test: {test}")
        print(trace)
else:
    print("\nAll tests passed!")
