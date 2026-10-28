"""H2 + watcher supervision: the stop path must never wait forever behind a hung call.

Local-only: threads, fake adapters and a socketpair; no hardware, no network.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
import unittest
from unittest import mock

from control_daemon import adapters as adapters_module
from control_daemon.adapters import AdapterActionResult, default_capture_runner, default_runner
from control_daemon.bridge_client import BridgeClient
from pave_runtime import lease as lease_module
from pave_runtime.lease import BodyLease, check_watcher, guarded_dispatch


class HangableAdapter:
    """``trot`` blocks until released (a hung docker/ROS call); everything else returns at once."""

    name = "hangable"
    capabilities = frozenset({"stop", "estop", "trot"})

    def __init__(self) -> None:
        self.release = threading.Event()
        self.in_trot = threading.Event()
        self.calls: list[str] = []

    def execute(self, action, params):
        self.calls.append(action)
        if action == "trot":
            self.in_trot.set()
            self.release.wait(10)
        return AdapterActionResult(success=True, steps=[])


class StopNotBlockedByHungMotionTests(unittest.TestCase):
    def setUp(self):
        self.adapter = HangableAdapter()
        self.lease = BodyLease(ttl_s=5.0)
        self.motion = threading.Thread(
            target=guarded_dispatch, args=(self.adapter, self.lease, "trot", {}), daemon=True)
        self.motion.start()
        self.assertTrue(self.adapter.in_trot.wait(2), "trot never started")

    def tearDown(self):
        self.adapter.release.set()
        self.motion.join(2)

    def test_estop_does_not_queue_behind_a_hung_motion(self):
        t0 = time.monotonic()
        state = guarded_dispatch(self.adapter, self.lease, "estop", {})
        self.assertLess(time.monotonic() - t0, 0.5)
        self.assertEqual(state["status"], "completed")
        self.assertIn("estop", self.adapter.calls)

    def test_stop_waits_only_briefly_then_goes_ahead(self):
        with mock.patch.object(lease_module, "STOP_LOCK_WAIT_S", 0.2):
            t0 = time.monotonic()
            state = guarded_dispatch(self.adapter, self.lease, "stop", {})
        self.assertLess(time.monotonic() - t0, 1.5)
        self.assertEqual(state["status"], "completed")
        self.assertIn("stop", self.adapter.calls)

    def test_expiry_stop_runs_even_while_a_motion_call_is_hung(self):
        self.lease.arm("trot", {})
        self.lease._deadline = 0.0  # already expired
        with mock.patch.object(lease_module, "STOP_LOCK_WAIT_S", 0.2):
            event = self.lease.expire_if_due(self.adapter)
        self.assertIsNotNone(event)
        self.assertIn("stop", self.adapter.calls)

    def test_a_stop_does_not_release_a_lock_it_never_took(self):
        with mock.patch.object(lease_module, "STOP_LOCK_WAIT_S", 0.1):
            guarded_dispatch(self.adapter, self.lease, "stop", {})
        self.adapter.release.set()
        self.motion.join(2)
        # the motion thread released its own lock; the lock must now be free for a normal verb
        self.assertTrue(self.lease.exec_lock.acquire(blocking=False))
        self.lease.exec_lock.release()


class CommandTimeoutTests(unittest.TestCase):
    def test_runner_returns_timeout_rc_instead_of_hanging(self):
        with mock.patch.dict("os.environ", {"OPENPAVE_CMD_TIMEOUT_S": "0.3"}):
            t0 = time.monotonic()
            rc = default_runner("sleep 5")
        self.assertEqual(rc, adapters_module.TIMEOUT_RC)
        self.assertLess(time.monotonic() - t0, 3)

    def test_capture_runner_returns_timeout_rc_instead_of_hanging(self):
        with mock.patch.dict("os.environ", {"OPENPAVE_CMD_TIMEOUT_S": "0.3"}):
            rc, out = default_capture_runner("sleep 5", "")
        self.assertEqual((rc, out), (adapters_module.TIMEOUT_RC, ""))

    def test_bad_timeout_setting_falls_back_to_a_finite_default(self):
        for raw in ("inf", "nan", "-1", "0", "abc"):
            with self.subTest(raw=raw), mock.patch.dict("os.environ", {"OPENPAVE_CMD_TIMEOUT_S": raw}):
                self.assertEqual(adapters_module._cmd_timeout_s(), 60.0)

    def test_normal_command_still_works(self):
        self.assertEqual(default_runner("true"), 0)
        self.assertEqual(default_capture_runner("cat", "hi"), (0, "hi"))


class BridgeOverallDeadlineTests(unittest.TestCase):
    def test_chatter_with_other_ids_cannot_extend_the_wait(self):
        server, client_sock = socket.socketpair()
        client = BridgeClient(("tcp", "unused", 0))
        client._sock = client_sock
        stop = threading.Event()

        def chatter():
            while not stop.is_set():
                try:
                    server.sendall(b'{"id":"other","type":"result"}\n')
                except OSError:
                    return
                time.sleep(0.05)

        t = threading.Thread(target=chatter, daemon=True)
        t.start()
        try:
            t0 = time.monotonic()
            with self.assertRaises(ConnectionError):
                client._await("wanted", "result", timeout=0.5)
            self.assertLess(time.monotonic() - t0, 2.0)
        finally:
            stop.set()
            server.close()
            t.join(1)


class WatcherSupervisionTests(unittest.TestCase):
    def test_check_watcher_passes_while_running_and_raises_when_dead(self):
        async def scenario():
            ok = asyncio.ensure_future(asyncio.sleep(10))
            check_watcher(ok)  # alive: no error

            async def dies():
                raise ValueError("watcher bug")

            dead = asyncio.ensure_future(dies())
            await asyncio.sleep(0.05)
            with self.assertRaises(RuntimeError):
                check_watcher(dead)
            finished = asyncio.ensure_future(asyncio.sleep(0))
            await asyncio.sleep(0.05)
            with self.assertRaises(RuntimeError):
                check_watcher(finished)
            ok.cancel()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
