#!/usr/bin/env python3
"""Measure adapter action latency on the real robot — before/after with distribution metrics.

Times one action (home / stop / trot) end-to-end N times via the capability `execute()`, and
reports n / min / p50 / p95 / max / failures, plus which path each run took (bridge / fallback_a)
for the B2 bridge adapter. Select the adapter with ROBOT_ADAPTER:

    ROBOT_ADAPTER=puppypi_local  ... python3 /tmp/bench_action.py home 20   # before (A)
    ROBOT_ADAPTER=puppypi_bridge ... python3 /tmp/bench_action.py home 20   # after (B)

Run from the repo root so `control_daemon` imports; keep this file OUTSIDE the git tree (e.g.
/tmp) so `git checkout` between before/after doesn't change it.

SAFETY: home / stop only re-pose the robot (no travel). trot makes it step in place — elevate the
robot before timing trot. Never bench `move` here (it drives).
"""

import os
import sys
import time

sys.path.insert(0, os.getcwd())  # repo root, so control_daemon / pave_runtime import

from control_daemon.adapters import create_robot_adapter


def percentile(data, p):
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "home"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    adapter_name = os.environ.get("ROBOT_ADAPTER", "puppypi_local")
    adapter = create_robot_adapter(adapter_name)
    print(f"benchmarking {action!r} x{n}  adapter={adapter.name} "
          f"container={os.environ.get('PUPPY_EXEC_CONTAINER', '(default)')}")

    adapter.execute(action, {})  # one warm-up (not counted)
    time.sleep(1.5)

    samples, failures, paths = [], 0, {}
    for i in range(n):
        t0 = time.perf_counter()
        result = adapter.execute(action, {})
        dt_ms = (time.perf_counter() - t0) * 1000
        samples.append(dt_ms)
        if not result.success:
            failures += 1
        path = result.detail.get("path", "-")  # bridge / fallback_a (bridge adapter); "-" for A
        paths[path] = paths.get(path, 0) + 1
        print(f"[{i + 1}/{n}] {action} {dt_ms:.0f} ms  ok={result.success}  path={path}")
        time.sleep(1.5)  # let the robot settle between runs

    path_summary = "  ".join(f"{k}={v}" for k, v in sorted(paths.items()))
    print(f"\n{action} [{adapter.name}]: n={n}  min={min(samples):.0f}  "
          f"p50={percentile(samples, 50):.0f}  p95={percentile(samples, 95):.0f}  "
          f"max={max(samples):.0f}  ms  failures={failures}")
    print(f"paths: {path_summary}")


if __name__ == "__main__":
    main()
