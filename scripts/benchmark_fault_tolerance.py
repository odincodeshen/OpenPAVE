#!/usr/bin/env python3
"""Dry-run brain failure benchmark; see docs/fault-tolerance-benchmark.md."""
from __future__ import annotations

import argparse
import asyncio
import csv
import math
import multiprocessing
import os
import signal
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pave_runtime.lease import LeaseClient
from pave_runtime.seam import create_seam_transport
from pave_runtime.shutdown import ShutdownRequested, bounded, run_with_graceful_shutdown

TIMESTAMPS = ["last_renewal_monotonic_s", "deadline_monotonic_s",
              "expiry_detected_monotonic_s", "stop_issued_monotonic_s", "stop_finished_monotonic_s"]
LATENCIES = ["renewal_to_expiry_ms", "expiry_to_stop_issued_ms",
             "expiry_to_stop_completed_ms", "response_ms", "brain_termination_to_stop_ms"]
FIELDS = ["run", "transport", "brain_platform", "body_platform", "body_id", "lease_id",
          "lease_duration_s", *TIMESTAMPS, *LATENCIES, "trot_accepted", "renewal_accepted",
          "brain_terminated", "expiry_observed", "stop_completed", "status", "error"]


class TrialError(Exception):
    def __init__(self, message, status="failed"):
        super().__init__(message)
        self.status = status


def accepted(state, action):
    if not isinstance(state, dict) or state.get("status") != "completed":
        status = state.get("status") if isinstance(state, dict) else None
        raise TrialError(f"{action}: {state}", "timeout" if status in {"no_reply", "timeout"} else "failed")
    return state


async def send(seam, action, params, body_id, timeout):
    try:
        return accepted(await bounded(
            seam.send(action, params, target=body_id, timeout=timeout), timeout), action)
    except asyncio.TimeoutError as exc:
        raise TrialError(f"{action}: exceeded {timeout:g}s", "timeout") from exc


async def brain_loop(pipe, body_id, timeout, ttl, factory):
    """This process alone starts/renews motion. Deliberately has no shutdown STOP."""
    seam = factory("raw_zenoh")
    state = await send(seam, "trot", {}, body_id, timeout)
    pipe.send({"stage": "trot", "state": state})
    client = LeaseClient()
    if client.begin("trot", {}, state) != "lease_id":
        raise TrialError("TROT returned no lease_id; legacy renewals are unsuitable")
    while True:
        await asyncio.sleep(ttl / 3)
        action, params = client.request()
        renewed = await send(seam, action, params, body_id, timeout)
        if (client.interpret(renewed) != LeaseClient.RENEWED
                or renewed.get("detail", {}).get("lease_id") != client.lease_id
                or renewed.get("detail", {}).get("renewed") is not True):
            raise TrialError(f"Lease renewal not confirmed: {renewed}")
        pipe.send({"stage": "renewed", "state": renewed})


def brain_worker(pipe, body_id, timeout, ttl, factory):
    try:
        asyncio.run(brain_loop(pipe, body_id, timeout, ttl, factory))
    except Exception as exc:
        pipe.send({"stage": "error", "error": str(exc), "status": getattr(exc, "status", "failed")})
    finally:
        pipe.close()


def kill_process(process):
    """Only ever receives the Process created for this trial; reap it even on errors."""
    if process.is_alive():
        process.kill()  # SIGKILL: simulate failure without brain-side cleanup
    process.join(timeout=2)
    if process.is_alive():
        raise TrialError("Test brain could not be reaped; stopping benchmark")


async def receive(pipe, process, timeout):
    deadline = time.monotonic() + timeout
    while True:
        if pipe.poll():
            try:
                message = pipe.recv()
            except EOFError as exc:
                raise TrialError("Test brain closed its pipe unexpectedly") from exc
            if message.get("stage") == "error":
                raise TrialError(message["error"], message["status"])
            return message
        if not process.is_alive():
            raise TrialError(f"Test brain exited unexpectedly ({process.exitcode})")
        if time.monotonic() >= deadline:
            raise TrialError("Timed out waiting for test brain", "timeout")
        await asyncio.sleep(0.01)


