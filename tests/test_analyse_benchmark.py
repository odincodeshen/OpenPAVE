"""Offline communication CSV analysis tests; no transport SDK or hardware needed."""
import contextlib
import csv
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import analyse_benchmark as analysis
from scripts import seam_bench as bench


ROOT = Path(__file__).resolve().parents[1]


class AnalyseBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "results.csv"

    def row(self, number=1, total=10, **changes):
        row = dict(zip(bench.FIELDS, (
            number, "raw_zenoh", "Test brain", "Test body", "stop",
            total, "", "", True, "completed", "",
        )))
        row.update(changes)
        return row

    def write(self, rows, fields=None):
        with self.path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fields or bench.FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def run_cli(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = analysis.main([str(self.path)])
        return status, out.getvalue(), err.getvalue()

    def assert_input_error(self, message):
        code, out, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn(message, err)
        self.assertNotIn("Traceback", err)

    def test_successful_summary_matches_original_benchmark(self):
        # Generate records through the real producer, not a hand-copied schema.
        with patch.dict(os.environ, {"BENCH_BRAIN_PLATFORM": "Test brain",
                                     "BENCH_BODY_PLATFORM": "Test body"}):
            rows = [bench.make_row(i, "raw_zenoh", "stop", {
                "state": {"status": "completed"}, "total_ms": value,
            }) for i, value in enumerate([30, 10, 20], 1)]
        self.assertEqual(tuple(bench.FIELDS), analysis.FIELDS)
        self.write(rows)
        code, out, err = self.run_cli()
        self.assertEqual((code, err), (0, ""))
        for text in ("Brain platform: Test brain", "Body platform:  Test body",
                     "Transport:      raw_zenoh", "Action:         stop",
                     "Requests attempted: 3", "Successful:         3",
                     "Failed:             0", "Timed out:          0",
                     "Success rate:       100.0%", "Mean:               20.0 ms",
                     "P50:                20.0 ms", "P95:                29.0 ms",
                     "Minimum:            10.0 ms", "0.5-second", "not pure network latency"):
            self.assertIn(text, out)
        with contextlib.redirect_stdout(io.StringIO()) as original:
            bench.summarize(rows)
        self.assertIn("min 10.0 mean 20.0 p50 20.0 p95 29.0", original.getvalue())

    def test_mixed_results_match_producer_and_exclude_failed_timings(self):
        results = [
            {"state": {"status": "completed"}, "total_ms": 10},
            {"state": {"status": "failed"}, "total_ms": 9000},
            {"status": "failed", "error": "offline"},
            {"state": {"status": "no_reply"}, "total_ms": 9000},
            {"state": {"status": "completed"}, "total_ms": 20},
        ]
        rows = [bench.make_row(i, "raw_zenoh", "stop", result)
                for i, result in enumerate(results, 1)]
        self.write(rows)
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        for text in ("Requests attempted: 5", "Successful:         2",
                     "Failed:             2", "Timed out:          1",
                     "Success rate:       40.0%", "Mean:               15.0 ms",
                     "P95:                19.5 ms"):
            self.assertIn(text, out)
        with contextlib.redirect_stdout(io.StringIO()) as original:
            bench.summarize(rows)
        self.assertIn("attempted=5 successful=2 failed=2 timed_out=1 success_rate=40.0%", original.getvalue())
        self.assertIn("mean 15.0 p50 15.0 p95 19.5", original.getvalue())

    def test_false_completed_is_not_successful(self):
        self.write([self.row(success=False)])
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("Successful:         0", out)
        self.assertIn("Failed:             1", out)
        self.assertIn("No successful requests", out)

    def test_no_successes_and_unavailable_latency(self):
        for rows, coverage in (
            ([self.row(total="", success=False, status="failed"),
              self.row(2, "", success=False, status="timeout")], "0/0"),
            ([self.row(total="")], "0/1"),
        ):
            with self.subTest(coverage=coverage):
                self.write(rows)
                code, out, _ = self.run_cli()
                self.assertEqual(code, 0)
                self.assertIn(f"Timing measurements: {coverage}", out)
                for label in ("Mean:", "P50:", "P95:", "Minimum:"):
                    self.assertIn(f"{label:<20}unavailable", out)

    def test_partial_timing_is_explicit_and_zero_is_valid(self):
        self.write([self.row(total=0), self.row(2, "")])
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("Timing measurements: 1/2", out)
        self.assertIn("Mean:               0.0 ms", out)
        self.assertIn("statistics use only measured successes", out)

    def test_empty_file_and_header_only(self):
        self.path.write_text("")
        self.assert_input_error("CSV is empty")
        self.write([])
        self.assert_input_error("no request rows")

    def test_missing_file_and_directory(self):
        self.assert_input_error("CSV file not found")
        self.path.mkdir()
        self.assert_input_error("Error reading")

    def test_invalid_headers(self):
        for headers, message in ((["request"], "Missing required columns"),
                                 (bench.FIELDS + ["success"], "Duplicate CSV headers")):
            with self.subTest(headers=headers):
                self.write([], headers)
                self.assert_input_error(message)

    def test_invalid_values(self):
        cases = [(field, value, field) for field in ("total_ms", "execution_ms", "seam_ms")
                 for value in ("oops", "NaN", "inf", "-inf")]
        cases += [("total_ms", "-1", "total_ms"), ("execution_ms", "-1", "execution_ms"),
                  ("request", "one", "request"), ("request", "0", "request"),
                  ("success", "yes", "True or False"), ("status", "pending", "status must"),
                  ("status", "timeout", "conflicts"), ("brain_platform", "", "is blank")]
        for field, value, message in cases:
            with self.subTest(field=field, value=value):
                self.write([self.row(**{field: value})])
                self.assert_input_error(message)

    def test_malformed_rows_and_encoding(self):
        for kind in ("extra", "short", "quote"):
            self.write([self.row()])
            text = self.path.read_text().rstrip("\n")
            malformed = {
                "extra": text + ",extra\n",
                "short": text.rsplit(",", 1)[0] + "\n",
                "quote": text + '"unterminated',
            }
            self.path.write_text(malformed[kind])
            self.assert_input_error("Error reading")
        self.path.write_bytes(b"\xff")
        self.assert_input_error("Error reading")

    def test_percentiles_match_benchmark(self):
        for values in ([42], [20, 10], [4, 1, 8, 3, 12], [0, 0, 100]):
            for p in (0, 50, 95, 100):
                with self.subTest(values=values, p=p):
                    self.assertEqual(analysis.percentile(values, p), bench._pct(values, p))
        self.assertEqual(analysis.percentile([0, 100], 95), 95)
        with self.assertRaises(ValueError):
            analysis.percentile([], 50)

    def test_conflicting_metadata_on_any_request(self):
        for field in analysis.METADATA:
            with self.subTest(field=field):
                self.write([self.row(), self.row(2, "", success=False, status="timeout",
                                                **{field: "different"})])
                self.assert_input_error(f"Conflicting benchmark metadata for {field}")

    def test_utf8_bom_and_negative_seam_measurement(self):
        self.write([self.row(seam_ms=-1)])
        self.path.write_bytes(b"\xef\xbb\xbf" + self.path.read_bytes())
        self.assertEqual(self.run_cli()[0], 0)

    def test_both_example_filenames_in_standalone_cli_without_site_packages(self):
        for name, platform in (("dgx-spark-rpi5-raw-zenoh.csv", "DGX Spark"),
                               ("radxa-orion-o6-rpi5-raw-zenoh.csv", "Radxa Orion O6")):
            with self.subTest(name=name):
                self.path = Path(self.temp.name) / name
                self.write([self.row(brain_platform=platform, body_platform="Raspberry Pi 5")])
                result = subprocess.run(
                    [sys.executable, "-I", "-S", str(ROOT / "scripts/analyse_benchmark.py"), str(self.path)],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"Brain platform: {platform}", result.stdout)


if __name__ == "__main__":
    unittest.main()
