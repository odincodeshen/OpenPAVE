#!/usr/bin/env python3
"""Neutral (non-ROS) body endpoint over raw zenoh — todo ② option (a).

Subscribes the action key on a **raw zenoh** session (zenoh-python, NOT rmw_zenoh — no ROS),
routes each `{action, params}` to a `CapabilityAdapter` via `create_robot_adapter`, and publishes
state back. With `ROBOT_ADAPTER=mock_arm` this is a **fully non-ROS body**: pure Python +
zenoh-python, no rclpy, no dog. That is the ② result — a non-ROS robot is a first-class body.

Same capability contract as the ROS body (`{action, params}` in, state out); only the transport is
neutral. A ROS robot would run a thin zenoh↔ROS bridge instead; a real PuppyPi run selects
`ROBOT_ADAPTER=puppypi_bridge` (the seam stays neutral, the adapter talks to the bridge internally).

Run:  ROBOT_ADAPTER=mock_arm python3 neutral_body.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import zenoh

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pave_runtime.capability_schema import now_iso
from pave_runtime.seam import dispatch  # single-source body endpoint (graduated from this experiment)
from control_daemon.adapters import create_robot_adapter

ACTION_KEY = "openpave/action"        # down: {action, params}
STATE_KEY = "openpave/action_state"   # up: {status, detail, ...}


def _payload_bytes(sample) -> bytes:
    try:
        return sample.payload.to_bytes()
    except AttributeError:
        return bytes(sample.payload)


def zenoh_config() -> "zenoh.Config":
    """Default peer (multicast) config; override for cross-host via env:
    ``ZENOH_LISTEN=tcp/0.0.0.0:7447`` (this side listens) or ``ZENOH_CONNECT=tcp/<host>:7447``."""
    conf = zenoh.Config()
    for key, env in (("connect/endpoints", "ZENOH_CONNECT"), ("listen/endpoints", "ZENOH_LISTEN")):
        val = os.environ.get(env)
        if val:
            conf.insert_json5(key, json.dumps([val]))
    return conf


def main() -> None:
    adapter = create_robot_adapter(os.environ.get("ROBOT_ADAPTER", "mock_arm"))
    session = zenoh.open(zenoh_config())
    state_pub = session.declare_publisher(STATE_KEY)

    def publish(obj: dict) -> None:
        state_pub.put(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def on_action(sample) -> None:
        try:
            payload = json.loads(_payload_bytes(sample))
        except json.JSONDecodeError as exc:
            publish({"status": "rejected", "error": f"bad json: {exc}", "updated_at": now_iso()})
            return
        state = dispatch(adapter, payload.get("action", ""), payload.get("params"))
        publish(state)
        print(f"action {payload.get('action')} -> {state['status']}")

    session.declare_subscriber(ACTION_KEY, on_action)
    print(f"neutral body up · adapter={adapter.name} · "
          f"capabilities={sorted(adapter.capabilities)} · sub {ACTION_KEY} (raw zenoh, no ROS)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        session.close()


if __name__ == "__main__":
    main()
