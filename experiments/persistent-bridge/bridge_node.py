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

    def _on_line(self, conn: socket.socket, line: str) -> None:
        req_id = None
        try:
            msg = bp.decode(line)
            req_id = msg.get("id")
            req_id, steps = bp.validate_request(msg)
            results = execute_steps(self.node, steps, self.clients)
            ok = all(r["rc"] == 0 for r in results)
            conn.sendall(bp.encode(bp.make_result(req_id, ok, results)))
            self.log.info(f"req {req_id} · {len(steps)} steps · ok={ok}")
        except bp.ProtocolError as exc:
            conn.sendall(bp.encode(bp.make_error(req_id, str(exc))))
            self.log.warn(f"rejected req {req_id}: {exc}")

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
