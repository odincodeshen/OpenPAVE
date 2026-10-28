"""Additional local-only tests for the body-side motion lease (complements tests/test_lease.py).

Focus: the expiry STOP (issued, retried until it lands, never abandoned), and `renew` with an unknown or
expired lease_id (answers ``lease_lost`` and never starts or restarts motion). Fake clock + recording
adapter: no zenoh, no robot, no real waiting.
"""

from __future__ import annotations

import unittest

from pave_runtime.lease import RETRY_TTL_S, BodyLease, guarded_dispatch
from tests.test_lease import FakeClock, RecordingAdapter


class FlakyStopAdapter(RecordingAdapter):
    """STOP fails the first ``stop_failures`` times, then succeeds."""

    def __init__(self, stop_failures: int) -> None:
        super().__init__()
        self.stop_failures = stop_failures

    def execute(self, action, params=None):
        if action == "stop" and self.stop_failures > 0:
            self.stop_failures -= 1
            self.calls.append((action, dict(params or {})))
            from control_daemon.adapters import AdapterActionResult

            return AdapterActionResult.failed("stop failed")
        return super().execute(action, params)


def _lease(ttl=5.0):
    clock = FakeClock()
    return BodyLease(ttl_s=ttl, clock=clock), clock


class ExpiryIssuesStopTests(unittest.TestCase):
    def test_expiry_issues_exactly_one_stop_with_no_params_then_goes_quiet(self):
        adapter = RecordingAdapter()
        lease, clock = _lease()
        guarded_dispatch(adapter, lease, "move", {"vx": 0.3})
        clock.advance(5.0)
        event = lease.expire_if_due(adapter)
        self.assertEqual(adapter.calls, [("move", {"vx": 0.3}), ("stop", {})])
        self.assertEqual(event["action"], "move")
        # already released: further polls must not re-issue STOPs
        clock.advance(60.0)
        self.assertIsNone(lease.expire_if_due(adapter))
        self.assertEqual(adapter.actions().count("stop"), 1)

    def test_expiry_stop_happens_exactly_at_the_deadline_not_before(self):
        adapter = RecordingAdapter()
        lease, clock = _lease(ttl=2.0)
        guarded_dispatch(adapter, lease, "trot")
        clock.advance(1.999)
        self.assertIsNone(lease.expire_if_due(adapter))
        clock.advance(0.001)
        self.assertIsNotNone(lease.expire_if_due(adapter))
        self.assertEqual(adapter.actions(), ["trot", "stop"])


class FailedExpiryStopRetryTests(unittest.TestCase):
    def test_retry_waits_for_the_short_retry_window(self):
        adapter = FlakyStopAdapter(stop_failures=1)
        lease, clock = _lease()
        guarded_dispatch(adapter, lease, "trot")
        clock.advance(5.0)
        self.assertEqual(lease.expire_if_due(adapter)["stop"]["status"], "failed")
        self.assertEqual(lease.active_action(), "trot")  # still guarded
        clock.advance(RETRY_TTL_S - 0.01)
        self.assertIsNone(lease.expire_if_due(adapter))  # too early
        self.assertEqual(adapter.actions().count("stop"), 1)

    def test_retry_that_succeeds_releases_the_lease_and_stops_retrying(self):
        adapter = FlakyStopAdapter(stop_failures=1)
        lease, clock = _lease()
        guarded_dispatch(adapter, lease, "trot")
        clock.advance(5.0)
        lease.expire_if_due(adapter)
        clock.advance(RETRY_TTL_S)
        event = lease.expire_if_due(adapter)
        self.assertEqual(event["stop"]["status"], "completed")
        self.assertIsNone(lease.active_action())
        clock.advance(60.0)
        self.assertIsNone(lease.expire_if_due(adapter))
        self.assertEqual(adapter.actions(), ["trot", "stop", "stop"])

    def test_a_persistently_failing_stop_is_retried_every_window_never_abandoned(self):
        adapter = RecordingAdapter(fail={"stop"})
        lease, clock = _lease()
        guarded_dispatch(adapter, lease, "trot")
        clock.advance(5.0)
        for attempt in range(1, 6):
            event = lease.expire_if_due(adapter)
            self.assertIsNotNone(event, attempt)
            self.assertEqual(event["stop"]["status"], "failed")
            self.assertEqual(lease.active_action(), "trot")
            clock.advance(RETRY_TTL_S)
        self.assertEqual(adapter.actions().count("stop"), 5)

    def test_the_retry_does_not_rerun_the_original_motion(self):
        adapter = FlakyStopAdapter(stop_failures=2)
        lease, clock = _lease()
        guarded_dispatch(adapter, lease, "trot")
        clock.advance(5.0)
        for _ in range(3):
            lease.expire_if_due(adapter)
            clock.advance(RETRY_TTL_S)
        self.assertEqual(adapter.actions(), ["trot", "stop", "stop", "stop"])

    def test_a_lease_awaiting_a_stop_retry_cannot_be_renewed_by_the_old_id(self):
        adapter = RecordingAdapter(fail={"stop"})
        lease, clock = _lease()
        old_id = guarded_dispatch(adapter, lease, "trot")["detail"]["lease_id"]
        clock.advance(5.0)
        lease.expire_if_due(adapter)  # STOP failed; lease re-armed as an unhealthy guard
        state = guarded_dispatch(adapter, lease, "renew", {"lease_id": old_id})
        self.assertEqual(state["status"], "lease_lost")
        self.assertEqual(adapter.actions(), ["trot", "stop"])
        # and the guard is not extended: the retry still comes on schedule
        clock.advance(RETRY_TTL_S)
        self.assertIsNotNone(lease.expire_if_due(adapter))

    def test_resending_the_motion_during_the_retry_window_runs_it_again_not_a_renewal(self):
        # the retry guard is unhealthy (ok=False): a legacy re-send must not be taken for a renewal
        adapter = RecordingAdapter(fail={"stop"})
        lease, clock = _lease()
        guarded_dispatch(adapter, lease, "trot")
        clock.advance(5.0)
        lease.expire_if_due(adapter)
        state = guarded_dispatch(adapter, lease, "trot")
        self.assertNotIn("renewed", state["detail"])
        self.assertEqual(adapter.actions(), ["trot", "stop", "trot"])


