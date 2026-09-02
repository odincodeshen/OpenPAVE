"""Unit tests for the seam transport plugin core (`pave_runtime.seam`): dispatch + registry.

Only the dependency-free core is exercised here — no transport backend is imported (they pull in
optional deps like zenoh / device-connect). Run: python3 tests/test_seam.py
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pave_runtime.seam import dispatch, create_seam_transport  # noqa: E402
from pave_runtime import seam  # noqa: E402
from control_daemon.adapters import create_robot_adapter  # noqa: E402


class DispatchTests(unittest.TestCase):
    """The single-source body-endpoint contract (same four cases ②a/②b used)."""

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

    def test_missing_action_rejected(self):
        s = dispatch(self.adapter, "")
        self.assertEqual(s["status"], "rejected")

    def test_bad_params_failed(self):
        with contextlib.redirect_stdout(io.StringIO()):
            s = dispatch(self.adapter, "move_joint", {"joint": 2})  # no position
        self.assertEqual(s["status"], "failed")
        self.assertIn("position", s["error"])


class RegistryTests(unittest.TestCase):
    def test_unknown_transport_raises(self):
        with self.assertRaises(ValueError):
            create_seam_transport("does_not_exist")

    def test_known_backends_registered_but_not_imported(self):
        # both backends are in the registry as lazy dotted paths (not imported at core load)
        self.assertIn("raw_zenoh", seam._BACKENDS)
        self.assertIn("device_connect", seam._BACKENDS)
        self.assertNotIn("pave_runtime.seam_backends.zenoh_seam", sys.modules)


if __name__ == "__main__":
    unittest.main()
