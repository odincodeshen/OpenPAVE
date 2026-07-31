"""Shared gait-step executor: run a list of {service / velocity / sleep} steps on one rclpy node.

The service clients / publishers are kept in a **caller-owned cache**, so a long-lived caller
(the persistent bridge) reuses them across requests and pays discovery only once — that reuse is
exactly what optimization B buys. Mirrors the step logic in
``control_daemon/puppy_gait_runner.py`` (opt A); kept here for the experiment, to be unified on
graduation.

Result per step: ``{"name": ..., "rc": 0}`` — rc 0 ok, 2 service unavailable, 3 call timed out,
9 unknown op.
"""

from __future__ import annotations

import importlib
import time
from typing import Any

import rclpy


def resolve_type(dotted: str):
    # "std_srvs/srv/SetBool" -> std_srvs.srv.SetBool
    pkg, kind, name = dotted.split("/")
    return getattr(importlib.import_module(f"{pkg}.{kind}"), name)


def _set_fields(msg, data: dict) -> None:
    for key, value in (data or {}).items():
        setattr(msg, key, value)


def execute_steps(
    node, steps: list[dict], clients: dict[Any, Any], default_timeout: float = 5.0
) -> list[dict]:
    """Run ``steps`` on ``node``, reusing service clients / publishers cached in ``clients``.

    ``clients`` is keyed by ``("svc", name)`` / ``("pub", name)`` and owned by the caller — pass
    the same dict across calls to reuse connections (bridge), or a fresh dict each time to force a
    cold start (the cold baseline in the benchmark). ``default_timeout`` (seconds) is used for a
    service step that doesn't set its own ``timeout`` — the bridge derives it from the request's
    ``timeout_ms``.
    """
    results: list[dict] = []
    for step in steps:
        op = step.get("op")

        if op == "sleep":
            time.sleep(float(step.get("sec", 0.0)))
            results.append({"name": "sleep", "rc": 0})

        elif op == "velocity":
            velocity_type = resolve_type("puppy_control_msgs/msg/Velocity")
            key = ("pub", "/puppy_control/velocity_move")
            pub = clients.get(key)
            if pub is None:
                pub = node.create_publisher(velocity_type, "/puppy_control/velocity_move", 10)
                clients[key] = pub
            msg = velocity_type()
            msg.x = float(step.get("x", 0.0))
            msg.y = float(step.get("y", 0.0))
            msg.yaw_rate = float(step.get("yaw_rate", 0.0))
            pub.publish(msg)
            end = time.time() + 0.3  # brief spin so the one-shot publish flushes
            while time.time() < end:
                rclpy.spin_once(node, timeout_sec=0.05)
            results.append({"name": "velocity_move", "rc": 0})

        elif op == "service":
            svc = step["service"]
            timeout = float(step.get("timeout", default_timeout))
            key = ("svc", svc)
            cli = clients.get(key)
            if cli is None:
                cli = node.create_client(resolve_type(step["type"]), svc)
                clients[key] = cli
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
