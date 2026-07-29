#!/usr/bin/env python3
"""Generic capability body node (ROS/zenoh runnable for the capability model).

Subscribes ``/openpave/action``, and for each ``{action, params}`` routes it to the selected
adapter **only if the adapter declares that capability**, then publishes the result on
``/openpave/action_state``. It knows nothing about arms or locomotion — a new robot class is a
new adapter and this node + the zenoh seam stay unchanged.

The capability model now lives in the runtime (``pave_runtime.capability_schema`` +
``control_daemon.adapters``); this node is just the ROS/zenoh execution layer over it. Select the
adapter with ``ROBOT_ADAPTER`` (e.g. ``mock_arm``). Runs on the body host as a zenoh ``client``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

# make the repo (runtime) importable: experiments/capability-mve/ -> repo root
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pave_runtime.capability_schema import CapabilityIntentError, normalize_action_payload
from pave_runtime.intent_schema import now_iso
from control_daemon.adapters import create_robot_adapter

ACTION_TOPIC = "/openpave/action"
STATE_TOPIC = "/openpave/action_state"


class CapabilityBody(Node):
    def __init__(self) -> None:
        super().__init__("openpave_body_capability")
        self.adapter = create_robot_adapter(os.environ.get("ROBOT_ADAPTER", "mock_arm"))

        self.state_pub = self.create_publisher(String, STATE_TOPIC, 10)
        self.create_subscription(String, ACTION_TOPIC, self.on_action, 10)
        self.get_logger().info(
            f"capability body up · adapter={self.adapter.name} · "
            f"capabilities={sorted(self.adapter.capabilities)} · listening {ACTION_TOPIC}"
        )

    def _publish(self, obj: dict) -> None:
        msg = String()
        msg.data = json.dumps(obj, ensure_ascii=False)
        self.state_pub.publish(msg)

    def on_action(self, msg: String) -> None:
        try:
            action = normalize_action_payload(json.loads(msg.data), default_source="capability-mve")
        except (json.JSONDecodeError, CapabilityIntentError) as exc:
            self.get_logger().warn(f"bad action: {exc}")
            self._publish({"status": "rejected", "error": str(exc), "updated_at": now_iso()})
            return

        name = action["action"]
        base = {"request_id": action["request_id"], "action": name, "updated_at": now_iso()}

        if name not in self.adapter.capabilities:
            self.get_logger().warn(f"unsupported capability: {name} (adapter={self.adapter.name})")
            self._publish({**base, "status": "unsupported",
                           "error": f"{self.adapter.name} does not support '{name}'"})
            return

        self.get_logger().info(f"action {name} req={action['request_id']} params={action['params']}")
        result = self.adapter.execute(name, action["params"])
        self._publish({
            **base,
            "status": "completed" if result.success else "failed",
            "detail": result.detail,
            "error": result.error,
        })


def main() -> None:
    rclpy.init()
    node = CapabilityBody()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
