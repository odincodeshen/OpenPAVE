"""Unit tests for the neutral-seam body endpoint (pure logic — no zenoh, no ROS).

`neutral_body` now imports the single-source `dispatch` from `pave_runtime.seam` (this experiment is
where it was first written); these tests exercise it through the neutral-seam module.

Run from this dir:  python3 -m unittest test_seam
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from neutral_body import dispatch  # noqa: E402
from control_daemon.adapters import create_robot_adapter  # noqa: E402


class SeamDispatchTests(unittest.TestCase):
    def setUp(self):
        self.adapter = create_robot_adapter("mock_arm")

    def test_supported_action_completed(self):
        with contextlib.redirect_stdout(io.StringIO()):
            s = dispatch(self.adapter, "move_joint", {"joint": 2, "position": 0.5})
        self.assertEqual(s["status"], "completed")
        self.assertEqual(s["detail"]["action"], "move_joint")
        self.assertTrue(s["request_id"])

    def test_unsupported_action(self):
        s = dispatch(self.adapter, "trot")  # mock_arm has no locomotion
        self.assertEqual(s["status"], "unsupported")
        self.assertIn("trot", s["error"])

    def test_missing_action_rejected(self):
        s = dispatch(self.adapter, "")  # blank action envelope
        self.assertEqual(s["status"], "rejected")

    def test_bad_params_failed(self):
        with contextlib.redirect_stdout(io.StringIO()):
            s = dispatch(self.adapter, "move_joint", {"joint": 2})  # no position
        self.assertEqual(s["status"], "failed")
        self.assertIn("position", s["error"])


if __name__ == "__main__":
    unittest.main()
