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
from pave_runtime.lease import LEASED_ACTIONS as MOTION_ACTIONS  # noqa: E402
from pave_runtime.observation import ObservationSourceError, create_observation_source  # noqa: E402
from pave_runtime.seam import create_seam_transport  # noqa: E402
from pave_runtime.shutdown import (  # noqa: E402
    STOP_UNCONFIRMED_EXIT,
    ShutdownRequested,
    StopUnconfirmed,
    bounded,
    run_with_graceful_shutdown,
)
from scripts.run_inference import DEFAULT_PROMPT_PRESET, load_prompt  # noqa: E402

IMMEDIATE_ACTIONS = frozenset({"stop", "estop", "home"})


# A body's definitive "no" — retrying cannot change it, so it is not a failed *delivery*.
REFUSED_STATUSES = frozenset({"rejected", "unsupported"})
STOP_ACTIONS = frozenset({"stop", "estop"})


class MotionGate:
    """Edge-triggered dispatch with multi-observation confirmation for motion verbs.

    ``admit(action, now_ms)`` returns the action to dispatch this tick, or ``None``. It records the action
    as sent *before* the send happens, so the caller must report the outcome:

    - ``delivered(action)``  — the body accepted it;
    - ``undelivered(action)`` — it did not (clearly) reach the body (no reply, transport error, a failed
      execution): the gate forgets it so the next tick tries again. Immediate verbs (stop / home) retry
      without limit; a motion verb retries up to ``max_retries`` times per episode, then is abandoned;
    - a definitive refusal (``rejected`` / ``unsupported``) is reported as ``delivered`` — retrying is futile.

    Without this, one lost packet left the gate convinced the body was already doing it, and an
    edge-triggered loop never sent it again until the decision changed.
    """

    def __init__(self, confirmations: int = 2, window_ms: float = 1500.0, max_retries: int = 3):
        self.confirmations = max(1, int(confirmations))
        self.window_ms = float(window_ms)
        self.max_retries = max(0, int(max_retries))
        self.current: str | None = None  # what the body was last told to do
        self.pending: str | None = None  # a motion verb being confirmed
        self.count = 0
        self._first_ms = 0.0
        # a motion send failed without a clear answer (it may have been delivered and only the reply lost):
        # the body may be moving even though `current` says otherwise, so a STOP is still owed
        self.uncertain = False
        self.retries = 0
        self._retry_action: str | None = None
        self._before: str | None = None  # `current` before the dispatch admit() last returned

    def admit(self, action: str, now_ms: float) -> str | None:
        prev = self.current
        if action in MOTION_ACTIONS:
            if self.pending == action and (now_ms - self._first_ms) <= self.window_ms:
                self.count += 1
            else:
                self.pending = action
                self.count = 1
                self._first_ms = now_ms
            if self.count >= self.confirmations and action != self.current:
                self._before, self.current = prev, action
                return action
            return None
        # immediate / non-motion verb: clear any motion confirmation, dispatch only on change — or, for a
        # STOP, whenever an earlier motion send left the body's state uncertain
        self.pending = None
        self.count = 0
        if action != self.current or (action in STOP_ACTIONS and self.uncertain):
            self._before, self.current = prev, action
            return action
        return None

    def delivered(self, action: str) -> None:
        """The dispatch admit() returned reached the body and was accepted (or definitively refused)."""
        self.retries = 0
        self._retry_action = None
        self.uncertain = False  # the body's state is known again

    def undelivered(self, action: str) -> bool:
        """The dispatch did not (clearly) reach the body; forget it so the next tick tries again.

        Returns ``False`` when retrying is abandoned (a motion verb out of retries); ``current`` then stays
        advanced, but ``uncertain`` keeps a STOP owed at shutdown.
        """
        if action in MOTION_ACTIONS:
            self.uncertain = True  # it may have been delivered and only the reply lost
            if self._retry_action != action:
                self.retries, self._retry_action = 0, action
            if self.retries >= self.max_retries:
                self.retries, self._retry_action = 0, None
                return False
            self.retries += 1
        self.current = self._before
        return True

    def force_stop(self) -> bool:
        """Watchdog / shutdown: record that the body is stopped. Returns True if it was (or may be) moving."""
        was_moving = self.current in MOTION_ACTIONS or self.uncertain
        self.current = "stop"
        self.pending = None
        self.count = 0
        self.uncertain = False
        return was_moving

    def stop_failed(self) -> None:
        """The STOP that force_stop() called for was not confirmed: the body may still be moving."""
        self.uncertain = True


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
    lease_renew_s: float = 2.0,
    emit: Callable[[dict], None] = lambda record: None,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    start = clock()
    ticks = 0
    # The BODY keeps a dead-man lease on every motion (BODY_MOTION_TTL_S, default 5 s) and STOPs itself
    # if the brain stops renewing — covering a crash, `kill -9` or a network drop that no cleanup here
    # could. A renewer task re-sends the active motion on its own cadence, so the lease measures the
    # brain's LIVENESS, not how long one inference happens to take.
    send_lock = asyncio.Lock()       # one seam send at a time: a renewal must never land after a STOP
    active: dict[str, Any] = {}      # the leased motion the body is running, if any
    stop_renewer = asyncio.Event()
    renewer: "asyncio.Future | None" = None
    renewal_send: dict[str, "asyncio.Future"] = {}  # the renewal send in flight, if any

    def preempt_renewal() -> None:
        """A STOP (or any new action) supersedes a renewal still waiting on the network.

        The renewal send holds ``send_lock`` until it returns, and a send to a dead link can take its full
        timeout. Without this, a STOP decided meanwhile would wait that long to leave the brain.
        """
        pending = renewal_send.get("task")
        if pending is not None and not pending.done():
            pending.cancel()

    async def renew_loop() -> None:
        while True:
            try:
                await bounded(stop_renewer.wait(), lease_renew_s)
                return  # told to stop
            except asyncio.TimeoutError:
                pass
            async with send_lock:
                if not active or gate.current not in MOTION_ACTIONS:
                    continue  # the loop already decided to stop (or never started a motion)
                send_task = asyncio.ensure_future(
                    seam.send(active["action"], active["params"], target=target)
                )
                renewal_send["task"] = send_task
                try:
                    await asyncio.wait({send_task})  # cancelling the renewer cancels this wait
                except asyncio.CancelledError:
                    send_task.cancel()
                    raise
                finally:
                    renewal_send.pop("task", None)
                if send_task.cancelled():
                    continue  # preempted: the STOP / new action that took its place is already on its way
                if send_task.exception() is not None:  # the body will STOP itself when the lease runs out
                    emit({"event": "renew_error", "error": str(send_task.exception())})
                    continue
                renew_state = send_task.result()
                if (renew_state or {}).get("status") != "completed":
                    emit({"event": "renew_failed", "state": renew_state})

    try:
        while True:
            if max_ticks is not None and ticks >= max_ticks:
                break
            if max_seconds is not None and (clock() - start) >= max_seconds:
                break
            tick_start = clock()
            now_ms = tick_start * 1000.0
            try:
                observation = await bounded(source.capture(), watchdog_s)
                result = await bounded(
                    runtime.infer(InferenceRequest(observation=observation, prompt=prompt)),
                    watchdog_s,
                )
            except (asyncio.TimeoutError, ObservationSourceError, InferenceRuntimeError) as exc:
                # observe/infer stalled or failed — if a motion is active, fail-safe STOP
                stopped = gate.force_stop()
                active.clear()
                stop_state = None
                if stopped:
                    preempt_renewal()
                    async with send_lock:
                        try:
                            stop_state = await seam.send("stop", {}, target=target)
                        except Exception as send_exc:  # a transport error is an undelivered STOP, not a crash
                            stop_state = {"status": "error", "error": str(send_exc), "action": "stop"}
                    if (stop_state or {}).get("status") != "completed":
                        gate.stop_failed()  # still owed: retried on the next failing tick and at shutdown
                emit({"tick": ticks, "event": "watchdog", "error": str(exc),
                      "dispatched": "stop" if stopped else None, "state": stop_state})
            else:
                proposal = application.decide(result)
                normalized = normalize_action_payload(
                    {"action": proposal.action, "params": proposal.params},
                    default_source=application.name,
                )
                action = normalized["action"]
                to_dispatch = gate.admit(action, now_ms)
                state = None
                delivery = None
                if to_dispatch is not None:
                    preempt_renewal()
                    async with send_lock:
                        try:
                            state = await seam.send(to_dispatch, normalized["params"], target=target)
                        except Exception as send_exc:  # a transport error is a failed delivery, not a crash
                            state = {"status": "error", "error": str(send_exc), "action": to_dispatch}
                        active.clear()
                        status = (state or {}).get("status")
                        if status == "completed":
                            gate.delivered(to_dispatch)
                            delivery = "delivered"
                            # renew only a motion the body actually accepted
                            if to_dispatch in MOTION_ACTIONS:
                                active.update(action=to_dispatch, params=normalized["params"])
                        elif status in REFUSED_STATUSES:
                            gate.delivered(to_dispatch)  # a definitive no: retrying cannot help
                            delivery = "refused"
                        else:
                            # not delivered (or not clearly): forget it so the next tick sends it again
                            delivery = "retry" if gate.undelivered(to_dispatch) else "abandoned"
                    if active and renewer is None:
                        renewer = asyncio.ensure_future(renew_loop())
                emit({
                    "tick": ticks,
                    "decided": action,
                    "confirm": gate.count,
                    "dispatched": to_dispatch,
                    "delivery": delivery,
                    "target": target,
                    "state": state,
                })
            # pace every tick, including a failing one, so a persistent error can't hot-loop
            ticks += 1
            elapsed = clock() - tick_start
            if period_s and elapsed < period_s:
                await asyncio.sleep(period_s - elapsed)
    finally:
        # stop renewing first, so no renewal can land after the final STOP
        stop_renewer.set()
        if renewer is not None:
            renewer.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await renewer
        active.clear()
        # always leave the body stopped — and say so loudly if that STOP could not be confirmed
        if gate.force_stop():
            try:
                stop_state = await seam.send("stop", {}, target=target)
                stop_ok = (stop_state or {}).get("status") == "completed"
            except Exception as exc:  # a failed send must not hide that the body may still move
                stop_state = {"status": "error", "error": str(exc)}
                stop_ok = False
            emit({"event": "shutdown_stop", "dispatched": "stop", "state": stop_state})
            if not stop_ok:
                raise StopUnconfirmed(stop_state)


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
    parser.add_argument("--lease-renew-seconds", type=float, default=2.0,
                        help="re-send the active motion this often to renew the body's dead-man lease; must be "
                        "comfortably below the body's BODY_MOTION_TTL_S (default 5 s)")
    parser.add_argument("--dispatch-retries", type=int, default=3,
                        help="how many times to re-send a motion that did not reach the body (no reply, "
                        "transport error, failed execution) before giving up on it; a STOP is retried without limit")
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
        max_retries=args.dispatch_retries,
    )

    def emit(record: dict[str, Any]) -> None:
        print(json.dumps(record, ensure_ascii=False), flush=True)

    try:
        # SIGINT, SIGTERM and SIGHUP (e.g. an SSH drop) all cancel the loop so its finally STOPs the body
        run_with_graceful_shutdown(
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
                lease_renew_s=args.lease_renew_seconds,
                emit=emit,
            )
        )
    except ShutdownRequested as exc:
        emit({"event": "interrupted", "signal": exc.signal_name})
        return exc.exit_code
    except StopUnconfirmed as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return STOP_UNCONFIRMED_EXIT
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
