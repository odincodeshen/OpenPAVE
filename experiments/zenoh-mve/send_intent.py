#!/usr/bin/env python3
"""Publish a single OpenPAVE intent — for the safety ladder / manual testing.

Usage:
    python3 send_intent.py STOP
    python3 send_intent.py HOME
    python3 send_intent.py TROT
    python3 send_intent.py MOVE '{"vx": 0.0, "yaw": 0.4, "duration_ms": 600}'

Publishes exactly ONE JSON intent to /openpave/intent (built with json.dumps, so there
are no shell-escaping pitfalls), then exits. It sends no heartbeat, so the body's fail-safe
watchdog stays dormant. Run it from a zenoh `client` on the same fabric as the body.
"""

from __future__ import annotations

import json
import sys
import time

import rclpy
from std_msgs.msg import String

TOPIC = "/openpave/intent"


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: send_intent.py INTENT [params_json]", file=sys.stderr)
        sys.exit(1)

    payload: dict = {"intent": sys.argv[1].upper()}
    if len(sys.argv) > 2:
        payload["params"] = json.loads(sys.argv[2])

    rclpy.init()
    node = rclpy.create_node("openpave_send_intent")
    pub = node.create_publisher(String, TOPIC, 10)

    # let the client connect to the router and match the body's subscription
    time.sleep(1.0)

    msg = String()
    msg.data = json.dumps(payload)
    pub.publish(msg)                      # exactly one intent
    for _ in range(10):                   # spin briefly to flush it out
        rclpy.spin_once(node, timeout_sec=0.05)
        time.sleep(0.05)

    node.get_logger().info(f"published {msg.data}")
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
