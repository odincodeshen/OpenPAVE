"""Local-only tests for the v1.8 live loop (scripts/run_live.py).

A scripted runtime, a trivial source, and a fake seam are injected into run_live, so the confirmation
gate, edge-triggering, watchdog auto-STOP, and shutdown STOP are exercised with no camera, model,
zenoh, or robot.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from pave_runtime.application import create_application_runtime
from pave_runtime.inference import InferenceResult, Observation
from scripts.run_live import MotionGate, run_live

STALL = object()


class FakeSource:
    async def capture(self):
        return Observation("application/x-test", b"")


class ScriptRuntime:
    """Returns a scripted model text per tick; STALL raises to exercise the watchdog."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.i = 0

    async def infer(self, request):
        out = self.outputs[self.i]
        self.i += 1
        if out is STALL:
            raise asyncio.TimeoutError("stall")
        return InferenceResult(backend="fake", text=out, latency_ms=0.0)


class FakeSeam:
    def __init__(self):
        self.sent: list[str] = []
        self.targets: list = []

    async def send(self, action, params=None, *, target=None, timeout=5.0):
        self.sent.append(action)
        self.targets.append(target)
        return {"status": "completed", "action": action}


def _drive(outputs, confirmations=2):
    seam = FakeSeam()
    records: list[dict] = []
    asyncio.run(
        run_live(
            source=FakeSource(),
            runtime=ScriptRuntime(outputs),
            application=create_application_runtime("gesture_commander"),
            seam=seam,
            prompt="p",
            gate=MotionGate(confirmations=confirmations),
            target="dog-A",
            watchdog_s=1.0,
            max_ticks=len(outputs),
            emit=records.append,
        )
    )
    return seam, records


class MotionGateTests(unittest.TestCase):
    def test_motion_needs_consecutive_confirmations(self):
        g = MotionGate(confirmations=2, window_ms=1000)
        self.assertIsNone(g.admit("trot", 0))            # 1st sighting
        self.assertEqual(g.admit("trot", 100), "trot")   # 2nd -> confirmed, dispatch
        self.assertIsNone(g.admit("trot", 200))          # already trotting (edge)

    def test_window_expiry_resets_count(self):
        g = MotionGate(confirmations=2, window_ms=500)
        self.assertIsNone(g.admit("trot", 0))
        self.assertIsNone(g.admit("trot", 2000))         # window blown -> back to count 1
        self.assertEqual(g.admit("trot", 2100), "trot")  # 2nd within the new window

    def test_immediate_verbs_dispatch_without_confirmation(self):
        g = MotionGate(confirmations=3)
        self.assertEqual(g.admit("stop", 0), "stop")
        self.assertIsNone(g.admit("stop", 10))           # edge: already stopped

    def test_stop_interrupts_a_pending_motion(self):
        g = MotionGate(confirmations=2)
        self.assertIsNone(g.admit("trot", 0))            # confirming, not yet moving
        self.assertEqual(g.admit("stop", 10), "stop")
        self.assertEqual(g.count, 0)

    def test_force_stop_reports_motion(self):
        g = MotionGate(confirmations=1)
        g.admit("trot", 0)                                # confirmations=1 -> dispatched
        self.assertTrue(g.force_stop())
        self.assertFalse(g.force_stop())                 # already stopped


class LiveLoopTests(unittest.TestCase):
    def test_trot_after_confirmation_then_stop(self):
        seam, _ = _drive(["TROT", "TROT", "STOP"])
        self.assertEqual(seam.sent, ["trot", "stop"])
        self.assertEqual(seam.targets, ["dog-A", "dog-A"])

    def test_edge_triggered_no_duplicate_dispatch(self):
        seam, _ = _drive(["TROT", "TROT", "TROT", "TROT"])
        # one confirmed trot, then a shutdown STOP (still moving when the bounded run ends)
        self.assertEqual(seam.sent, ["trot", "stop"])

    def test_stall_while_moving_triggers_stop(self):
        seam, records = _drive(["TROT", "TROT", STALL])
        self.assertEqual(seam.sent, ["trot", "stop"])
        self.assertTrue(any(r.get("event") == "watchdog" for r in records))

    def test_shutdown_always_stops_active_motion(self):
        seam, _ = _drive(["TROT", "TROT"])               # run ends while trotting
        self.assertEqual(seam.sent[-1], "stop")

    def test_unconfirmed_motion_is_never_dispatched(self):
        seam, _ = _drive(["TROT", "STOP"])               # trot seen once, never confirmed
        self.assertEqual(seam.sent, ["stop"])            # only the immediate stop

    def test_no_spurious_stop_when_already_stopped(self):
        seam, _ = _drive(["banana", "banana"])           # invalid -> gesture_commander stop
        self.assertEqual(seam.sent, ["stop"])            # dispatched once; no shutdown re-STOP

    def test_error_ticks_are_paced_not_hot_looped(self):
        # a persistent inference failure must still honor --period-seconds, not spin
        sleeps: list[float] = []

        async def fake_sleep(d):
            sleeps.append(d)

        with mock.patch("scripts.run_live.asyncio.sleep", fake_sleep):
            asyncio.run(
                run_live(
                    source=FakeSource(),
                    runtime=ScriptRuntime([STALL, STALL, STALL]),
                    application=create_application_runtime("gesture_commander"),
                    seam=FakeSeam(),
                    prompt="p",
                    gate=MotionGate(confirmations=2),
                    period_s=2.0,
                    watchdog_s=1.0,
                    max_ticks=3,
                    emit=lambda r: None,
                )
            )
        self.assertEqual(len(sleeps), 3)                 # one pacing sleep per (failed) tick
        self.assertTrue(all(abs(s - 2.0) < 0.5 for s in sleeps))


if __name__ == "__main__":
    unittest.main()
