#!/usr/bin/env python3
"""OpenPAVE zenoh MVE (E1b) — @rpc body service (runs on the RPi / body host).

Serves ``openpave_interfaces/srv/SubmitIntent`` on ``/openpave/submit_intent``.
Each request carries an intent as JSON; the handler runs it through the existing
``MockAdapter`` and returns the ``command_result`` JSON in the SAME reply — a
true request/reply (``@rpc``), not a correlated pub/sub pair. No robot motion.

Compared to ``body_node.py`` (E1a, pub/sub topics), this is the request/reply
form: the brain gets its result synchronously on the call it made.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import rclpy
from rclpy.node import Node

from openpave_interfaces.srv import SubmitIntent

# make the repo modules importable (experiments/zenoh-mve/ -> repo root)
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pave_runtime.intent_schema import (
    IntentValidationError,
    normalize_intent_payload,
    now_iso,
)
from control_daemon.adapters import create_robot_adapter
from control_daemon.feedback import command_result

SERVICE = "/openpave/submit_intent"


class BodyRpc(Node):
    def __init__(self) -> None:
        super().__init__("openpave_body_rpc")
        # safe default: mock. Set ROBOT_ADAPTER=puppypi to drive the real robot.
        self.adapter = create_robot_adapter(os.environ.get("ROBOT_ADAPTER", "mock"))
        self.srv = self.create_service(SubmitIntent, SERVICE, self.on_submit)
        self.get_logger().info(
            f"body @rpc up · adapter={self.adapter.name} · serving {SERVICE}"
        )

    def on_submit(self, request, response):
        try:
            payload = json.loads(request.payload)
            normalized = normalize_intent_payload(
                payload, default_source="zenoh-mve-rpc", safe_default=True
            )
        except (json.JSONDecodeError, IntentValidationError) as exc:
            self.get_logger().warn(f"bad intent: {exc}")
            response.result = json.dumps(
                command_result(
                    intent=None,
                    adapter_name=self.adapter.name,
                    status="rejected",
                    completed_at=now_iso(),
                    error=str(exc),
                ),
                ensure_ascii=False,
            )
            return response

        intent = normalized["intent"]
        params = normalized.get("params", {})
        self.get_logger().info(f"@rpc intent {intent} req={normalized['request_id']}")

        started = now_iso()
        if intent == "TROT":
            result = self.adapter.trot()
        elif intent == "HOME":
            result = self.adapter.home()
        elif intent == "MOVE":
            result = self.adapter.move(
                vx=float(params.get("vx", 0.0)),
                yaw=float(params.get("yaw", 0.0)),
                duration_ms=int(params.get("duration_ms", 500)),
            )
        else:
            result = self.adapter.stop()

        response.result = json.dumps(
            command_result(
                intent=normalized,
                adapter_name=self.adapter.name,
                status="completed" if result.success else "failed",
                started_at=started,
                completed_at=now_iso(),
                steps=result.steps,
                error=result.error,
            ),
            ensure_ascii=False,
        )
        return response


def main() -> None:
    rclpy.init()
    node = BodyRpc()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
