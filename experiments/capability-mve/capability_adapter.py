"""Capability adapter interface (Plan A).

Replaces the fixed ``stop/trot/home/move`` interface with a capability-declarative one: an
adapter declares which actions it supports (``capabilities``) and executes any of them
(``execute``). The generic body node routes actions to the adapter by capability, so it needs
no per-robot knowledge — which is what makes a new robot class a new adapter, nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ActionResult:
    success: bool
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def ok(cls, detail: dict[str, Any] | None = None) -> "ActionResult":
        return cls(True, detail or {})

    @classmethod
    def failed(cls, error: str, detail: dict[str, Any] | None = None) -> "ActionResult":
        return cls(False, detail or {}, error)


@runtime_checkable
class CapabilityAdapter(Protocol):
    """A robot behind a capability-declarative interface."""

    name: str
    capabilities: frozenset[str]

    def execute(self, action: str, params: dict[str, Any]) -> ActionResult:
        """Run one declared action with its params."""
