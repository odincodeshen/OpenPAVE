#!/usr/bin/env python3
"""Benchmark per-call seam round trips, including connection/discovery overhead.

See docs/seam-benchmark.md for safe mock-body setup and timeout limitations.
This does not measure pure network latency or persistent-session performance.
"""
from __future__ import annotations

import asyncio
import csv
import json
import math
import multiprocessing
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pave_runtime.seam import create_seam_transport

FIELDS = ["request", "transport", "brain_platform", "body_platform", "action",
          "total_ms", "execution_ms", "seam_ms", "success", "status", "error"]


def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100.0
    f = int(k)
    return xs[f] if f + 1 >= len(xs) else xs[f] + (xs[f + 1] - xs[f]) * (k - f)


def _send_worker(pipe, transport, action, params, timeout, factory):
    """Own all backend resources, including synchronous device-connect calls."""
    try:
        seam = factory(transport)
        start = time.perf_counter()
        state = asyncio.run(seam.send(action, params, timeout=timeout))
        pipe.send({"state": state, "total_ms": (time.perf_counter() - start) * 1000})
    except Exception as exc:
        pipe.send({"error": f"{type(exc).__name__}: {exc}",
                   "status": "timeout" if isinstance(exc, TimeoutError) else "failed"})
    finally:
        pipe.close()


async def run_attempt(transport, action, params, timeout, factory=create_seam_transport):
    # A thread or wait_for(send()) cannot interrupt device-connect's blocking SDK.
    # Spawn also avoids inheriting live native transport state between requests.
    ctx = multiprocessing.get_context("spawn")
    reader, writer = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_send_worker,
                          args=(writer, transport, action, params, timeout, factory))
    started = False
    try:
        process.start()
        started = True
        writer.close()
        deadline = time.monotonic() + timeout
        while not reader.poll():
            if time.monotonic() >= deadline:
                return {"status": "timeout", "error": f"request exceeded {timeout:g}s"}
            if not process.is_alive():
                return {"status": "failed", "error": f"worker exited ({process.exitcode}) without response"}
            await asyncio.sleep(0.01)
        try:
            return reader.recv()
        except EOFError:
            return {"status": "failed", "error": "worker closed without response"}
    except Exception as exc:
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        reader.close()
        writer.close()
        if started:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join()
            process.close()


def make_row(number, transport, action, result):
    row = dict.fromkeys(FIELDS, "")
    row.update(request=number, transport=transport, action=action,
               brain_platform=os.getenv("BENCH_BRAIN_PLATFORM", "unknown"),
               body_platform=os.getenv("BENCH_BODY_PLATFORM", "unknown"),
               success=False, status=result.get("status", "failed"), error=result.get("error", ""))
    state = result.get("state")
    if not isinstance(state, dict) or not isinstance(state.get("status"), str):
        if "state" in result:
            row["error"] = "invalid response: expected a state dictionary with status"
        return row
    status = state["status"]
    row.update(status="completed" if status == "completed" else "failed",
               success=status == "completed", error=state.get("error") or ("" if status == "completed" else status))
    if status in {"timeout", "no_reply"}:
        row.update(status="timeout", success=False)
        return row
    row["total_ms"] = round(result["total_ms"], 3)
    detail = state.get("detail")
    value = detail.get("latency_ms") if isinstance(detail, dict) else None
    # Absence of body timing (including mock_arm) is unknown, never zero.
    if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        row["execution_ms"] = round(value, 3)
        row["seam_ms"] = round(result["total_ms"] - value, 3)
    return row


def summarize(rows):
    good = [r for r in rows if r["success"]]
    failed = sum(r["status"] == "failed" for r in rows)
    timed_out = sum(r["status"] == "timeout" for r in rows)
    rate = len(good) / len(rows) * 100 if rows else 0
    print(f"\n[seam_bench] attempted={len(rows)} successful={len(good)} failed={failed} timed_out={timed_out} success_rate={rate:.1f}%")
    print("  Each send includes connection/discovery overhead; this is not pure network or steady-state latency.")
    if not good:
        print("  No successful requests; latency statistics unavailable.")
        return
    for field, label in (("total_ms", "total e2e"), ("execution_ms", "body execution"), ("seam_ms", "seam segment")):
        values = [r[field] for r in good if r[field] != ""]
        if values:
            print(f"  {label} ms: min {min(values):.1f} mean {statistics.mean(values):.1f} p50 {_pct(values, 50):.1f} p95 {_pct(values, 95):.1f} (n={len(values)})")
        else:
            print(f"  {label} ms: unavailable (body did not report execution timing)")


async def main():
    action = os.getenv("BENCH_ACTION", "stop")
    if action not in {"stop", "estop"} and os.getenv("BENCH_ALLOW_MOTION") != "1":
        raise ValueError("Non-stop actions require BENCH_ALLOW_MOTION=1; first verify the remote body uses ROBOT_ADAPTER=mock_arm")
    params = json.loads(os.getenv("BENCH_PARAMS", '{"joint": 1, "position": 0.2}'))
    n = int(os.getenv("BENCH_N", "20"))
    timeout = float(os.getenv("BENCH_TIMEOUT_SECONDS", "15"))
    if n < 0 or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("BENCH_N must be nonnegative and BENCH_TIMEOUT_SECONDS finite and positive")
    transport = os.getenv("SEAM_TRANSPORT", "raw_zenoh").strip().lower()
    output = Path(os.getenv("BENCH_OUTPUT", "benchmark-results/seam-benchmark.csv"))
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    print(f"[seam_bench] transport={transport} action={action} n={n} timeout={timeout:g}s")
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        for number in range(1, n + 1):
            result = await run_attempt(transport, action, params, timeout)
            row = make_row(number, transport, action, result)
            rows.append(row)
            writer.writerow(row)
            file.flush()
            print(f"  {number}: {row['status']} total_ms={row['total_ms']} execution_ms={row['execution_ms']} seam_ms={row['seam_ms']} {row['error']}")
            if transport == "raw_zenoh" and row["total_ms"] == "":
                print("  Stopping: raw_zenoh received no valid reply. Check body availability, "
                      "matching current OpenPAVE code and connectivity before restarting.")
                break
    print(f"[seam_bench] results saved to {output}")
    summarize(rows)


if __name__ == "__main__":
    asyncio.run(main())
