import unittest
from acceptance_checks import unsupported_execution_status


class AcceptanceCheckTests(unittest.TestCase):
    def test_observed_false_status_is_rejected(self):
        self.assertTrue(unsupported_execution_status(['已决定先做两周试点（尚未开始，也未完成）']))

    def test_observed_explicit_unknown_is_allowed(self):
        self.assertFalse(unsupported_execution_status(['已决定先做两周试点；试点是否已开始或完成未知']))

    def test_unknown_in_other_clause_does_not_mask_false_status(self):
        self.assertTrue(unsupported_execution_status(['试点未开始；是否已完成未知']))

    def test_decision_only_is_allowed(self):
        self.assertFalse(unsupported_execution_status(['已决定先做两周试点']))

    def test_not_stated_is_unknown_not_positive_execution(self):
        self.assertFalse(unsupported_execution_status(['已决定先做两周试点，未说明已开始或完成']))
        self.assertTrue(unsupported_execution_status(['未说明已开始，但已完成验收']))
