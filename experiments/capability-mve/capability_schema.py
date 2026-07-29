"""Capability-declarative action schema (Plan A — capability-model generalization).

Generalizes the fixed locomotion vocabulary (STOP/TROT/HOME/MOVE, with vx/yaw/duration params)
into an open ``{action, params}`` contract:

    {"action": "move_joint", "params": {"joint": 2, "position": 0.5}}

The ``action`` is a free string; the transport and the generic body node stay robot-agnostic.
Adapters declare which actions (capabilities) they support and validate their own params. This
is what lets a *different robot class* (e.g. an arm) run over the same seam by adding only a new
adapter + capability set.

This is a self-contained experimental prototype (see the zenoh MVE for the validated transport);
if it proves out it graduates into ``pave_runtime`` alongside intent schema v0.1.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "cap-0.1"

# Actions every robot class is expected to support (so the brain always has a safe verb).
COMMON_CAPABILITIES = frozenset({"stop", "estop", "home"})


class CapabilityIntentError(ValueError):
    """Raised when an action payload cannot be normalized."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_action_payload(
    payload: dict[str, Any], *, default_source: str = "unknown"
) -> dict[str, Any]:
    """Normalize a ``{action, params, ...}`` payload into one action shape.

    Only the envelope is validated here (action present, params is an object). *What* the
    params must contain is the adapter's concern — it declares and checks that per capability.
    """
    if not isinstance(payload, dict):
        raise CapabilityIntentError("payload must be an object")

    action = str(payload.get("action", "")).strip().lower()
    if not action:
        raise CapabilityIntentError("missing 'action'")

    params = payload.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise CapabilityIntentError("'params' must be an object")

    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": str(payload.get("request_id") or uuid.uuid4()),
        "action": action,
        "params": params,
        "source": str(payload.get("source") or default_source),
        "timestamp": str(payload.get("timestamp") or now_iso()),
    }