class RenewUnknownOrExpiredTests(unittest.TestCase):
    def setUp(self):
        self.adapter = RecordingAdapter()
        self.lease, self.clock = _lease()

    def renew(self, lease_id):
        return guarded_dispatch(self.adapter, self.lease, "renew", {"lease_id": lease_id})

    def test_renew_with_nothing_ever_armed_is_lease_lost_unknown_and_starts_nothing(self):
        state = self.renew("deadbeef")
        self.assertEqual(state["status"], "lease_lost")
        self.assertEqual(state["detail"]["reason"], "unknown")
        self.assertEqual(state["detail"]["lease_id"], "deadbeef")
        self.assertEqual(state["action"], "renew")
        self.assertEqual(self.adapter.calls, [])
        self.assertIsNone(self.lease.active_action())

    def test_renew_with_an_unknown_id_while_another_lease_runs_leaves_it_untouched(self):
        real = guarded_dispatch(self.adapter, self.lease, "trot")["detail"]["lease_id"]
        self.clock.advance(4.0)
        state = self.renew("some-other-id")
        self.assertEqual(state["status"], "lease_lost")
        self.assertEqual(self.adapter.actions(), ["trot"])
        self.clock.advance(1.0)  # 5 s after start: the unknown renew must NOT have extended it
        self.assertTrue(self.lease.expired())
        self.assertEqual(self.lease.lease_id(), real)

    def test_renew_with_an_expired_id_never_restarts_motion_however_often_it_is_retried(self):
        lease_id = guarded_dispatch(self.adapter, self.lease, "trot")["detail"]["lease_id"]
        self.clock.advance(5.0)
        self.lease.expire_if_due(self.adapter)
        for _ in range(5):
            self.clock.advance(1.0)
            state = self.renew(lease_id)
            self.assertEqual(state["status"], "lease_lost")
            self.assertEqual(state["detail"]["reason"], "expired")
        self.assertEqual(self.adapter.actions(), ["trot", "stop"])
        self.assertIsNone(self.lease.active_action())
        self.assertFalse(self.lease.expired())

    def test_lease_lost_reply_is_never_a_completed_status(self):
        lease_id = guarded_dispatch(self.adapter, self.lease, "trot")["detail"]["lease_id"]
        self.clock.advance(5.0)
        self.lease.expire_if_due(self.adapter)
        state = self.renew(lease_id)
        self.assertNotEqual(state["status"], "completed")
        self.assertTrue(state["error"])
        self.assertNotIn("renewed", state["detail"])

    def test_malformed_lease_ids_are_rejected_without_side_effects(self):
        guarded_dispatch(self.adapter, self.lease, "trot")
        for bad in ("", None, 0, 12, ["x"], {"a": 1}, b"abc"):
            with self.subTest(lease_id=bad):
                state = guarded_dispatch(self.adapter, self.lease, "renew", {"lease_id": bad})
                self.assertEqual(state["status"], "rejected")
        self.assertEqual(self.adapter.actions(), ["trot"])
        self.clock.advance(5.0)
        self.assertTrue(self.lease.expired())  # none of the rejects extended the lease

    def test_renew_does_not_need_the_adapter_to_be_alive(self):
        # a renewal never touches the adapter, so a wedged body cannot turn it into motion
        class Exploding(RecordingAdapter):
            def execute(self, action, params=None):
                raise AssertionError("renew must not reach the adapter")

        adapter = Exploding()
        state = guarded_dispatch(adapter, self.lease, "renew", {"lease_id": "nope"})
        self.assertEqual(state["status"], "lease_lost")


if __name__ == "__main__":
    unittest.main()
