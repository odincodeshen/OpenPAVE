#!/usr/bin/env python3
"""Measure the seam round-trip latency against a running body (control plane).

For each of BENCH_N sends this reports the **total** round-trip and the body-side **execution**
(`detail.latency_ms`), so the **seam segment = total - execution**. Run it against a *mock* body
(`ROBOT_ADAPTER=mock_arm`) so execution is ~0 and the seam segment is isolated.

  body : SEAM_TRANSPORT=raw_zenoh ROBOT_ADAPTER=mock_arm python scripts/seam_cli.py serve
  bench: SEAM_TRANSPORT=raw_zenoh python scripts/seam_bench.py

Note: the current `send()` opens a fresh transport session per call. For `raw_zenoh` that includes a
fixed ~500 ms discovery settle (`asyncio.sleep(0.5)` in the backend); for `device_connect` it includes
D2D discovery. This is a per-session setup cost that a persistent brain session would pay once, not per
action — the steady-state wire round-trip is what remains after subtracting that.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pave_runtime.seam import create_seam_transport


def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * p / 100.0
    f = int(k)
    return xs[f] if f + 1 >= len(xs) else xs[f] + (xs[f + 1] - xs[f]) * (k - f)


async def main() -> None:
    action = os.getenv("BENCH_ACTION", "move_joint")
    params = json.loads(os.getenv("BENCH_PARAMS", '{"joint": 1, "position": 0.2}'))
    n = int(os.getenv("BENCH_N", "20"))
    seam = create_seam_transport()
    print(f"[seam_bench] transport={seam.name} action={action} n={n}")

    rows: list[tuple[float, float, float, bool]] = []
    for i in range(n):
        t0 = time.perf_counter()
        state = await seam.send(action, params)
        total = (time.perf_counter() - t0) * 1000.0
        detail = state.get("detail") if isinstance(state, dict) else None
        execu = float(detail.get("latency_ms", 0.0)) if isinstance(detail, dict) else 0.0
        ok = isinstance(state, dict) and state.get("status") == "completed"
        rows.append((total, execu, total - execu, ok))
        tag = "ok" if ok else f"FAIL {state}"
        print(f"  {i:2d}  total={total:8.1f}ms  exec={execu:7.1f}ms  seam={total - execu:8.1f}ms  {tag}")

    good = [r for r in rows if r[3]]
    if not good:
        print("\n[seam_bench] no completed sends")
        return
    seam_vals = [r[2] for r in good]
    tot_vals = [r[0] for r in good]
    print(f"\n[seam_bench] completed {len(good)}/{n}  (first send carries one-time discovery/settle)")
    print(f"  seam segment ms : min {min(seam_vals):7.1f}  p50 {_pct(seam_vals, 50):7.1f}  p95 {_pct(seam_vals, 95):7.1f}")
    print(f"  total e2e   ms  : min {min(tot_vals):7.1f}  p50 {_pct(tot_vals, 50):7.1f}  p95 {_pct(tot_vals, 95):7.1f}")


if __name__ == "__main__":
    asyncio.run(main())
