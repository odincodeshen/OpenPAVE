"""Local-only tests for the v1.7 inference/application runtime plugin."""

from __future__ import annotations

import asyncio
import contextlib
import io
import sys
import unittest

from pave_runtime import inference
from pave_runtime.application import GestureCommander, create_application_runtime
from pave_runtime.inference import (
    InferenceRequest,
    InferenceResult,
    Observation,
    create_inference_runtime,
)
from scripts.run_inference import run_once


def _result(text: str) -> InferenceResult:
    return InferenceResult(backend="test", text=text, latency_ms=0.0)


class InferenceRegistryTests(unittest.TestCase):
    def test_unknown_runtime_raises(self):
        with self.assertRaises(ValueError):
            create_inference_runtime("missing")

    def test_backend_is_lazy(self):
        modules = {
            "mock": "pave_runtime.inference_backends.mock",
            "vllm_openai": "pave_runtime.inference_backends.vllm_openai",
        }
        for name, module in modules.items():
            with self.subTest(name=name):
                sys.modules.pop(module, None)
                self.assertIn(name, inference._BACKENDS)
                self.assertNotIn(module, sys.modules)
                create_inference_runtime(name)
                self.assertIn(module, sys.modules)

    def test_mock_backend_returns_deterministic_result(self):
        runtime = create_inference_runtime("mock", output="TROT")
        request = InferenceRequest(
            observation=Observation("image/jpeg", b"jpeg", source="fixture.jpg"),
            prompt="command",
        )
        result = asyncio.run(runtime.infer(request))
        self.assertEqual(result.text, "TROT")
        self.assertEqual(result.backend, "mock")
        self.assertEqual(result.metadata["observation_source"], "fixture.jpg")
        self.assertGreaterEqual(result.latency_ms, 0.0)


class GestureCommanderTests(unittest.TestCase):
    def setUp(self):
        self.application = GestureCommander()

    def test_exact_tokens_map_to_capabilities(self):
        self.assertEqual(self.application.decide(_result("STOP")).action, "stop")
        self.assertEqual(self.application.decide(_result("  trot\n")).action, "trot")

    def test_extra_text_and_punctuation_fail_closed(self):
        for output in ("TROT.", "TROT now", "", "unknown", "STOP TROT"):
            with self.subTest(output=output):
                proposal = self.application.decide(_result(output))
                self.assertEqual(proposal.action, "stop")
                self.assertTrue(proposal.safety_fallback)

    def test_unknown_application_raises(self):
        with self.assertRaises(ValueError):
            create_application_runtime("missing")


class HeadlessWorkflowTests(unittest.TestCase):
    def run_workflow(self, **overrides):
        args = {
            "runtime_name": "mock",
            "application_name": "gesture_commander",
            "observation": Observation("application/x-test", b""),
            "prompt": "test",
            "prompt_id": "test_prompt",
            "mock_output": "TROT",
        }
        args.update(overrides)
        with contextlib.redirect_stdout(io.StringIO()):
            return asyncio.run(run_once(**args))

    def test_default_is_dry_run(self):
        payload = self.run_workflow()
        self.assertEqual(payload["proposal"]["action"], "trot")
        self.assertEqual(payload["dispatch"]["status"], "dry_run")

    def test_explicit_mock_dispatch_completes(self):
        payload = self.run_workflow(should_dispatch=True, adapter_name="mock")
        self.assertEqual(payload["dispatch"]["status"], "completed")
        self.assertEqual(payload["dispatch"]["action"], "trot")
        self.assertIn("MOCK ACTION=TROT", payload["dispatch"]["adapter_log"])

    def test_physical_adapter_dispatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "mock adapter"):
            self.run_workflow(should_dispatch=True, adapter_name="puppypi")

    def test_invalid_output_dispatches_safe_stop_to_mock(self):
        payload = self.run_workflow(
            mock_output="The robot should trot.", should_dispatch=True, adapter_name="mock"
        )
        self.assertTrue(payload["proposal"]["safety_fallback"])
        self.assertEqual(payload["dispatch"]["action"], "stop")
        self.assertEqual(payload["dispatch"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
