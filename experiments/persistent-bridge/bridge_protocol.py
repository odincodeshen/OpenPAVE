"""Persistent Body-Side Bridge — wire protocol (newline-delimited JSON over a localhost socket).

The **sync** request/result path is implemented. The **async / long-running** path (for AMR-style
navigate-and-report actions) is reserved: message types, request mode, and step op are defined so
future code only adds branches — the wire format does not change. `ping`/`pong` is implemented so a
body-side adapter can probe the bridge before deciding to use it (B2 fallback). Every message
carries `version` + `type`; every message except the initial handshake carries `id`.

See the B1 design doc (`persistent_bridge_b1_design.md`).
"""

from __future__ import annotations

import json
from typing import Any, Iterator

PROTOCOL_VERSION = "0.1"

# ---- message types ----
T_REQUEST = "request"
T_RESULT = "result"
T_ERROR = "error"
T_PING = "ping"           # body -> bridge: liveness/readiness probe
T_PONG = "pong"           # bridge -> body: reply to ping
T_CANCEL = "cancel"       # reserved (async): cancel an in-flight task by id
T_ACCEPTED = "accepted"   # reserved (async): task accepted, work started
T_PROGRESS = "progress"   # reserved (async): interim progress for a task id

# ---- request modes ----
MODE_SYNC = "sync"
MODE_ASYNC = "async"      # reserved: long-running action with progress + cancel

# ---- step ops ----
OP_SERVICE = "service"
OP_VELOCITY = "velocity"
OP_SLEEP = "sleep"
OP_ACTION = "action"      # reserved: long-running ROS action (e.g. Nav2 NavigateToPose)

SYNC_OPS = frozenset({OP_SERVICE, OP_VELOCITY, OP_SLEEP})

# ---- error codes (machine-readable; lets B2 fallback branch without parsing messages) ----
E_BAD_JSON = "bad_json"
E_BAD_REQUEST = "bad_request"
E_UNSUPPORTED_MODE = "unsupported_mode"
E_UNSUPPORTED_OP = "unsupported_op"


class ProtocolError(ValueError):
    """A wire message can't be parsed or is malformed. Carries a machine-readable ``code``."""

    def __init__(self, message: str, code: str = E_BAD_REQUEST) -> None:
        super().__init__(message)
        self.code = code


def encode(msg: dict[str, Any]) -> bytes:
    """One message -> one newline-terminated JSON line (bytes)."""
    return (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")


def decode(line: str) -> dict[str, Any]:
    """Parse one JSON line into a message dict (must be an object with a ``type``)."""
    try:
        msg = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {exc}", code=E_BAD_JSON) from exc
    if not isinstance(msg, dict) or "type" not in msg:
        raise ProtocolError("message must be a JSON object with a 'type' field")
    return msg


# ---- message builders (keep call sites off raw dict literals; all stamp `version`) ----
def make_request(
    req_id: str, steps: list[dict], mode: str = MODE_SYNC, timeout_ms: int | None = None
) -> dict[str, Any]:
    msg = {"type": T_REQUEST, "version": PROTOCOL_VERSION, "id": req_id, "mode": mode, "steps": steps}
    if timeout_ms is not None:
        msg["timeout_ms"] = timeout_ms
    return msg


def make_result(req_id: str, ok: bool, steps: list[dict]) -> dict[str, Any]:
    return {"type": T_RESULT, "version": PROTOCOL_VERSION, "id": req_id, "ok": ok, "steps": steps}


def make_error(req_id: str | None, message: str, code: str = E_BAD_REQUEST) -> dict[str, Any]:
    return {"type": T_ERROR, "version": PROTOCOL_VERSION, "id": req_id,
            "ok": False, "code": code, "message": message}


def make_ping(ping_id: str) -> dict[str, Any]:
    return {"type": T_PING, "version": PROTOCOL_VERSION, "id": ping_id}


def make_pong(ping_id: str, ready: bool, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": T_PONG, "version": PROTOCOL_VERSION, "id": ping_id,
            "ok": True, "ready": ready, "detail": detail or {}}


def validate_request(msg: dict[str, Any]) -> tuple[str, list[dict], int | None]:
    """Validate a sync request, returning (id, steps, timeout_ms). Raises ProtocolError (with a
    ``code``) otherwise — async requests and reserved ops are rejected here so a caller can turn
    the error into an ``error`` response.
    """
    if msg.get("type") != T_REQUEST:
        raise ProtocolError(f"expected a '{T_REQUEST}', got '{msg.get('type')}'")
    req_id = msg.get("id")
    if not req_id:
        raise ProtocolError("request missing 'id'")
    mode = msg.get("mode", MODE_SYNC)
    if mode != MODE_SYNC:
        raise ProtocolError(f"mode '{mode}' not yet supported (only '{MODE_SYNC}')",
                            code=E_UNSUPPORTED_MODE)
    steps = msg.get("steps")
    if not isinstance(steps, list):
        raise ProtocolError("request 'steps' must be a list")
    for step in steps:
        op = step.get("op") if isinstance(step, dict) else None
        if op not in SYNC_OPS:
            raise ProtocolError(f"step op '{op}' not supported in sync mode", code=E_UNSUPPORTED_OP)
    timeout_ms = msg.get("timeout_ms")
    return req_id, steps, timeout_ms


class LineBuffer:
    """Reassembles a byte stream into complete newline-terminated messages.

    A socket ``recv`` may return half a message or several glued together; feed the raw bytes in
    and iterate the complete lines out. Keeps any trailing partial line buffered for next time.
    """

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, data: bytes) -> Iterator[str]:
        self._buf += data
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            text = line.strip()
            if text:
                yield text.decode("utf-8")
