"""Unit tests for the capability schema + MockArmAdapter (pure logic, no ROS).

Run: python3 -m unittest experiments.capability-mve.test_capability   # (or from this dir)
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capability_schema import (  # noqa: E402
    COMMON_CAPABILITIES,
    CapabilityIntentError,
    normalize_action_payload,
)
from mock_arm_adapter import MockArmAdapter  # noqa: E402


class CapabilitySchemaTests(unittest.TestCase):
    def test_normalize_minimal_lowercases_action(self):
        a = normalize_action_payload({"action": "GRASP"})
        self.assertEqual(a["action"], "grasp")
        self.assertEqual(a["params"], {})
        self.assertTrue(a["request_id"])

    def test_normalize_keeps_params_and_request_id(self):
        a = normalize_action_payload({"action": "move_joint", "params": {"joint": 2}, "request_id": "r1"})
        self.assertEqual(a["params"], {"joint": 2})
        self.assertEqual(a["request_id"], "r1")

    def test_missing_action_raises(self):
        with self.assertRaises(CapabilityIntentError):
            normalize_action_payload({"params": {}})

    def test_params_not_object_raises(self):
        with self.assertRaises(CapabilityIntentError):
            normalize_action_payload({"action": "home", "params": 5})


class MockArmAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = MockArmAdapter()

    def test_declares_manipulation_and_common_caps(self):
        self.assertIn("move_joint", self.adapter.capabilities)
        self.assertTrue(COMMON_CAPABILITIES <= self.adapter.capabilities)  # stop/estop/home
        self.assertNotIn("trot", self.adapter.capabilities)  # not a locomotion robot

    def test_execute_ok(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = self.adapter.execute("grasp", {})
        self.assertTrue(result.success)
        self.assertEqual(result.detail["action"], "grasp")

    def test_move_joint_requires_params(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = self.adapter.execute("move_joint", {"joint": 2})  # missing 'position'
        self.assertFalse(result.success)
        self.assertIn("position", result.error)


if __name__ == "__main__":
    unittest.main()
