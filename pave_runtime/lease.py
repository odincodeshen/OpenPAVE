"""Body-side motion lease — a dead-man switch for the body endpoint.

A locomotion verb (``trot`` / ``move``) is *persistent* on most bodies: it runs until someone sends
``stop``. If the brain dies (``kill -9``, power loss, a crash) or the network drops, nobody sends that
STOP, so the body keeps moving. The brain's own cleanup cannot help — it is gone.

So the **body** keeps the clock. Every leased motion carries a time-to-live (``BODY_MOTION_TTL_S``,
default 5 s). The brain keeps it alive by **re-sending the same motion** (a renewal: the lease layer
extends the deadline without calling the adapter again, so there is no gait hiccup). If the lease is not
renewed in time the body issues ``stop`` itself.

The TTL is a *body safety policy*, not a brain request: there is no brain-supplied TTL, so a buggy brain
cannot ask for a longer one. Both seam backends route every incoming action through
``guarded_dispatch`` and run ``BodyLease.watch`` next to their serve loop, so the protection is the
same over raw_zenoh and device_connect.

Known limit: the lease lives in the body *process*. A crash or ``kill -9`` of that process is not
covered (e.g. PuppyPi's ``puppy_control`` runs in its own container and would keep marching); that needs
enforcement in the controller/bridge below the body process.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from typing import Any, Callable

from pave_runtime.capability_schema import now_iso
from pave_runtime.seam import dispatch
from pave_runtime.shutdown import StopUnconfirmed

# Verbs that start motion which persists until a STOP. Single source for the body lease and the brain
# drivers (run_live / run_inference) that gate and renew them.
LEASED_ACTIONS = frozenset({"trot", "move"})
# Verbs that end a leased motion once they complete. (`home` deliberately does not: whether it halts a
# running gait is adapter-specific, and an extra STOP at expiry is harmless.)
RELEASING_ACTIONS = frozenset({"stop", "estop"})

DEFAULT_TTL_S = 5.0
RETRY_TTL_S = 1.0  # if the lease-expiry STOP fails, try again this soon


def _ttl_from_env() -> float:
    raw = os.environ.get("BODY_MOTION_TTL_S", "")
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TTL_S
    return value if value > 0 else DEFAULT_TTL_S


def _action_name(action: Any) -> str:
    return str(action or "").strip().lower()  # same normalization as normalize_action_payload


class BodyLease:
    """The deadline for the motion the body is currently running (thread-safe)."""

    def __init__(self, ttl_s: float | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_s = float(ttl_s) if ttl_s and ttl_s > 0 else _ttl_from_env()
        self._clock = clock
        self._state_lock = threading.RLock()
        # serializes body actions: an incoming action vs. the expiry STOP (zenoh calls back on its own
        # threads; the expiry runs on a worker thread)
        self.exec_lock = threading.RLock()
        self._action: str | None = None
        self._params: dict | None = None
        self._deadline = 0.0

    # --- state -------------------------------------------------------------------------------
    def arm(self, action: str, params: dict | None, ttl_s: float | None = None) -> None:
        with self._state_lock:
            self._action = action
            self._params = dict(params or {})
            self._deadline = self._clock() + (ttl_s if ttl_s is not None else self.ttl_s)

    def disarm(self) -> None:
        with self._state_lock:
            self._action = None
            self._params = None
            self._deadline = 0.0

    def active_action(self) -> str | None:
        with self._state_lock:
            return self._action

    def is_active_same(self, action: str, params: dict | None) -> bool:
        with self._state_lock:
            return self._action == action and self._params == dict(params or {})

    def remaining(self) -> float:
        with self._state_lock:
            return max(0.0, self._deadline - self._clock()) if self._action else 0.0

    def expired(self) -> bool:
        with self._state_lock:
            return self._action is not None and self._clock() >= self._deadline

    # --- expiry ------------------------------------------------------------------------------
    def expire_if_due(self, adapter) -> dict | None:
        """If the lease ran out, STOP the body now. Returns an event dict, or None if nothing was due."""
        with self.exec_lock:
            if not self.expired():  # re-check under the lock: a renewal may have just landed
                return None
            with self._state_lock:
                action, params = self._action, self._params
            self.disarm()
            state = dispatch(adapter, "stop", {})
            if state.get("status") != "completed":
                # the body may still be moving: keep protecting it and retry the STOP shortly
                self.arm(action or "", params, ttl_s=RETRY_TTL_S)
            return {"event": "lease_expired", "action": action, "stop": state}

    async def watch(self, adapter, poll_s: float = 0.1, emit: Callable[[dict], None] | None = None) -> None:
        """Run next to the serve loop: STOP the body whenever its lease runs out."""
        while True:
            await asyncio.sleep(poll_s)
            if self.expired():
                event = await asyncio.to_thread(self.expire_if_due, adapter)
                if event is not None and emit is not None:
                    emit(event)


def guarded_dispatch(adapter, lease: BodyLease, action: str, params: dict | None = None) -> dict:
    """``dispatch`` plus the motion lease — the single body entry point for every seam backend."""
    name = _action_name(action)
    with lease.exec_lock:
        if name in LEASED_ACTIONS:
            if lease.is_active_same(name, params):
                # renewal: the body is already doing exactly this — just extend the deadline
                lease.arm(name, params)
                return {
                    "request_id": str(uuid.uuid4()),
                    "action": name,
                    "updated_at": now_iso(),
                    "status": "completed",
                    "detail": {"renewed": True, "lease_ttl_s": lease.ttl_s},
                    "error": None,
                }
            state = dispatch(adapter, action, params)
            if state.get("status") in ("completed", "failed"):
                # arm even on `failed`: a half-started gait may be moving, and the lease will STOP it
                lease.arm(name, params)
                state = {**state, "detail": {**(state.get("detail") or {}), "lease_ttl_s": lease.ttl_s}}
            return state
        state = dispatch(adapter, action, params)
        if name in RELEASING_ACTIONS and state.get("status") == "completed":
            lease.disarm()  # only once the STOP really completed; a failed STOP stays protected
        return state


def safe_stop(adapter) -> dict | None:
    """Put the body in its safe state (``stop``) as the body process shuts down.

    Raises ``StopUnconfirmed`` if the STOP did not complete. Returns None for adapters with no ``stop``
    (e.g. a camera), which have nothing to make safe.
    """
    if "stop" not in getattr(adapter, "capabilities", ()):
        return None
    state = dispatch(adapter, "stop", {})
    if state.get("status") != "completed":
        raise StopUnconfirmed(state)
    return state
