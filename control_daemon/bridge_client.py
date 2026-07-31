"""Runtime-side client for the Persistent Body-Side Bridge (B2).

A thin, dependency-free client the ``PuppyPiBridgeAdapter`` uses to talk to a running bridge over
a localhost **TCP** or **Unix domain** socket. It carries a minimal copy of the wire protocol so
the runtime does not depend on ``experiments/persistent-bridge`` (the full protocol + bridge node
live there; this is the small client slice, to be unified on graduation).

Sync only. ``ping`` returns the raw readiness detail; the adapter decides usability from
``ok && ready && services_ready`` (see the B2 design, §3.3).
"""

from __future__ import annotations

import json
import socket
from typing import Any

PROTOCOL_VERSION = "0.1"
T_REQUEST, T_RESULT, T_ERROR, T_PING, T_PONG = "request", "result", "error", "ping", "pong"
MODE_SYNC = "sync"


class BridgeError(RuntimeError):
    """A bridge ``error`` response. ``code`` is machine-readable (e.g. busy / unsupported_mode)."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(f"[{code}] {message}" if code else message)
        self.code = code


def _encode(msg: dict) -> bytes:
    return (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")


def _iter_lines(buf: bytearray):
    while b"\n" in buf:
        line, _, rest = buf.partition(b"\n")
        del buf[: len(line) + 1]
        text = line.strip()
        if text:
            yield text.decode("utf-8")


class BridgeClient:
    """Connect to a bridge and exchange one request at a time.

    ``endpoint`` is either ``("tcp", host, port)`` or ``("unix", path)`` — chosen by the deployment
    per the socket-namespace decision (design §3.1).
    """

    def __init__(self, endpoint: tuple, connect_timeout: float = 3.0) -> None:
        self.endpoint = endpoint
        self._connect_timeout = connect_timeout
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        self._seq = 0

    # ---- connection ----
    def _connect(self) -> socket.socket:
        if self._sock is not None:
            return self._sock
        kind = self.endpoint[0]
        if kind == "tcp":
            _, host, port = self.endpoint
            sock = socket.create_connection((host, port), timeout=self._connect_timeout)
        elif kind == "unix":
            _, path = self.endpoint
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self._connect_timeout)
            sock.connect(path)
        else:
            raise ValueError(f"unknown bridge endpoint kind: {kind!r}")
        self._sock, self._buf = sock, bytearray()
        return sock

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _reset(self) -> None:
        """Drop the connection so the next call reconnects (after any socket error)."""
        self.close()

    # ---- exchange ----
    def _await(self, req_id: str, want: str, timeout: float) -> dict:
        sock = self._connect()
        sock.settimeout(timeout)
        while True:
            try:
                data = sock.recv(65536)
            except (socket.timeout, OSError) as exc:
                self._reset()
                raise ConnectionError(f"bridge recv failed: {exc}") from exc
            if not data:
                self._reset()
                raise ConnectionError("bridge closed the connection")
            self._buf.extend(data)
            for line in _iter_lines(self._buf):
                msg = json.loads(line)
                if msg.get("id") != req_id:
                    continue
                mtype = msg.get("type")
                if mtype == want:
                    return msg
                if mtype == T_ERROR:
                    raise BridgeError(msg.get("message", "bridge error"), msg.get("code"))

    def _send(self, msg: dict) -> None:
        try:
            self._connect().sendall(_encode(msg))
        except OSError as exc:
            self._reset()
            raise ConnectionError(f"bridge send failed: {exc}") from exc

    def ping(self, timeout: float = 2.0) -> tuple[bool, dict[str, Any]]:
        """Probe the bridge. Returns (ready, detail). The adapter gates usability on
        ``ready and detail.get('services_ready')``. Raises on no/failed reply."""
        self._seq += 1
        ping_id = f"a{self._seq}"
        self._send({"type": T_PING, "version": PROTOCOL_VERSION, "id": ping_id})
        pong = self._await(ping_id, T_PONG, timeout)
        return bool(pong.get("ready")), pong.get("detail", {})

    def run_steps(self, steps: list[dict], timeout: float = 10.0,
                  timeout_ms: int | None = None) -> tuple[bool, list[dict]]:
        """Send one sync request, block until its result. Returns (ok, steps).
        Raises BridgeError (e.g. code='busy') or ConnectionError."""
        self._seq += 1
        req_id = f"a{self._seq}"
        msg = {"type": T_REQUEST, "version": PROTOCOL_VERSION, "id": req_id,
               "mode": MODE_SYNC, "steps": steps}
        if timeout_ms is not None:
            msg["timeout_ms"] = timeout_ms
        self._send(msg)
        result = self._await(req_id, T_RESULT, timeout)
        return bool(result.get("ok")), result.get("steps", [])
