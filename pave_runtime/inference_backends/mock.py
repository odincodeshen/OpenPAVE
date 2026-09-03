"""Dependency-free deterministic inference backend for local validation."""

from __future__ import annotations

import os
import time

from pave_runtime.inference import InferenceRequest, InferenceResult


class MockInferenceRuntime:
    name = "mock"

    def __init__(self, output: str | None = None, model: str = "openpave-mock") -> None:
        self.output = output if output is not None else os.getenv("MOCK_INFERENCE_OUTPUT", "STOP")
        self.model = model

    async def infer(self, request: InferenceRequest) -> InferenceResult:
        started = time.perf_counter()
        return InferenceResult(
            backend=self.name,
            model=request.model or self.model,
            text=self.output,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            metadata={"observation_source": request.observation.source},
        )
