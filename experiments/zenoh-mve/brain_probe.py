#!/usr/bin/env python3
"""OpenPAVE zenoh MVE — brain probe (runs on the DGX / brain host).

Publishes a short sequence of intents on ``/openpave/intent`` plus a 1 Hz
heartbeat on ``/openpave/heartbeat``, subscribes to ``/openpave/robot_state``,
and measures round-trip latency per ``request_id``. No robot is involved.

Round-trip is timed entirely on this host with a monotonic clock, so it needs
no clock sync between the two machines.

Kill this probe (or the zenoh router) to test the body node's fail-safe: once
the heartbeat stops, the body logs a STOP stub.
"""

from __future__ import annotations

import json
import time
import uuid

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

INTENT_TOPIC = "/openpave/intent"
STATE_TOPIC = "/openpave/robot_state"
HEARTBEAT_TOPIC = "/openpave/heartbeat"

# raw payloads; the body node normalizes them via intent_schema v0.1
SEQUENCE: list[dict] = [
    {"intent": "STOP"},
    {"intent": "TROT"},
    {"intent": "MOVE", "params": {"vx": 0.0, "yaw": 0.6, "duration_ms": 600}},
    {"intent": "HOME"},
]


class BrainProbe(Node):
    def __init__(self) -> None:
        super().__init__("openpave_brain_probe")
        self.intent_pub = self.create_publisher(String, INTENT_TOPIC, 10)
        self.beat_pub = self.create_publisher(String, HEARTBEAT_TOPIC, 10)
        self.create_subscription(String, STATE_TOPIC, self.on_state, 10)

        self._sent: dict[str, float] = {}      # request_id -> monotonic send time
        self._latency_ms: dict[str, float] = {}  # request_id -> round-trip ms
        self._beat_seq = 0
        self._idx = 0

        self.create_timer(1.0, self._beat)          # 1 Hz heartbeat
        self.create_timer(1.5, self._send_next)     # start sending after discovery settles
        self.create_timer(0.5, self._maybe_summary)
        self.get_logger().info("brain probe up")

    def _beat(self) -> None:
        self._beat_seq += 1
        msg = String()
        msg.data = json.dumps({"seq": self._beat_seq})
        self.beat_pub.publish(msg)

    def _send_next(self) -> None:
        if self._idx >= len(SEQUENCE):
            return
        payload = dict(SEQUENCE[self._idx])
        self._idx += 1
        rid = f"probe-{uuid.uuid4().hex[:8]}"
        payload["request_id"] = rid
        self._sent[rid] = time.monotonic()

        msg = String()
        msg.data = json.dumps(payload)
        self.intent_pub.publish(msg)
        self.get_logger().info(f"-> sent {payload['intent']} req={rid}")

    def on_state(self, msg: String) -> None:
        try:
            state = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        rid = state.get("request_id")
        status = state.get("status")
        if rid in self._sent and status in {"completed", "failed"} and rid not in self._latency_ms:
            dt_ms = (time.monotonic() - self._sent[rid]) * 1000.0
            self._latency_ms[rid] = dt_ms
            self.get_logger().info(f"<- {status} req={rid} · round-trip {dt_ms:.1f} ms")

    def _maybe_summary(self) -> None:
        # print a one-shot summary once every sent intent has a reply
        if self._idx < len(SEQUENCE) or len(self._latency_ms) < len(SEQUENCE):
            return
        if getattr(self, "_summarized", False):
            return
        self._summarized = True
        vals = list(self._latency_ms.values())
        avg = sum(vals) / len(vals)
        self.get_logger().info(
            f"SUMMARY · {len(vals)}/{len(SEQUENCE)} round-trips · "
            f"avg {avg:.1f} ms · min {min(vals):.1f} · max {max(vals):.1f}"
        )
        self.get_logger().info("heartbeat still running — Ctrl-C (or kill the router) to test fail-safe")


def main() -> None:
    rclpy.init()
    node = BrainProbe()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
