"""Graceful shutdown for drivers that command a real body.

A driver that holds motion owes the body a STOP however it ends. Python only runs ``finally`` blocks
for SIGINT (``KeyboardInterrupt``); SIGTERM (``kill``, a supervisor, ``docker stop``) and SIGHUP (an
SSH session dropping) terminate the process immediately, so a body left trotting would never be told to
stop. ``run_with_graceful_shutdown`` turns all three into a task cancellation, so the driver's own
``finally`` (its STOP) runs, then reports the signal as ``ShutdownRequested`` with the conventional
``128 + signum`` exit code.

While that STOP is in flight further signals are ignored, so an impatient second ``Ctrl+C`` cannot
interrupt the very STOP that makes the body safe.
"""

from __future__ import annotations

import asyncio
import signal
from typing import Any, Coroutine

STOP_UNCONFIRMED_EXIT = 5  # same code as run_inference's safety-critical "stop did not complete"

HANDLED_SIGNALS = tuple(
    sig
    for sig in (
        getattr(signal, "SIGINT", None),
        getattr(signal, "SIGTERM", None),
        getattr(signal, "SIGHUP", None),
    )
    if sig is not None
)


class ShutdownRequested(Exception):
    """The run was ended by a signal (after its cleanup, including any STOP, had run)."""

    def __init__(self, signal_name: str) -> None:
        super().__init__(f"shutdown requested by {signal_name}")
        self.signal_name = signal_name

    @property
    def exit_code(self) -> int:
        return 128 + int(signal.Signals[self.signal_name])


class StopUnconfirmed(Exception):
    """A STOP the driver owed the body (shutdown, or the end of a motion lease) did not complete.

    Safety-critical: the body may still be moving. Callers should surface it loudly and exit
    ``STOP_UNCONFIRMED_EXIT``.
    """

    def __init__(self, state: Any) -> None:
        super().__init__(f"STOP not confirmed: {state!r}")
        self.state = state


async def bounded(aw: Any, timeout: float) -> Any:
    """``asyncio.wait_for`` that can never swallow a cancellation.

    Before CPython 3.12, ``wait_for`` returns the inner result instead of raising ``CancelledError`` when
    the outer task is cancelled in the same event-loop iteration in which the inner awaitable finishes
    (measured on 3.9: about 40% of aligned cancels were lost; not reproducible on 3.12). For a driver whose
    shutdown *is* a cancellation, a lost cancel means the signal is ignored and the loop keeps running —
    and because the shutdown path ignores further signals, nothing short of ``SIGKILL`` would stop it.
    ``asyncio.wait`` has no such window, so this is built on it.

    Raises ``asyncio.TimeoutError`` after ``timeout`` seconds (cancelling the inner awaitable), and
    re-raises whatever the inner awaitable raised.
    """
    task = asyncio.ensure_future(aw)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout)
    except asyncio.CancelledError:
        task.cancel()  # the outer task was cancelled: do not leave the inner one running
        raise
    if not done:
        task.cancel()
        await asyncio.wait({task})  # let the cancellation land before reporting the timeout
        raise asyncio.TimeoutError()
    return task.result()


async def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(coro)
    received: list[str] = []

    def on_signal(sig: "signal.Signals") -> None:
        if received:  # already shutting down: let the STOP in flight finish
            return
        received.append(sig.name)
        task.cancel()

    installed = []
    for sig in HANDLED_SIGNALS:
        try:
            loop.add_signal_handler(sig, on_signal, sig)
            installed.append(sig)
        except (NotImplementedError, RuntimeError, ValueError):
            continue  # non-main thread / unsupported platform: fall back to default behaviour
    try:
        return await task
    except asyncio.CancelledError:
        if received:
            raise ShutdownRequested(received[0]) from None
        raise
    finally:
        for sig in installed:
            loop.remove_signal_handler(sig)


def run_with_graceful_shutdown(coro: Coroutine[Any, Any, Any]) -> Any:
    """``asyncio.run`` that turns SIGINT/SIGTERM/SIGHUP into a clean, cleanup-running shutdown."""
    return asyncio.run(_run(coro))
