"""Brain-side inference runtime contracts and lazy plugin registry."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Observation:
    media_type: str
    data: bytes
    source: str = "unknown"
    timestamp: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InferenceRequest:
    observation: Observation
    prompt: str
    model: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InferenceResult:
    backend: str
    text: str
    latency_ms: float
    model: str | None = None
    structured_output: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class InferenceRuntime(Protocol):
    name: str

    async def infer(self, request: InferenceRequest) -> InferenceResult:
        """Run one inference request without making an application decision."""


_BACKENDS: dict[str, str] = {
    "mock": "pave_runtime.inference_backends.mock:MockInferenceRuntime",
}


def create_inference_runtime(name: str | None = None, **opts: Any) -> InferenceRuntime:
    """Create the selected backend without importing unselected optional dependencies."""
    key = (name or os.getenv("INFERENCE_RUNTIME", "mock")).strip().lower()
    if key not in _BACKENDS:
        raise ValueError(f"unknown inference runtime {key!r}; known: {sorted(_BACKENDS)}")
    module_path, class_name = _BACKENDS[key].split(":")
    cls = getattr(importlib.import_module(module_path), class_name)
    return cls(**opts)
