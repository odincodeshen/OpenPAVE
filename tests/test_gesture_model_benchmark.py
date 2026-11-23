"""Gesture benchmark tests use fake runtimes/HTTP responses, never a real model."""
from __future__ import annotations

import base64
import contextlib
import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from pave_runtime.application import GestureCommander
from pave_runtime.inference import InferenceResult, InferenceRuntimeError
from scripts import benchmark_gesture_models as bench


def result(text="STOP", latency=10):
    return InferenceResult(backend="vllm_openai", text=text, latency_ms=latency, model="reported-model",
                           metadata={"finish_reason": "stop", "usage": {"total_tokens": 5}})


class FakeRuntime:
    endpoint = "http://test/v1/chat/completions"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def infer(self, request):
        self.requests.append(request)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class DatasetFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "images").mkdir()
        (self.root / "images/go.jpg").write_bytes(b"saved JPEG input")
        (self.root / "images/stop.png").write_bytes(b"saved PNG input")
        self.manifest = self.root / "manifest.csv"
        self.manifest.write_text("image,label\nimages/go.jpg,TROT\nimages/stop.png,STOP\n")
        self.output = self.root / "results.csv"

    def args(self, *extra):
        return bench.parse_args(["--model", "test-model", "--dataset", str(self.manifest),
                                 "--output", str(self.output), "--warmup", "0", *extra])

    def rows(self):
        with self.output.open(newline="") as file:
            return list(csv.DictReader(file))


class ManifestTests(DatasetFixture, unittest.IsolatedAsyncioTestCase):
    async def test_paths_labels_order_and_hashes(self):
        samples, manifest_hash = bench.load_manifest(self.manifest)
        self.assertEqual([s.label for s in samples], ["TROT", "STOP"])
        self.assertEqual(samples[0].path, (self.root / "images/go.jpg").resolve())
        fingerprint = await bench.prepare_samples(samples)
        self.assertEqual(samples[0].observation.data, b"saved JPEG input")
        self.assertEqual(samples[1].observation.media_type, "image/png")
        self.assertEqual(samples[0].image_sha256, hashlib.sha256(b"saved JPEG input").hexdigest())
        self.assertEqual(manifest_hash, hashlib.sha256(self.manifest.read_bytes()).hexdigest())
        # Input order and labels participate in the dataset fingerprint.
        self.assertNotEqual(fingerprint, await bench.prepare_samples(list(reversed(samples))))
        samples[0].label = "STOP"
        self.assertNotEqual(fingerprint, await bench.prepare_samples(samples))

    async def test_missing_empty_and_unsupported_images_become_error_samples(self):
        (self.root / "empty.jpg").write_bytes(b"")
        (self.root / "other.gif").write_bytes(b"not supported")
        self.manifest.write_text("image,label\nmissing.jpg,STOP\nempty.jpg,TROT\nother.gif,STOP\n")
        samples, _ = bench.load_manifest(self.manifest)
        await bench.prepare_samples(samples)
        for sample in samples:
            self.assertIsNone(sample.observation)
            self.assertTrue(sample.error)
            self.assertEqual(sample.image_sha256, "")
        self.assertIn("unsupported image type", samples[-1].error)

    def test_malformed_manifests_rejected(self):
        for content in ("", "image,label\n", "path,label\na.jpg,STOP\n", "image,image\na.jpg,STOP\n",
                        "image,label,extra\na.jpg,STOP,x\n", "image,label\na.jpg,GO\n",
                        "image,label\n,STOP\n", "image,label\na.jpg\n", "image,label\na.jpg,STOP,x\n",
                        'image,label\n"unterminated,STOP\n'):
            with self.subTest(content=content):
                self.manifest.write_text(content)
                with self.assertRaises((ValueError, csv.Error)):
                    bench.load_manifest(self.manifest)

    def test_bom_quoted_paths_and_label_case(self):
        self.manifest.write_text('\ufeffimage,label\n"images/a,b.jpg", trot \n')
        samples, _ = bench.load_manifest(self.manifest)
        self.assertEqual((samples[0].image, samples[0].label), ("images/a,b.jpg", "TROT"))


