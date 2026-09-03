"""OpenAI-compatible multimodal backend for a vLLM-served vision model."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from typing import Any
from urllib import error, request

from pave_runtime.inference import (
    InferenceRequest,
    InferenceResult,
    InferenceRuntimeError,
)


SUPPORTED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png"})


class VllmOpenAIRuntime:
    """Call a vLLM OpenAI-compatible ``/chat/completions`` endpoint."""

    name = "vllm_openai"

    def __init__(
        self,
        *,
        api_base: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_sec: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.api_base = (
            api_base
            or os.getenv("INFERENCE_API_BASE")
            or os.getenv("UI_API_BASE")
            or "http://127.0.0.1:8000/v1"
        ).rstrip("/")
        self.api_key = (
            api_key
            if api_key is not None
            else os.getenv("INFERENCE_API_KEY", os.getenv("UI_API_KEY", "EMPTY"))
        )
        self.model = (
            model
            or os.getenv("INFERENCE_MODEL")
            or os.getenv("UI_MODEL")
            or "llava-hf/llava-v1.6-mistral-7b-hf"
        )
        self.timeout_sec = float(
            timeout_sec
            if timeout_sec is not None
            else os.getenv("INFERENCE_TIMEOUT_SECONDS", "30")
        )
        self.max_tokens = int(
            max_tokens
            if max_tokens is not None
            else os.getenv("INFERENCE_MAX_TOKENS", "16")
        )

    @property
    def endpoint(self) -> str:
        if self.api_base.endswith("/chat/completions"):
            return self.api_base
        return f"{self.api_base}/chat/completions"

    async def infer(self, inference_request: InferenceRequest) -> InferenceResult:
        return await asyncio.to_thread(self._infer_sync, inference_request)

    def _infer_sync(self, inference_request: InferenceRequest) -> InferenceResult:
        observation = inference_request.observation
        if observation.media_type not in SUPPORTED_IMAGE_TYPES:
            raise InferenceRuntimeError(
                "vllm_openai requires a static JPEG or PNG observation; "
                f"got {observation.media_type!r}"
            )
        if not observation.data:
            raise InferenceRuntimeError("vllm_openai observation is empty")
        if not inference_request.prompt.strip():
            raise InferenceRuntimeError("vllm_openai prompt is empty")

        encoded = base64.b64encode(observation.data).decode("ascii")
        model = inference_request.model or self.model
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": inference_request.prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{observation.media_type};base64,{encoded}"
                            },
                        },
                    ],
                }
            ],
            "max_tokens": int(inference_request.options.get("max_tokens", self.max_tokens)),
            "temperature": float(inference_request.options.get("temperature", 0.0)),
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        http_request = request.Request(
            self.endpoint, data=body, headers=headers, method="POST"
        )

        started = time.perf_counter()
        try:
            with request.urlopen(http_request, timeout=self.timeout_sec) as response:
                response_body = response.read().decode("utf-8")
                status = getattr(response, "status", 200)
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise InferenceRuntimeError(
                f"vllm_openai HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise InferenceRuntimeError(f"vllm_openai request failed: {reason}") from exc
        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)

        try:
            decoded = json.loads(response_body)
            choice = decoded["choices"][0]
            content = choice["message"]["content"]
            text = self._content_text(content)
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise InferenceRuntimeError("vllm_openai returned an invalid chat completion") from exc

        return InferenceResult(
            backend=self.name,
            model=str(decoded.get("model") or model),
            text=text,
            latency_ms=latency_ms,
            metadata={
                "endpoint": self.endpoint,
                "http_status": status,
                "finish_reason": choice.get("finish_reason"),
                "usage": decoded.get("usage"),
                "observation_source": observation.source,
            },
        )

    @staticmethod
    def _content_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                str(item["text"])
                for item in content
                if isinstance(item, dict) and item.get("type") == "text" and "text" in item
            ]
            if parts:
                return "".join(parts)
        raise ValueError("message content is not text")
