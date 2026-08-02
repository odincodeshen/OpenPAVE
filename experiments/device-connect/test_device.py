"""Unit tests for the device-connect driver — dispatch, label mapping, and dynamic labeled-RPC
generation (option B). Pure logic — no device-connect runtime needed at test time, no ROS.

Run from this dir:  python3 -m unittest test_device
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openpave_device import dispatch, OpenPaveBodyDriver, _function_labels  # noqa: E402
from control_daemon.adapters import create_robot_adapter  # noqa: E402


class DispatchTests(unittest.TestCase):
    """Same contract as the ②a neutral seam — proving the body endpoint is identical across transports."""

    def setUp(self):
        self.adapter = create_robot_adapter("mock_arm")

    def test_supported_completed(self):
        with contextlib.redirect_stdout(io.StringIO()):
            s = dispatch(self.adapter, "move_joint", {"joint": 2, "position": 0.5})
        self.assertEqual(s["status"], "completed")
        self.assertEqual(s["detail"]["action"], "move_joint")

    def test_unsupported_action(self):
        s = dispatch(self.adapter, "trot")
        self.assertEqual(s["status"], "unsupported")
        self.assertIn("trot", s["error"])

    def test_bad_params_failed(self):
        with contextlib.redirect_stdout(io.StringIO()):
            s = dispatch(self.adapter, "move_joint", {"joint": 2})  # no position
        self.assertEqual(s["status"], "failed")
        self.assertIn("position", s["error"])


class LabelTests(unittest.TestCase):
    def test_safety_critical(self):
        self.assertEqual(_function_labels("estop")["safety"], "critical")
        self.assertEqual(_function_labels("stop")["safety"], "critical")
        self.assertEqual(_function_labels("home")["safety"], "informational")

    def test_direction(self):
        self.assertEqual(_function_labels("move_joint")["direction"], "write")
        self.assertEqual(_function_labels("get_image")["direction"], "read")


class DynamicRpcTests(unittest.TestCase):
    """B1: every capability must appear as its own labeled RPC that the SDK collects."""

    def test_each_capability_becomes_labeled_rpc(self):
        driver = OpenPaveBodyDriver()  # ROBOT_ADAPTER default mock_arm
        names = {f.name for f in driver.functions}
        self.assertTrue(set(driver.adapter.capabilities) <= names)  # all capabilities exposed
        self.assertIn("list_capabilities", names)

    def test_estop_is_safety_critical(self):
        driver = OpenPaveBodyDriver()
        estop = next(f for f in driver.functions if f.name == "estop")
        self.assertEqual(estop.labels.get("safety"), "critical")  # so function(safety:critical) works


if __name__ == "__main__":
    unittest.main()
