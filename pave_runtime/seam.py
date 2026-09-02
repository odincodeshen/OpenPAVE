"""Neutral seam transport — the transport dimension made pluggable.

The capability contract (`{action, params}` -> state) is transport-agnostic — proven by ②a
(raw zenoh) and ②b (device-connect), which each carried the *same* dispatch over a different
transport. This module makes that explicit:

- `dispatch(adapter, action, params)` — the single source of the body-endpoint contract
  (②a/②b previously duplicated it).
- `SeamTransport` — a pluggable brain<->body transport. Body: `serve(adapter)`. Brain:
  `send(action, params)`. (Q2 = 乙: advanced backend-specific features like fleet broadcast /
  discovery are NOT in this common interface — reach for them on the concrete backend.)
- `create_seam_transport(name)` — a registry that **lazily** imports the chosen backend, so this
  core module has **zero external dependencies**; only the selected backend pulls in zenoh /
  device-connect. Mirrors `create_robot_adapter`.

Backends live in `pave_runtime.seam_backends.*`.
"""

from __future__ import annotations

import importlib
import os
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pave_runtime.capability_schema import (
    CapabilityIntentError,
    normalize_action_payload,
    now_iso,
)

if TYPE_CHECKING:
    from control_daemon.adapters import CapabilityAdapter


# --- body-endpoint contract (single source, shared by every transport) ------------------------

def dispatch(adapter, action: str, params: dict | None = None) -> dict:
    """Body endpoint — transport-agnostic. An `(action, params)` in, a capability state dict out.

    Rejects an unparseable action envelope (`rejected`) and one the adapter doesn't declare
    (`unsupported`); otherwise runs it and reports `completed` / `failed`. This is exactly the
    logic ②a's `neutral_body` and ②b's `openpave_device` each copied — now the single source.
    """
    try:
        norm = normalize_action_payload(
            {"action": action, "params": params or {}}, default_source="seam"
        )
    except CapabilityIntentError as exc:
        return {"status": "rejected", "error": str(exc), "updated_at": now_iso()}
    name = norm["action"]
    base = {"request_id": norm["request_id"], "action": name, "updated_at": now_iso()}
    if name not in adapter.capabilities:
        return {**base, "status": "unsupported",
                "error": f"{adapter.name} does not support '{name}'"}
    result = adapter.execute(name, norm["params"])
    return {**base, "status": "completed" if result.success else "failed",
            "detail": result.detail, "error": result.error}


# --- pluggable transport interface ------------------------------------------------------------

@runtime_checkable
class SeamTransport(Protocol):
    """A pluggable brain<->body transport. The common contract is intentionally minimal
    (Q2 = 乙): `serve` (body) + `send` (brain). Backend-specific advanced features (fleet
    broadcast, selector discovery) are exposed on the concrete backend, not here."""

    name: str

    async def serve(self, adapter: "CapabilityAdapter") -> None:
        """Body side: receive `{action, params}`, run `dispatch(adapter, ...)`, publish state.
        Blocks on the transport's serve loop."""
        ...

    async def send(self, action: str, params: dict | None = None,
                    *, target: str | None = None, timeout: float = 5.0) -> dict:
        """Brain side: send one capability action to a body and return its state dict.
        `target` selects a body when the transport supports addressing (else ignored)."""
        ...


# --- registry (lazy import — the core stays dependency-free) ----------------------------------

_BACKENDS: dict[str, str] = {
    "raw_zenoh": "pave_runtime.seam_backends.zenoh_seam:ZenohSeam",
    "device_connect": "pave_runtime.seam_backends.dc_seam:DeviceConnectSeam",
}


def create_seam_transport(name: str | None = None, **opts) -> SeamTransport:
    """Factory for a seam transport. Lazily imports the selected backend, so this core never
    requires zenoh / device-connect unless that backend is actually chosen. `name` defaults to
    `$SEAM_TRANSPORT`, else `raw_zenoh`."""
    key = (name or os.getenv("SEAM_TRANSPORT", "raw_zenoh")).strip().lower()
    if key not in _BACKENDS:
        raise ValueError(f"unknown seam transport {key!r}; known: {sorted(_BACKENDS)}")
    module_path, cls_name = _BACKENDS[key].split(":")
    cls = getattr(importlib.import_module(module_path), cls_name)
    return cls(**opts)
