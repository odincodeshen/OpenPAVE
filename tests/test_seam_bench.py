"""Benchmark tests use fake transports, never hardware or transport SDKs."""
import asyncio
import contextlib
import csv
import io
import multiprocessing
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from scripts import seam_bench as bench


class FakeSeam:
    async def send(self, action, params, timeout):
        if action == "exception":
            raise ConnectionError("offline")
        if action == "timeout_exception":
            raise TimeoutError("SDK deadline")
        if action == "blocking":
            time.sleep(30)  # synchronous SDK: asyncio.wait_for would not help
        return {"status": "completed", "detail": {"latency_ms": 1}}


def fake_factory(name):
    return FakeSeam()


class SeamBenchTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_success_exceptions_and_blocking_timeout(self):
        for action, status in (("success", None), ("exception", "failed"),
                               ("timeout_exception", "timeout"), ("blocking", "timeout")):
            with self.subTest(action=action):
                result = await bench.run_attempt("device_connect", action, {}, 1, fake_factory)
                if status:
                    self.assertEqual(result["status"], status)
                    self.assertNotIn("total_ms", result)
                else:
                    self.assertEqual(result["state"]["status"], "completed")
                    self.assertGreater(result["total_ms"], 0)
        self.assertEqual(multiprocessing.active_children(), [])

    def test_response_classification_and_missing_timing(self):
        for status in ("completed", "failed", "rejected", "unsupported", "no_device", "no_reply"):
            row = bench.make_row(1, "raw_zenoh", "stop", {
                "state": {"status": status, "error": "reason"}, "total_ms": 10})
            self.assertEqual(row["success"], status == "completed")
            self.assertEqual(row["execution_ms"], "")
            self.assertEqual(row["seam_ms"], "")
            self.assertEqual(row["status"], "timeout" if status == "no_reply" else
                             "completed" if status == "completed" else "failed")
        row = bench.make_row(1, "raw_zenoh", "stop", {"state": None, "total_ms": 10})
        self.assertEqual(row["total_ms"], "")

    async def test_csv_and_summary_include_all_attempts_success_only_stats(self):
        results = [
            {"state": {"status": "completed", "detail": {"latency_ms": 2}}, "total_ms": 10},
            {"state": {"status": "failed", "error": "rejected"}, "total_ms": 1000},
            {"status": "failed", "error": "ConnectionError: offline"},
            {"status": "timeout", "error": "deadline"},
            {"state": {"status": "completed"}, "total_ms": 20},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            env = {"SEAM_TRANSPORT": "device_connect", "BENCH_ACTION": "stop", "BENCH_N": "5",
                   "BENCH_OUTPUT": str(path), "BENCH_BRAIN_PLATFORM": "DGX Spark",
                   "BENCH_BODY_PLATFORM": "Raspberry Pi 5"}
            out = io.StringIO()
            with patch.dict(os.environ, env), patch.object(bench, "run_attempt", AsyncMock(side_effect=results)), contextlib.redirect_stdout(out):
                await bench.main()
            with path.open() as file:
                rows = list(csv.DictReader(file))
        self.assertEqual([r["status"] for r in rows], ["completed", "failed", "failed", "timeout", "completed"])
        self.assertEqual(rows[0]["seam_ms"], "8")
        self.assertEqual(rows[2]["total_ms"], "")
        self.assertEqual(rows[0]["body_platform"], "Raspberry Pi 5")
        self.assertIn("attempted=5 successful=2 failed=2 timed_out=1 success_rate=40.0%", out.getvalue())
        self.assertIn("mean 15.0 p50 15.0 p95 19.5", out.getvalue())

    async def test_raw_timeout_stops_for_connection_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"SEAM_TRANSPORT": "raw_zenoh", "BENCH_ACTION": "stop", "BENCH_N": "3", "BENCH_OUTPUT": str(Path(directory) / "out.csv")}), patch.object(bench, "run_attempt", AsyncMock(return_value={"status": "timeout", "error": "deadline"})) as send, contextlib.redirect_stdout(io.StringIO()) as out:
                await bench.main()
            self.assertEqual(send.await_count, 1)
            self.assertIn("No successful requests", out.getvalue())
            self.assertIn("Check body availability", out.getvalue())
            self.assertNotIn("no request correlation", out.getvalue())

    def test_empty_summary(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            bench.summarize([])
        self.assertIn("success_rate=0.0%", out.getvalue())

    async def test_motion_requires_opt_in(self):
        with patch.dict(os.environ, {"BENCH_ACTION": "move_joint", "BENCH_ALLOW_MOTION": "0"}):
            with self.assertRaisesRegex(ValueError, "mock_arm"):
                await bench.main()
