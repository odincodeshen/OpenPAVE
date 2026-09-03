"""Local-only tests for the servo actuator adapter (control_daemon.adapters.GpioServoAdapter).

Runs in dry-run (no gpiozero, no GPIO): the adapter records the servo angle, so the capability→angle
mapping, the trot sweep lifecycle, and the capability routing are asserted anywhere.
"""

from __future__ import annotations

import time
import unittest

from control_daemon.adapters import GpioServoAdapter, create_robot_adapter
from pave_runtime.seam import dispatch


class GpioServoAdapterTests(unittest.TestCase):
    def setUp(self):
        # fast sweep so the background thread records several angles quickly
        self.a = GpioServoAdapter(dry_run=True, home_deg=0.0, sweep_deg=40.0, sweep_hz=20.0)

    def tearDown(self):
        self.a._stop_sweep()  # never leak the sweep thread between tests

    def test_capabilities(self):
        self.assertEqual(
            self.a.capabilities, frozenset({"stop", "estop", "home", "trot", "move"})
        )

    def test_home_centers(self):
        self.a.execute("home")
        self.assertEqual(self.a.servo.angle, 0.0)
        self.assertFalse(self.a._running)

    def test_stop_centers_and_detaches(self):
        self.a.execute("stop")
        self.assertEqual(self.a.servo.angle, 0.0)
        self.assertTrue(self.a.servo.detached)
        self.assertFalse(self.a._running)

    def test_estop_maps_to_stop(self):
        self.a.execute("estop")
        self.assertEqual(self.a.servo.angle, 0.0)
        self.assertTrue(self.a.servo.detached)

    def test_trot_sweeps_until_stopped(self):
        self.a.execute("trot")
        self.assertTrue(self.a._running)
        time.sleep(0.12)  # let the sweeper toggle a few times
        moved = set(self.a.servo.angles)
        self.assertTrue(self.a._running)
        self.assertGreaterEqual(len(moved), 2)          # actually swept between endpoints
        self.assertTrue(moved <= {40.0, -40.0})         # to the configured sweep endpoints
        self.a.execute("stop")
        self.assertFalse(self.a._running)
        self.assertEqual(self.a.servo.angle, 0.0)       # ends centered

    def test_move_steers_by_yaw(self):
        self.a.execute("move", {"yaw": 0.5})
        self.assertEqual(self.a.servo.angle, 45.0)      # home 0 + 90*0.5
        self.assertFalse(self.a._running)

    def test_move_clamps_to_range(self):
        self.a.execute("move", {"yaw": -2.0})           # would be -180, clamped
        self.assertEqual(self.a.servo.angle, -90.0)

    def test_move_interrupts_a_running_sweep(self):
        self.a.execute("trot")
        self.assertTrue(self.a._running)
        self.a.execute("move", {"yaw": 0.0})
        self.assertFalse(self.a._running)               # steering stops the sweep
        self.assertEqual(self.a.servo.angle, 0.0)

    def test_dispatch_routes_through_capability_layer(self):
        state = dispatch(self.a, "move", {"yaw": 1.0})
        self.assertEqual(state["status"], "completed")
        self.assertEqual(self.a.servo.angle, 90.0)

    def test_registry_returns_servo_adapter(self):
        # no gpiozero on the test host → dry-run fallback, still a GpioServoAdapter
        self.assertIsInstance(create_robot_adapter("gpio_servo"), GpioServoAdapter)


if __name__ == "__main__":
    unittest.main()