def verify_body(state):
    detail = accepted(state, "lease_status").get("detail", {})
    ttl = detail.get("lease_ttl_s")
    if (detail.get("version") != 1 or detail.get("adapter") != "gpio_servo"
            or detail.get("dry_run") is not True or detail.get("servo_dryrun_env") is not True
            or not {"trot", "stop"}.issubset(detail.get("capabilities", []))
            or not isinstance(detail.get("body_id"), str) or not detail["body_id"]
            or not valid_number(ttl) or ttl <= 0):
        raise TrialError("Body must report gpio_servo, SERVO_DRYRUN=1, active dry-run mode, "
                         "TROT/STOP, and version 1 lease diagnostics; no TROT sent")
    if detail.get("lease_id") is not None:
        raise TrialError("Body already has an active motion lease; use an idle, dedicated test body")
    return detail


def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def record_event(row, event):
    row["expiry_observed"] = True
    row["stop_completed"] = event.get("stop", {}).get("status") == "completed"
    values = [event.get(key) for key in TIMESTAMPS]
    if not all(valid_number(v) for v in values) or values != sorted(values):
        raise TrialError("Missing or invalid body-clock timestamps; latency unavailable")
    last, deadline, expired, issued, finished = values
    if not math.isclose(deadline - last, row["lease_duration_s"], abs_tol=1e-6):
        raise TrialError("Observed lease duration changed; latency unavailable")
    row.update(zip(TIMESTAMPS, values))
    for key, value in zip(LATENCIES, [(expired - last) * 1000, (issued - expired) * 1000,
                                     (finished - expired) * 1000, (finished - last) * 1000]):
        row[key] = value
    if not row["stop_completed"]:
        raise TrialError(f"Expiry STOP did not complete: {event.get('stop')}")


async def observe_expiry(seam, body, row, timeout, expiry_timeout):
    deadline = time.monotonic() + expiry_timeout
    while time.monotonic() < deadline:
        state = await send(seam, "lease_status", {}, body["body_id"],
                           min(timeout, max(0.001, deadline - time.monotonic())))
        detail = state.get("detail", {})
        if detail.get("body_id") != body["body_id"]:
            raise TrialError("Body instance changed; stopping benchmark")
        for event in detail.get("expiry_events", []):
            if event.get("lease_id") == row["lease_id"] and event.get("body_id") == body["body_id"]:
                record_event(row, event)
                if detail.get("lease_id") is not None:
                    raise TrialError("Another lease is active after expiry; stopping benchmark")
                return
        if detail.get("lease_id") != row["lease_id"]:
            raise TrialError("Test lease disappeared without its expiry event; stopping benchmark")
        await asyncio.sleep(0.05)
    raise TrialError("No matching lease expiry event before deadline", "timeout")


async def run_trial(seam, body, row, timeout, expiry_timeout, factory=create_seam_transport):
    ctx = multiprocessing.get_context("spawn")
    reader, writer = ctx.Pipe(duplex=False)
    process = ctx.Process(target=brain_worker,
                          args=(writer, body["body_id"], timeout, body["lease_ttl_s"], factory),
                          daemon=True)
    started = False
    try:
        # Successful trials end with no active lease; STOP also confirms the initial baseline.
        await send(seam, "stop", {}, body["body_id"], timeout)
        process.start()
        started = True
        writer.close()
        message = await receive(reader, process, timeout)
        if message.get("stage") != "trot":
            raise TrialError("Expected TROT acknowledgement")
        row["trot_accepted"] = True
        row["lease_id"] = message["state"].get("detail", {}).get("lease_id", "")
        if not row["lease_id"]:
            raise TrialError("TROT did not establish a lease")
        message = await receive(reader, process, timeout + body["lease_ttl_s"] / 3)
        if message.get("stage") != "renewed":
            raise TrialError("Expected accepted lease renewal")
        row["renewal_accepted"] = True
        if not process.is_alive():
            raise TrialError("Test brain exited before deliberate termination")
        kill_process(process)
        if process.exitcode != -signal.SIGKILL:
            raise TrialError(f"Test brain exited unexpectedly during termination ({process.exitcode})")
        row["brain_terminated"] = True
        await observe_expiry(seam, body, row, timeout, expiry_timeout)
        row["status"] = "completed"
    finally:
        try:
            if started:
                kill_process(process)
            process.close()
        finally:
            reader.close()
            writer.close()
            if row["status"] != "completed":
                # Cleanup is not a measured expiry STOP, and cannot turn a failed trial into success.
                try:
                    await send(seam, "stop", {}, body["body_id"], timeout)
                except Exception as exc:
                    row["error"] += f" Cleanup STOP unconfirmed: {exc}."


