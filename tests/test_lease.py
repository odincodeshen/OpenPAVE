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
    LeaseClient,
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
        self.send("move", {"vx": 0.4})
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

    def test_a_repeat_of_a_failed_motion_runs_again_instead_of_renewing(self):
        # The brain re-sends a motion whose first attempt failed. The body must run it again, not answer
        # "completed (renewed)" for a half-started gait that never started cleanly.
        class FailsOnce(RecordingAdapter):
            def execute(self, action, params=None):
                self.calls.append((action, dict(params or {})))
                if action == "trot" and self.actions().count("trot") == 1:
                    return AdapterActionResult.failed("trot failed")
                return AdapterActionResult.ok(detail={"ran": action})

        adapter = FailsOnce()
        lease, _ = _lease()
        first = guarded_dispatch(adapter, lease, "trot")
        self.assertEqual(first["status"], "failed")
        self.assertEqual(lease.active_action(), "trot")  # still armed: a half-started gait must be STOPped
        second = guarded_dispatch(adapter, lease, "trot")
        self.assertEqual(adapter.actions(), ["trot", "trot"])  # it really ran again
        self.assertNotIn("renewed", second["detail"])
        self.assertEqual(second["status"], "completed")
        third = guarded_dispatch(adapter, lease, "trot")  # now healthy: THIS is a renewal
        self.assertTrue(third["detail"]["renewed"])
        self.assertEqual(adapter.actions(), ["trot", "trot"])

    def test_a_failed_motion_is_still_stopped_when_its_lease_runs_out(self):
        adapter = RecordingAdapter(fail={"trot"})
        lease, clock = _lease()
        guarded_dispatch(adapter, lease, "trot")
        clock.advance(5.0)
        self.assertIsNotNone(lease.expire_if_due(adapter))
        self.assertEqual(adapter.actions(), ["trot", "stop"])

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


class RenewVerbTests(unittest.TestCase):
    """v1.8.5: renewal is its own verb. It can extend a running lease and can never start a motion."""

    def setUp(self):
        self.adapter = RecordingAdapter()
        self.lease, self.clock = _lease()

    def send(self, action, params=None):
        return guarded_dispatch(self.adapter, self.lease, action, params)

    def start_trot(self):
        state = self.send("trot")
        return state["detail"]["lease_id"]

    def renew(self, lease_id):
        return self.send("renew", {"lease_id": lease_id})

    def test_starting_a_motion_returns_a_lease_id(self):
        state = self.send("trot")
        self.assertIsInstance(state["detail"]["lease_id"], str)
        self.assertTrue(state["detail"]["lease_id"])

    def test_a_failed_motion_is_guarded_but_gets_no_lease_id(self):
        adapter = RecordingAdapter(fail={"trot"})
        state = guarded_dispatch(adapter, self.lease, "trot")
        self.assertEqual(state["status"], "failed")
        self.assertNotIn("lease_id", state["detail"])
        self.assertEqual(self.lease.active_action(), "trot")  # still armed: it may be half-moving

    def test_renew_extends_the_lease_and_never_touches_the_adapter(self):
        lease_id = self.start_trot()
        self.clock.advance(4.0)
        state = self.renew(lease_id)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["detail"]["lease_id"], lease_id)
        self.assertEqual(self.adapter.actions(), ["trot"])  # no second gait command
        self.clock.advance(4.0)  # 8 s after the start, 4 s after the renewal: still inside the TTL
        self.assertFalse(self.lease.expired())

    def test_renew_keeps_the_same_lease_id(self):
        lease_id = self.start_trot()
        self.renew(lease_id)
        self.assertEqual(self.renew(lease_id)["status"], "completed")
        self.assertEqual(self.lease.lease_id(), lease_id)

    def test_renew_after_the_lease_expired_is_lease_lost_and_does_not_restart_the_motion(self):
        lease_id = self.start_trot()
        self.clock.advance(6.0)
        self.assertIsNotNone(self.lease.expire_if_due(self.adapter))  # the body stops itself
        self.assertEqual(self.adapter.actions(), ["trot", "stop"])
        state = self.renew(lease_id)
        self.assertEqual(state["status"], "lease_lost")
        self.assertEqual(state["detail"]["reason"], "expired")
        self.assertEqual(self.adapter.actions(), ["trot", "stop"])  # THE point: nothing started again
        self.assertIsNone(self.lease.active_action())

    def test_renew_past_the_deadline_but_before_the_watcher_ran_does_not_resurrect_the_lease(self):
        lease_id = self.start_trot()
        self.clock.advance(5.05)  # expired, the watcher has not polled yet
        state = self.renew(lease_id)
        self.assertEqual(state["status"], "lease_lost")
        self.assertEqual(state["detail"]["reason"], "expired")
        self.assertTrue(self.lease.expired())  # still due: the watcher will STOP the body
        self.lease.expire_if_due(self.adapter)
        self.assertEqual(self.adapter.actions(), ["trot", "stop"])

    def test_a_delayed_renewal_arriving_after_a_stop_is_harmless(self):
        lease_id = self.start_trot()
        self.send("stop")
        state = self.renew(lease_id)
        self.assertEqual(state["status"], "lease_lost")
        self.assertEqual(state["detail"]["reason"], "stopped")
        self.assertEqual(self.adapter.actions(), ["trot", "stop"])

    def test_a_renewal_for_an_old_lease_cannot_extend_a_newer_one(self):
        old = self.start_trot()
        self.send("stop")
        new = self.start_trot()
        self.assertNotEqual(old, new)
        self.clock.advance(4.0)
        self.assertEqual(self.renew(old)["status"], "lease_lost")
        self.clock.advance(2.0)  # 6 s after the new motion started: it must still expire on schedule
        self.assertTrue(self.lease.expired())

    def test_a_different_motion_supersedes_the_lease(self):
        first = self.send("trot")["detail"]["lease_id"]
        self.send("move", {"vx": 0.5})
        state = self.renew(first)
        self.assertEqual(state["status"], "lease_lost")
        self.assertEqual(state["detail"]["reason"], "superseded")
        self.assertEqual(self.lease.active_action(), "move")  # the newer motion is untouched

    def test_an_unknown_or_missing_lease_id_is_refused_without_side_effects(self):
        self.start_trot()
        self.assertEqual(self.renew("not-a-lease")["detail"]["reason"], "unknown")
        self.assertEqual(self.send("renew", {})["status"], "rejected")
        self.assertEqual(self.send("renew", None)["status"], "rejected")
        self.assertEqual(self.send("renew", {"lease_id": 7})["status"], "rejected")
        self.assertEqual(self.adapter.actions(), ["trot"])
        self.assertEqual(self.lease.active_action(), "trot")

    def test_a_failed_motion_cannot_be_renewed_by_id(self):
        adapter = RecordingAdapter(fail={"trot"})
        guarded_dispatch(adapter, self.lease, "trot")
        armed_id = self.lease.lease_id()
        state = guarded_dispatch(adapter, self.lease, "renew", {"lease_id": armed_id})
        self.assertEqual(state["status"], "lease_lost")
        self.assertEqual(state["detail"]["reason"], "failed")

    def test_renew_is_not_an_adapter_capability(self):
        self.assertNotIn("renew", self.adapter.capabilities)
        self.assertEqual(self.renew("x")["action"], "renew")  # yet the body answers it

    def test_the_action_name_is_normalized(self):
        lease_id = self.start_trot()
        self.assertEqual(self.send("  RENEW ", {"lease_id": lease_id})["status"], "completed")

    def test_the_legacy_resend_still_renews_a_running_motion(self):
        # compatibility with brains older than v1.8.5
        lease_id = self.start_trot()
        self.clock.advance(4.0)
        state = self.send("trot")
        self.assertTrue(state["detail"]["renewed"])
        self.assertEqual(state["detail"]["lease_id"], lease_id)
        self.assertEqual(self.adapter.actions(), ["trot"])
        self.clock.advance(4.0)
        self.assertFalse(self.lease.expired())

    def test_the_legacy_resend_after_expiry_still_starts_the_motion_this_is_the_old_weakness(self):
        # kept for old brains; the reason v1.8.5 brains use `renew` instead
        self.start_trot()
        self.clock.advance(6.0)
        self.lease.expire_if_due(self.adapter)
        self.send("trot")
        self.assertEqual(self.adapter.actions(), ["trot", "stop", "trot"])

    def test_the_expiry_event_names_the_lease(self):
        lease_id = self.start_trot()
        self.clock.advance(6.0)
        self.assertEqual(self.lease.expire_if_due(self.adapter)["lease_id"], lease_id)


