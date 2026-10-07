"""``bounded`` must behave like ``wait_for`` except that it can never swallow a cancellation.

The cancellation tests align a ``cancel()`` with the very event-loop iteration in which the inner awaitable
finishes — the window in which ``asyncio.wait_for`` (CPython before 3.12) returns the result instead of
raising ``CancelledError``. A lost cancel makes a signal-driven shutdown a no-op.
"""

from __future__ import annotations

import asyncio
import sys
import unittest

from pave_runtime.shutdown import bounded


async def _value(x, delay=0.0):
    if delay:
        await asyncio.sleep(delay)
    return x


class BoundedBasicsTests(unittest.TestCase):
    def test_returns_the_result(self):
        self.assertEqual(asyncio.run(bounded(_value(7), 1.0)), 7)

    def test_times_out_and_cancels_the_inner_awaitable(self):
        cancelled = []

        async def slow():
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        async def go():
            with self.assertRaises(asyncio.TimeoutError):
                await bounded(slow(), 0.05)

        asyncio.run(go())
        self.assertEqual(cancelled, [True])

    def test_reraises_the_inner_exception(self):
        async def boom():
            raise ValueError("inner")

        with self.assertRaises(ValueError):
            asyncio.run(bounded(boom(), 1.0))

    def test_cancelling_the_caller_cancels_the_inner_awaitable(self):
        inner_cancelled = []

        async def inner():
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                inner_cancelled.append(True)
                raise

        async def go():
            t = asyncio.ensure_future(bounded(inner(), 10))
            await asyncio.sleep(0.02)
            t.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await t

        asyncio.run(go())
        self.assertEqual(inner_cancelled, [True])


class BoundedNeverSwallowsCancellationTests(unittest.TestCase):
    async def _trial(self, offset: float) -> str:
        loop = asyncio.get_running_loop()
        seen: dict = {}

        async def worker():
            return await bounded(_value("done", delay=0.02), 5)

        t = asyncio.ensure_future(worker())

        def cancel_now():
            seen["already_done"] = t.done()  # was the task still running when cancel() was sent?
            t.cancel()

        loop.call_later(0.02 + offset, cancel_now)
        try:
            await t
            outcome = "finished"
        except asyncio.CancelledError:
            outcome = "cancelled"
        await asyncio.sleep(0.01)  # let the cancel timer fire BEFORE classifying (it may be scheduled later)
        if "already_done" not in seen:
            return "cancel never fired"
        if outcome == "cancelled":
            return "cancelled"
        return "finished-before-cancel" if seen["already_done"] else "SWALLOWED"

    def test_a_cancel_aligned_with_completion_is_never_swallowed(self):
        async def sweep():
            out = {}
            for off in [x * 0.0001 for x in range(-10, 11)] * 4:
                r = await self._trial(off)
                out[r] = out.get(r, 0) + 1
            return out

        results = asyncio.run(sweep())
        self.assertEqual(results.get("SWALLOWED", 0), 0, results)
        self.assertGreater(results.get("cancelled", 0), 0, "the sweep never exercised the cancel path")

    def test_the_stdlib_wait_for_swallows_on_older_pythons(self):
        """Documents WHY this module exists; skipped where the interpreter has fixed ``wait_for``."""

        async def trial(off):
            loop = asyncio.get_running_loop()
            seen = {}

            async def worker():
                return await asyncio.wait_for(_value("done", delay=0.02), 5)

            t = asyncio.ensure_future(worker())

            def cancel_now():
                seen["done"] = t.done()
                t.cancel()

            loop.call_later(0.02 + off, cancel_now)
            try:
                await t
                outcome = "finished"
            except asyncio.CancelledError:
                outcome = "cancelled"
            await asyncio.sleep(0.01)
            return outcome == "finished" and seen.get("done") is False

        async def sweep():
            return sum([await trial(x * 0.0001) for x in range(-10, 11)] * 3)

        if sys.version_info >= (3, 12):
            self.skipTest("wait_for no longer swallows a cancel on CPython 3.12+; bounded() is belt and braces")
        self.assertGreater(asyncio.run(sweep()), 0)


if __name__ == "__main__":
    unittest.main()
