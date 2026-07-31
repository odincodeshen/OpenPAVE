#!/usr/bin/env python3
"""Cold baseline for B1 — build a fresh node + service clients per action (no reuse).

The opposite of the persistent bridge: each action pays node startup + service discovery again,
so this is the "before" the bridge improves on. Same mock service, same STOP step list, same host
as the bridge benchmark — so the difference is purely "reuse vs cold start", with no docker exec
in either (that extra saving only appears on the real robot, B2).

Run inside the ROS 2 container, with mock_controller already running:
    python3 bench_cold.py [N]
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import rclpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gait_steps import execute_steps  # noqa: E402
from bridge_client import STOP_STEPS  # noqa: E402


def one_action(idx: int) -> None:
    node = rclpy.create_node(f"cold_bench_{idx}")
    clients: dict = {}  # fresh cache every action -> discovery paid each time
    try:
        execute_steps(node, STOP_STEPS, clients)
    finally:
        node.destroy_node()


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    rclpy.init()
    try:
        one_action(0)  # warm-up (not counted)
        samples = []
        for i in range(n):
            t0 = time.perf_counter()
            one_action(i + 1)
            dt_ms = (time.perf_counter() - t0) * 1000
            samples.append(dt_ms)
            print(f"[{i + 1}/{n}] stop(cold) {dt_ms:.1f} ms")
        print(f"\ncold STOP: avg {statistics.mean(samples):.1f} ms  "
              f"min {min(samples):.1f}  max {max(samples):.1f}  (n={n})")
    finally:
        rclpy.shutdown()


if __name__ == "__main__":
    main()
