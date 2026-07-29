#!/usr/bin/env python3
"""One-shot gait runner: run a batch of puppy_control calls in a single rclpy node.

Optimization A for ``PuppyPiLocalAdapter``. Instead of one ``docker exec`` + one ``ros2`` CLI
per call (each paying ``source`` + a fresh node + service discovery), the adapter sends the whole
action as a step list to this script, run **once** inside the puppy_control container: one node,
service clients created once and reused across the steps, so N calls pay startup/discovery once.

Runs INSIDE the puppy_control container (FastDDS). The adapter feeds this file to ``python3 -``
over ``docker exec -i`` (no need to install it in the container) and passes the steps as a
**base64-encoded** JSON string in ``argv[1]`` (base64 keeps it free of shell-escaping).

Step ops::

    {"op": "service", "service": "/puppy_control/set_running",
     "type": "std_srvs/srv/SetBool", "data": {"data": true}, "timeout": 3.0}
    {"op": "velocity", "x": 0.0, "y": 0.0, "yaw_rate": 0.6}   # -> /puppy_control/velocity_move
    {"op": "sleep", "sec": 0.5}

Prints ``{"steps": [{"name": ..., "rc": 0}, ...]}`` to stdout (rc 0 = ok, nonzero = failure:
2 = service unavailable, 3 = call timed out, 9 = unknown op). Exit 0 iff every step rc == 0.
"""

from __future__ import annotations

import base64
import importlib
import json
import sys
import time

import rclpy


def _resolve_type(dotted: str):
    # "std_srvs/srv/SetBool" -> std_srvs.srv.SetBool
    pkg, kind, name = dotted.split("/")
    return getattr(importlib.import_module(f"{pkg}.{kind}"), name)


def _set_fields(msg, data: dict) -> None:
    for key, value in (data or {}).items():
        setattr(msg, key, value)


def run(node, steps: list[dict]) -> list[dict]:
    clients: dict = {}
    results: list[dict] = []
    for step in steps:
        op = step.get("op")
        if op == "sleep":
            time.sleep(float(step.get("sec", 0.0)))
            results.append({"name": "sleep", "rc": 0})
        elif op == "velocity":
            velocity_type = _resolve_type("puppy_control_msgs/msg/Velocity")
            pub = node.create_publisher(velocity_type, "/puppy_control/velocity_move", 10)
            msg = velocity_type()
            msg.x = float(step.get("x", 0.0))
            msg.y = float(step.get("y", 0.0))
            msg.yaw_rate = float(step.get("yaw_rate", 0.0))
            pub.publish(msg)
            end = time.time() + 0.3  # brief spin so the one-shot publish is flushed out
            while time.time() < end:
                rclpy.spin_once(node, timeout_sec=0.05)
            results.append({"name": "velocity_move", "rc": 0})
        elif op == "service":
            svc = step["service"]
            timeout = float(step.get("timeout", 5.0))
            cli = clients.get(svc)
            if cli is None:
                cli = node.create_client(_resolve_type(step["type"]), svc)
                clients[svc] = cli
            if not cli.wait_for_service(timeout_sec=timeout):
                results.append({"name": f"service:{svc}", "rc": 2})  # unavailable
                continue
            req = cli.srv_type.Request()
            _set_fields(req, step.get("data", {}))
            future = cli.call_async(req)
            rclpy.spin_until_future_complete(node, future, timeout_sec=timeout)
            ok = future.done() and future.result() is not None
            results.append({"name": f"service:{svc}", "rc": 0 if ok else 3})  # 3 = timed out
        else:
            results.append({"name": f"unknown:{op}", "rc": 9})
    return results


def main() -> None:
    payload = json.loads(base64.b64decode(sys.argv[1]).decode()) if len(sys.argv) > 1 else {}
    steps = payload["steps"] if isinstance(payload, dict) else payload

    rclpy.init()
    node = rclpy.create_node("openpave_gait_runner")
    try:
        results = run(node, steps)
    finally:
        node.destroy_node()
        rclpy.shutdown()

    print(json.dumps({"steps": results}))
    sys.exit(0 if all(r["rc"] == 0 for r in results) else 1)


if __name__ == "__main__":
    main()
