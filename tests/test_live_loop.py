"""Local-only tests for the v1.8 live loop (scripts/run_live.py).

A scripted runtime, a trivial source, and a fake seam are injected into run_live, so the confirmation
gate, edge-triggering, watchdog auto-STOP, and shutdown STOP are exercised with no camera, model,
zenoh, or robot.
"""

from __future__ import annotations

import asyncio
import contextlib
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


class MotionGateRetryTests(unittest.TestCase):
    def test_undelivered_motion_is_offered_again_on_the_next_frame(self):
        g = MotionGate(confirmations=1, window_ms=1000, max_retries=3)
        self.assertEqual(g.admit("trot", 0), "trot")
        self.assertTrue(g.undelivered("trot"))
        self.assertEqual(g.admit("trot", 100), "trot")  # offered again
        g.delivered("trot")
        self.assertIsNone(g.admit("trot", 200))  # edge-triggered again

    def test_a_retry_after_the_confirmation_window_must_reconfirm(self):
        g = MotionGate(confirmations=2, window_ms=500, max_retries=3)
        g.admit("trot", 0)
        self.assertEqual(g.admit("trot", 100), "trot")
        g.undelivered("trot")
        self.assertIsNone(g.admit("trot", 5000))  # window blown: back to one sighting
        self.assertEqual(g.admit("trot", 5100), "trot")

    def test_motion_retries_are_bounded(self):
        g = MotionGate(confirmations=1, max_retries=2)
        results = []
        for t in range(5):
            if g.admit("trot", t * 10):
                results.append(g.undelivered("trot"))
        self.assertEqual(results, [True, True, False])  # two retries, then abandoned
        self.assertIsNone(g.admit("trot", 1000))  # abandoned: no more attempts for this episode

    def test_stop_retries_are_unbounded(self):
        g = MotionGate(confirmations=1, max_retries=1)
        g.admit("trot", 0)
        g.delivered("trot")
        outcomes = []
        for t in range(10):
            if g.admit("stop", 100 + t):
                outcomes.append(g.undelivered("stop"))
        self.assertEqual(outcomes, [True] * 10)

    def test_uncertain_motion_keeps_a_stop_owed(self):
        g = MotionGate(confirmations=1, max_retries=3)
        g.admit("trot", 0)
        self.assertTrue(g.undelivered("trot"))  # rolled back so it is retried...
        self.assertNotIn(g.current, ("trot", "move"))
        self.assertTrue(g.uncertain)  # ...but the body may be moving
        self.assertTrue(g.force_stop())  # so a STOP is still owed
        self.assertFalse(g.force_stop())  # and only once

    def test_an_abandoned_motion_still_owes_a_stop(self):
        g = MotionGate(confirmations=1, max_retries=0)
        g.admit("trot", 0)
        self.assertFalse(g.undelivered("trot"))  # out of retries: abandoned, `current` stays advanced
        self.assertEqual(g.current, "trot")
        self.assertTrue(g.force_stop())

    def test_a_stop_decision_is_resent_while_the_body_state_is_uncertain(self):
        g = MotionGate(confirmations=1, max_retries=3)
        g.admit("trot", 0)
        g.undelivered("trot")
        self.assertEqual(g.admit("stop", 10), "stop")  # decided STOP, but the body may be moving: send it
        g.delivered("stop")
        self.assertIsNone(g.admit("stop", 20))  # now known: edge-triggered again

    def test_stop_failed_after_a_watchdog_keeps_the_stop_owed(self):
        g = MotionGate(confirmations=1)
        g.admit("trot", 0)
        g.delivered("trot")
        self.assertTrue(g.force_stop())
        g.stop_failed()
        self.assertTrue(g.force_stop())  # still owed on the next failing tick / at shutdown

    def test_refusal_reported_as_delivered_clears_uncertainty(self):
        g = MotionGate(confirmations=1)
        g.admit("trot", 0)
        g.delivered("trot")
        self.assertFalse(g.uncertain)


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

    def test_a_stop_is_not_held_up_by_a_renewal_hanging_on_the_network(self):
        # The renewal send holds the send lock until it returns; a send to a dead link can take its whole
        # timeout. A STOP decided meanwhile must preempt it, not queue behind it.
        class HangingRenewal(FakeSeam):
            def __init__(self):
                super().__init__()
                self.trots = 0
                self.at = {}

            async def send(self, action, params=None, *, target=None, timeout=5.0):
                import time as _t
                if action == "trot":
                    self.trots += 1
                    if self.trots > 1:
                        await asyncio.sleep(3.0)  # every renewal hangs like a send to a dead link
                self.sent.append(action)
                self.at.setdefault(action, _t.monotonic())
                return {"status": "completed", "action": action}

        import time as _time
        seam = HangingRenewal()
        decided = {}

        class Rt(ScriptRuntime):
            async def infer(self, request):
                res = await super().infer(request)
                if res.text == "STOP" and "t" not in decided:
                    decided["t"] = _time.monotonic()
                return res

        asyncio.run(
            run_live(
                source=FakeSource(),
                runtime=Rt(["TROT", "TROT", "TROT", "STOP", "STOP", "STOP", "STOP"]),
                application=create_application_runtime("gesture_commander"),
                seam=seam,
                prompt="p",
                gate=MotionGate(confirmations=1),
                period_s=0.3,
                watchdog_s=2.0,
                lease_renew_s=0.2,
                max_ticks=7,
                emit=lambda r: None,
            )
        )
        delay = seam.at["stop"] - decided["t"]
        self.assertLess(delay, 0.5, f"the STOP waited {delay:.2f}s behind a hanging renewal")
        # and the preempted renewal was never delivered after the STOP
        self.assertEqual(seam.sent.count("trot"), 1)
        self.assertNotIn("trot", seam.sent[seam.sent.index("stop"):])

    def test_a_failed_motion_is_retried_a_bounded_number_of_times_never_renewed(self):
        # A failed start is re-sent (up to --dispatch-retries) as a fresh command, then abandoned; it is never
        # "renewed" — a half-started gait is left to the body's lease rather than kept alive.
        class TrotFails(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                status = "failed" if action == "trot" else "completed"
                return {"status": status, "action": action}

        seam = self._run_renewing(["TROT"] * 10, seam=TrotFails(), period_s=0.03, renew_s=0.01)
        self.assertEqual(seam.sent.count("trot"), 1 + 3)  # the first attempt + 3 retries, then it stops trying
        self.assertEqual(seam.sent[-1], "stop")  # and the shutdown STOP is still owed and sent

    # --- failed deliveries are retried (the gate used to mark an action "sent" before it was) --------

    def _run_gate(self, outputs, seam, *, retries=3, ticks=None, confirmations=1):
        records = []
        asyncio.run(
            run_live(
                source=FakeSource(),
                runtime=ScriptRuntime(outputs),
                application=create_application_runtime("gesture_commander"),
                seam=seam,
                prompt="p",
                gate=MotionGate(confirmations=confirmations, max_retries=retries),
                period_s=0.02,
                watchdog_s=1.0,
                lease_renew_s=0.01,
                max_ticks=ticks if ticks is not None else len(outputs),
                emit=records.append,
            )
        )
        return records

    def test_a_motion_whose_reply_was_lost_is_retried_until_delivered(self):
        class LoseFirstTwo(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                if action == "trot" and self.sent.count("trot") <= 2:
                    return {"status": "no_reply", "error": "timeout", "action": action}
                return {"status": "completed", "action": action}

        seam = LoseFirstTwo()
        records = self._run_gate(["TROT"] * 8, seam)
        self.assertGreaterEqual(seam.sent.count("trot"), 3)  # attempts 1,2 lost; 3 delivered
        deliveries = [r["delivery"] for r in records if r.get("dispatched") == "trot"]
        self.assertEqual(deliveries[:3], ["retry", "retry", "delivered"])
        self.assertNotIn("abandoned", deliveries)

    def test_after_a_retry_succeeds_the_loop_is_edge_triggered_again(self):
        class LoseFirst(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                if action == "trot" and self.sent.count("trot") == 1:
                    return {"status": "no_reply", "error": "timeout", "action": action}
                return {"status": "completed", "action": action}

        records = self._run_gate(["TROT"] * 10, LoseFirst())
        dispatches = [r for r in records if r.get("dispatched") == "trot"]
        self.assertEqual([d["delivery"] for d in dispatches], ["retry", "delivered"])  # exactly two commands

    def test_a_stop_that_was_not_delivered_is_retried_every_tick_until_it_is(self):
        class StopLostTwice(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                if action == "stop" and self.sent.count("stop") <= 2:
                    return {"status": "no_reply", "error": "timeout", "action": action}
                return {"status": "completed", "action": action}

        seam = StopLostTwice()
        records = self._run_gate(["TROT", "STOP", "STOP", "STOP", "STOP", "STOP"], seam)
        stops = [r for r in records if r.get("dispatched") == "stop" and "tick" in r]
        self.assertEqual([r["delivery"] for r in stops], ["retry", "retry", "delivered"])

    def test_a_transport_exception_does_not_kill_the_loop_and_is_retried(self):
        class Flaky(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                if action == "trot" and self.sent.count("trot") == 1:
                    raise RuntimeError("zenoh session failed")
                return {"status": "completed", "action": action}

        seam = Flaky()
        records = self._run_gate(["TROT"] * 6, seam)  # must not raise
        first = next(r for r in records if r.get("dispatched") == "trot")
        self.assertEqual(first["delivery"], "retry")
        self.assertEqual(first["state"]["status"], "error")
        self.assertGreaterEqual(seam.sent.count("trot"), 2)

    def test_a_definitive_refusal_is_not_retried(self):
        class CannotTrot(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                status = "unsupported" if action == "trot" else "completed"
                return {"status": status, "action": action}

        seam = CannotTrot()
        records = self._run_gate(["TROT"] * 6, seam)
        self.assertEqual(seam.sent.count("trot"), 1)  # asked once; retrying cannot change a "no"
        self.assertEqual(next(r["delivery"] for r in records if r.get("dispatched") == "trot"), "refused")

    def test_a_motion_whose_reply_was_lost_still_gets_a_shutdown_stop(self):
        # The send may have reached the body even though no reply came back. The gate rolled `current` back,
        # but the body may be moving — so the final STOP must still be sent.
        class AlwaysNoReply(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                if action == "trot":
                    return {"status": "no_reply", "error": "timeout", "action": action}
                return {"status": "completed", "action": action}

        seam = AlwaysNoReply()
        self._run_gate(["TROT"] * 2, seam, retries=3, confirmations=1)  # ends mid-retry, `current` rolled back
        self.assertEqual(seam.sent[-1], "stop")

    def test_a_watchdog_stop_that_fails_is_retried_and_stays_owed(self):
        class StopFailsFirst(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                if action == "stop" and self.sent.count("stop") == 1:
                    return {"status": "no_reply", "error": "timeout", "action": action}
                return {"status": "completed", "action": action}

        seam = StopFailsFirst()
        # TROT delivered, then observe/infer stalls twice: the 1st watchdog STOP is lost, the 2nd must go out
        records = self._run_gate(["TROT", "TROT", STALL, STALL, STALL], seam)
        watchdogs = [r for r in records if r.get("event") == "watchdog"]
        self.assertEqual(watchdogs[0]["state"]["status"], "no_reply")
        self.assertEqual(watchdogs[1]["dispatched"], "stop")  # retried on the next failing tick
        self.assertGreaterEqual(seam.sent.count("stop"), 2)

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


class LeaseLostTests(unittest.TestCase):
    """v1.8.5: a renewal can no longer restart a motion whose lease the body has already ended."""

    def _scenario(self, *, confirmations=2, confirmations_after_cut=None, cut_for=0.5, ttl=0.2, ticks_after=0.4):
        """Real BodyLease behind a cuttable link. Returns (body actions, brain records)."""
        from pave_runtime.lease import BodyLease, guarded_dispatch
        from tests.test_lease import RecordingAdapter

        body = RecordingAdapter()
        lease = BodyLease(ttl_s=ttl)
        records: list[dict] = []
        gate = MotionGate(confirmations=confirmations)

        class CuttableSeam(FakeSeam):
            reachable = True

            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                if not self.reachable:
                    return {"status": "no_reply", "error": "timeout", "action": action}
                return guarded_dispatch(body, lease, action, params)

        async def scenario():
            seam = CuttableSeam()
            watcher = asyncio.ensure_future(lease.watch(body, poll_s=0.01))
            task = asyncio.ensure_future(
                run_live(
                    source=FakeSource(),
                    runtime=ScriptRuntime(["TROT"] * 10000),
                    application=create_application_runtime("gesture_commander"),
                    seam=seam,
                    prompt="p",
                    gate=gate,
                    period_s=0.02,
                    watchdog_s=1.0,
                    lease_renew_s=0.05,
                    emit=records.append,
                )
            )
            await asyncio.sleep(0.3)  # moving, renewed
            if confirmations_after_cut is not None:
                gate.confirmations = confirmations_after_cut
            seam.reachable = False  # the link drops for longer than the lease
            await asyncio.sleep(cut_for)
            seam.reachable = True  # ...and comes back; the brain's renewals resume
            await asyncio.sleep(ticks_after)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopUnconfirmed):
                await task
            watcher.cancel()

        asyncio.run(scenario())
        return body.actions(), records

    def test_a_link_that_comes_back_after_the_lease_expired_does_not_restart_the_motion_by_itself(self):
        # Before v1.8.5 the first renewal after the outage was a bare `trot`, which the body started anew
        # with no decision behind it. Now the renewal is refused and the loop must re-confirm.
        actions, records = self._scenario(confirmations=1, confirmations_after_cut=500)  # no re-confirm in time
        self.assertEqual(actions[:2], ["trot", "stop"])  # started, then the BODY stopped itself
        self.assertEqual(actions.count("trot"), 1, actions)  # and nothing started it again
        events = [r["event"] for r in records if "event" in r]
        self.assertIn("lease_lost", events)
        self.assertEqual(events.count("lease_lost"), 1)  # it stopped renewing the dead lease

    def test_the_motion_is_restarted_only_after_it_is_confirmed_again(self):
        actions, records = self._scenario(confirmations=3)
        self.assertEqual(actions[:3], ["trot", "stop", "trot"], actions)  # a deliberate, re-confirmed restart
        lost_at = next(i for i, r in enumerate(records) if r.get("event") == "lease_lost")
        restarts = [r for r in records[lost_at:] if r.get("dispatched") == "trot"]
        self.assertEqual(len(restarts), 1)
        self.assertEqual(restarts[0]["confirm"], 3)  # it counted its way up again from zero

    def test_an_uninterrupted_motion_is_renewed_without_ever_being_re_commanded(self):
        from pave_runtime.lease import BodyLease, guarded_dispatch
        from tests.test_lease import RecordingAdapter

        body = RecordingAdapter()
        lease = BodyLease(ttl_s=0.2)

        class DirectSeam(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                return guarded_dispatch(body, lease, action, params)

        async def scenario():
            seam = DirectSeam()
            watcher = asyncio.ensure_future(lease.watch(body, poll_s=0.01))
            task = asyncio.ensure_future(
                run_live(
                    source=FakeSource(),
                    runtime=ScriptRuntime(["TROT"] * 10000),
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
            await asyncio.sleep(0.6)  # three TTLs
            moving = body.actions()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            watcher.cancel()
            return seam, moving

        seam, moving = asyncio.run(scenario())
        self.assertEqual(moving, ["trot"])  # one gait command; every renewal was a `renew`
        self.assertGreaterEqual(seam.sent.count("renew"), 5)
        self.assertEqual(body.actions(), ["trot", "stop"])

    def test_lease_lost_neither_sends_a_stop_nor_owes_one(self):
        gate = MotionGate(confirmations=1)
        self.assertEqual(gate.admit("trot", 0.0), "trot")
        gate.lease_lost()
        self.assertFalse(gate.force_stop())  # nothing owed at shutdown: the body already stopped itself

    def test_lease_lost_makes_the_next_motion_earn_its_confirmations_again(self):
        gate = MotionGate(confirmations=3, window_ms=100000)
        for t in (0, 1, 2):
            gate.admit("trot", float(t))
        self.assertEqual(gate.current, "trot")
        for t in (3, 4, 5, 6):  # a long run of "trot" decisions while it is moving
            self.assertIsNone(gate.admit("trot", float(t)))
        gate.lease_lost()
        self.assertIsNone(gate.admit("trot", 7.0))  # 1 of 3
        self.assertIsNone(gate.admit("trot", 8.0))  # 2 of 3
        self.assertEqual(gate.admit("trot", 9.0), "trot")  # 3 of 3

    def test_after_lease_lost_a_stop_decision_is_not_re_sent(self):
        gate = MotionGate(confirmations=1)
        gate.admit("trot", 0.0)
        gate.lease_lost()
        self.assertIsNone(gate.admit("stop", 1.0))  # already stopped: edge-triggered

    def test_a_body_older_than_v1_8_5_is_renewed_the_legacy_way_and_flagged(self):
        # The fake body gives no lease_id, like a pre-v1.8.5 body.
        seam = FakeSeam()
        records: list[dict] = []
        asyncio.run(
            run_live(
                source=FakeSource(),
                runtime=ScriptRuntime(["TROT"] * 8),
                application=create_application_runtime("gesture_commander"),
                seam=seam,
                prompt="p",
                gate=MotionGate(confirmations=1),
                period_s=0.04,
                watchdog_s=1.0,
                lease_renew_s=0.02,
                max_ticks=8,
                emit=records.append,
            )
        )
        self.assertGreaterEqual(seam.sent.count("trot"), 4)  # the motion re-sent as before
        self.assertNotIn("renew", seam.sent)
        self.assertIn("lease_legacy_body", [r.get("event") for r in records])

    def test_a_body_that_does_not_know_renew_is_downgraded_to_the_legacy_resend(self):
        class RenewUnsupported(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                if action == "renew":
                    return {"status": "unsupported", "action": "renew"}
                return {"status": "completed", "action": action, "detail": {"lease_id": "L1"}}

        seam = RenewUnsupported()
        records: list[dict] = []
        asyncio.run(
            run_live(
                source=FakeSource(),
                runtime=ScriptRuntime(["TROT"] * 10),
                application=create_application_runtime("gesture_commander"),
                seam=seam,
                prompt="p",
                gate=MotionGate(confirmations=1),
                period_s=0.04,
                watchdog_s=1.0,
                lease_renew_s=0.02,
                max_ticks=10,
                emit=records.append,
            )
        )
        self.assertEqual(seam.sent.count("renew"), 1)  # tried once, then gave up on the verb
        self.assertGreaterEqual(seam.sent.count("trot"), 4)  # ...and kept the motion alive the old way
        events = [r.get("event") for r in records]
        self.assertEqual(events.count("renew_downgraded"), 1)
        self.assertNotIn("renew_failed", events)

    def test_a_lost_renewal_reply_is_a_failure_not_a_lost_lease(self):
        # no_reply is ambiguous (the body may or may not have it): keep renewing, don't forget the motion
        class FlakyRenew(FakeSeam):
            async def send(self, action, params=None, *, target=None, timeout=5.0):
                self.sent.append(action)
                if action == "renew":
                    return {"status": "no_reply", "error": "timeout", "action": action}
                return {"status": "completed", "action": action, "detail": {"lease_id": "L1"}}

        seam = FlakyRenew()
        records: list[dict] = []
        asyncio.run(
            run_live(
                source=FakeSource(),
                runtime=ScriptRuntime(["TROT"] * 10),
                application=create_application_runtime("gesture_commander"),
                seam=seam,
                prompt="p",
                gate=MotionGate(confirmations=1),
                period_s=0.04,
                watchdog_s=1.0,
                lease_renew_s=0.02,
                max_ticks=10,
                emit=records.append,
            )
        )
        events = [r.get("event") for r in records]
        self.assertGreaterEqual(events.count("renew_failed"), 3)
        self.assertNotIn("lease_lost", events)
        self.assertGreaterEqual(seam.sent.count("renew"), 4)  # still trying


if __name__ == "__main__":
    unittest.main()