def make_row(number, args, body=None):
    row = dict.fromkeys(FIELDS, "")
    row.update(run=number, transport=args.transport, brain_platform=args.brain_platform,
               body_platform=args.body_platform, status="failed", trot_accepted=False,
               renewal_accepted=False, brain_terminated=False, expiry_observed=False, stop_completed=False)
    if body:
        row.update(body_id=body["body_id"], lease_duration_s=body["lease_ttl_s"])
    return row


def percentile(values, percent):
    values = sorted(values)
    position = (len(values) - 1) * percent / 100
    lo = int(position)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (position - lo)


def summarize(rows):
    successful = [r for r in rows if r["status"] == "completed"]
    result = {"total": len(rows), "successful": len(successful),
              "failed": sum(r["status"] == "failed" for r in rows),
              "timeouts": sum(r["status"] == "timeout" for r in rows),
              "success_rate": 100 * len(successful) / len(rows) if rows else 0}
    print("Trials: {total}; successful: {successful}; failed: {failed}; timeouts: {timeouts}; "
          "success rate: {success_rate:.1f}%".format(**result))
    for field in LATENCIES[:-1]:
        values = [r[field] for r in successful if valid_number(r[field]) and r[field] >= 0]
        result[field] = ({"mean": statistics.mean(values), "p50": percentile(values, 50),
                          "p95": percentile(values, 95)} if values else None)
        if values:
            print(f"  {field}: mean {statistics.mean(values):.3f}, p50 {percentile(values, 50):.3f}, "
                  f"p95 {percentile(values, 95):.3f} (n={len(values)})")
        else:
            print(f"  {field}: unavailable")
    print("response_ms = last accepted renewal to software STOP completion (body clock).")
    print("Brain termination to STOP is unavailable: host clocks are not synchronized. "
          "Software STOP is not physical motor stopping time.")
    return result


async def main(args):
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows, body = [], None
    with args.output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        for number in range(1, args.runs + 1):
            row = make_row(number, args, body)
            try:
                if body is None:
                    seam = create_seam_transport(args.transport)
                    body = verify_body(await send(seam, "lease_status", {}, None, args.timeout))
                    row.update(body_id=body["body_id"], lease_duration_s=body["lease_ttl_s"])
                    print(f"Verified dry-run gpio_servo body {body['body_id']}; TTL={body['lease_ttl_s']:g}s")
                await run_trial(seam, body, row, args.timeout,
                                args.expiry_timeout or body["lease_ttl_s"] + args.timeout + 2)
            except asyncio.CancelledError:
                row["error"] = "Benchmark interrupted." + row["error"]
                raise
            except Exception as exc:
                row["status"] = getattr(exc, "status", "failed")
                row["error"] = f"{type(exc).__name__}: {exc}." + row["error"]
            finally:
                rows.append(row)
                writer.writerow(row)
                file.flush()
                print(f"Run {number}: {row['status']} response_ms={row['response_ms']} {row['error']}")
            if row["status"] != "completed":
                print("Stopping after unsuccessful trial: delayed motion or uncertain body state "
                      "could invalidate subsequent measurements. Resolve the error before restarting.")
                break
    print(f"CSV: {args.output}")
    summarize(rows)
    return 0 if all(r["status"] == "completed" for r in rows) else 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("benchmark-results/fault-tolerance.csv"))
    parser.add_argument("--transport", choices=["raw_zenoh"], default="raw_zenoh")
    parser.add_argument("--timeout", type=float, default=10, help="per-request/brain startup timeout in seconds")
    parser.add_argument("--expiry-timeout", type=float, help="observation timeout after killing brain (default TTL + timeout + 2)")
    parser.add_argument("--brain-platform", default=os.getenv("BENCH_BRAIN_PLATFORM", "unknown"))
    parser.add_argument("--body-platform", default=os.getenv("BENCH_BODY_PLATFORM", "unknown"))
    args = parser.parse_args(argv)
    if args.runs <= 0 or any(not math.isfinite(x) or x <= 0
                             for x in (args.timeout, args.expiry_timeout) if x is not None):
        parser.error("runs must be positive; timeouts must be finite and positive")
    return args


if __name__ == "__main__":
    try:
        sys.exit(run_with_graceful_shutdown(main(parse_args())))
    except ShutdownRequested as exc:
        sys.exit(exc.exit_code)
    except KeyboardInterrupt:
        sys.exit(130)
