"""The device_connect body must expose ``renew`` as an RPC next to the adapter's capabilities.

``device_connect_edge`` is not installed in the local test environment, so a minimal stand-in is
injected just far enough to run ``DeviceConnectSeam.serve`` and capture the driver it builds. This
checks the wiring (which RPCs exist, that they route through the lease) — not Device Connect itself.
"""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest import mock

from tests.test_lease import RecordingAdapter


def _fake_device_connect(captured: dict) -> dict:
    edge = types.ModuleType("device_connect_edge")
    drivers = types.ModuleType("device_connect_edge.drivers")
    dtypes = types.ModuleType("device_connect_edge.types")

    class DeviceDriver:
        def __init__(self):
            pass

        def _invalidate_caches(self):
            pass

    def rpc(name=None, labels=None):
        def deco(fn):
            fn._rpc_name, fn._rpc_labels = name or fn.__name__, labels
            return fn
        return deco

    class DeviceRuntime:
        def __init__(self, driver, device_id):
            captured["driver"] = driver

        async def run(self):
            return None

    drivers.DeviceDriver, drivers.rpc = DeviceDriver, rpc
    edge.DeviceRuntime = DeviceRuntime
    dtypes.DeviceIdentity = dtypes.DeviceStatus = lambda **kw: kw
    return {"device_connect_edge": edge, "device_connect_edge.drivers": drivers,
            "device_connect_edge.types": dtypes}


class DeviceConnectRenewWiringTests(unittest.TestCase):
    def _serve(self):
        from pave_runtime.seam_backends.dc_seam import DeviceConnectSeam

        captured: dict = {}
        adapter = RecordingAdapter()
        with mock.patch.dict(sys.modules, _fake_device_connect(captured)):
            asyncio.run(DeviceConnectSeam().serve(adapter))
        return captured["driver"], adapter

    def test_renew_is_an_rpc_even_though_it_is_not_an_adapter_capability(self):
        driver, adapter = self._serve()
        self.assertNotIn("renew", adapter.capabilities)
        self.assertTrue(callable(driver.renew))
        self.assertEqual(driver.renew._rpc_name, "renew")

    def test_the_renew_rpc_goes_through_the_lease_and_never_runs_the_adapter(self):
        driver, adapter = self._serve()
        started = asyncio.run(driver.trot({}))
        lease_id = started["detail"]["lease_id"]
        renewed = asyncio.run(driver.renew({"lease_id": lease_id}))
        self.assertEqual(renewed["status"], "completed")
        asyncio.run(driver.stop({}))
        lost = asyncio.run(driver.renew({"lease_id": lease_id}))
        self.assertEqual(lost["status"], "lease_lost")
        self.assertEqual(adapter.actions(), ["trot", "stop"])  # no renewal ever reached the adapter

    def test_every_capability_is_still_an_rpc(self):
        driver, adapter = self._serve()
        for cap in adapter.capabilities:
            self.assertTrue(callable(getattr(driver, cap)), cap)


if __name__ == "__main__":
    unittest.main()
