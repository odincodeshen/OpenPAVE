"""Local-only tests for the body-side motion lease (pave_runtime.lease): the dead-man switch.

A leased motion (trot/move) that the brain stops renewing must be STOPped by the BODY itself. The lease
is driven here with a fake clock and a recording adapter — no zenoh, no robot, no real waiting (except
one test of the real watch loop at a tiny TTL).
"""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest import mock

from control_daemon.adapters import AdapterActionResult
from pave_runtime.lease import (
    DEFAULT_TTL_S,
    BodyLease,
    guarded_dispatch,
    safe_stop,
)
from pave_runtime.shutdown import StopUnconfirmed


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class RecordingAdapter:
    """A body that records what it was asked to do; can be told to fail specific actions."""

    name = "recording"
    capabilities = frozenset({"stop", "estop", "home", "trot", "move"})

    def __init__(self, fail: set[str] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail = fail or set()

    def execute(self, action, params=None):
        self.calls.append((action, dict(params or {})))
        if action in self.fail:
            return AdapterActionResult.failed(f"{action} failed")
        return AdapterActionResult.ok(detail={"ran": action})

    def actions(self) -> list[str]:
        return [a for a, _ in self.calls]


def _lease(ttl=5.0):
    clock = FakeClock()
    return BodyLease(ttl_s=ttl, clock=clock), clock


class GuardedDispatchTests(unittest.TestCase):
    def setUp(self):
        self.adapter = RecordingAdapter()
        self.lease, self.clock = _lease()

    def send(self, action, params=None):
        return guarded_dispatch(self.adapter, self.lease, action, params)

    def test_trot_runs_and_arms_the_lease(self):
        state = self.send("trot")
        self.assertEqual(state["status"], "completed")
        self.assertEqual(self.adapter.actions(), ["trot"])
        self.assertEqual(self.lease.active_action(), "trot")
        self.assertEqual(state["detail"]["lease_ttl_s"], 5.0)

    def test_action_name_is_normalized_like_the_capability_schema(self):
        self.send("  TROT ")
        self.assertEqual(self.lease.active_action(), "trot")

    def test_resending_the_same_motion_renews_without_touching_the_adapter(self):
        self.send("trot")
        self.clock.advance(4.0)
        state = self.send("trot")  # a renewal
        self.assertTrue(state["detail"]["renewed"])
        self.assertEqual(state["status"], "completed")
        self.assertEqual(self.adapter.actions(), ["trot"])  # no second gait command
        self.assertAlmostEqual(self.lease.remaining(), 5.0)  # the deadline moved out again

    def test_changed_params_are_a_new_motion_not_a_renewal(self):
        self.send("move", {"vx": 0.1})
        self.send("move", {"vx": 0.9})
        self.assertEqual(self.adapter.actions(), ["move", "move"])

    def test_a_different_motion_replaces_the_lease(self):
        self.send("trot")
        self.send("move", {"vx": 0.2})
        self.assertEqual(self.lease.active_action(), "move")
        self.assertEqual(self.adapter.actions(), ["trot", "move"])

    def test_stop_releases_the_lease(self):
        self.send("trot")
        self.send("stop")
        self.assertIsNone(self.lease.active_action())
        self.assertFalse(self.lease.expired())

    def test_a_failed_stop_keeps_the_lease_armed(self):
        adapter = RecordingAdapter(fail={"stop"})
        lease, _ = _lease()
        guarded_dispatch(adapter, lease, "trot")
        state = guarded_dispatch(adapter, lease, "stop")
        self.assertEqual(state["status"], "failed")
        self.assertEqual(lease.active_action(), "trot")  # still protected: the expiry will retry

    def test_a_failed_motion_still_arms_the_lease(self):
        # a half-started gait may be moving; the lease will STOP it
        adapter = RecordingAdapter(fail={"trot"})
        lease, _ = _lease()
        state = guarded_dispatch(adapter, lease, "trot")
        self.assertEqual(state["status"], "failed")
        self.assertEqual(lease.active_action(), "trot")

    def test_unsupported_or_rejected_motion_does_not_arm(self):
        adapter = RecordingAdapter()
        adapter.capabilities = frozenset({"stop"})  # cannot trot
        lease, _ = _lease()
        state = guarded_dispatch(adapter, lease, "trot")
        self.assertEqual(state["status"], "unsupported")
        self.assertIsNone(lease.active_action())
        self.assertEqual(guarded_dispatch(adapter, lease, "")["status"], "rejected")
        self.assertIsNone(lease.active_action())

    def test_home_neither_arms_nor_releases(self):
        self.send("trot")
        self.send("home")
        self.assertEqual(self.lease.active_action(), "trot")  # home does not release (adapter-specific)
        other, _ = _lease()
        guarded_dispatch(RecordingAdapter(), other, "home")
        self.assertIsNone(other.active_action())


class ExpiryTests(unittest.TestCase):
    def setUp(self):
        self.adapter = RecordingAdapter()
        self.lease, self.clock = _lease(ttl=5.0)

    def test_nothing_is_due_before_the_ttl(self):
        guarded_dispatch(self.adapter, self.lease, "trot")
        self.clock.advance(4.9)
        self.assertFalse(self.lease.expired())
        self.assertIsNone(self.lease.expire_if_due(self.adapter))
        self.assertEqual(self.adapter.actions(), ["trot"])

    def test_the_body_stops_itself_when_the_lease_runs_out(self):
        guarded_dispatch(self.adapter, self.lease, "trot")
        self.clock.advance(5.0)
        self.assertTrue(self.lease.expired())
        event = self.lease.expire_if_due(self.adapter)
        self.assertEqual(self.adapter.actions(), ["trot", "stop"])  # the body issued the STOP
        self.assertEqual(event["event"], "lease_expired")
        self.assertEqual(event["stop"]["status"], "completed")
        self.assertIsNone(self.lease.active_action())  # released after a good STOP

    def test_renewals_keep_the_motion_alive_indefinitely(self):
        guarded_dispatch(self.adapter, self.lease, "trot")
        for _ in range(10):  # 10 x 3 s = 30 s of motion on a 5 s lease
            self.clock.advance(3.0)
            self.assertIsNone(self.lease.expire_if_due(self.adapter))
            guarded_dispatch(self.adapter, self.lease, "trot")
        self.assertEqual(self.adapter.actions(), ["trot"])  # never stopped, never re-commanded

    def test_a_missed_renewal_stops_the_body_even_after_good_ones(self):
        guarded_dispatch(self.adapter, self.lease, "trot")
        self.clock.advance(3.0)
        guarded_dispatch(self.adapter, self.lease, "trot")  # renewed
        self.clock.advance(5.0)  # then the brain goes silent (kill -9 / network drop)
        self.assertIsNotNone(self.lease.expire_if_due(self.adapter))
        self.assertEqual(self.adapter.actions(), ["trot", "stop"])

    def test_a_failed_expiry_stop_is_retried(self):
        adapter = RecordingAdapter(fail={"stop"})
        lease, clock = _lease()
        guarded_dispatch(adapter, lease, "trot")
        clock.advance(5.0)
        first = lease.expire_if_due(adapter)
        self.assertEqual(first["stop"]["status"], "failed")
        self.assertIsNone(lease.expire_if_due(adapter))  # not yet: a short retry window
        clock.advance(1.0)
        self.assertIsNotNone(lease.expire_if_due(adapter))  # tries again
        self.assertEqual(adapter.actions().count("stop"), 2)

    def test_no_lease_no_expiry(self):
        self.assertFalse(self.lease.expired())
        self.assertIsNone(self.lease.expire_if_due(self.adapter))


class WatchLoopTests(unittest.TestCase):
    def test_the_real_watch_loop_stops_an_unrenewed_motion(self):
        adapter = RecordingAdapter()
        lease = BodyLease(ttl_s=0.15)  # real clock, tiny TTL
        events: list[dict] = []

        async def scenario():
            guarded_dispatch(adapter, lease, "trot")
            watcher = asyncio.ensure_future(lease.watch(adapter, poll_s=0.02, emit=events.append))
            await asyncio.sleep(0.6)  # the brain never renews
            watcher.cancel()

        asyncio.run(scenario())
        self.assertEqual(adapter.actions(), ["trot", "stop"])
        self.assertEqual(events[0]["event"], "lease_expired")

    def test_the_real_watch_loop_leaves_a_renewed_motion_alone(self):
        adapter = RecordingAdapter()
        lease = BodyLease(ttl_s=0.2)

        async def scenario():
            guarded_dispatch(adapter, lease, "trot")
            watcher = asyncio.ensure_future(lease.watch(adapter, poll_s=0.02))
            for _ in range(8):  # renew every 50 ms for 400 ms (twice the TTL)
                await asyncio.sleep(0.05)
                guarded_dispatch(adapter, lease, "trot")
            watcher.cancel()

        asyncio.run(scenario())
        self.assertEqual(adapter.actions(), ["trot"])


class ConfigTests(unittest.TestCase):
    def test_default_ttl_is_five_seconds(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BODY_MOTION_TTL_S", None)
            self.assertEqual(BodyLease().ttl_s, DEFAULT_TTL_S)
            self.assertEqual(DEFAULT_TTL_S, 5.0)

    def test_env_overrides_the_ttl(self):
        with mock.patch.dict(os.environ, {"BODY_MOTION_TTL_S": "2.5"}):
            self.assertEqual(BodyLease().ttl_s, 2.5)

    def test_a_bad_or_non_positive_env_falls_back_to_the_default(self):
        for bad in ("abc", "0", "-3", ""):
            with self.subTest(value=bad), mock.patch.dict(os.environ, {"BODY_MOTION_TTL_S": bad}):
                self.assertEqual(BodyLease().ttl_s, DEFAULT_TTL_S)


class SafeStopTests(unittest.TestCase):
    def test_safe_stop_stops_the_actuator(self):
        adapter = RecordingAdapter()
        state = safe_stop(adapter)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(adapter.actions(), ["stop"])

    def test_safe_stop_raises_when_the_stop_does_not_complete(self):
        with self.assertRaises(StopUnconfirmed) as ctx:
            safe_stop(RecordingAdapter(fail={"stop"}))
        self.assertEqual(ctx.exception.state["status"], "failed")

    def test_adapters_without_a_stop_have_nothing_to_make_safe(self):
        adapter = RecordingAdapter()
        adapter.capabilities = frozenset({"get_image"})  # e.g. a camera
        self.assertIsNone(safe_stop(adapter))
        self.assertEqual(adapter.calls, [])


if __name__ == "__main__":
    unittest.main()
