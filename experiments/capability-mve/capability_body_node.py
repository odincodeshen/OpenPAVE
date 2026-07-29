#!/usr/bin/env python3
"""Generic capability body node (Plan A).

Subscribes ``/openpave/action``, and for each ``{action, params}`` routes it to the selected
adapter **only if the adapter declares that capability**, then publishes the result on
``/openpave/action_state``. It knows nothing about arms or locomotion — that is the whole point:
a new robot class is a new adapter, and this node + the zenoh seam stay unchanged.

Select the adapter with ``ROBOT_ADAPTER`` (default ``mock_arm``). Runs on the body host (e.g.
the plain RPi5 at 192.168.0.13) as a zenoh ``client``, same as the zenoh MVE.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capability_schema import CapabilityIntentError, normalize_action_payload, now_iso
from mock_arm_adapter import MockArmAdapter

ACTION_TOPIC = "/openpave/action"
STATE_TOPIC = "/openpave/action_state"

# adapter registry (add new robot classes here — nothing else in this file changes)
ADAPTERS = {"mock_arm": MockArmAdapter}


class CapabilityBody(Node):
    def __init__(self) -> None:
        super().__init__("openpave_body_capability")
        adapter_name = os.environ.get("ROBOT_ADAPTER", "mock_arm")
        if adapter_name not in ADAPTERS:
            raise SystemExit(f"unknown ROBOT_ADAPTER: {adapter_name} (have {sorted(ADAPTERS)})")
        self.adapter = ADAPTERS[adapter_name]()

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
