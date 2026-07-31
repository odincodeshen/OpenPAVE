"""B1 bridge wire protocol — newline-delimited JSON over a localhost socket.

The **sync** request/response path is implemented. The **async / long-running** path (for AMR-style
navigate-and-report actions) is reserved: the message types, request mode, and step op are defined
here so future code only adds branches — the wire format does not change. See the B1 design doc.

Every message is one line of JSON with a ``type`` and (except the initial handshake) an ``id``.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

# ---- message types ----
T_REQUEST = "request"
T_RESULT = "result"
T_ERROR = "error"
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


class ProtocolError(ValueError):
    """Raised when a wire message can't be parsed or is malformed."""


def encode(msg: dict[str, Any]) -> bytes:
    """One message -> one newline-terminated JSON line (bytes)."""
    return (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")


def decode(line: str) -> dict[str, Any]:
    """Parse one JSON line into a message dict (must be an object with a ``type``)."""
    try:
        msg = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {exc}") from exc
    if not isinstance(msg, dict) or "type" not in msg:
        raise ProtocolError("message must be a JSON object with a 'type' field")
    return msg


# ---- message builders (keep call sites off raw dict literals) ----
def make_request(req_id: str, steps: list[dict], mode: str = MODE_SYNC) -> dict[str, Any]:
    return {"type": T_REQUEST, "id": req_id, "mode": mode, "steps": steps}


def make_result(req_id: str, ok: bool, steps: list[dict]) -> dict[str, Any]:
    return {"type": T_RESULT, "id": req_id, "ok": ok, "steps": steps}


def make_error(req_id: str | None, message: str) -> dict[str, Any]:
    return {"type": T_ERROR, "id": req_id, "message": message}


def validate_request(msg: dict[str, Any]) -> tuple[str, list[dict]]:
    """Validate a sync request and return (id, steps). Raises ProtocolError otherwise.

    async requests are rejected here (reserved but not yet implemented), so a caller can turn the
    ProtocolError into an ``error`` response.
    """
    if msg.get("type") != T_REQUEST:
        raise ProtocolError(f"expected a '{T_REQUEST}', got '{msg.get('type')}'")
    req_id = msg.get("id")
    if not req_id:
        raise ProtocolError("request missing 'id'")
    mode = msg.get("mode", MODE_SYNC)
    if mode != MODE_SYNC:
        raise ProtocolError(f"mode '{mode}' not yet supported (only '{MODE_SYNC}')")
    steps = msg.get("steps")
    if not isinstance(steps, list):
        raise ProtocolError("request 'steps' must be a list")
    for step in steps:
        op = step.get("op") if isinstance(step, dict) else None
        if op not in SYNC_OPS:
            raise ProtocolError(f"step op '{op}' not supported in sync mode")
    return req_id, steps


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
