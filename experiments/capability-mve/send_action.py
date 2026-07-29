#!/usr/bin/env python3
"""Publish one capability action to /openpave/action — for manual testing (Plan A).

Usage:
    python3 send_action.py home
    python3 send_action.py grasp
    python3 send_action.py move_joint '{"joint": 2, "position": 0.5}'
    python3 send_action.py trot            # -> body rejects (arm has no such capability)

Builds the JSON with json.dumps (no shell-escaping pitfalls) and publishes exactly one action,
then exits. Run from a zenoh ``client`` on the same fabric as the body.
"""

from __future__ import annotations

import json
import sys
import time

import rclpy
from std_msgs.msg import String

TOPIC = "/openpave/action"


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: send_action.py ACTION [params_json]", file=sys.stderr)
        sys.exit(1)

    payload: dict = {"action": sys.argv[1]}
    if len(sys.argv) > 2:
        payload["params"] = json.loads(sys.argv[2])

    rclpy.init()
    node = rclpy.create_node("openpave_send_action")
    pub = node.create_publisher(String, TOPIC, 10)

    time.sleep(1.0)  # let the client connect + match the body's subscription
    msg = String()
    msg.data = json.dumps(payload)
    pub.publish(msg)
    for _ in range(10):
        rclpy.spin_once(node, timeout_sec=0.05)
        time.sleep(0.05)

    node.get_logger().info(f"published {msg.data}")
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
