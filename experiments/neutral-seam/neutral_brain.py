#!/usr/bin/env python3
"""Neutral brain: send one {action, params} and print the state reply — todo ② option (a).

Raw zenoh (zenoh-python), no ROS. Usage:
    python3 neutral_brain.py move_joint '{"joint": 2, "position": 0.5}'
    python3 neutral_brain.py grasp
    python3 neutral_brain.py trot        # -> body rejects (mock_arm has no such capability)
"""

from __future__ import annotations

import json
import sys
import time

import zenoh

ACTION_KEY = "openpave/action"
STATE_KEY = "openpave/action_state"


def _payload_bytes(sample) -> bytes:
    try:
        return sample.payload.to_bytes()
    except AttributeError:
        return bytes(sample.payload)


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: neutral_brain.py ACTION [params_json]", file=sys.stderr)
        sys.exit(1)
    payload: dict = {"action": sys.argv[1]}
    if len(sys.argv) > 2:
        payload["params"] = json.loads(sys.argv[2])

    session = zenoh.open(zenoh.Config())
    replies: list[dict] = []
    session.declare_subscriber(STATE_KEY, lambda s: replies.append(json.loads(_payload_bytes(s))))
    pub = session.declare_publisher(ACTION_KEY)

    time.sleep(0.5)  # let zenoh discovery + the body's subscription match
    pub.put(json.dumps(payload).encode("utf-8"))
    print(f"sent {payload}")

    deadline = time.time() + 5.0
    while time.time() < deadline and not replies:
        time.sleep(0.05)
    if replies:
        print("state:", json.dumps(replies[-1], ensure_ascii=False))
    else:
        print("no state reply within timeout", file=sys.stderr)
    session.close()


if __name__ == "__main__":
    main()
