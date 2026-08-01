#!/usr/bin/env python3
"""Neutral brain over Device Connect — todo ②(b): discover the OpenPAVE body, invoke one action.

The brain uses the device-connect **agent** SDK (`discover_devices` / `invoke_device`) instead of
raw zenoh pub/sub (②a). The body-endpoint contract is unchanged: it calls the body's `execute`
RPC with `{action, params}` and prints the returned capability state.

Usage (D2D, zero infra):
  DEVICE_CONNECT_ALLOW_INSECURE=true python3 openpave_agent.py move_joint '{"joint":2,"position":0.5}'
  DEVICE_CONNECT_ALLOW_INSECURE=true python3 openpave_agent.py grasp
  DEVICE_CONNECT_ALLOW_INSECURE=true python3 openpave_agent.py trot        # -> unsupported (mock_arm)
"""

from __future__ import annotations

import json
import sys

from device_connect_agent_tools import connect, discover_devices, invoke_device

DEVICE_TYPE = "openpave-body"


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: openpave_agent.py ACTION [params_json]", file=sys.stderr)
        sys.exit(1)
    action = sys.argv[1]
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    connect()
    devices = discover_devices(device_type=DEVICE_TYPE)
    if not devices:
        print(f"no {DEVICE_TYPE} device found", file=sys.stderr)
        sys.exit(2)
    device_id = devices[0].get("device_id") or devices[0].get("id")
    print(f"found {len(devices)} device(s), using: {device_id}")

    result = invoke_device(device_id, "execute", params={"action": action, "params": params})
    print("state:", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
