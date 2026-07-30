#!/usr/bin/env python3
"""Measure PuppyPiLocalAdapter action latency on the real robot (opt A before/after).

Times one action (home / stop / trot) end-to-end N times and prints per-run + avg/min/max
wall-clock ms. Run from the repo root so `control_daemon` imports; select the puppy_control
container via env. Same script for the "before" (main) and "after" (feat/persistent-bridge)
checkouts — keep it OUTSIDE the git tree (e.g. /tmp) so `git checkout` doesn't change it.

Usage (on the PuppyPi, from the repo root):
    ROBOT_ADAPTER=puppypi_local \
    PUPPY_EXEC_CONTAINER=puppypi_ros2 \
    python3 /tmp/bench_action.py home 5

SAFETY: home / stop only re-pose the robot (no travel). trot makes it step in place — elevate
the robot before timing trot. Never bench `move` here (it drives).
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.getcwd())  # repo root, so `control_daemon` / `pave_runtime` import

from control_daemon.adapters import create_robot_adapter

action = sys.argv[1] if len(sys.argv) > 1 else "home"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 5

adapter = create_robot_adapter("puppypi_local")
fn = {"home": adapter.home, "stop": adapter.stop, "trot": adapter.trot}[action]

print(f"benchmarking {action!r} x{n}  adapter={adapter.name} "
      f"container={os.environ.get('PUPPY_EXEC_CONTAINER', '(default)')}")

# one warm-up (not counted) to shed first-call OS/docker cache effects
fn()
time.sleep(1.5)

samples = []
for i in range(n):
    t0 = time.perf_counter()
    result = fn()
    dt_ms = (time.perf_counter() - t0) * 1000
    samples.append(dt_ms)
    print(f"[{i + 1}/{n}] {action} {dt_ms:.0f} ms  success={result.success}")
    time.sleep(1.5)  # let the robot settle between runs

print(f"\n{action}: avg {statistics.mean(samples):.0f} ms  "
      f"min {min(samples):.0f}  max {max(samples):.0f}  (n={n})")
