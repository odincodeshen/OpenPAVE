"""Local fault benchmark coverage: no transport SDK or physical hardware needed."""
from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import importlib.util
import json
import multiprocessing
import os
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from control_daemon.adapters import GpioServoAdapter
from pave_runtime.lease import BodyLease, guarded_dispatch
from scripts import benchmark_fault_tolerance as bench
from tests.test_lease import FakeClock, RecordingAdapter


def event(stop="completed", lease_id="test-lease"):
    return dict(event="lease_expired", action="trot", body_id="test-body", lease_id=lease_id,
                last_renewal_monotonic_s=90000, deadline_monotonic_s=90000.3,
                expiry_detected_monotonic_s=90000.35, stop_issued_monotonic_s=90000.36,
                stop_finished_monotonic_s=90000.38, stop={"status": stop})


def body():
    return dict(version=1, body_id="test-body", adapter="gpio_servo", dry_run=True,
                servo_dryrun_env=True, capabilities=["trot", "stop"], lease_ttl_s=.3,
                lease_id=None, expiry_events=[])


class FakeBrainSeam:
    async def send(self, action, params, **kwargs):
        return {"status": "completed", "detail": {"lease_id": "test-lease", "renewed": action == "renew"}}


def brain_factory(name):
    return FakeBrainSeam()


class HangingBrainSeam:
    async def send(self, *args, **kwargs):
        time.sleep(30)


def hanging_factory(name):
    return HangingBrainSeam()


def exiting_factory(name):
    os._exit(7)


class RejectedBrainSeam:
    async def send(self, *args, **kwargs):
        return {"status": "rejected", "error": "no TROT"}


def rejected_factory(name):
    return RejectedBrainSeam()


class NoLeaseBrainSeam:
    async def send(self, *args, **kwargs):
        return {"status": "completed", "detail": {}}


def no_lease_factory(name):
    return NoLeaseBrainSeam()


class ObservingSeam:
    def __init__(self, events=None, lease_id=None):
        self.events = [event()] if events is None else events
        self.lease_id = lease_id
        self.calls = []

    async def send(self, action, params, **kwargs):
        self.calls.append((action, kwargs))
        detail = {**body(), "expiry_events": self.events, "lease_id": self.lease_id}
        return {"status": "completed", "detail": detail}


class LeaseDiagnosticsTests(unittest.TestCase):
    def test_real_lease_timestamps_and_failed_stop_retry_preserved(self):
        clock = FakeClock()

        class SlowStop(RecordingAdapter):
            def execute(self, action, params=None):
                if action == "stop":
                    clock.advance(.02)
                return super().execute(action, params)

        for failed in (False, True):
            with self.subTest(failed=failed):
                adapter = SlowStop(fail={"stop"} if failed else set())
                lease = BodyLease(ttl_s=5, clock=clock)
                state = guarded_dispatch(adapter, lease, "trot")
                lease_id = state["detail"]["lease_id"]
                clock.advance(2)
                renewed = guarded_dispatch(adapter, lease, "renew", {"lease_id": lease_id})
                self.assertTrue(renewed["detail"]["renewed"])
                last = clock()
                clock.advance(5.1)
                expired = lease.expire_if_due(adapter)
                self.assertAlmostEqual(expired["last_renewal_monotonic_s"], last)
                self.assertAlmostEqual(expired["expiry_detected_monotonic_s"] - last, 5.1)
                self.assertAlmostEqual(expired["stop_finished_monotonic_s"] - expired["stop_issued_monotonic_s"], .02)
                snapshot = guarded_dispatch(adapter, lease, "lease_status")["detail"]
                self.assertEqual(snapshot["expiry_events"], [expired])
                self.assertEqual(expired["lease_id"], lease_id)
                if failed:
                    self.assertIsNotNone(snapshot["lease_id"])
                    clock.advance(1)
                    self.assertIsNotNone(lease.expire_if_due(adapter))
                else:
                    self.assertIsNone(snapshot["lease_id"])
                self.assertEqual(adapter.actions()[:2], ["trot", "stop"])

    def test_actual_servo_dryrun_verified_without_motion(self):
        with patch.dict(os.environ, {"SERVO_DRYRUN": "1"}):
            adapter = GpioServoAdapter()
            lease = BodyLease()
            state = guarded_dispatch(adapter, lease, "lease_status")
            self.assertEqual(bench.verify_body(state)["adapter"], "gpio_servo")
            self.assertFalse(adapter._running)
        for changes in ({"dry_run": False}, {"servo_dryrun_env": False}, {"adapter": "mock_arm"},
                        {"version": 0}, {"lease_ttl_s": float("nan")}, {"capabilities": ["stop"]},
                        {"lease_id": "someone-else"}):
            with self.subTest(changes=changes), self.assertRaises(bench.TrialError):
                bench.verify_body({"status": "completed", "detail": {**body(), **changes}})


