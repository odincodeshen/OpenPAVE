#!/usr/bin/env python3
"""Run OpenPAVE scenario-driven control-path benchmarks."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INTENT_URL = "http://127.0.0.1:7071/intent"
DEFAULT_COMMAND_RESULT_PATH = "/tmp/vla_command_result.json"
DEFAULT_ROBOT_STATE_PATH = "/tmp/vla_robot_state.json"
RESULT_SCHEMA_VERSION = "0.1"
RUNTIME_ENV_KEYS = [
    "ROBOT_ADAPTER",
    "ROBOT_IP_ADDRESS",
    "UI_MODEL",
    "UI_API_BASE",
    "INTENT_INGRESS_URL",
    "INTENT_PATH",
    "COMMAND_RESULT_PATH",
    "ROBOT_STATE_PATH",
    "ROS_DOMAIN_ID",
    "RMW_IMPLEMENTATION",
    "ROS_SVC_IMAGE",
    "ROS_PUB_IMAGE",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def resolve_repo_path(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else ROOT / path


def read_json_file(path: str) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def capture_runtime_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    environ = environ if environ is not None else os.environ
    return {key: environ[key] for key in RUNTIME_ENV_KEYS if key in environ}


def post_intent(url: str, payload: dict[str, Any], timeout_sec: float) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"error": body}
        return exc.code, parsed


def wait_for_command_result(
    *,
    request_id: str,
    command_result_path: str,
    timeout_sec: float,
    poll_sec: float,
) -> tuple[dict[str, Any] | None, float]:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        payload = read_json_file(command_result_path)
        if payload and payload.get("request_id") == request_id:
            status = payload.get("status")
            if status in {"completed", "failed", "rejected"}:
                return payload, time.monotonic()
        time.sleep(poll_sec)
    return None, time.monotonic()


def build_output_path(results_dir: Path, scenario: dict[str, Any], run_id: str) -> Path:
    scenario_id = str(scenario["id"]).replace("/", "_")
    return results_dir / f"{slug_timestamp()}_{scenario_id}_{run_id[:8]}.jsonl"


def benchmark_intents(
    *,
    scenario: dict[str, Any],
    prompt: dict[str, Any],
    intents: list[str],
    intent_url: str,
    command_result_path: str,
    robot_state_path: str,
    timeout_sec: float,
    poll_sec: float,
    run_id: str | None = None,
    runtime_env: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    run_id = run_id or str(uuid.uuid4())
    runtime_env = runtime_env or {}
    records: list[dict[str, Any]] = []

    for expected_intent in intents:
        request_id = str(uuid.uuid4())
        intent_payload = {
            "schema_version": "0.1",
            "request_id": request_id,
            "intent": expected_intent,
            "source": "benchmark",
            "timestamp": now_iso(),
        }
        sent_monotonic = time.monotonic()
        sent_at = now_iso()

        error_text = None
        http_status = None
        http_body: dict[str, Any] = {}
        command_result = None
        completed_monotonic = sent_monotonic

        try:
            http_status, http_body = post_intent(intent_url, intent_payload, timeout_sec=timeout_sec)
            if http_status < 200 or http_status >= 300:
                error_text = f"intent POST failed with HTTP {http_status}"
            else:
                command_result, completed_monotonic = wait_for_command_result(
                    request_id=request_id,
                    command_result_path=command_result_path,
                    timeout_sec=timeout_sec,
                    poll_sec=poll_sec,
                )
                if command_result is None:
                    error_text = "timed out waiting for command result"
        except Exception as exc:  # pragma: no cover - exercised through CLI failures
            error_text = str(exc)
            completed_monotonic = time.monotonic()

        latency_ms = round((completed_monotonic - sent_monotonic) * 1000.0, 3)
        robot_state = read_json_file(robot_state_path)
        observed_intent = command_result.get("intent") if command_result else None
        observed_status = command_result.get("status") if command_result else None
        passed = (
            error_text is None
            and observed_intent == expected_intent
            and observed_status == "completed"
        )

        records.append(
            {
                "schema_version": RESULT_SCHEMA_VERSION,
                "run_id": run_id,
                "request_id": request_id,
                "scenario": {
                    "id": scenario.get("id"),
                    "title": scenario.get("title"),
                    "version": scenario.get("version"),
                    "runtime_profile": scenario.get("runtime_profile"),
                },
                "prompt": {
                    "id": prompt.get("id"),
                    "title": prompt.get("title"),
                    "version": prompt.get("version"),
                    "ref": scenario.get("prompt_ref"),
                },
                "benchmark": {
                    "type": "control_path",
                    "expected_intent": expected_intent,
                    "observed_intent": observed_intent,
                    "observed_status": observed_status,
                    "pass": passed,
                    "latency_ms": latency_ms,
                    "sent_at": sent_at,
                    "completed_at": now_iso(),
                    "error": error_text,
                },
                "runtime": {
                    "intent_url": intent_url,
                    "command_result_path": command_result_path,
                    "robot_state_path": robot_state_path,
                },
                "runtime_env": runtime_env,
                "inference_node": scenario.get("inference_node", {}),
                "robot_sensor_endpoint": scenario.get("robot_sensor_endpoint", {}),
                "adapter": scenario.get("adapter", {}),
                "safety_constraints": scenario.get("safety_constraints", {}),
                "http": {
                    "status": http_status,
                    "response": http_body,
                },
                "command_result": command_result,
                "robot_state": robot_state,
            }
        )

    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [
        record["benchmark"]["latency_ms"]
        for record in records
        if record["benchmark"].get("latency_ms") is not None
    ]
    passed = sum(1 for record in records if record["benchmark"].get("pass"))
    summary: dict[str, Any] = {
        "total": len(records),
        "passed": passed,
        "failed": len(records) - passed,
    }
    if latencies:
        summary.update(
            {
                "avg_latency_ms": round(statistics.mean(latencies), 3),
                "min_latency_ms": round(min(latencies), 3),
                "max_latency_ms": round(max(latencies), 3),
            }
        )
    return summary


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OpenPAVE control-path benchmark")
    parser.add_argument("scenario", help="Path to scenario JSON")
    parser.add_argument(
        "--intent-url",
        default=DEFAULT_INTENT_URL,
        help=f"Intent Ingress URL (default: {DEFAULT_INTENT_URL})",
    )
    parser.add_argument(
        "--command-result-path",
        default=DEFAULT_COMMAND_RESULT_PATH,
        help=f"Command result file path (default: {DEFAULT_COMMAND_RESULT_PATH})",
    )
    parser.add_argument(
        "--robot-state-path",
        default=DEFAULT_ROBOT_STATE_PATH,
        help=f"Robot state file path (default: {DEFAULT_ROBOT_STATE_PATH})",
    )
    parser.add_argument(
        "--results-dir",
        default="benchmark-results",
        help="Directory for JSONL benchmark output (default: benchmark-results)",
    )
    parser.add_argument(
        "--intent",
        action="append",
        help="Override scenario expected_intents. Can be specified multiple times.",
    )
    parser.add_argument("--timeout-sec", type=float, default=10.0)
    parser.add_argument("--poll-sec", type=float, default=0.1)
    parser.add_argument(
        "--allow-physical",
        action="store_true",
        help="Allow scenarios with physical_robot_motion_allowed=true",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    scenario_path = resolve_repo_path(args.scenario)
    scenario = load_json(scenario_path)
    prompt = load_json(resolve_repo_path(str(scenario["prompt_ref"])))

    safety = scenario.get("safety_constraints", {})
    if safety.get("physical_robot_motion_allowed") and not args.allow_physical:
        print(
            "Refusing to run physical-motion scenario without --allow-physical",
            file=sys.stderr,
        )
        return 2

    intents = [intent.upper() for intent in (args.intent or scenario.get("expected_intents", []))]
    if not intents:
        print("No expected intents found. Use --intent for control-path benchmark.", file=sys.stderr)
        return 2

    run_id = str(uuid.uuid4())
    records = benchmark_intents(
        scenario=scenario,
        prompt=prompt,
        intents=intents,
        intent_url=args.intent_url,
        command_result_path=args.command_result_path,
        robot_state_path=args.robot_state_path,
        timeout_sec=args.timeout_sec,
        poll_sec=args.poll_sec,
        run_id=run_id,
        runtime_env=capture_runtime_env(),
    )

    output_path = build_output_path(resolve_repo_path(args.results_dir), scenario, run_id)
    write_jsonl(output_path, records)
    summary = summarize(records)

    print(f"scenario={scenario.get('id')} run_id={run_id}")
    print(f"output={output_path}")
    print(
        "summary="
        f"total={summary['total']} "
        f"passed={summary['passed']} "
        f"failed={summary['failed']} "
        f"avg_latency_ms={summary.get('avg_latency_ms', 'n/a')}"
    )
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
