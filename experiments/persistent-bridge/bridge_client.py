#!/usr/bin/env python3
"""Body-side bridge client (B1) — connect, send a request's steps, get the result.

Pure socket, no ROS: the body talks to the bridge over localhost. Sync only for B1; the receive
loop is structured so async (accepted -> progress... -> result) slots in later without changing
callers — see the marked hook.

Run standalone to benchmark the bridge against a running bridge_node + mock_controller:
    python3 bridge_client.py [N]
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bridge_protocol as bp  # noqa: E402

# a STOP as a step list (mock puppy_control answers these): motion-stop x2 + go_home
STOP_STEPS = [
    {"op": "service", "service": "/puppy_control/set_mark_time",
     "type": "std_srvs/srv/SetBool", "data": {"data": False}, "timeout": 3.0},
    {"op": "service", "service": "/puppy_control/set_running",
     "type": "std_srvs/srv/SetBool", "data": {"data": False}, "timeout": 3.0},
    {"op": "service", "service": "/puppy_control/go_home",
     "type": "std_srvs/srv/Empty", "data": {}, "timeout": 3.0},
]


class BridgeClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 8787, connect_timeout: float = 5.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=connect_timeout)
        self.buf = bp.LineBuffer()
        self._seq = 0

    def run_steps(self, steps: list[dict], mode: str = bp.MODE_SYNC, timeout: float = 15.0):
        """Send one request, block until its result. Returns (ok, steps). Raises on bridge error."""
        self._seq += 1
        req_id = f"c{self._seq}"
        self.sock.sendall(bp.encode(bp.make_request(req_id, steps, mode)))
        self.sock.settimeout(timeout)
        while True:
            data = self.sock.recv(65536)
            if not data:
                raise ConnectionError("bridge closed the connection")
            for line in self.buf.feed(data):
                msg = bp.decode(line)
                if msg.get("id") != req_id:
                    continue
                mtype = msg.get("type")
                if mtype == bp.T_RESULT:
                    return bool(msg.get("ok")), msg.get("steps", [])
                if mtype == bp.T_ERROR:
                    raise RuntimeError(msg.get("message", "bridge error"))
                # --- async hook: T_ACCEPTED / T_PROGRESS would be handled here (loop again
                #     until T_RESULT). Sync B1 never sees them, so we just keep reading. ---

    def close(self) -> None:
        self.sock.close()


def main() -> None:
    import statistics
    import time

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    host = os.environ.get("OPENPAVE_BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("OPENPAVE_BRIDGE_PORT", "8787"))

    client = BridgeClient(host, port)
    print(f"connected to bridge {host}:{port}; benchmarking STOP x{n}")
    client.run_steps(STOP_STEPS)  # warm-up (not counted)

    samples = []
    for i in range(n):
        t0 = time.perf_counter()
        ok, _ = client.run_steps(STOP_STEPS)
        dt_ms = (time.perf_counter() - t0) * 1000
        samples.append(dt_ms)
        print(f"[{i + 1}/{n}] stop {dt_ms:.1f} ms  ok={ok}")

    print(f"\nbridge STOP: avg {statistics.mean(samples):.1f} ms  "
          f"min {min(samples):.1f}  max {max(samples):.1f}  (n={n})")
    client.close()


if __name__ == "__main__":
    main()