class LeaseClientTests(unittest.TestCase):
    """The brain half: what to send to keep a motion alive, and what each reply means."""

    def state(self, status="completed", lease_id=None, **extra):
        detail = {"lease_id": lease_id} if lease_id else {}
        return {"status": status, "detail": detail, **extra}

    def test_a_body_that_returns_a_lease_id_is_renewed_with_renew(self):
        c = LeaseClient()
        self.assertEqual(c.begin("trot", {}, self.state(lease_id="abc")), "lease_id")
        self.assertEqual(c.request(), ("renew", {"lease_id": "abc"}))

    def test_a_body_without_a_lease_id_is_renewed_by_resending_the_motion(self):
        c = LeaseClient()
        self.assertEqual(c.begin("move", {"vx": 1}, self.state()), "legacy")
        self.assertEqual(c.request(), ("move", {"vx": 1}))

    def test_replies_are_classified(self):
        c = LeaseClient()
        c.begin("trot", {}, self.state(lease_id="abc"))
        self.assertEqual(c.interpret(self.state()), LeaseClient.RENEWED)
        self.assertEqual(c.interpret(self.state("lease_lost")), LeaseClient.LOST)
        for bad in (
            {"status": "no_reply", "error": "timeout"},
            {"status": "error", "error": "boom"},
            {"status": "rejected"},
            {"status": "failed"},
            None,
            {},
        ):
            self.assertEqual(c.interpret(bad), LeaseClient.FAILED, bad)
        self.assertEqual(c.request(), ("renew", {"lease_id": "abc"}))  # a failure keeps the lease id

    def test_an_old_body_answering_renew_unsupported_downgrades_to_the_legacy_resend(self):
        c = LeaseClient()
        c.begin("trot", {}, self.state(lease_id="abc"))
        self.assertEqual(c.interpret({"status": "unsupported"}), LeaseClient.DOWNGRADED)
        self.assertEqual(c.mode, "legacy")
        self.assertEqual(c.request(), ("trot", {}))
        # in legacy mode `unsupported` is just a failure (the motion itself is unsupported)
        self.assertEqual(c.interpret({"status": "unsupported"}), LeaseClient.FAILED)

    def test_clear_forgets_the_motion(self):
        c = LeaseClient()
        c.begin("trot", {}, self.state(lease_id="abc"))
        c.clear()
        self.assertFalse(c.active)
        with self.assertRaises(RuntimeError):
            c.request()

    def test_a_non_string_lease_id_is_ignored(self):
        c = LeaseClient()
        self.assertEqual(c.begin("trot", {}, {"status": "completed", "detail": {"lease_id": 5}}), "legacy")
        self.assertEqual(c.begin("trot", {}, {"status": "completed", "detail": None}), "legacy")
        self.assertEqual(c.begin("trot", {}, None), "legacy")


if __name__ == "__main__":
    unittest.main()
