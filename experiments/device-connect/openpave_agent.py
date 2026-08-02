#!/usr/bin/env python3
"""Neutral brain over Device Connect — todo ②(b), option B: address individual capability RPCs
by **selector**, and drive a fleet-wide e-stop by **function label**.

Unlike ②a (raw zenoh pub/sub) or the A-version single `execute`, here each capability is its own
labeled RPC, so the brain speaks device-connect natively:
  - invoke one capability:  device(<id>).function(<action>)
  - fleet e-stop:           broadcast("function(estop)")   (no device id — label-addressed)

Usage (D2D, zero infra):
  DEVICE_CONNECT_ALLOW_INSECURE=true python3 openpave_agent.py home
  DEVICE_CONNECT_ALLOW_INSECURE=true python3 openpave_agent.py move_joint '{"joint":2,"position":0.5}'
  DEVICE_CONNECT_ALLOW_INSECURE=true python3 openpave_agent.py --discover
  DEVICE_CONNECT_ALLOW_INSECURE=true python3 openpave_agent.py --estop
"""

from __future__ import annotations

import json
import sys

from device_connect_agent_tools import (
    connect, discover, discover_devices, invoke, broadcast, await_replies,
)

DEVICE_TYPE = "openpave-body"


def _find_device_id() -> str | None:
    devices = discover_devices(device_type=DEVICE_TYPE)
    if not devices:
        return None
    return devices[0].get("device_id") or devices[0].get("id")


def main() -> None:
    args = sys.argv[1:]
    connect()

    if args and args[0] == "--discover":
        res = discover(f"device(category:*).function(*)")
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    if args and args[0] == "--estop":
        # fleet-wide emergency stop by function label — no device id needed
        res = broadcast("function(estop)")
        cid = res.get("correlation_id")
        print(f"estop broadcast: candidates={res.get('candidates')} correlation={cid}")
        if cid:
            replies = await_replies(cid, timeout=5.0)
            print("replies:", json.dumps(replies, ensure_ascii=False))
        return

    if not args:
        print("usage: openpave_agent.py ACTION [params_json] | --discover | --estop", file=sys.stderr)
        sys.exit(1)

    action = args[0]
    params = json.loads(args[1]) if len(args) > 1 else {}
    device_id = _find_device_id()
    if not device_id:
        print(f"no {DEVICE_TYPE} device found", file=sys.stderr)
        sys.exit(2)
    print(f"found device: {device_id}")

    # address the individual capability RPC by selector (device-connect native)
    result = invoke(f"device({device_id}).function({action})", params={"params": params})
    print("state:", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
