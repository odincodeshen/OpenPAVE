"""Local-only tests for the v1.8 real-body seam dispatch path and its motion safety gate.

A fake ``SeamTransport`` is injected by patching ``create_seam_transport``, so these tests never
start zenoh, Device Connect, or a real robot — they exercise the gate/lease logic in ``run_once``.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import unittest
from unittest import mock

from pave_runtime.inference import Observation
from scripts.run_inference import parse_args, run_once, summarize_outcome


class FakeSeamTransport:
    """Records every send; returns a configurable body state per action."""

    def __init__(self, state_by_action: dict | None = None):
        self.sent: list[tuple[str, dict]] = []
        self._state_by_action = state_by_action or {}

    async def send(self, action, params):
        self.sent.append((action, dict(params)))
        return self._state_by_action.get(
            action,
            {
                "request_id": "fake",
                "action": action,
                "status": "completed",
                "detail": {"path": "fake", "latency_ms": 0.0},
            },
        )


class _Factory:
    """Stand-in for ``create_seam_transport``; records the transport names it is asked for."""

    def __init__(self, fake: FakeSeamTransport):
        self.fake = fake
        self.names: list = []

    def __call__(self, name=None, **opts):
        self.names.append(name)
        return self.fake


BASE = {
    "runtime_name": "mock",
    "application_name": "gesture_commander",
    "observation": Observation("application/x-test", b""),
    "prompt": "t",
    "prompt_id": "t",
}


def _run(fake: FakeSeamTransport, **overrides):
    args = {**BASE, "mock_output": "TROT", "seam_transport": "raw_zenoh"}
    args.update(overrides)
    factory = _Factory(fake)
    with mock.patch("pave_runtime.seam.create_seam_transport", factory):
        with contextlib.redirect_stdout(io.StringIO()):
            payload = asyncio.run(run_once(**args))
    return payload, factory


def _actions(fake: FakeSeamTransport) -> list[str]:
    return [action for action, _ in fake.sent]


class SeamDispatchTests(unittest.TestCase):
    def test_safe_verb_is_sent_over_seam(self):
        fake = FakeSeamTransport()
        payload, factory = _run(fake, mock_output="STOP")
        self.assertEqual(factory.names, ["raw_zenoh"])
        self.assertEqual(_actions(fake), ["stop"])
        self.assertEqual(payload["dispatch"]["status"], "sent_over_seam")
        self.assertEqual(payload["dispatch"]["state"]["status"], "completed")
        self.assertNotIn("motion_lease", payload["dispatch"])
        self.assertEqual(payload["outcome"], {"ok": True, "exit_code": 0, "kind": "completed"})

    def test_motion_blocked_without_opt_in(self):
        fake = FakeSeamTransport()
        payload, factory = _run(fake, mock_output="TROT")  # gesture_commander -> trot
        self.assertEqual(payload["dispatch"]["status"], "blocked")
        self.assertEqual(payload["dispatch"]["gate"], "motion")
        self.assertEqual(payload["dispatch"]["action"], "trot")
        # a blocked motion must not touch the transport at all: no connection, no send
        self.assertEqual(factory.names, [])
        self.assertEqual(fake.sent, [])
        self.assertEqual(payload["outcome"]["exit_code"], 4)

    def test_motion_with_opt_in_leases_and_auto_stops(self):
        fake = FakeSeamTransport()
        payload, _ = _run(fake, mock_output="TROT", allow_motion=True, motion_hold_seconds=0.0)
        self.assertEqual(payload["dispatch"]["status"], "sent_over_seam")
        # the motion is sent, then an automatic STOP closes the lease
        self.assertEqual(_actions(fake), ["trot", "stop"])
        lease = payload["dispatch"]["motion_lease"]
        self.assertEqual(lease["hold_seconds"], 0.0)
        self.assertEqual(lease["auto_stop"]["action"], "stop")

    def test_auto_stop_fires_even_if_hold_raises(self):
        fake = FakeSeamTransport()
        factory = _Factory(fake)
        with mock.patch("pave_runtime.seam.create_seam_transport", factory), mock.patch(
            "scripts.run_inference.asyncio.sleep", side_effect=RuntimeError("boom")
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    asyncio.run(
                        run_once(
                            **{
                                **BASE,
                                "mock_output": "TROT",
                                "seam_transport": "raw_zenoh",
                                "allow_motion": True,
                                "motion_hold_seconds": 1.0,
                            }
                        )
                    )
        # the finally must still have issued STOP after the failed hold (F2 guarantee)
        self.assertEqual(_actions(fake), ["trot", "stop"])

    def test_body_failure_state_is_forwarded(self):
        fake = FakeSeamTransport(
            state_by_action={
                "stop": {
                    "request_id": "x",
                    "action": "stop",
                    "status": "failed",
                    "detail": {"path": "fake"},
                    "error": "bridge down",
                }
            }
        )
        payload, _ = _run(fake, mock_output="STOP")
        self.assertEqual(payload["dispatch"]["status"], "sent_over_seam")
        self.assertEqual(payload["dispatch"]["state"]["status"], "failed")
        # a failed STOP is safety-critical: not ok, exit 5
        self.assertEqual(payload["outcome"], {"ok": False, "exit_code": 5, "kind": "stop_unconfirmed"})

    def test_dry_run_never_creates_a_transport(self):
        fake = FakeSeamTransport()
        payload, factory = _run(fake, seam_transport=None)
        self.assertEqual(payload["dispatch"]["status"], "dry_run")
        self.assertEqual(factory.names, [])
        self.assertEqual(fake.sent, [])


class OutcomeMappingTests(unittest.TestCase):
    """F3: dispatch result -> explicit outcome + exit code."""

    def test_mapping(self):
        cases = [
            ({"status": "dry_run", "action": "trot"}, (True, 0, "dry_run")),
            ({"status": "blocked", "action": "trot"}, (False, 4, "blocked")),
            ({"status": "sent_over_seam", "action": "trot", "state": {"status": "completed"}},
             (True, 0, "completed")),
            ({"status": "sent_over_seam", "action": "trot", "state": {"status": "failed"}},
             (False, 3, "failed")),
            # a failed STOP/eSTOP is safety-critical
            ({"status": "sent_over_seam", "action": "stop", "state": {"status": "failed"}},
             (False, 5, "stop_unconfirmed")),
            # a failed automatic lease STOP is safety-critical even though the motion "completed"
            ({"status": "sent_over_seam", "action": "trot", "state": {"status": "completed"},
              "motion_lease": {"auto_stop": {"status": "failed"}}}, (False, 5, "stop_unconfirmed")),
            ({"status": "sent_over_seam", "action": "trot", "state": {"status": "completed"},
              "motion_lease": {"auto_stop": {"status": "completed"}}}, (True, 0, "completed")),
            ({"status": "completed", "action": "trot"}, (True, 0, "completed")),      # in-process mock
            ({"status": "rejected", "action": "move"}, (False, 3, "failed")),         # in-process reject
            ({"status": "failed", "action": "stop"}, (False, 5, "stop_unconfirmed")),
        ]
        for dispatch, (ok, code, kind) in cases:
            with self.subTest(dispatch=dispatch):
                out = summarize_outcome(dispatch)
                self.assertEqual((out["ok"], out["exit_code"], out["kind"]), (ok, code, kind))


class ArgparseTests(unittest.TestCase):
    def test_dispatch_and_seam_are_mutually_exclusive(self):
        argv = ["run_inference.py", "--dispatch", "--seam", "raw_zenoh"]
        with mock.patch("sys.argv", argv):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parse_args()


if __name__ == "__main__":
    unittest.main()
