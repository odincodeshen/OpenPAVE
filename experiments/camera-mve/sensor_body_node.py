#!/usr/bin/env python3
"""Generic sensor body node (ROS/zenoh runnable) — control plane + data plane.

Same generic-body idea as the capability body, extended to *sensing*:

* **control plane** — subscribe ``/openpave/action``; for ``{action:"get_image"}`` (only if the
  adapter declares it) call ``adapter.execute`` and publish the small **metadata** on
  ``/openpave/action_state``.
* **data plane** — if the adapter produced a frame (``last_jpeg``), publish it as a
  ``sensor_msgs/CompressedImage`` on ``/openpave/image``. The heavy image never rides in the
  JSON result — that separation is the point.

The camera adapter now lives in the runtime (``control_daemon.camera_adapter``); this node is
just the ROS/zenoh execution layer over it. Select it with ``ROBOT_ADAPTER`` (``camera_mock`` /
``camera_usb``; ``CAMERA_DEVICE`` picks the USB device). Runs on the body host as a zenoh
``client``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

# make the repo (runtime) importable: experiments/camera-mve/ -> repo root
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pave_runtime.capability_schema import CapabilityIntentError, normalize_action_payload
from pave_runtime.intent_schema import now_iso
from control_daemon.adapters import create_robot_adapter

ACTION_TOPIC = "/openpave/action"
STATE_TOPIC = "/openpave/action_state"
IMAGE_TOPIC = "/openpave/image"  # data plane


class SensorBody(Node):
    def __init__(self) -> None:
        super().__init__("openpave_body_sensor")
        self.adapter = create_robot_adapter(os.environ.get("ROBOT_ADAPTER", "camera_mock"))

        self.state_pub = self.create_publisher(String, STATE_TOPIC, 10)
        self.image_pub = self.create_publisher(CompressedImage, IMAGE_TOPIC, 10)
        self.create_subscription(String, ACTION_TOPIC, self.on_action, 10)
        self.get_logger().info(
            f"sensor body up · adapter={self.adapter.name} · "
            f"capabilities={sorted(self.adapter.capabilities)} · "
            f"control {ACTION_TOPIC} · data {IMAGE_TOPIC}"
        )

    def _publish_state(self, obj: dict) -> None:
        msg = String()
        msg.data = json.dumps(obj, ensure_ascii=False)
        self.state_pub.publish(msg)

    def _publish_frame(self, jpeg: bytes) -> None:
        img = CompressedImage()
        img.header.stamp = self.get_clock().now().to_msg()
        img.format = "jpeg"
        img.data = list(jpeg)
        self.image_pub.publish(img)

    def on_action(self, msg: String) -> None:
        try:
            action = normalize_action_payload(json.loads(msg.data), default_source="camera-mve")
        except (json.JSONDecodeError, CapabilityIntentError) as exc:
            self.get_logger().warn(f"bad action: {exc}")
            self._publish_state({"status": "rejected", "error": str(exc), "updated_at": now_iso()})
            return

        name = action["action"]
        base = {"request_id": action["request_id"], "action": name, "updated_at": now_iso()}

        if name not in self.adapter.capabilities:
            self.get_logger().warn(f"unsupported capability: {name} (adapter={self.adapter.name})")
            self._publish_state({**base, "status": "unsupported",
                                 "error": f"{self.adapter.name} does not support '{name}'"})
            return

        self.get_logger().info(f"action {name} req={action['request_id']} params={action['params']}")
        result = self.adapter.execute(name, action["params"])

        # data plane: if the sensor produced a frame, publish it on the image topic
        jpeg = getattr(self.adapter, "last_jpeg", None)
        if result.success and jpeg:
            self._publish_frame(jpeg)
            self.get_logger().info(f"published frame {len(jpeg)} bytes on {IMAGE_TOPIC}")

        # control plane: small metadata only
        self._publish_state({
            **base,
            "status": "completed" if result.success else "failed",
            "detail": result.detail,
            "error": result.error,
        })


def main() -> None:
    rclpy.init()
    node = SensorBody()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
