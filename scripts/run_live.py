#!/usr/bin/env python3
"""Persistent OpenPAVE live-body loop: observe -> infer -> decide -> confirm -> dispatch.

Unlike ``run_inference.py`` (one shot), this owns the motion lifecycle over many observations, so it
is where locomotion is *confirmed* rather than opt-in:

- a motion verb (``trot``/``move``) is dispatched only after it is decided on N consecutive
  observations within a time window (``TROT_CONFIRMATIONS`` / ``TROT_CONFIRMATION_WINDOW_MS``);
- ``stop``/``home``/``estop`` dispatch immediately (fail-safe);
- dispatch is edge-triggered (only on a change), so the seam is not spammed every tick;
- a per-tick watchdog auto-STOPs if observe+infer stalls while a motion is active;
- the body is ALWAYS stopped on shutdown (Ctrl+C, error, or a bounded run finishing).

The seam send is per-call (a persistent session is a later optimization); observations are re-captured
each tick from an HTTP/MJPEG source.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time
from typing import Any, Awaitable, Callable

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pave_runtime.application import create_application_runtime  # noqa: E402
from pave_runtime.capability_schema import normalize_action_payload  # noqa: E402
from pave_runtime.inference import (  # noqa: E402
    InferenceRequest,
    InferenceRuntimeError,
    create_inference_runtime,
)
from pave_runtime.observation import ObservationSourceError, create_observation_source  # noqa: E402
from pave_runtime.seam import create_seam_transport  # noqa: E402
from scripts.run_inference import DEFAULT_PROMPT_PRESET, load_prompt  # noqa: E402

MOTION_ACTIONS = frozenset({"trot", "move"})
IMMEDIATE_ACTIONS = frozenset({"stop", "estop", "home"})


class MotionGate:
    """Edge-triggered dispatch with multi-observation confirmation for motion verbs.

    ``admit(action, now_ms)`` returns the action to dispatch this tick, or ``None``.
    """

    def __init__(self, confirmations: int = 2, window_ms: float = 1500.0):
        self.confirmations = max(1, int(confirmations))
        self.window_ms = float(window_ms)
        self.current: str | None = None  # what the body was last told to do
        self.pending: str | None = None  # a motion verb being confirmed
        self.count = 0
        self._first_ms = 0.0

    def admit(self, action: str, now_ms: float) -> str | None:
        if action in MOTION_ACTIONS:
            if self.pending == action and (now_ms - self._first_ms) <= self.window_ms:
                self.count += 1
            else:
                self.pending = action
                self.count = 1
                self._first_ms = now_ms
            if self.count >= self.confirmations and action != self.current:
                self.current = action
                return action
            return None
        # immediate / non-motion verb: clear any motion confirmation, dispatch only on change
        self.pending = None
        self.count = 0
        if action != self.current:
            self.current = action
            return action
        return None

    def force_stop(self) -> bool:
        """Watchdog / shutdown: record that the body is stopped. Returns True if it was moving."""
        was_moving = self.current in MOTION_ACTIONS
        self.current = "stop"
        self.pending = None
        self.count = 0
        return was_moving


async def run_live(
    *,
    source,
    runtime,
    application,
    seam,
    prompt: str,
    gate: MotionGate,
    target: str | None = None,
    period_s: float = 0.0,
    watchdog_s: float = 4.0,
    max_ticks: int | None = None,
    max_seconds: float | None = None,
    emit: Callable[[dict], None] = lambda record: None,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    start = clock()
    ticks = 0
    try:
        while True:
            if max_ticks is not None and ticks >= max_ticks:
                break
            if max_seconds is not None and (clock() - start) >= max_seconds:
                break
            tick_start = clock()
            now_ms = tick_start * 1000.0
            try:
                observation = await asyncio.wait_for(source.capture(), timeout=watchdog_s)
                result = await asyncio.wait_for(
                    runtime.infer(InferenceRequest(observation=observation, prompt=prompt)),
                    timeout=watchdog_s,
                )
            except (asyncio.TimeoutError, ObservationSourceError, InferenceRuntimeError) as exc:
                # observe/infer stalled or failed — if a motion is active, fail-safe STOP
                stopped = gate.force_stop()
                if stopped:
                    await seam.send("stop", {}, target=target)
                emit({"tick": ticks, "event": "watchdog", "error": str(exc),
                      "dispatched": "stop" if stopped else None})
                ticks += 1
                continue

            proposal = application.decide(result)
            normalized = normalize_action_payload(
                {"action": proposal.action, "params": proposal.params},
                default_source=application.name,
            )
            action = normalized["action"]
            to_dispatch = gate.admit(action, now_ms)
            state = None
            if to_dispatch is not None:
                state = await seam.send(to_dispatch, normalized["params"], target=target)
            emit({
                "tick": ticks,
                "decided": action,
                "confirm": gate.count,
                "dispatched": to_dispatch,
                "target": target,
                "state": state,
            })
            ticks += 1
            elapsed = clock() - tick_start
            if period_s and elapsed < period_s:
                await asyncio.sleep(period_s - elapsed)
    finally:
        # always leave the body stopped
        if gate.force_stop():
            with contextlib.suppress(Exception):
                await seam.send("stop", {}, target=target)
            emit({"event": "shutdown_stop", "dispatched": "stop"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-url", help="HTTP snapshot / MJPEG stream (default: env OBSERVATION_URL)")
    parser.add_argument("--transport", default=None, help="Seam transport (default: env SEAM_TRANSPORT)")
    parser.add_argument("--action-target", default=None, metavar="ID",
                        help="body to drive (default: env ACTION_TARGET); required for device_connect with >1 body")
    parser.add_argument("--runtime", default=None, help="Inference runtime (default: env or vllm_openai)")
    parser.add_argument("--application", default=None, help="Application runtime")
    parser.add_argument("--prompt-preset", type=__import__("pathlib").Path, default=None)
    parser.add_argument("--period-seconds", type=float, default=0.0, help="min seconds between ticks")
    parser.add_argument("--confirmations", type=int, default=None,
                        help="consecutive observations to confirm a motion verb (default: env TROT_CONFIRMATIONS or 2)")
    parser.add_argument("--confirmation-window-ms", type=float, default=None,
                        help="window for those confirmations (default: env TROT_CONFIRMATION_WINDOW_MS or 1500)")
    parser.add_argument("--motion-watchdog-ms", type=float, default=4000.0,
                        help="auto-STOP if observe+infer stalls longer than this while moving")
    parser.add_argument("--max-ticks", type=int, default=None)
    parser.add_argument("--max-seconds", type=float, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    url = args.input_url or os.getenv("OBSERVATION_URL")
    if not url:
        print(json.dumps({"status": "error", "error": "live loop needs --input-url or OBSERVATION_URL"}),
              file=sys.stderr)
        return 2
    prompt_path = args.prompt_preset or __import__("pathlib").Path(
        os.getenv("PROMPT_PRESET", str(DEFAULT_PROMPT_PRESET))
    )
    _, prompt = load_prompt(prompt_path)

    source = create_observation_source(
        "http_mjpeg",
        url=url,
        timeout_sec=float(os.getenv("OBSERVATION_TIMEOUT_SECONDS", "10")),
        max_frame_bytes=int(os.getenv("OBSERVATION_MAX_FRAME_BYTES", str(10 * 1024 * 1024))),
    )
    runtime = create_inference_runtime(args.runtime or os.getenv("INFERENCE_RUNTIME", "vllm_openai"))
    application = create_application_runtime(
        args.application or os.getenv("APPLICATION_RUNTIME", "gesture_commander")
    )
    seam = create_seam_transport(args.transport or os.getenv("SEAM_TRANSPORT"))
    gate = MotionGate(
        confirmations=args.confirmations
        if args.confirmations is not None
        else int(os.getenv("TROT_CONFIRMATIONS", "2")),
        window_ms=args.confirmation_window_ms
        if args.confirmation_window_ms is not None
        else float(os.getenv("TROT_CONFIRMATION_WINDOW_MS", "1500")),
    )

    def emit(record: dict[str, Any]) -> None:
        print(json.dumps(record, ensure_ascii=False), flush=True)

    try:
        asyncio.run(
            run_live(
                source=source,
                runtime=runtime,
                application=application,
                seam=seam,
                prompt=prompt,
                gate=gate,
                target=args.action_target or os.getenv("ACTION_TARGET"),
                period_s=args.period_seconds,
                watchdog_s=args.motion_watchdog_ms / 1000.0,
                max_ticks=args.max_ticks,
                max_seconds=args.max_seconds,
                emit=emit,
            )
        )
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
