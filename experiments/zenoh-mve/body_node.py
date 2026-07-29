#!/usr/bin/env python3
"""OpenPAVE zenoh MVE — mock body node (runs on the RPi / body host).

Subscribes ``/openpave/intent``, runs each intent through the existing
``MockAdapter``, and publishes lifecycle state on ``/openpave/robot_state``.
No ``puppy_control``, no motion. A heartbeat watchdog logs a STOP stub when the
brain link goes quiet.

This reuses the validated OpenPAVE runtime modules unchanged; only the transport
(file bus -> zenoh topic) is new. To drive a real robot later, swap the mock
adapter for ``ROBOT_ADAPTER=puppypi``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

# make the repo modules importable (experiments/zenoh-mve/ -> repo root)
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pave_runtime.intent_schema import (
    IntentValidationError,
    intent_to_capability_action,
    normalize_intent_payload,
    now_iso,
)
from control_daemon.adapters import AdapterActionResult, create_robot_adapter
from control_daemon.feedback import command_result, robot_state

INTENT_TOPIC = "/openpave/intent"
STATE_TOPIC = "/openpave/robot_state"
HEARTBEAT_TOPIC = "/openpave/heartbeat"
HEARTBEAT_TIMEOUT_SEC = 2.0


class BodyNode(Node):
    def __init__(self) -> None:
        super().__init__("openpave_body_mock")
        # safe default: mock. Set ROBOT_ADAPTER=puppypi to drive the real robot.
        self.adapter = create_robot_adapter(os.environ.get("ROBOT_ADAPTER", "mock"))

        self.state_pub = self.create_publisher(String, STATE_TOPIC, 10)
        self.create_subscription(String, INTENT_TOPIC, self.on_intent, 10)
        self.create_subscription(String, HEARTBEAT_TOPIC, self.on_heartbeat, 10)

        self._last_beat: float | None = None
        self._link_down = False
        self.create_timer(0.5, self._watchdog)

        self.get_logger().info(
            f"body node up · adapter={self.adapter.name} · listening {INTENT_TOPIC}"
        )
        self._publish_state("idle")

    # ---- feedback publishing -------------------------------------------------
    def _publish(self, obj: dict) -> None:
        msg = String()
        msg.data = json.dumps(obj, ensure_ascii=False)
        self.state_pub.publish(msg)

    def _publish_state(self, status: str, last_command: dict | None = None) -> None:
        self._publish(
            robot_state(
                adapter_name=self.adapter.name,
                status=status,
                last_command=last_command,
            )
        )

    # ---- heartbeat / fail-safe watchdog -------------------------------------
    def on_heartbeat(self, _msg: String) -> None:
        self._last_beat = time.monotonic()
        if self._link_down:
            self._link_down = False
            self.get_logger().info("brain link restored")

    def _watchdog(self) -> None:
        if self._last_beat is None:
            return  # never heard the brain yet; nothing to fail safe from
        gap = time.monotonic() - self._last_beat
        if not self._link_down and gap > HEARTBEAT_TIMEOUT_SEC:
            self._link_down = True
            self.get_logger().warn(
                f"heartbeat lost ({gap:.1f}s) -> FAIL-SAFE STOP (stub)"
            )
            self.adapter.stop()
            self._publish_state("fail_safe_stop")

    # ---- intent handling -----------------------------------------------------
    def on_intent(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
            normalized = normalize_intent_payload(
                payload, default_source="zenoh-mve", safe_default=True
            )
        except (json.JSONDecodeError, IntentValidationError) as exc:
            self.get_logger().warn(f"bad intent: {exc}")
            self._publish(
                command_result(
                    intent=None,
                    adapter_name=self.adapter.name,
                    status="rejected",
                    completed_at=now_iso(),
                    error=str(exc),
                )
            )
            return

        intent = normalized["intent"]
        self.get_logger().info(f"intent {intent} req={normalized['request_id']}")

        started = now_iso()
        self._publish(
            command_result(
                intent=normalized,
                adapter_name=self.adapter.name,
                status="executing",
                started_at=started,
            )
        )

        # translate the legacy intent to a capability action, then dispatch generically
        action_req = intent_to_capability_action(normalized)
        action = action_req["action"]
        if action not in self.adapter.capabilities:
            result = AdapterActionResult.failed(
                f"{self.adapter.name} does not support '{action}'"
            )
        else:
            result = self.adapter.execute(action, action_req["params"])

        self._publish(
            command_result(
                intent=normalized,
                adapter_name=self.adapter.name,
                status="completed" if result.success else "failed",
                started_at=started,
                completed_at=now_iso(),
                steps=result.steps,
                error=result.error,
            )
        )


def main() -> None:
    rclpy.init()
    node = BodyNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