class BenchmarkTests(unittest.IsolatedAsyncioTestCase):
    def row(self):
        return bench.make_row(1, bench.parse_args([]), body())

    async def test_spawned_brain_trot_renew_kill_expiry_stop_and_cleanup(self):
        seam, row = ObservingSeam(), self.row()
        await bench.run_trial(seam, body(), row, 3, 1, brain_factory)
        self.assertEqual(row["status"], "completed")
        for field in ("trot_accepted", "renewal_accepted", "brain_terminated", "expiry_observed", "stop_completed"):
            self.assertTrue(row[field], field)
        self.assertAlmostEqual(row["response_ms"], 380)
        self.assertEqual(row["brain_termination_to_stop_ms"], "")
        self.assertEqual(multiprocessing.active_children(), [])
        self.assertTrue(all(kw["target"] == "test-body" for _, kw in seam.calls))
        self.assertEqual([a for a, _ in seam.calls], ["stop", "lease_status"])

    async def test_hanging_and_unexpected_exit_and_rejected_brains_cleaned_up(self):
        for factory, expected in ((hanging_factory, "timeout"), (exiting_factory, "failed"),
                                  (rejected_factory, "failed"), (no_lease_factory, "failed")):
            row, seam = self.row(), ObservingSeam()
            with self.subTest(factory=factory), self.assertRaises(bench.TrialError) as raised:
                await bench.run_trial(seam, body(), row, .7, 1, factory)
            self.assertEqual(raised.exception.status, expected)
            self.assertFalse(row["brain_terminated"])
            self.assertEqual([a for a, _ in seam.calls], ["stop", "stop"])
            self.assertEqual(multiprocessing.active_children(), [])

    async def test_failed_stop_missing_and_unrelated_expiry_and_body_change(self):
        scenarios = [(ObservingSeam([event("failed")]), "failed", True),
                     (ObservingSeam([], "test-lease"), "timeout", False),
                     (ObservingSeam([event(lease_id="old-lease")], "test-lease"), "timeout", False),
                     (ObservingSeam([], None), "failed", False)]
        for seam, status, seen in scenarios:
            row = self.row()
            row["lease_id"] = "test-lease"
            with self.subTest(status=status, seen=seen), self.assertRaises(bench.TrialError) as raised:
                await bench.observe_expiry(seam, body(), row, .2, .1)
            self.assertEqual(raised.exception.status, status)
            self.assertEqual(row["expiry_observed"], seen)
            self.assertFalse(row["stop_completed"])
        seam = ObservingSeam()
        seam.send = AsyncMock(return_value={"status": "completed", "detail": {**body(), "body_id": "restarted"}})
        with self.assertRaisesRegex(bench.TrialError, "instance changed"):
            await bench.observe_expiry(seam, body(), self.row(), .2, .1)

    async def test_failed_baseline_stop_never_starts_brain(self):
        seam = ObservingSeam()
        seam.send = AsyncMock(return_value={"status": "failed", "error": "STOP failed"})
        with self.assertRaises(bench.TrialError):
            await bench.run_trial(seam, body(), self.row(), 1, 1, brain_factory)
        self.assertEqual(multiprocessing.active_children(), [])

    async def test_send_timeout_and_connection_failure(self):
        seam = types.SimpleNamespace(send=AsyncMock(side_effect=ConnectionError("offline")))
        with self.assertRaises(ConnectionError):
            await bench.send(seam, "lease_status", {}, None, .1)
        async def stall(*args, **kwargs):
            await asyncio.sleep(10)
        seam.send = stall
        with self.assertRaises(bench.TrialError) as raised:
            await bench.send(seam, "lease_status", {}, None, .01)
        self.assertEqual(raised.exception.status, "timeout")

    async def test_interrupted_trial_kills_child_and_attempts_cleanup_stop(self):
        seam, row = ObservingSeam(), self.row()
        task = asyncio.create_task(bench.run_trial(seam, body(), row, 3, 1, hanging_factory))
        try:
            for _ in range(300):
                if multiprocessing.active_children():
                    break
                await asyncio.sleep(.01)
            self.assertTrue(multiprocessing.active_children())
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(multiprocessing.active_children(), [])
        self.assertEqual([action for action, _ in seam.calls], ["stop", "stop"])

    def test_accurate_body_clock_timing_and_invalid_values(self):
        row = self.row()
        with patch.object(bench.time, "monotonic", return_value=1):
            bench.record_event(row, event())
        for key, expected in zip(bench.LATENCIES[:-1], (350, 10, 30, 380)):
            self.assertAlmostEqual(row[key], expected)
        for value in (None, float("nan"), float("inf"), True, 0):
            row = self.row()
            with self.subTest(value=value), self.assertRaises(bench.TrialError):
                bench.record_event(row, {**event(), "stop_finished_monotonic_s": value})
            self.assertEqual(row["response_ms"], "")

    async def test_csv_failures_stopping_and_one_preflight_for_multiple_runs(self):
        for fail_first in (False, True):
            seam = ObservingSeam()
            async def trial(seam, body, row, *args):
                if fail_first:
                    raise bench.TrialError("missing expiry", "timeout")
                bench.record_event(row, event())
                row["status"] = "completed"
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "nested" / "fault.csv"
                args = bench.parse_args(["--runs", "3", "--output", str(path), "--brain-platform", "DGX Spark"])
                with patch.object(bench, "create_seam_transport", return_value=seam), \
                     patch.object(bench, "run_trial", side_effect=trial), contextlib.redirect_stdout(io.StringIO()):
                    result = await bench.main(args)
                with path.open() as file:
                    rows = list(csv.DictReader(file))
            self.assertEqual(result, 1 if fail_first else 0)
            self.assertEqual(len(rows), 1 if fail_first else 3)
            self.assertEqual(rows[0]["status"], "timeout" if fail_first else "completed")
            self.assertEqual(rows[0]["brain_platform"], "DGX Spark")
            self.assertEqual(rows[0]["brain_termination_to_stop_ms"], "")
            self.assertEqual(len(seam.calls), 1)  # initial dry-run verification only
            if fail_first:
                self.assertIn("missing expiry", rows[0]["error"])

    async def test_preflight_failure_recorded_and_no_trot(self):
        for state in ({"status": "no_reply"}, {"status": "completed", "detail": {**body(), "dry_run": False}}):
            seam = types.SimpleNamespace(send=AsyncMock(return_value=state))
            with tempfile.TemporaryDirectory() as directory:
                args = bench.parse_args(["--output", str(Path(directory) / "fault.csv")])
                with patch.object(bench, "create_seam_transport", return_value=seam), \
                     patch.object(bench, "run_trial", new_callable=AsyncMock) as trial, \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(await bench.main(args), 1)
                trial.assert_not_called()
                with args.output.open() as file:
                    rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0]["status"] == "completed")
            self.assertEqual(seam.send.call_args.args[0], "lease_status")

    def test_statistics_only_successful_valid_measurements(self):
        rows = []
        for status, value in (("completed", 10), ("completed", 30), ("failed", 10000),
                              ("timeout", 10000), ("completed", ""), ("completed", float("nan"))):
            row = self.row()
            row.update(status=status, response_ms=value)
            rows.append(row)
        with contextlib.redirect_stdout(io.StringIO()):
            summary = bench.summarize(rows)
            empty = bench.summarize([])
        self.assertEqual(summary["response_ms"], {"mean": 20, "p50": 20, "p95": 29})
        self.assertEqual((summary["total"], summary["successful"], summary["failed"], summary["timeouts"]), (6, 4, 1, 1))
        self.assertAlmostEqual(summary["success_rate"], 200 / 3)
        self.assertEqual(empty["success_rate"], 0)


