#!/usr/bin/env python3
"""Run one headless OpenPAVE inference/application cycle."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pave_runtime.application import create_application_runtime  # noqa: E402
from pave_runtime.capability_schema import normalize_action_payload  # noqa: E402
from pave_runtime.inference import (  # noqa: E402
    InferenceRequest,
    InferenceRuntimeError,
    Observation,
    create_inference_runtime,
)
from pave_runtime.observation import (  # noqa: E402
    ObservationSourceError,
    create_observation_source,
)
from pave_runtime.seam import dispatch as dispatch_to_adapter  # noqa: E402


DEFAULT_PROMPT_PRESET = ROOT / "prompts" / "robot-commander-gesture.json"
MOCK_ADAPTER_NAMES = frozenset({"mock", "dry-run", "dry_run"})
# Locomotion verbs that start/continue unattended motion on a real body. Over a single-shot
# --seam dispatch these are blocked unless the operator opts in with --allow-motion; stop/home/
# estop are always allowed. See F1/F2 in the v1.8 live-body review.
MOTION_ACTIONS = frozenset({"trot", "move"})


def load_prompt(path: Path) -> tuple[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not str(payload.get("prompt", "")).strip():
        raise ValueError(f"prompt preset has no non-empty prompt: {path}")
    return str(payload.get("id", path.stem)), str(payload["prompt"])


async def load_observation(path: Path | None, url: str | None = None) -> Observation:
    if path is not None:
        return await create_observation_source("file", path=path).capture()
    observation_url = url or os.getenv("OBSERVATION_URL")
    if observation_url:
        source = create_observation_source(
            "http_mjpeg",
            url=observation_url,
            timeout_sec=float(os.getenv("OBSERVATION_TIMEOUT_SECONDS", "10")),
            max_frame_bytes=int(os.getenv("OBSERVATION_MAX_FRAME_BYTES", str(10 * 1024 * 1024))),
        )
        return await source.capture()
    return Observation(
        media_type="application/x-openpave-mock",
        data=b"",
        source="mock://empty-observation",
    )


# F3: map a dispatch result to an explicit outcome + process exit code, so a body-side failure (or an
# unconfirmed STOP) never exits 0. Exit codes: 0 ok · 3 dispatch failed · 4 blocked by the safety gate ·
# 5 safety-critical — a STOP/eSTOP (including the automatic lease STOP) did not complete.
def summarize_outcome(dispatch: dict[str, Any]) -> dict[str, Any]:
    status = dispatch.get("status")
    action = dispatch.get("action")
    if status == "dry_run":
        return {"ok": True, "exit_code": 0, "kind": "dry_run"}
    if status == "blocked":
        return {"ok": False, "exit_code": 4, "kind": "blocked"}
    if status == "sent_over_seam":
        lease = dispatch.get("motion_lease") or {}
        if "auto_stop" in lease and (lease.get("auto_stop") or {}).get("status") != "completed":
            return {"ok": False, "exit_code": 5, "kind": "stop_unconfirmed"}
        if (dispatch.get("state") or {}).get("status") == "completed":
            return {"ok": True, "exit_code": 0, "kind": "completed"}
        if action in ("stop", "estop"):
            return {"ok": False, "exit_code": 5, "kind": "stop_unconfirmed"}
        return {"ok": False, "exit_code": 3, "kind": "failed"}
    if status == "completed":
        return {"ok": True, "exit_code": 0, "kind": "completed"}
    # in-process rejected / unsupported / failed, or anything unexpected
    if action in ("stop", "estop"):
        return {"ok": False, "exit_code": 5, "kind": "stop_unconfirmed"}
    return {"ok": False, "exit_code": 3, "kind": "failed"}


async def run_once(
    *,
    runtime_name: str,
    application_name: str,
    observation: Observation,
    prompt: str,
    prompt_id: str,
    mock_output: str | None = None,
    should_dispatch: bool = False,
    adapter_name: str = "mock",
    seam_transport: str | None = None,
    allow_motion: bool = False,
    motion_hold_seconds: float = 3.0,
) -> dict[str, Any]:
    runtime_opts = {"output": mock_output} if runtime_name == "mock" and mock_output is not None else {}
    runtime = create_inference_runtime(runtime_name, **runtime_opts)
    application = create_application_runtime(application_name)

    started = time.perf_counter()
    result = await runtime.infer(InferenceRequest(observation=observation, prompt=prompt))
    decision_started = time.perf_counter()
    proposal = application.decide(result)
    application_latency_ms = round((time.perf_counter() - decision_started) * 1000.0, 3)
    normalized = normalize_action_payload(
        {"action": proposal.action, "params": proposal.params},
        default_source=application.name,
    )

    if seam_transport:
        # v1.8: dispatch the validated action to a REAL body over the seam. create_seam_transport
        # picks the backend and reads its env (e.g. ZENOH_CONNECT), exactly like seam_cli.py send —
        # the body-side adapter (e.g. puppypi_bridge) lives on the robot, not in this process.
        action = normalized["action"]
        params = normalized["params"]
        if action in MOTION_ACTIONS and not allow_motion:
            # F1/F2 safety gate: a single-shot CLI must not start unattended locomotion on a real
            # body (the headless path has no TROT confirmation, and the process exits without a
            # follow-up STOP). Block motion verbs — no connection, no send — unless the operator
            # opts in with --allow-motion. stop/home/estop always pass.
            dispatch_result = {
                "status": "blocked",
                "gate": "motion",
                "transport": seam_transport,
                "action": action,
                "params": params,
                "reason": (
                    f"motion verb {action!r} requires --allow-motion; single-shot seam dispatch "
                    "blocks locomotion by default (stop/home/estop always pass)"
                ),
            }
        else:
            from pave_runtime.seam import create_seam_transport

            seam = create_seam_transport(seam_transport)
            state = await seam.send(action, params)
            dispatch_result = {
                "status": "sent_over_seam",
                "transport": seam_transport,
                "action": action,
                "params": params,
                "state": state,
            }
            if action in MOTION_ACTIONS:
                # F2 motion lease: hold the motion for a bounded window, then ALWAYS auto-STOP —
                # including on Ctrl+C or an error during the hold — so the body is never left
                # marking time after this single-shot command exits.
                hold = max(0.0, motion_hold_seconds)
                auto_stop_state = None
                try:
                    await asyncio.sleep(hold)
                finally:
                    auto_stop_state = await seam.send("stop", {})
                dispatch_result["motion_lease"] = {
                    "hold_seconds": hold,
                    "auto_stop": auto_stop_state,
                }
    elif should_dispatch:
        if adapter_name.strip().lower() not in MOCK_ADAPTER_NAMES:
            raise ValueError(
                "in-process --dispatch permits only the mock adapter; "
                "use --seam <transport> to reach a real body"
            )
        from control_daemon.adapters import create_robot_adapter

        adapter = create_robot_adapter(adapter_name)
        adapter_output = io.StringIO()
        with contextlib.redirect_stdout(adapter_output):
            dispatch_result = dispatch_to_adapter(
                adapter, normalized["action"], normalized["params"]
            )
        log_text = adapter_output.getvalue().strip()
        if log_text:
            dispatch_result["adapter_log"] = log_text
    else:
        dispatch_result = {
            "status": "dry_run",
            "action": normalized["action"],
            "params": normalized["params"],
        }

    return {
        "schema_version": "inference-run-0.2",
        "observation": {
            "media_type": observation.media_type,
            "source": observation.source,
            "bytes": len(observation.data),
            "timestamp": observation.timestamp,
        },
        "prompt": {"id": prompt_id},
        "inference": asdict(result),
        "proposal": asdict(proposal),
        "capability": normalized,
        "dispatch": dispatch_result,
        "outcome": summarize_outcome(dispatch_result),
        "latency": {
            "inference_ms": result.latency_ms,
            "application_ms": application_latency_ms,
            "total_ms": round((time.perf_counter() - started) * 1000.0, 3),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", default=None, help="Inference runtime (default: env or mock)")
    parser.add_argument("--application", default=None, help="Application runtime")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--input", type=Path, help="Local JPEG/PNG observation file")
    inputs.add_argument(
        "--input-url",
        help="HTTP snapshot or MJPEG stream; captures one frame (for example PuppyPi :8080)",
    )
    parser.add_argument("--prompt-preset", type=Path, default=None)
    parser.add_argument("--mock-output", help="Deterministic output for the mock backend")
    # F6: in-process --dispatch and over-the-seam --seam are mutually exclusive dispatch modes.
    dispatch = parser.add_mutually_exclusive_group()
    dispatch.add_argument("--dispatch", action="store_true", help="Execute the proposal in-process (mock only)")
    dispatch.add_argument(
        "--seam",
        default=None,
        metavar="TRANSPORT",
        help="v1.8: send the action to a real body over this seam transport (e.g. raw_zenoh); "
        "needs the brain-side transport env, e.g. ZENOH_CONNECT=tcp/<body>:7447",
    )
    parser.add_argument("--adapter", default="mock", help="In-process dispatch adapter (mock only)")
    parser.add_argument(
        "--allow-motion",
        action="store_true",
        help="allow locomotion verbs (trot/move) over --seam; the CLI then holds the motion for a "
        "bounded window and issues an automatic STOP (see --motion-hold-seconds)",
    )
    parser.add_argument(
        "--motion-hold-seconds",
        type=float,
        default=3.0,
        help="with --allow-motion, seconds to hold a motion action before the automatic STOP (default 3.0)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        prompt_path = args.prompt_preset or Path(
            os.getenv("PROMPT_PRESET", str(DEFAULT_PROMPT_PRESET))
        )
        prompt_id, prompt = load_prompt(prompt_path)
        async def execute() -> dict[str, Any]:
            observation = await load_observation(args.input, args.input_url)
            return await run_once(
                runtime_name=args.runtime or os.getenv("INFERENCE_RUNTIME", "mock"),
                application_name=args.application
                or os.getenv("APPLICATION_RUNTIME", "gesture_commander"),
                observation=observation,
                prompt=prompt,
                prompt_id=prompt_id,
                mock_output=args.mock_output,
                should_dispatch=args.dispatch,
                adapter_name=args.adapter,
                seam_transport=args.seam,
                allow_motion=args.allow_motion,
                motion_hold_seconds=args.motion_hold_seconds,
            )

        payload = asyncio.run(execute())
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        InferenceRuntimeError,
        ObservationSourceError,
    ) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    # F3: exit code reflects the body outcome (0 ok · 3 failed · 4 blocked · 5 stop unconfirmed).
    return int(payload.get("outcome", {}).get("exit_code", 0))


if __name__ == "__main__":
    raise SystemExit(main())
