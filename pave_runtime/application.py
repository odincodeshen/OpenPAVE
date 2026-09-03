"""Application runtimes that turn inference results into capability proposals."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pave_runtime.inference import InferenceResult


@dataclass(frozen=True)
class ActionProposal:
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    application: str = "unknown"
    raw_output: str = ""
    safety_fallback: bool = False
    reason: str | None = None


@runtime_checkable
class ApplicationRuntime(Protocol):
    name: str

    def decide(self, result: InferenceResult) -> ActionProposal:
        """Convert a model result into an unexecuted capability proposal."""


class GestureCommander:
    name = "gesture_commander"

    def decide(self, result: InferenceResult) -> ActionProposal:
        token = result.text.strip().upper()
        if token == "TROT":
            return ActionProposal(
                action="trot", application=self.name, raw_output=result.text
            )
        if token == "STOP":
            return ActionProposal(
                action="stop", application=self.name, raw_output=result.text
            )
        return ActionProposal(
            action="stop",
            application=self.name,
            raw_output=result.text,
            safety_fallback=True,
            reason="model output did not match the exact STOP/TROT contract",
        )


_APPLICATIONS: dict[str, type[ApplicationRuntime]] = {
    "gesture_commander": GestureCommander,
}


def create_application_runtime(name: str | None = None, **opts: Any) -> ApplicationRuntime:
    key = (name or os.getenv("APPLICATION_RUNTIME", "gesture_commander")).strip().lower()
    if key not in _APPLICATIONS:
        raise ValueError(f"unknown application runtime {key!r}; known: {sorted(_APPLICATIONS)}")
    return _APPLICATIONS[key](**opts)
