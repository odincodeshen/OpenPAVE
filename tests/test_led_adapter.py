"""Local-only tests for the LED status adapter (control_daemon.adapters.LedAdapter).

Runs in dry-run (no gpiozero, no GPIO): the adapter records LED state, so the capability→light
mapping and the capability routing are asserted anywhere — Mac, CI, or a Pi without a wired LED.
"""

from __future__ import annotations

import unittest

from control_daemon.adapters import LedAdapter, create_robot_adapter
from pave_runtime.seam import dispatch


class LedAdapterTests(unittest.TestCase):
    def setUp(self):
        self.a = LedAdapter(dry_run=True, blink_hz=2.0)

    def test_capabilities(self):
        self.assertEqual(
            self.a.capabilities, frozenset({"stop", "estop", "home", "trot", "move"})
        )

    def test_stop_is_solid_on(self):
        self.a.execute("stop")
        self.assertEqual(self.a.led.state, "on")

    def test_estop_maps_to_stop(self):
        self.a.execute("estop")
        self.assertEqual(self.a.led.state, "on")

    def test_home_is_dim(self):
        self.a.execute("home")
        self.assertEqual(self.a.led.state, "dim")
        self.assertAlmostEqual(self.a.led.brightness, 0.15)

    def test_trot_pulses(self):
        self.a.execute("trot")
        self.assertEqual(self.a.led.state, "pulse")

    def test_stop_clears_a_running_pulse(self):
        self.a.execute("trot")
        self.a.execute("stop")
        self.assertEqual(self.a.led.state, "on")
        self.assertIsNone(self.a.led.animation)

    def test_move_pulse_rate_rises_with_speed(self):
        slow = LedAdapter(dry_run=True, blink_hz=2.0)
        fast = LedAdapter(dry_run=True, blink_hz=2.0)
        slow.execute("move", {"vx": 0.1})
        fast.execute("move", {"vx": 1.0})
        # faster speed → higher pulse Hz → shorter fade half-period
        self.assertLess(fast.led.animation[1], slow.led.animation[1])

    def test_dispatch_routes_through_capability_layer(self):
        state = dispatch(self.a, "trot", {})
        self.assertEqual(state["status"], "completed")
        self.assertEqual(self.a.led.state, "pulse")

    def test_unsupported_action_is_rejected(self):
        state = dispatch(self.a, "grasp", {})  # manipulation verb, not a locomotion LED
        self.assertEqual(state["status"], "unsupported")

    def test_registry_returns_led_adapter(self):
        # no gpiozero on the test host → falls back to dry-run, still a LedAdapter
        self.assertIsInstance(create_robot_adapter("led"), LedAdapter)


if __name__ == "__main__":
    unittest.main()