class BenchmarkTests(DatasetFixture, unittest.IsolatedAsyncioTestCase):
    async def execute(self, responses, *extra):
        runtime = FakeRuntime(responses)
        calls = []
        def factory(name, **kwargs):
            calls.append((name, kwargs))
            return runtime
        with contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
            code = await bench.run(self.args(*extra), factory=factory)
        return code, runtime, calls, stdout.getvalue(), stderr.getvalue()

    async def test_correct_predictions_csv_and_settings(self):
        code, runtime, calls, stdout, _ = await self.execute([result(" trot \n", 10), result("stop", 30)],
                "--api-base", "http://test/v1", "--temperature", ".2", "--max-tokens", "12",
                "--timeout", "7", "--server-notes", "test serving config")
        rows = self.rows()
        self.assertEqual(code, 0)
        self.assertEqual([r["prediction"] for r in rows], ["TROT", "STOP"])
        self.assertEqual([r["correct"] for r in rows], ["True", "True"])
        self.assertEqual(rows[0]["raw_response"], " trot \n")
        self.assertEqual(rows[0]["reported_model"], "reported-model")
        self.assertEqual(rows[0]["server_notes"], "test serving config")
        self.assertEqual(rows[0]["endpoint"], FakeRuntime.endpoint)
        self.assertEqual(len(rows[0]["prompt_sha256"]), 64)
        self.assertEqual(rows[0]["dataset_sha256"], rows[1]["dataset_sha256"])
        self.assertEqual(calls, [("vllm_openai", dict(model="test-model", api_base="http://test/v1", timeout_sec=7, max_tokens=12))])
        self.assertEqual(runtime.requests[0].options, {"temperature": .2, "max_tokens": 12})
        self.assertIn("accuracy=100.00%", stdout)
        self.assertIn("mean=20.000 p50=20.000 p95=29.000", stdout)

    async def test_incorrect_and_invalid_stop_fallback_never_count_as_correct(self):
        code, _, _, stdout, _ = await self.execute([result("STOP", 10), result("STOP, because unsure", 30)])
        rows = self.rows()
        self.assertEqual(code, 0)  # API completion is independent of classification quality.
        self.assertEqual(rows[0]["prediction"], "STOP")
        self.assertEqual(rows[0]["correct"], "False")
        self.assertEqual(rows[1]["prediction"], "")
        self.assertEqual(rows[1]["invalid_output"], "True")
        self.assertEqual(rows[1]["fallback_stop"], "True")
        self.assertEqual(rows[1]["correct"], "False")
        self.assertIn("invalid_outputs=1 correct=0 accuracy=0.00%", stdout)
        self.assertIn("mean=20.000", stdout)  # Incorrect and invalid labels retain valid API latency.

    async def test_errors_timeouts_continue_and_preserve_full_accuracy_denominator(self):
        self.manifest.write_text("image,label\nimages/go.jpg,TROT\nimages/stop.png,STOP\nimages/go.jpg,TROT\n")
        try:
            try:
                raise URLError(TimeoutError("timed out"))
            except URLError as exc:
                raise InferenceRuntimeError("request failed") from exc
        except InferenceRuntimeError as timeout:
            responses = [ConnectionError("offline"), timeout, result("TROT", 15)]
        code, runtime, _, stdout, _ = await self.execute(responses)
        rows = self.rows()
        self.assertEqual(code, 1)
        self.assertEqual([r["status"] for r in rows], ["failed", "timeout", "completed"])
        self.assertEqual(len(runtime.requests), 3)
        self.assertEqual(rows[0]["api_response_ms"], "")
        self.assertEqual(rows[1]["prediction"], "")
        self.assertEqual(rows[0]["invalid_output"], "")  # No model output to classify.
        self.assertIn("accuracy=33.33%", stdout)
        self.assertIn("mean=15.000", stdout)
        self.assertIn("offline", rows[0]["error"])

    async def test_missing_images_recorded_and_no_requests_when_all_unreadable(self):
        self.manifest.write_text("image,label\nmissing.jpg,TROT\nmissing.png,STOP\n")
        code, runtime, _, stdout, _ = await self.execute([])
        self.assertEqual(code, 1)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(runtime.requests, [])
        self.assertIn("accuracy=0.00%", stdout)
        self.assertIn("latency: unavailable", stdout)

    async def test_warmups_excluded_and_frozen_inputs_reused(self):
        runtime = FakeRuntime([result("wrong", 10000), result("STOP", 20000), result("TROT", 10), result("STOP", 30)])
        original = runtime.infer
        async def mutate_after_first(request):
            response = await original(request)
            (self.root / "images/go.jpg").write_bytes(b"modified after preload")
            return response
        runtime.infer = mutate_after_first
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = await bench.run(self.args("--warmup", "2"), lambda *a, **k: runtime)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual([r.observation.data for r in runtime.requests],
                         [b"saved JPEG input", b"saved PNG input", b"saved JPEG input", b"saved PNG input"])
        self.assertEqual(len({r.prompt for r in runtime.requests}), 1)
        self.assertIn("mean=20.000", stdout.getvalue())
        self.assertNotIn("mean=7510", stdout.getvalue())

    async def test_failed_warmup_is_reported_but_not_a_measured_image(self):
        code, runtime, _, stdout, stderr = await self.execute([TimeoutError("warmup"), result("TROT"), result("STOP")], "--warmup", "1")
        self.assertEqual(code, 1)
        self.assertEqual(len(self.rows()), 2)
        self.assertTrue(all(r["warmup_failures"] == "1" for r in self.rows()))
        self.assertIn("Warm-up 1 failed", stderr)
        self.assertIn("accuracy=100.00%", stdout)

    async def test_two_models_receive_identical_actual_http_image_payloads(self):
        payloads = []
        class Response:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return b'{"model":"served","choices":[{"message":{"content":"STOP"}}]}'
        def urlopen(request, timeout):
            payloads.append(json.loads(request.data))
            return Response()
        hashes = []
        for model in ("Qwen/Qwen2.5-VL-3B-Instruct", "llava-hf/llava-v1.6-mistral-7b-hf"):
            with patch("pave_runtime.inference_backends.vllm_openai.request.urlopen", side_effect=urlopen), \
                 contextlib.redirect_stdout(io.StringIO()):
                await bench.run(self.args("--model", model, "--warmup", "1"))
            hashes.append(self.rows()[0]["dataset_sha256"])
        self.assertEqual(hashes[0], hashes[1])
        for left, right in zip(payloads[:3], payloads[3:]):
            self.assertNotEqual(left.pop("model"), right.pop("model"))
            self.assertEqual(left, right)
        image = payloads[1]["messages"][0]["content"][1]["image_url"]["url"]
        self.assertEqual(base64.b64decode(image.split(",", 1)[1]), b"saved JPEG input")

    async def test_output_cannot_overwrite_inputs_and_bad_manifest_never_calls_model(self):
        for protected in (self.manifest, self.root / "images/go.jpg", bench.DEFAULT_PROMPT_PRESET):
            with self.subTest(protected=protected), self.assertRaisesRegex(ValueError, "overwrite"):
                await bench.run(self.args("--output", str(protected)), lambda *a, **k: self.fail("no runtime"))
        self.manifest.write_text("image,label\nimages/go.jpg,NOT_A_LABEL\n")
        with self.assertRaises(ValueError):
            await bench.run(self.args(), lambda *a, **k: self.fail("no runtime"))

    def test_empty_invalid_and_nonfinite_latencies(self):
        for text in ("", "TROT.", "STOP\nTROT", "I think STOP"):
            row = {"label": "STOP"}
            bench.score_result(row, result(text), GestureCommander())
            self.assertFalse(row["correct"])
            self.assertTrue(row["fallback_stop"])
            self.assertEqual(row["prediction"], "")
        for latency in (float("nan"), float("inf"), -1, True, None):
            with self.subTest(latency=latency), self.assertRaises(ValueError):
                bench.score_result({"label": "STOP"}, result(latency=latency), GestureCommander())


class CLITests(DatasetFixture, unittest.TestCase):
    def test_invalid_arguments_and_help_never_run_inference(self):
        for extra in (("--timeout", "0"), ("--timeout", "nan"), ("--temperature", "-1"),
                      ("--temperature", "inf"), ("--max-tokens", "0"), ("--warmup", "-1"),
                      ("--api-base", "ftp://test"), ("--model", " ")):
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                self.args(*extra)
            self.assertEqual(raised.exception.code, 2)
        with patch.object(bench, "create_inference_runtime") as factory, contextlib.redirect_stdout(io.StringIO()), \
             self.assertRaises(SystemExit) as raised:
            bench.cli(["--help"])
        self.assertEqual(raised.exception.code, 0)
        factory.assert_not_called()

    def test_setup_error_exit_code(self):
        with contextlib.redirect_stderr(io.StringIO()):
            code = bench.cli(["--model", "test", "--dataset", str(self.root / "missing.csv"), "--output", str(self.output)])
        self.assertEqual(code, 2)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
