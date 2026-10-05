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
from pave_runtime.shutdown import StopUnconfirmed
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

    # --- body dead-man lease: the brain must keep renewing an active motion --------------------

    def _run_renewing(self, outputs, *, seam=None, renew_s=0.02, period_s=0.04, ticks=None):
        seam = seam or FakeSeam()
        asyncio.run(
            run_live(
                source=FakeSource(),
                runtime=ScriptRuntime(outputs),
                application=create_application_runtime("gesture_commander"),
                seam=seam,
                prompt="p",
                gate=MotionGate(confirmations=1),
                period_s=period_s,
                watchdog_s=1.0,
                lease_renew_s=renew_s,
                max_ticks=ticks if ticks is not None else len(outputs),
                emit=lambda r: None,
            )
        )
        return seam

    def test_an_active_motion_is_renewed_so_the_body_lease_does_not_run_out(self):
        seam = self._run_renewing(["TROT"] * 8)  # ~0.3 s of motion, renewing every 20 ms
        trots = seam.sent.count("trot")
        self.assertGreaterEqual(trots, 4)  # the initial command plus several renewals
        self.assertEqual(seam.sent[-1], "stop")  # and the shutdown STOP

    def test_no_renewal_when_nothing_is_moving(self):
        seam = self._run_renewing(["STOP"] * 8)
        self.assertEqual(seam.sent, ["stop"])  # one edge-triggered stop, no trot renewals

    def test_renewals_stop_once_the_loop_decides_to_stop(self):
        seam = self._run_renewing(["TROT", "TROT", "STOP", "STOP", "STOP", "STOP"], period_s=0.05)
        stop_at = seam.sent.index("stop")
        self.assertNotIn("trot", seam.sent[stop_at:])  # nothing re-starts the body after the STOP

    def test_a_renewal_cannot_land_after_a_stop_while_the_stop_awaits_its_reply(self):
        # Real zenoh send = settle, then `put` (DELIVERED), then wait for the reply. Model a STOP that is
        # delivered at once but whose reply is slow: renewals decided in that window must not be sent,
        # or they would be delivered AFTER the STOP and restart the body.
        class SlowStopReply(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)  # delivered now
                if action == "stop":
                    await asyncio.sleep(0.15)  # ...reply slow; many renew intervals pass
                return {"status": "completed", "action": action}

        seam = self._run_renewing(["TROT", "TROT", "STOP", "STOP"], seam=SlowStopReply(), period_s=0.05)
        stop_at = seam.sent.index("stop")
        self.assertNotIn("trot", seam.sent[stop_at:])

    def test_a_renewal_already_in_flight_is_delivered_before_a_later_stop(self):
        # The opposite order: a slow renewal is mid-flight (delivered late) when the loop decides to
        # STOP. The STOP must wait its turn, otherwise it is delivered first and the late renewal then
        # restarts the body.
        class SlowRenewal(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                if action == "trot" and "trot" in self.sent:  # a renewal (the first trot is the command)
                    await asyncio.sleep(0.12)  # settle: delivered late
                self.sent.append(action)
                return {"status": "completed", "action": action}

        # timeline: command at t=0; a renewal is in flight from ~0.02 s to ~0.14 s; the loop decides STOP
        # at tick 3 (t=0.10 s) — squarely inside that window
        seam = self._run_renewing(
            ["TROT", "TROT", "STOP", "STOP", "STOP", "STOP"], seam=SlowRenewal(), renew_s=0.02, period_s=0.05
        )
        stop_at = seam.sent.index("stop")
        self.assertNotIn("trot", seam.sent[stop_at:])  # nothing delivered after the STOP

    def test_a_failed_motion_is_not_renewed(self):
        # a half-started gait must be left to the body's lease, not kept alive by renewals
        class TrotFails(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                status = "failed" if action == "trot" else "completed"
                return {"status": status, "action": action}

        seam = self._run_renewing(["TROT"] * 8, seam=TrotFails())
        self.assertEqual(seam.sent.count("trot"), 1)

    def test_a_renewal_that_raises_does_not_kill_the_loop(self):
        class RenewalsFail(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                if action == "trot" and self.sent.count("trot") > 1:
                    raise RuntimeError("network blip")
                return {"status": "completed", "action": action}

        seam = self._run_renewing(["TROT"] * 8, seam=RenewalsFail())
        self.assertEqual(seam.sent[-1], "stop")  # still ended with the shutdown STOP

    def test_the_body_stops_itself_when_the_brain_can_no_longer_reach_it(self):
        # End to end with the REAL lease. The network is cut mid-motion: nothing the brain sends reaches
        # the body any more — not renewals, and not even its final STOP. Only the body-side dead-man
        # can stop the motion, and it must.
        from pave_runtime.lease import BodyLease, guarded_dispatch
        from tests.test_lease import RecordingAdapter

        body = RecordingAdapter()
        lease = BodyLease(ttl_s=0.2)

        class CuttableSeam(FakeSeam):
            reachable = True

            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                if not self.reachable:
                    return {"status": "no_reply", "error": "timeout", "action": action}
                return guarded_dispatch(body, lease, action, params)

        async def scenario():
            seam = CuttableSeam()
            watcher = asyncio.ensure_future(lease.watch(body, poll_s=0.02))
            task = asyncio.ensure_future(
                run_live(
                    source=FakeSource(),
                    runtime=ScriptRuntime(["TROT"] * 1000),
                    application=create_application_runtime("gesture_commander"),
                    seam=seam,
                    prompt="p",
                    gate=MotionGate(confirmations=1),
                    period_s=0.02,
                    watchdog_s=1.0,
                    lease_renew_s=0.05,
                    emit=lambda r: None,
                )
            )
            await asyncio.sleep(0.5)  # 2.5 TTLs of motion: only the renewals keep the body going
            moving_actions = list(body.actions())
            seam.reachable = False  # the link drops
            await asyncio.sleep(0.5)  # > 2 TTLs with no renewal reaching the body
            stopped_actions = list(body.actions())
            task.cancel()  # the brain's own shutdown STOP is lost too
            with self.assertRaises(StopUnconfirmed):
                await task
            watcher.cancel()
            return moving_actions, stopped_actions

        moving, stopped = asyncio.run(scenario())
        self.assertEqual(moving, ["trot"])  # renewed for 2.5 TTLs, never stopped, never re-commanded
        self.assertEqual(stopped, ["trot", "stop"])  # then the BODY stopped itself

    def test_unconfirmed_shutdown_stop_is_loud(self):
        # if the final STOP cannot be confirmed the body may still be moving: raise, don't swallow
        class StopFails(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                if action == "stop":
                    return {"status": "failed", "action": "stop"}
                return {"status": "completed", "action": action}

        seam = StopFails()
        with self.assertRaises(StopUnconfirmed) as ctx:
            asyncio.run(
                run_live(
                    source=FakeSource(),
                    runtime=ScriptRuntime(["TROT", "TROT"]),
                    application=create_application_runtime("gesture_commander"),
                    seam=seam,
                    prompt="p",
                    gate=MotionGate(confirmations=2),
                    watchdog_s=1.0,
                    max_ticks=2,
                    emit=lambda r: None,
                )
            )
        self.assertEqual(seam.sent, ["trot", "stop"])  # it did try to STOP
        self.assertEqual(ctx.exception.state["status"], "failed")

    def test_stop_that_raises_is_loud_too(self):
        class StopRaises(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                if action == "stop":
                    raise RuntimeError("transport down")
                return {"status": "completed", "action": action}

        with self.assertRaises(StopUnconfirmed):
            asyncio.run(
                run_live(
                    source=FakeSource(),
                    runtime=ScriptRuntime(["TROT", "TROT"]),
                    application=create_application_runtime("gesture_commander"),
                    seam=StopRaises(),
                    prompt="p",
                    gate=MotionGate(confirmations=2),
                    watchdog_s=1.0,
                    max_ticks=2,
                    emit=lambda r: None,
                )
            )

    def test_cancellation_mid_motion_still_stops_the_body(self):
        # what a SIGTERM/SIGHUP does: cancel the loop task while the body is moving
        async def scenario():
            seam = FakeSeam()
            task = asyncio.ensure_future(
                run_live(
                    source=FakeSource(),
                    runtime=ScriptRuntime(["TROT"] * 1000),
                    application=create_application_runtime("gesture_commander"),
                    seam=seam,
                    prompt="p",
                    gate=MotionGate(confirmations=1),
                    period_s=0.01,
                    watchdog_s=1.0,
                    emit=lambda r: None,
                )
            )
            while "trot" not in seam.sent:
                await asyncio.sleep(0.005)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            return seam

        seam = asyncio.run(scenario())
        self.assertEqual(seam.sent[-1], "stop")

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
