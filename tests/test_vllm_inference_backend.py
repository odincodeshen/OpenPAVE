"""Contract tests for the OpenAI-compatible vLLM vision backend."""

from __future__ import annotations

import asyncio
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from pave_runtime.inference import (
    InferenceRequest,
    InferenceRuntimeError,
    Observation,
    create_inference_runtime,
)


class _Response:
    def __init__(self, payload, status=200):
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class VllmOpenAIRuntimeTests(unittest.TestCase):
    def runtime(self):
        return create_inference_runtime(
            "vllm_openai",
            api_base="http://vllm.test:8000/v1/",
            api_key="test-key",
            model="test-vlm",
            timeout_sec=4,
            max_tokens=12,
        )

    def request(self, media_type="image/jpeg", data=b"image-bytes"):
        return InferenceRequest(
            observation=Observation(media_type, data, source="fixture"),
            prompt="Return STOP or TROT.",
        )

    def test_jpeg_and_png_use_openai_multimodal_payload(self):
        for media_type, prefix in (
            ("image/jpeg", "data:image/jpeg;base64,"),
            ("image/png", "data:image/png;base64,"),
        ):
            with self.subTest(media_type=media_type):
                captured = {}

                def fake_urlopen(http_request, timeout):
                    captured["request"] = http_request
                    captured["timeout"] = timeout
                    return _Response(
                        {
                            "model": "served-vlm",
                            "choices": [
                                {
                                    "message": {"content": "TROT"},
                                    "finish_reason": "stop",
                                }
                            ],
                            "usage": {"total_tokens": 9},
                        }
                    )

                with patch(
                    "pave_runtime.inference_backends.vllm_openai.request.urlopen",
                    side_effect=fake_urlopen,
                ):
                    result = asyncio.run(self.runtime().infer(self.request(media_type)))

                http_request = captured["request"]
                payload = json.loads(http_request.data.decode("utf-8"))
                content = payload["messages"][0]["content"]
                self.assertEqual(http_request.full_url, "http://vllm.test:8000/v1/chat/completions")
                self.assertEqual(http_request.get_header("Authorization"), "Bearer test-key")
                self.assertEqual(captured["timeout"], 4.0)
                self.assertEqual(payload["model"], "test-vlm")
                self.assertEqual(payload["max_tokens"], 12)
                self.assertEqual(payload["temperature"], 0.0)
                self.assertEqual(content[0], {"type": "text", "text": "Return STOP or TROT."})
                self.assertTrue(content[1]["image_url"]["url"].startswith(prefix))
                self.assertEqual(result.text, "TROT")
                self.assertEqual(result.model, "served-vlm")
                self.assertEqual(result.metadata["usage"], {"total_tokens": 9})

    def test_request_options_override_generation_defaults(self):
        inference_request = self.request()
        inference_request = InferenceRequest(
            observation=inference_request.observation,
            prompt=inference_request.prompt,
            model="request-model",
            options={"max_tokens": 5, "temperature": 0.2},
        )
        captured = {}

        def fake_urlopen(http_request, timeout):
            captured.update(json.loads(http_request.data.decode("utf-8")))
            return _Response({"choices": [{"message": {"content": "STOP"}}]})

        with patch(
            "pave_runtime.inference_backends.vllm_openai.request.urlopen",
            side_effect=fake_urlopen,
        ):
            asyncio.run(self.runtime().infer(inference_request))
        self.assertEqual(captured["model"], "request-model")
        self.assertEqual(captured["max_tokens"], 5)
        self.assertEqual(captured["temperature"], 0.2)

    def test_rejects_unsupported_or_empty_observation(self):
        runtime = self.runtime()
        for inference_request in (
            self.request("image/gif"),
            self.request("image/jpeg", b""),
        ):
            with self.subTest(media_type=inference_request.observation.media_type):
                with self.assertRaises(InferenceRuntimeError):
                    asyncio.run(runtime.infer(inference_request))

    def test_http_and_connection_errors_are_normalized(self):
        failures = (
            HTTPError(
                "http://vllm.test",
                500,
                "server error",
                {},
                io.BytesIO(b'{"error":"model failed"}'),
            ),
            URLError("connection refused"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch(
                    "pave_runtime.inference_backends.vllm_openai.request.urlopen",
                    side_effect=failure,
                ):
                    with self.assertRaises(InferenceRuntimeError):
                        asyncio.run(self.runtime().infer(self.request()))

    def test_invalid_completion_is_rejected(self):
        with patch(
            "pave_runtime.inference_backends.vllm_openai.request.urlopen",
            return_value=_Response({"choices": []}),
        ):
            with self.assertRaisesRegex(InferenceRuntimeError, "invalid chat completion"):
                asyncio.run(self.runtime().infer(self.request()))

    def test_list_text_content_is_supported(self):
        response = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "ST"},
                            {"type": "text", "text": "OP"},
                        ]
                    }
                }
            ]
        }
        with patch(
            "pave_runtime.inference_backends.vllm_openai.request.urlopen",
            return_value=_Response(response),
        ):
            result = asyncio.run(self.runtime().infer(self.request()))
        self.assertEqual(result.text, "STOP")


if __name__ == "__main__":
    unittest.main()
