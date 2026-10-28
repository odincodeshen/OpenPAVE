"""Body-side motion lease — a dead-man switch for the body endpoint.

A locomotion verb (``trot`` / ``move``) is *persistent* on most bodies: it runs until someone sends
``stop``. If the brain dies (``kill -9``, power loss, a crash) or the network drops, nobody sends that
STOP, so the body keeps moving. The brain's own cleanup cannot help — it is gone.

So the **body** keeps the clock. Every leased motion carries a time-to-live (``BODY_MOTION_TTL_S``,
default 5 s). If the lease is not renewed in time the body issues ``stop`` itself.

Renewal is a **separate verb** (``renew``, v1.8.5). Starting a motion returns a ``lease_id``; the brain
keeps the lease alive by sending ``renew`` with that id. A renewal can only *extend* a lease that is still
running — it can never start a motion. If the lease is gone (it expired and the body stopped, a STOP
ended it, another motion took over) the body answers ``lease_lost`` and does nothing, so a delayed or
late renewal cannot restart a motion that has ended. (Before v1.8.5 a renewal was a re-send of the same
motion, which a body could not tell apart from a new command after the lease had expired; that legacy
path is kept for brains that do not know ``renew``.)

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

# The lease-layer verb that extends a running lease. Handled by ``guarded_dispatch`` before any adapter,
# so it is not (and must not be) an adapter capability. An old body answers it ``unsupported``.
RENEW_ACTION = "renew"
LEASE_LOST = "lease_lost"  # state status: the lease named by a renewal is not running (nothing was done)

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
        # whether the armed motion actually started (completed). A motion that FAILED stays armed — a
        # half-started gait may be moving, so the lease must still STOP it — but it is not healthy, so a
        # repeat of the same motion must run again instead of being taken for a renewal.
        self._ok = True
        self._lease_id: str | None = None
        # why the most recent lease ended, so a late renewal can be told the truth (log value only)
        self._ended: tuple[str, str] | None = None

    # --- state -------------------------------------------------------------------------------
    def arm(self, action: str, params: dict | None, ttl_s: float | None = None, ok: bool = True) -> str:
        """Start a NEW lease for this motion and return its id (a different lease, even for the same motion)."""
        with self._state_lock:
            if self._lease_id is not None:
                self._ended = (self._lease_id, "superseded")  # whatever it was, this replaces it
            self._action = action
            self._params = dict(params or {})
            self._deadline = self._clock() + (ttl_s if ttl_s is not None else self.ttl_s)
            self._ok = ok
            self._lease_id = uuid.uuid4().hex
            return self._lease_id

    def extend(self, ttl_s: float | None = None) -> None:
        """Push the deadline of the running lease out by a full TTL. Does not start or change anything."""
        with self._state_lock:
            self._deadline = self._clock() + (ttl_s if ttl_s is not None else self.ttl_s)

    def disarm(self, reason: str = "stopped") -> None:
        with self._state_lock:
            if self._lease_id is not None:
                self._ended = (self._lease_id, reason)
            self._action = None
            self._params = None
            self._deadline = 0.0
            self._ok = True
            self._lease_id = None

    def lease_id(self) -> str | None:
        with self._state_lock:
            return self._lease_id

    def renew(self, lease_id: str) -> tuple[bool, str]:
        """Extend the lease ``lease_id`` if — and only if — it is the running, healthy, unexpired one.

        Returns ``(True, "renewed")`` or ``(False, reason)``; reason is one of ``expired``, ``failed``,
        ``stopped``, ``superseded`` or ``unknown``. Never starts a motion and never touches the adapter.
        """
        with self._state_lock:
            if self._action is not None and self._lease_id == lease_id:
                if not self._ok:
                    return False, "failed"  # a half-started gait is only being guarded, not kept alive
                if self._clock() >= self._deadline:
                    return False, "expired"  # past the deadline: the watcher is about to STOP — don't extend
                self.extend()
                return True, "renewed"
            if self._ended is not None and self._ended[0] == lease_id:
                return False, self._ended[1]
            return False, "unknown"

    def active_action(self) -> str | None:
        with self._state_lock:
            return self._action

    def is_active_same(self, action: str, params: dict | None) -> bool:
        """True only for a HEALTHY active motion identical to this one — i.e. a genuine renewal."""
        with self._state_lock:
            return self._ok and self._action == action and self._params == dict(params or {})

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
                action, params, lease_id = self._action, self._params, self._lease_id
            self.disarm("expired")
            state = dispatch(adapter, "stop", {})
            if state.get("status") != "completed":
                # the body may still be moving: keep protecting it and retry the STOP shortly
                self.arm(action or "", params, ttl_s=RETRY_TTL_S, ok=False)  # state unknown: a repeat re-runs
            return {"event": "lease_expired", "action": action, "lease_id": lease_id, "stop": state}

    async def watch(self, adapter, poll_s: float = 0.1, emit: Callable[[dict], None] | None = None) -> None:
        """Run next to the serve loop: STOP the body whenever its lease runs out."""
        while True:
            await asyncio.sleep(poll_s)
            if self.expired():
                try:
                    event = await asyncio.to_thread(self.expire_if_due, adapter)
                except Exception as exc:  # the dead-man watcher must outlive any single failure
                    print(f"lease watcher: expiry STOP raised {type(exc).__name__}: {exc}; retrying")
                    continue
                if event is not None and emit is not None:
                    emit(event)


def _renew_state(lease: BodyLease, params: dict | None) -> dict:
    """Answer a ``renew``: extend the named lease, or say it is gone. Never runs an adapter action."""
    lease_id = (params or {}).get("lease_id") if isinstance(params, dict) else None
    base = {"request_id": str(uuid.uuid4()), "action": RENEW_ACTION, "updated_at": now_iso()}
    if not isinstance(lease_id, str) or not lease_id:
        return {**base, "status": "rejected", "error": "renew needs params.lease_id (a string)"}
    renewed, reason = lease.renew(lease_id)
    if renewed:
        return {**base, "status": "completed", "error": None,
                "detail": {"renewed": True, "lease_id": lease_id, "lease_ttl_s": lease.ttl_s}}
    return {**base, "status": LEASE_LOST, "error": f"lease {reason}",
            "detail": {"lease_id": lease_id, "reason": reason}}


def guarded_dispatch(adapter, lease: BodyLease, action: str, params: dict | None = None) -> dict:
    """``dispatch`` plus the motion lease — the single body entry point for every seam backend."""
    name = _action_name(action)
    with lease.exec_lock:
        if name == RENEW_ACTION:
            return _renew_state(lease, params)  # a lease-layer verb: extends a lease, can never start a motion
        if name in LEASED_ACTIONS:
            if lease.is_active_same(name, params):
                # legacy renewal (brains before v1.8.5 re-send the same motion): the body is already doing
                # exactly this — just extend the deadline. Kept for compatibility; `renew` supersedes it.
                lease.extend()
                return {
                    "request_id": str(uuid.uuid4()),
                    "action": name,
                    "updated_at": now_iso(),
                    "status": "completed",
                    "detail": {"renewed": True, "lease_id": lease.lease_id(), "lease_ttl_s": lease.ttl_s},
                    "error": None,
                }
            state = dispatch(adapter, action, params)
            if state.get("status") in ("completed", "failed"):
                # arm even on `failed`: a half-started gait may be moving, and the lease will STOP it. Only a
                # completed motion is healthy; a repeat of a failed one runs again rather than "renewing" it.
                healthy = state.get("status") == "completed"
                lease_id = lease.arm(name, params, ok=healthy)
                detail = {**(state.get("detail") or {}), "lease_ttl_s": lease.ttl_s}
                if healthy:
                    detail["lease_id"] = lease_id  # the handle the brain renews with; not for a failed start
                state = {**state, "detail": detail}
            return state
        state = dispatch(adapter, action, params)
        if name in RELEASING_ACTIONS and state.get("status") == "completed":
            lease.disarm("stopped")  # only once the STOP really completed; a failed STOP stays protected
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


class LeaseClient:
    """Brain side of the lease: what to send to keep the body's current motion alive, and what a reply means.

    ``begin(action, params, state)`` records the motion the body just accepted. With a v1.8.5+ body the
    reply carries a ``lease_id`` and renewals are ``renew`` requests that cannot start a motion. A body
    that returns no ``lease_id`` (older than v1.8.5) — or that answers ``renew`` with ``unsupported`` —
    gets the legacy renewal instead (re-send the same motion), which has the old weakness: after the
    lease expired it starts the motion again.

    The driver sends the request itself (each driver has its own cancellation rules) and passes the reply
    to ``interpret``.
    """

    RENEWED, LOST, DOWNGRADED, FAILED = "renewed", "lost", "downgraded", "failed"

    def __init__(self) -> None:
        self.action: str | None = None
        self.params: dict = {}
        self.lease_id: str | None = None

    @property
    def active(self) -> bool:
        return self.action is not None

    @property
    def mode(self) -> str:
        return "lease_id" if self.lease_id else "legacy"

    def begin(self, action: str, params: dict | None, state: dict | None) -> str:
        """Record a motion the body accepted. Returns the renewal mode: ``lease_id`` or ``legacy``."""
        self.action, self.params = action, dict(params or {})
        detail = (state or {}).get("detail")
        lease_id = detail.get("lease_id") if isinstance(detail, dict) else None
        self.lease_id = lease_id if isinstance(lease_id, str) and lease_id else None
        return self.mode

    def clear(self) -> None:
        self.action, self.params, self.lease_id = None, {}, None

    def request(self) -> tuple[str, dict]:
        """The ``(action, params)`` to send as the next renewal."""
        if self.action is None:
            raise RuntimeError("no active motion to renew")
        if self.lease_id:
            return RENEW_ACTION, {"lease_id": self.lease_id}
        return self.action, dict(self.params)

    def interpret(self, state: dict | None) -> str:
        """Classify a renewal reply: RENEWED, LOST (the lease is gone), DOWNGRADED or FAILED.

        ``LOST`` means the body is no longer running our motion — the caller must forget it and not renew
        again. ``DOWNGRADED`` (the body does not know ``renew``) switches to legacy renewals for this motion.
        Anything else (no reply, transport error, a failed re-run) is ``FAILED``: try again next interval.
        """
        status = (state or {}).get("status")
        if status == "completed":
            return self.RENEWED
        if status == LEASE_LOST:
            return self.LOST
        if status == "unsupported" and self.lease_id:
            self.lease_id = None
            return self.DOWNGRADED
        return self.FAILED
