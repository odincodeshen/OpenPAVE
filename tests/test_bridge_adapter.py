"""Unit tests for PuppyPiBridgeAdapter (B2) — bridge-or-fallback, cooldown, STOP timeout,
path metadata. A fake bridge client + fake capture runner stand in; no ROS, no Docker, no dog.
"""

import contextlib
import io
import json
import unittest

from control_daemon.adapters import (
    PuppyPiBridgeAdapter,
    PuppyPiLocalAdapter,
    RosCliConfig,
    create_robot_adapter,
)
from control_daemon.bridge_client import BridgeError


def _config() -> RosCliConfig:
    return RosCliConfig("0", "rmw_fastrtps_cpp", "ros:humble", "puppy-ros2-cli:humble")


class FakeBridge:
    """Stand-in BridgeClient: scripts ping readiness and run_steps outcome."""

    def __init__(self, ready=True, services_ready=True, run_error=None, run_ok=True):
        self._ready, self._services_ready = ready, services_ready
        self._run_error, self._run_ok = run_error, run_ok
        self.pings = 0
        self.runs = []  # each: {"timeout": ...}

    def ping(self, timeout=2.0):
        self.pings += 1
        return self._ready, {"services_ready": self._services_ready, "controller": "puppy_control"}

    def run_steps(self, steps, timeout=10.0, timeout_ms=None):
        self.runs.append({"timeout": timeout})
        if self._run_error:
            raise self._run_error
        out = [{"name": f"service:{s.get('service', '?')}", "rc": 0 if self._run_ok else 3}
               for s in steps if s.get("op") == "service"]
        return self._run_ok, out


def _fake_capture():
    """Stand-in capture_runner for the A fallback path; records calls, returns success."""
    calls = []

    def cap(cmd, stdin):
        calls.append(cmd)
        return 0, json.dumps({"steps": [{"name": "service:x", "rc": 0}]})

    return cap, calls


def _adapter(fake, cap):
    return PuppyPiBridgeAdapter(config=_config(), capture_runner=cap, bridge_client=fake)


class BridgeAdapterTests(unittest.TestCase):
    def test_registry_returns_bridge_adapter(self):
        self.assertIsInstance(create_robot_adapter("puppypi_bridge"), PuppyPiBridgeAdapter)

    def test_bridge_success_records_path_bridge(self):
        fake = FakeBridge(ready=True, services_ready=True, run_ok=True)
        cap, cap_calls = _fake_capture()
        adapter = _adapter(fake, cap)
        with contextlib.redirect_stdout(io.StringIO()):
            result = adapter.execute("home", {})
        self.assertTrue(result.success)
        self.assertEqual(result.detail["path"], "bridge")
        self.assertEqual(len(fake.runs), 1)      # went through the bridge
        self.assertEqual(len(cap_calls), 0)      # A path (docker exec) NOT used

    def test_not_ready_falls_back_to_A(self):
        fake = FakeBridge(ready=True, services_ready=False)  # alive but not connected to controller
        cap, cap_calls = _fake_capture()
        adapter = _adapter(fake, cap)
        with contextlib.redirect_stdout(io.StringIO()):
            result = adapter.execute("home", {})
        self.assertTrue(result.success)
        self.assertEqual(result.detail["path"], "fallback_a")
        self.assertEqual(result.detail["fallback_reason"], "bridge_not_ready")
        self.assertEqual(len(fake.runs), 0)      # never ran steps on the bridge
        self.assertGreater(len(cap_calls), 0)    # A path used

    def test_bridge_error_falls_back_then_cooldown_skips_bridge(self):
        fake = FakeBridge(run_error=BridgeError("busy", code="busy"))
        cap, cap_calls = _fake_capture()
        adapter = _adapter(fake, cap)
        with contextlib.redirect_stdout(io.StringIO()):
            first = adapter.execute("home", {})   # tries bridge -> error -> fallback A + cooldown
            second = adapter.execute("home", {})  # in cooldown -> straight to A, no bridge attempt
        self.assertEqual(first.detail["path"], "fallback_a")
        self.assertEqual(first.detail["fallback_reason"], "busy")
        self.assertEqual(len(fake.runs), 1)       # bridge tried once, then suppressed by cooldown
        self.assertEqual(second.detail["path"], "fallback_a")
        self.assertEqual(len(cap_calls), 2)       # both actions went through A

    def test_stop_uses_short_bridge_timeout(self):
        fake = FakeBridge(ready=True, services_ready=True, run_ok=True)
        cap, _ = _fake_capture()
        adapter = _adapter(fake, cap)
        with contextlib.redirect_stdout(io.StringIO()):
            adapter.execute("stop", {})
        # first run is the motion-stop; it must use the short STOP bridge timeout
        self.assertEqual(fake.runs[0]["timeout"], adapter.bridge_stop_timeout)
        self.assertLess(adapter.bridge_stop_timeout, adapter.bridge_call_timeout)

    def test_puppypi_local_still_default_and_unchanged(self):
        # the validated path is a plain PuppyPiLocalAdapter, not the bridge
        self.assertIs(type(create_robot_adapter("puppypi_local")), PuppyPiLocalAdapter)


if __name__ == "__main__":
    unittest.main()
