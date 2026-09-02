#!/usr/bin/env python3
"""OpenPAVE capability body as a Device Connect device — todo ②(b), **option B** (labeled RPCs).

Each OpenPAVE capability is exposed as its **own labeled `@rpc`**, generated dynamically from
`adapter.capabilities`, so the device-connect selector grammar addresses them natively:
`function(estop)` (fleet e-stop), `function(safety:critical)`, `device(category:robot).function(...)`,
and `broadcast(..., fire_at=)` for synchronized multi-robot actuation.

The dispatch is the **same** capability contract as ②a (raw zenoh) — only the transport differs.
This is the device-connect integration *path* (see `openpave_deviceconnect.md`); OpenPAVE's core is
untouched. With `ROBOT_ADAPTER=mock_arm` the whole device is pure Python, no ROS.

Params travel as a `dict` (the adapter validates its own `_required`); the RPC *name* is the
capability. Fine-grained per-capability signatures are a later optimization.

Run (D2D, zero infra):
  DEVICE_CONNECT_ALLOW_INSECURE=true ROBOT_ADAPTER=mock_arm python3 openpave_device.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from pathlib import Path
from typing import Any

from device_connect_edge import DeviceRuntime
from device_connect_edge.drivers import DeviceDriver, rpc
from device_connect_edge.types import DeviceIdentity, DeviceStatus

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pave_runtime.seam import dispatch  # single-source body endpoint (graduated from this experiment)
from control_daemon.adapters import create_robot_adapter


# --- capability semantics -> device-connect labels --------------------------------------------
_SAFETY_CRITICAL = frozenset({"estop", "stop"})
_SENSING = frozenset({"get_image"})          # read; everything else is actuation (write)

# adapter name -> device `category` label
_CATEGORY = {
    "puppypi": "robot", "puppypi_local": "robot", "puppypi_bridge": "robot", "mock": "robot",
    "mock_arm": "actuator",
    "camera_mock": "sensor", "camera_usb": "sensor",
}


def _function_labels(action: str) -> dict[str, str]:
    """Map a capability's semantics to device-connect well-known function labels, so selectors like
    `function(estop)` / `function(safety:critical)` / `function(direction:write)` just work."""
    return {
        "safety": "critical" if action in _SAFETY_CRITICAL else "informational",
        "direction": "read" if action in _SENSING else "write",
    }


def _make_capability_rpc(action: str):
    """Factory: an async method for one capability, wrapped as a labeled `@rpc`. The RPC name is the
    capability so device-connect selectors address it natively; params travel as a dict."""
    async def method(self, params: dict | None = None) -> dict[str, Any]:
        return dispatch(self.adapter, action, params)

    method.__name__ = action
    method.__doc__ = f"Run the '{action}' capability.\n\nArgs:\n    params: capability params dict."
    return rpc(name=action, labels=_function_labels(action))(method)


class OpenPaveBodyDriver(DeviceDriver):
    """OpenPAVE capability body over Device Connect (option B): every capability is a labeled `@rpc`,
    generated dynamically from `adapter.capabilities`. Same dispatch as the ②a neutral seam."""

    def __init__(self) -> None:
        super().__init__()
        self.adapter = create_robot_adapter(os.getenv("ROBOT_ADAPTER", "mock_arm"))
        self.device_type = os.getenv("DEVICE_TYPE", "openpave-body")
        self._category = _CATEGORY.get(self.adapter.name, "actuator")
        self.labels = {"category": self._category}
        # dynamically expose each capability as its own labeled RPC (bound instance method).
        # collection scans dir(self) for _is_device_function (base.py), so instance methods count.
        for action in sorted(self.adapter.capabilities):
            self.__dict__[action] = types.MethodType(_make_capability_rpc(action), self)
        self._invalidate_caches()

    @property
    def identity(self) -> DeviceIdentity:
        return DeviceIdentity(device_type=self.device_type, manufacturer="OpenPAVE",
                              model=self.adapter.name)

    @property
    def status(self) -> DeviceStatus:
        return DeviceStatus(availability="available")

    @rpc()
    async def list_capabilities(self) -> dict[str, Any]:
        """List the capabilities (each is also exposed as its own labeled RPC)."""
        return {"adapter": self.adapter.name, "category": self._category,
                "capabilities": sorted(self.adapter.capabilities)}


async def main() -> None:
    driver = OpenPaveBodyDriver()
    device_id = os.getenv("DEVICE_ID", f"openpave-{driver.adapter.name}-d2d")
    print(f"openpave device up · adapter={driver.adapter.name} · category={driver._category} · "
          f"device_id={device_id} · RPCs={sorted(driver.adapter.capabilities)} (+list_capabilities)")
    await DeviceRuntime(driver=driver, device_id=device_id).run()


if __name__ == "__main__":
    asyncio.run(main())
