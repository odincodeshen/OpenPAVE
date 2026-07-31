#!/usr/bin/env python3
"""Persistent bridge node (B1) — the "cerebellum" that stays connected to the controller.

A long-lived rclpy node + a localhost TCP socket server. On startup it creates the node once;
service clients are created lazily on first use and **kept** (cached in ``self.clients``), so
after the first call every request is just ``socket + already-connected call()`` — no per-action
docker exec / node startup / discovery. That reuse is the whole point of B.

Wire protocol: newline-delimited JSON (see ``bridge_protocol``). B1 handles sync requests only;
async / cancel are reserved in the protocol and rejected here for now.

Runs inside a ROS 2 container (FastDDS, same graph as the controller). Single-threaded: it serves
one connection at a time and drives rclpy inline while executing a request — enough for B1.

    OPENPAVE_BRIDGE_PORT=8787 python3 bridge_node.py
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import rclpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bridge_protocol as bp  # noqa: E402
from gait_steps import execute_steps  # noqa: E402


class Bridge:
    def __init__(self, host: str, port: int) -> None:
        rclpy.init()
        self.node = rclpy.create_node("openpave_bridge")
        self.clients: dict = {}  # ("svc"/"pub", name) -> client/publisher, reused across requests
        self.host, self.port = host, port
        self.log = self.node.get_logger()
        self._active = False  # single active request guard (B2 busy behavior)

    def serve(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(4)
        self.log.info(f"bridge up · listening {self.host}:{self.port} · clients reused across requests")
        try:
            while True:
                conn, addr = srv.accept()
                self.log.info(f"client connected: {addr}")
                self._handle(conn)
        finally:
            srv.close()

    def _handle(self, conn: socket.socket) -> None:
        buf = bp.LineBuffer()
        with conn:
            while True:
                try:
                    data = conn.recv(65536)
                except ConnectionError:
                    break
                if not data:
                    break
                for line in buf.feed(data):
                    self._on_line(conn, line)
        self.log.info("client disconnected")

    def _services_ready(self) -> bool:
        """Whether every already-created service client is connected (best-effort readiness)."""
        svc_clients = [c for key, c in self.clients.items() if key[0] == "svc"]
        return all(c.service_is_ready() for c in svc_clients)  # True (vacuously) before first use

    def _pong_detail(self) -> dict:
        # readiness + diagnostics; the adapter gates usability on services_ready (review #4)
        return {
            "services_ready": self._services_ready(),
            "controller": "puppy_control",
            "rmw": os.environ.get("RMW_IMPLEMENTATION", ""),
            "ros_domain_id": os.environ.get("ROS_DOMAIN_ID", ""),
            "bridge_pid": os.getpid(),
        }

    def _on_line(self, conn: socket.socket, line: str) -> None:
        req_id = None
        try:
            msg = bp.decode(line)
            req_id = msg.get("id")
            if msg.get("type") == bp.T_PING:  # liveness/readiness probe (B2 fallback uses this)
                conn.sendall(bp.encode(bp.make_pong(req_id, ready=True, detail=self._pong_detail())))
                return
            # single active request, no queue (B2): overlap -> 'busy'. Single-threaded serving makes
            # this rare, but it defines the contract for any future concurrency.
            if self._active:
                conn.sendall(bp.encode(bp.make_error(
                    req_id, "bridge is executing another request", bp.E_BUSY)))
                return
            self._active = True
            try:
                req_id, steps, timeout_ms = bp.validate_request(msg)
                default_timeout = timeout_ms / 1000.0 if timeout_ms else 5.0
                results = execute_steps(self.node, steps, self.clients, default_timeout=default_timeout)
                ok = all(r["rc"] == 0 for r in results)
                conn.sendall(bp.encode(bp.make_result(req_id, ok, results)))
                self.log.info(f"req {req_id} · {len(steps)} steps · ok={ok}")
            finally:
                self._active = False
        except bp.ProtocolError as exc:
            conn.sendall(bp.encode(bp.make_error(req_id, str(exc), exc.code)))
            self.log.warn(f"rejected req {req_id}: [{exc.code}] {exc}")

    def shutdown(self) -> None:
        self.node.destroy_node()
        rclpy.shutdown()


def main() -> None:
    host = os.environ.get("OPENPAVE_BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("OPENPAVE_BRIDGE_PORT", "8787"))
    bridge = Bridge(host, port)
    try:
        bridge.serve()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.shutdown()


if __name__ == "__main__":
    main()
