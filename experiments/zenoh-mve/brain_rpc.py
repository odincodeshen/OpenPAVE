#!/usr/bin/env python3
"""OpenPAVE zenoh MVE (E1b) — @rpc brain client (runs on the DGX / brain host).

Calls ``/openpave/submit_intent`` (``openpave_interfaces/srv/SubmitIntent``) for a
short sequence of intents and measures request/reply round-trip. True ``@rpc``:
the result comes back on the same call, no separate state topic. No robot involved.

Round-trip is timed on this host with a monotonic clock (call -> response), so it
needs no clock sync between the two machines.
"""

from __future__ import annotations

import json
import time
import uuid

import rclpy
from rclpy.node import Node

from openpave_interfaces.srv import SubmitIntent

SERVICE = "/openpave/submit_intent"

# raw payloads; the body normalizes them via intent_schema v0.1
SEQUENCE: list[dict] = [
    {"intent": "STOP"},
    {"intent": "TROT"},
    {"intent": "MOVE", "params": {"vx": 0.0, "yaw": 0.6, "duration_ms": 600}},
    {"intent": "HOME"},
]


class BrainRpc(Node):
    def __init__(self) -> None:
        super().__init__("openpave_brain_rpc")
        self.cli = self.create_client(SubmitIntent, SERVICE)
        self.get_logger().info(f"brain @rpc up · waiting for {SERVICE}")
        self.cli.wait_for_service()
        self.get_logger().info("service available")
        self.latencies: list[float] = []

    def run_sequence(self) -> None:
        for raw in SEQUENCE:
            payload = dict(raw)
            rid = f"probe-{uuid.uuid4().hex[:8]}"
            payload["request_id"] = rid

            req = SubmitIntent.Request()
            req.payload = json.dumps(payload)

            t0 = time.monotonic()
            future = self.cli.call_async(req)
            rclpy.spin_until_future_complete(self, future)
            dt_ms = (time.monotonic() - t0) * 1000.0

            resp = future.result()
            try:
                state = json.loads(resp.result) if resp is not None else {}
            except json.JSONDecodeError:
                state = {}
            self.latencies.append(dt_ms)
            self.get_logger().info(
                f"-> {payload['intent']} req={rid}  <- {state.get('status')}  "
                f"round-trip {dt_ms:.1f} ms"
            )

        vals = self.latencies
        if vals:
            self.get_logger().info(
                f"SUMMARY · {len(vals)}/{len(SEQUENCE)} @rpc calls · "
                f"avg {sum(vals)/len(vals):.1f} ms · min {min(vals):.1f} · max {max(vals):.1f}"
            )


def main() -> None:
    rclpy.init()
    node = BrainRpc()
    try:
        node.run_sequence()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
