#!/usr/bin/env python3
"""Brain side of the camera MVE: request one frame on demand and save it.

Publishes ``{action:"get_image"}`` on ``/openpave/action`` (control plane), then waits for:

* the **metadata** on ``/openpave/action_state`` (small — the reply), and
* the **frame** on ``/openpave/image`` (``sensor_msgs/CompressedImage`` — the data plane),

writes the JPEG to ``--out`` (default ``/tmp/openpave_frame.jpg``) and prints the metadata. Run
from a zenoh ``client`` on the same fabric as the sensor body.

Usage:
    python3 get_image.py
    python3 get_image.py --out /tmp/shot.jpg --timeout 8
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import rclpy
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

ACTION_TOPIC = "/openpave/action"
STATE_TOPIC = "/openpave/action_state"
IMAGE_TOPIC = "/openpave/image"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/openpave_frame.jpg")
    ap.add_argument("--timeout", type=float, default=8.0)
    args = ap.parse_args()

    rclpy.init()
    node = rclpy.create_node("openpave_get_image")

    state: dict = {}
    frame: dict = {}

    def on_state(msg: String) -> None:
        try:
            state.update(json.loads(msg.data))
        except json.JSONDecodeError:
            pass

    def on_image(msg: CompressedImage) -> None:
        frame["bytes"] = bytes(msg.data)
        frame["format"] = msg.format

    node.create_subscription(String, STATE_TOPIC, on_state, 10)
    node.create_subscription(CompressedImage, IMAGE_TOPIC, on_image, 10)
    pub = node.create_publisher(String, ACTION_TOPIC, 10)

    time.sleep(1.0)  # let the client connect + match subscriptions
    msg = String()
    msg.data = json.dumps({"action": "get_image"})
    pub.publish(msg)
    node.get_logger().info(f"requested get_image -> {ACTION_TOPIC}")

    deadline = time.time() + args.timeout
    while time.time() < deadline and ("bytes" not in frame or "status" not in state):
        rclpy.spin_once(node, timeout_sec=0.1)

    if "status" in state:
        print(f"metadata: {json.dumps(state.get('detail', {}), ensure_ascii=False)}  "
              f"status={state.get('status')}")

    if frame.get("bytes"):
        with open(args.out, "wb") as fh:
            fh.write(frame["bytes"])
        print(f"saved {len(frame['bytes'])} bytes ({frame.get('format')}) -> {args.out}")
        rc = 0
    else:
        print("no frame received within timeout", file=sys.stderr)
        rc = 1

    node.destroy_node()
    rclpy.shutdown()
    sys.exit(rc)


if __name__ == "__main__":
    main()
