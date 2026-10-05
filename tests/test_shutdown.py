"""Signals must STOP the body: SIGINT, SIGTERM and SIGHUP all run the driver's cleanup.

Python only runs ``finally`` for SIGINT; SIGTERM (kill / a supervisor) and SIGHUP (an SSH drop) used to
kill the driver outright, leaving a trotting body unstopped. These tests send REAL signals to a child
process, so they exercise the actual signal -> cancellation -> STOP chain, with no robot, camera, or
model: the child drives the real ``run_live`` loop against a fake seam that prints what it is sent.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The child: the real run_live loop, forced to TROT, against a seam that prints every send.
RUN_LIVE_CHILD = textwrap.dedent(
    """
    import asyncio, sys
    from pave_runtime.application import create_application_runtime
    from pave_runtime.inference import InferenceResult, Observation
    from pave_runtime.shutdown import ShutdownRequested, run_with_graceful_shutdown
    from scripts.run_live import MotionGate, run_live

    class Source:
        async def capture(self):
            return Observation("application/x-test", b"")

    class Runtime:
        async def infer(self, request):
            return InferenceResult(backend="fake", text="TROT", latency_ms=0.0)

    class Seam:
        async def send(self, action, params=None, *, target=None, timeout=5.0):
            print("SEND", action, flush=True)
            return {"status": "completed", "action": action}

    try:
        run_with_graceful_shutdown(run_live(
            source=Source(), runtime=Runtime(),
            application=create_application_runtime("gesture_commander"),
            seam=Seam(), prompt="p", gate=MotionGate(confirmations=1),
            period_s=0.05, watchdog_s=1.0, emit=lambda r: None))
    except ShutdownRequested as exc:
        sys.exit(exc.exit_code)
    """
)

# The children below run the REAL CLI entrypoints (main()), swapping only the seam/camera for fakes —
# this is where the original gap lived (main() used a bare asyncio.run with no signal handling).
FAKES = textwrap.dedent(
    """
    import sys
    from pave_runtime.inference import Observation

    class Source:
        async def capture(self):
            return Observation("application/x-test", b"")

    class Seam:
        async def send(self, action, params=None, *, target=None, timeout=5.0):
            print("SEND", action, flush=True)
            return {"status": "completed", "action": action}
    """
)

RUN_LIVE_MAIN_CHILD = FAKES + textwrap.dedent(
    """
    import scripts.run_live as rl
    rl.create_observation_source = lambda *a, **k: Source()
    rl.create_seam_transport = lambda name=None, **k: Seam()
    sys.argv = ["run_live.py", "--input-url", "http://fake/", "--runtime", "mock",
                "--confirmations", "1", "--period-seconds", "0.05"]
    sys.exit(rl.main())
    """
)

RUN_INFERENCE_MAIN_CHILD = FAKES + textwrap.dedent(
    """
    import pave_runtime.seam as seam_mod
    seam_mod.create_seam_transport = lambda name=None, **k: Seam()
    import scripts.run_inference as ri
    sys.argv = ["run_inference.py", "--runtime", "mock", "--mock-output", "TROT", "--seam", "fake",
                "--allow-motion", "--motion-hold-seconds", "30"]
    sys.exit(ri.main())
    """
)

# The body process: the REAL seam_cli.cli() entrypoint serving a mock adapter over a fake transport.
SEAM_CLI_BODY_CHILD = textwrap.dedent(
    """
    import asyncio, sys
    import scripts.seam_cli as sc

    class FakeServe:
        async def serve(self, adapter):
            print("serving", flush=True)
            await asyncio.sleep(30)

    sc.create_seam_transport = lambda *a, **k: FakeServe()
    sys.argv = ["seam_cli.py", "serve"]
    sys.exit(sc.cli())
    """
)

SEAM_CLI_STOP_FAILS_CHILD = SEAM_CLI_BODY_CHILD.replace(
    "sys.argv = [",
    "from pave_runtime.shutdown import StopUnconfirmed\n"
    "def boom(adapter):\n"
    "    raise StopUnconfirmed({'status': 'failed'})\n"
    "sc.safe_stop = boom\n"
    "sys.argv = [",
)

SEAM_CLI_USAGE_CHILD = textwrap.dedent(
    """
    import sys
    import scripts.seam_cli as sc
    sc.create_seam_transport = lambda *a, **k: object()
    sys.argv = ["seam_cli.py", "send"]
    sys.exit(sc.cli())
    """
)

# The child: a driver whose STOP takes time, to prove a second signal cannot interrupt it.
SLOW_STOP_CHILD = textwrap.dedent(
    """
    import asyncio, sys
    from pave_runtime.shutdown import ShutdownRequested, run_with_graceful_shutdown

    async def work():
        try:
            print("running", flush=True)
            await asyncio.sleep(30)
        finally:
            await asyncio.sleep(0.6)          # a STOP that takes a moment
            print("STOP_DONE", flush=True)

    try:
        run_with_graceful_shutdown(work())
    except ShutdownRequested as exc:
        sys.exit(exc.exit_code)
    """
)


def _spawn(code: str, env_extra: dict | None = None) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUNBUFFERED": "1", **(env_extra or {})}
    return subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for(proc: subprocess.Popen, needle: str, timeout: float = 10.0) -> list[str]:
    """Read stdout lines until one contains ``needle``; returns every line read so far."""
    lines: list[str] = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        lines.append(line.strip())
        if needle in line:
            return lines
    raise AssertionError(f"never saw {needle!r}; got {lines!r}; stderr={proc.stderr.read()!r}")


@unittest.skipUnless(hasattr(signal, "SIGHUP"), "POSIX signals required")
class SignalStopTests(unittest.TestCase):
    def _signal_run_live(self, sig: signal.Signals) -> tuple[list[str], int]:
        proc = _spawn(RUN_LIVE_CHILD)
        try:
            _wait_for(proc, "SEND trot")  # the body is now moving
            proc.send_signal(sig)
            out, _ = proc.communicate(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
        return [ln.strip() for ln in out.splitlines()], proc.returncode

    def test_sigint_stops_the_body(self):
        lines, code = self._signal_run_live(signal.SIGINT)
        self.assertEqual(lines[-1], "SEND stop")
        self.assertEqual(code, 128 + signal.SIGINT)

    def test_sigterm_stops_the_body(self):
        lines, code = self._signal_run_live(signal.SIGTERM)
        self.assertEqual(lines[-1], "SEND stop")  # this is the regression: SIGTERM used to skip it
        self.assertEqual(code, 128 + signal.SIGTERM)

    def test_sighup_stops_the_body(self):
        lines, code = self._signal_run_live(signal.SIGHUP)
        self.assertEqual(lines[-1], "SEND stop")  # an SSH drop sends SIGHUP
        self.assertEqual(code, 128 + signal.SIGHUP)

    def _signal_main(self, child: str, sig: signal.Signals, env_extra=None) -> tuple[list[str], int]:
        env = {"MOCK_INFERENCE_OUTPUT": "TROT", **(env_extra or {})}
        proc = _spawn(child, env)
        try:
            seen = _wait_for(proc, "SEND trot")  # the body is now moving
            proc.send_signal(sig)
            out, _ = proc.communicate(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
        lines = seen + [ln.strip() for ln in out.splitlines()]  # `seen` was already read off stdout
        return [ln for ln in lines if ln.startswith("SEND")], proc.returncode

    def test_run_live_cli_stops_the_body_on_sigterm_and_sighup(self):
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            with self.subTest(signal=sig.name):
                sends, code = self._signal_main(RUN_LIVE_MAIN_CHILD, sig)
                self.assertEqual(sends[-1], "SEND stop")  # the body is told to STOP
                self.assertEqual(code, 128 + sig)

    def test_run_inference_cli_stops_the_body_on_sigterm_and_sighup(self):
        # a signal arriving during the --allow-motion hold must still end the lease with a STOP
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            with self.subTest(signal=sig.name):
                sends, code = self._signal_main(RUN_INFERENCE_MAIN_CHILD, sig)
                self.assertEqual(sends, ["SEND trot", "SEND stop"])
                self.assertEqual(code, 128 + sig)

    def test_body_process_makes_its_actuator_safe_when_it_is_shut_down(self):
        # the body process itself being kill-ed / hung up must leave the actuator stopped
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            with self.subTest(signal=sig.name):
                proc = _spawn(SEAM_CLI_BODY_CHILD, {"ROBOT_ADAPTER": "mock"})
                try:
                    _wait_for(proc, "serving")
                    proc.send_signal(sig)
                    out, _ = proc.communicate(timeout=10)
                finally:
                    if proc.poll() is None:
                        proc.kill()
                self.assertIn("MOCK ACTION=STOP", out)  # the adapter was told to stop
                self.assertIn("adapter mock stopped", out)
                self.assertEqual(proc.returncode, 128 + sig)

    def test_body_shutdown_with_an_unconfirmed_stop_exits_safety_critical(self):
        proc = _spawn(SEAM_CLI_STOP_FAILS_CHILD, {"ROBOT_ADAPTER": "mock"})
        try:
            _wait_for(proc, "serving")
            proc.send_signal(signal.SIGTERM)
            _, err = proc.communicate(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
        self.assertEqual(proc.returncode, 5)
        self.assertIn("safety-critical", err)

    def test_seam_cli_usage_error_still_exits_one(self):
        # sys.exit inside the coroutine must survive the graceful-shutdown runner
        proc = _spawn(SEAM_CLI_USAGE_CHILD)
        _, err = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("usage", err)

    def test_a_second_signal_cannot_interrupt_the_stop(self):
        proc = _spawn(SLOW_STOP_CHILD)
        try:
            _wait_for(proc, "running")
            proc.send_signal(signal.SIGTERM)
            time.sleep(0.15)
            proc.send_signal(signal.SIGINT)  # an impatient second Ctrl+C mid-STOP
            out, _ = proc.communicate(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
        self.assertIn("STOP_DONE", out)
        self.assertEqual(proc.returncode, 128 + signal.SIGTERM)  # the FIRST signal is reported


if __name__ == "__main__":
    unittest.main()
