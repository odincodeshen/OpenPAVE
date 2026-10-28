"""Tests that PROVE two hardware-safety blockers (written to fail against the code as reviewed).

B1: an exception from the adapter's ``stop`` escapes ``dispatch`` -> ``expire_if_due`` -> ``watch``; the
    watcher dies, the lease is left disarmed and the STOP is never retried.
B2: ``move`` params are not range-checked on the seam path (``dispatch`` / ``guarded_dispatch``); the limits
    exist only in ``pave_runtime.intent_schema`` (file-bus).

Local-only: fake clock and fake adapters, no hardware, no network.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from control_daemon.adapters import AdapterActionResult
from pave_runtime import lease as lease_module
from pave_runtime.intent_schema import VX_MAX, VX_MIN, YAW_MAX, YAW_MIN
from pave_runtime.lease import RETRY_TTL_S, BodyLease, guarded_dispatch
from pave_runtime.seam import dispatch


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class RaisingStopAdapter:
    """Records calls; ``stop`` raises ``stop_raises`` times, then succeeds."""

    name = "raising"
    capabilities = frozenset({"stop", "estop", "home", "trot", "move"})

    def __init__(self, stop_raises: int = 1) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.stop_raises = stop_raises
        self.stops_ok = 0

    def execute(self, action, params=None):
        self.calls.append((action, dict(params or {})))
        if action == "stop":
            if self.stop_raises > 0:
                self.stop_raises -= 1
                raise RuntimeError("serial link dropped")
            self.stops_ok += 1
        return AdapterActionResult.ok(detail={"ran": action})

    def actions(self) -> list[str]:
        return [a for a, _ in self.calls]


class AlwaysRaisingAdapter(RaisingStopAdapter):
    def execute(self, action, params=None):
        self.calls.append((action, dict(params or {})))
        raise RuntimeError("boom")


class B1DispatchAdapterExceptionTests(unittest.TestCase):
    def test_dispatch_turns_an_adapter_exception_into_a_failed_state(self):
        adapter = AlwaysRaisingAdapter()
        try:
            state = dispatch(adapter, "stop", {})
        except Exception as exc:  # noqa: BLE001 - this IS the bug being proven
            self.fail(f"dispatch let an adapter exception escape: {type(exc).__name__}: {exc}")
        self.assertEqual(state["status"], "failed")
        self.assertIn("boom", str(state.get("error")))


class B1ExpiryStopRaisesTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.lease = BodyLease(ttl_s=5.0, clock=self.clock)
        self.adapter = RaisingStopAdapter(stop_raises=1)
        guarded_dispatch(self.adapter, self.lease, "trot")
        self.clock.advance(5.0)

    def test_a_stop_that_raises_keeps_the_lease_armed_and_is_retried(self):
        raised = None
        try:
            self.lease.expire_if_due(self.adapter)
        except Exception as exc:  # noqa: BLE001
            raised = exc
        self.assertIsNone(raised, f"expire_if_due let the stop exception escape: {raised!r}")
        # the body may still be moving: the lease must keep protecting it
        self.assertEqual(self.lease.active_action(), "trot")
        # not due until the retry window passes, then the next poll issues a successful STOP
        self.clock.advance(RETRY_TTL_S)
        event = self.lease.expire_if_due(self.adapter)
        self.assertIsNotNone(event)
        self.assertEqual(event["stop"]["status"], "completed")
        self.assertEqual(self.adapter.stops_ok, 1)
        self.assertIsNone(self.lease.active_action())  # released only after a confirmed STOP

    def test_motion_after_a_raising_stop_is_not_left_running_without_a_lease(self):
        try:
            self.lease.expire_if_due(self.adapter)
        except Exception:  # noqa: BLE001
            pass
        # whatever happened, an unconfirmed STOP must not leave the body with no lease guarding it
        self.assertIsNotNone(self.lease.active_action(), "lease was disarmed although STOP never completed")


class B1WatchSurvivesTests(unittest.TestCase):
    def test_watch_survives_a_stop_exception_and_stops_the_body_on_retry(self):
        adapter = RaisingStopAdapter(stop_raises=1)
        lease = BodyLease(ttl_s=0.1)  # real clock, tiny TTL
        events: list[dict] = []
        result: dict = {}

        async def scenario():
            guarded_dispatch(adapter, lease, "trot")
            watcher = asyncio.ensure_future(lease.watch(adapter, poll_s=0.02, emit=events.append))
            await asyncio.sleep(0.6)  # TTL 0.1 s + retry window (patched to 0.1 s) + slack
            result["done"] = watcher.done()
            result["exc"] = watcher.exception() if watcher.done() and not watcher.cancelled() else None
            watcher.cancel()
            try:
                await watcher
            except BaseException:  # noqa: BLE001
                pass

        with mock.patch.object(lease_module, "RETRY_TTL_S", 0.1):
            asyncio.run(scenario())

        self.assertFalse(result["done"], f"watcher died: {result['exc']!r}")
        self.assertEqual(adapter.stops_ok, 1, "the STOP was never successfully retried")
        self.assertIsNone(lease.active_action())


class _MoveRecorder:
    name = "move-recorder"
    capabilities = frozenset({"stop", "trot", "move"})

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, action, params=None):
        self.calls.append((action, dict(params or {})))
        return AdapterActionResult.ok(detail={"ran": action})


_BAD_MOVES = {
    "vx_huge": {"vx": 1e9, "yaw": 0.0},
    "vx_just_over_max": {"vx": VX_MAX + 0.01, "yaw": 0.0},
    "vx_just_under_min": {"vx": VX_MIN - 0.01, "yaw": 0.0},
    "yaw_huge": {"vx": 0.0, "yaw": 1e9},
    "yaw_just_over_max": {"vx": 0.0, "yaw": YAW_MAX + 0.01},
    "yaw_just_under_min": {"vx": 0.0, "yaw": YAW_MIN - 0.01},
    "yaw_nan": {"vx": 0.1, "yaw": float("nan")},
    "vx_nan": {"vx": float("nan"), "yaw": 0.0},
    "vx_inf": {"vx": float("inf"), "yaw": 0.0},
    "vx_neg_inf": {"vx": float("-inf"), "yaw": 0.0},
    "yaw_inf": {"vx": 0.0, "yaw": float("inf")},
    "vx_string": {"vx": "fast", "yaw": 0.0},
    "yaw_string": {"vx": 0.0, "yaw": "left"},
    "vx_none": {"vx": None, "yaw": 0.0},
    "vx_list": {"vx": [0.1], "yaw": 0.0},
    "yaw_dict": {"vx": 0.0, "yaw": {"x": 1}},
}

_GOOD_MOVE = {"vx": 0.2, "yaw": 0.3}


class B2MoveRangeCheckTests(unittest.TestCase):
    def test_dispatch_rejects_bad_move_params_without_touching_the_adapter(self):
        for label, params in _BAD_MOVES.items():
            with self.subTest(case=label):
                adapter = _MoveRecorder()
                state = dispatch(adapter, "move", dict(params))
                self.assertEqual(state["status"], "rejected", f"{params!r} -> {state.get('status')}")
                self.assertEqual(adapter.calls, [], f"adapter.execute was called with {adapter.calls!r}")

    def test_guarded_dispatch_rejects_bad_move_params_without_touching_the_adapter(self):
        for label, params in _BAD_MOVES.items():
            with self.subTest(case=label):
                adapter = _MoveRecorder()
                lease = BodyLease(ttl_s=5.0, clock=FakeClock())
                state = guarded_dispatch(adapter, lease, "move", dict(params))
                self.assertEqual(state["status"], "rejected", f"{params!r} -> {state.get('status')}")
                self.assertEqual(adapter.calls, [], f"adapter.execute was called with {adapter.calls!r}")
                self.assertIsNone(lease.active_action(), "a rejected move must not arm the lease")

    def test_in_range_move_still_passes_through_dispatch(self):
        adapter = _MoveRecorder()
        state = dispatch(adapter, "move", dict(_GOOD_MOVE))
        self.assertEqual(state["status"], "completed")
        self.assertEqual([a for a, _ in adapter.calls], ["move"])

    def test_in_range_move_still_passes_through_guarded_dispatch(self):
        adapter = _MoveRecorder()
        lease = BodyLease(ttl_s=5.0, clock=FakeClock())
        state = guarded_dispatch(adapter, lease, "move", dict(_GOOD_MOVE))
        self.assertEqual(state["status"], "completed")
        self.assertEqual([a for a, _ in adapter.calls], ["move"])
        self.assertEqual(lease.active_action(), "move")

    def test_limits_themselves_are_accepted(self):
        for vx, yaw in ((VX_MAX, YAW_MAX), (VX_MIN, YAW_MIN), (0.0, 0.0)):
            with self.subTest(vx=vx, yaw=yaw):
                adapter = _MoveRecorder()
                state = dispatch(adapter, "move", {"vx": vx, "yaw": yaw})
                self.assertEqual(state["status"], "completed")


if __name__ == "__main__":
    unittest.main()