class ZenohCorrelationTests(unittest.IsolatedAsyncioTestCase):
    async def test_body_status_addressing_and_stale_response_filtering(self):
        """Exercise the real backend with an in-memory Zenoh API stand-in."""
        subscriptions = []
        sent = []

        class Session:
            def declare_subscriber(self, key, callback):
                subscriptions.append((self, key, callback))

            def declare_publisher(self, key):
                def put(payload):
                    sent.append((key, json.loads(payload)))
                    callbacks = [fn for _, k, fn in subscriptions if k == key]
                    # Inject unrelated/malformed traffic before the actual response.
                    if key == "openpave/action_state":
                        for bad in (b"invalid JSON", b"[]", b'{"status":"completed"}',
                                    b'{"correlation_id":"old","status":"completed"}'):
                            for fn in callbacks:
                                fn(types.SimpleNamespace(payload=bad))
                    for fn in callbacks:
                        fn(types.SimpleNamespace(payload=payload))
                return types.SimpleNamespace(put=put)

            def close(self):
                subscriptions[:] = [s for s in subscriptions if s[0] is not self]

        fake = types.SimpleNamespace(open=lambda config: Session(),
                                     Config=lambda: types.SimpleNamespace(insert_json5=lambda *a: None))
        # Avoid importing the optional backend into sys.modules used by registry tests.
        source = Path(bench.__file__).parents[1] / "pave_runtime/seam_backends/zenoh_seam.py"
        spec = importlib.util.spec_from_file_location("test_zenoh_backend", source)
        module = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", {"zenoh": fake}):
            spec.loader.exec_module(module)
        seam = module.ZenohSeam()
        with contextlib.redirect_stdout(io.StringIO()):
            serving = asyncio.create_task(seam.serve(RecordingAdapter()))
            await asyncio.sleep(0)
            try:
                state = await seam.send("lease_status", timeout=.1)
                self.assertEqual(state["action"], "lease_status")
                body_id = state["detail"]["body_id"]
                state = await seam.send("trot", target=body_id, timeout=.1)
                self.assertEqual(state["status"], "completed")
                lease_id = state["detail"]["lease_id"]
                state = await seam.send("renew", {"lease_id": lease_id}, target=body_id, timeout=.1)
                self.assertTrue(state["detail"]["renewed"])
                wrong = await seam.send("stop", target="other-body", timeout=.01)
                self.assertEqual(wrong["status"], "no_reply")
                await seam.send("stop", target=body_id, timeout=.1)
            finally:
                serving.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await serving
        requests = [p for k, p in sent if k == "openpave/action"]
        self.assertEqual(len({p["correlation_id"] for p in requests}), len(requests))
        self.assertEqual(subscriptions, [])


if __name__ == "__main__":
    unittest.main()
