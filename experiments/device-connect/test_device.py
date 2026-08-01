"""Unit tests for the device-connect driver's dispatch (pure logic — no device-connect runtime, no ROS).

Same four cases as the ②a neutral-seam tests, on the same contract — proving the body endpoint is
identical across transports. Run from this dir:  python3 -m unittest test_device
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openpave_device import dispatch  # noqa: E402
from control_daemon.adapters import create_robot_adapter  # noqa: E402


class DeviceDispatchTests(unittest.TestCase):
    def setUp(self):
        self.adapter = create_robot_adapter("mock_arm")

    def test_supported_completed(self):
        with contextlib.redirect_stdout(io.StringIO()):
            s = dispatch(self.adapter, {"action": "move_joint", "params": {"joint": 2, "position": 0.5}})
        self.assertEqual(s["status"], "completed")
        self.assertEqual(s["detail"]["action"], "move_joint")
        self.assertTrue(s["request_id"])

    def test_unsupported_action(self):
        s = dispatch(self.adapter, {"action": "trot"})  # mock_arm has no locomotion
        self.assertEqual(s["status"], "unsupported")
        self.assertIn("trot", s["error"])

    def test_missing_action_rejected(self):
        s = dispatch(self.adapter, {"params": {}})
        self.assertEqual(s["status"], "rejected")

    def test_bad_params_failed(self):
        with contextlib.redirect_stdout(io.StringIO()):
            s = dispatch(self.adapter, {"action": "move_joint", "params": {"joint": 2}})  # no position
        self.assertEqual(s["status"], "failed")
        self.assertIn("position", s["error"])


if __name__ == "__main__":
    unittest.main()
