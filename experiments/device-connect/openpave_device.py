#!/usr/bin/env python3
"""OpenPAVE capability body as a Device Connect device — todo ②(b).

Wraps an OpenPAVE `CapabilityAdapter` as a device-connect `DeviceDriver`: the **same**
capability contract (`{action, params}` -> state) the raw-zenoh neutral seam (②a) validated,
now carried over the **device-connect** transport (zenoh / NATS / MQTT backends). The
body-endpoint dispatch is byte-for-byte the same as ②a — only the transport differs. That is
the whole point of ②(b): swap the transport, keep the contract.

With `ROBOT_ADAPTER=mock_arm` this is a **fully non-ROS device** (pure Python). It also
complements the colleague's read-only PuppyPi device-connect adapter by adding **actuation**
(their adapter is inspection-only; ours drives the robot through the capability model).

Run (D2D, zero infra — zenoh multicast discovers peers):
  DEVICE_CONNECT_ALLOW_INSECURE=true ROBOT_ADAPTER=mock_arm python3 openpave_device.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from device_connect_edge import DeviceRuntime
from device_connect_edge.drivers import DeviceDriver, rpc
from device_connect_edge.types import DeviceStatus

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pave_runtime.capability_schema import CapabilityIntentError, normalize_action_payload, now_iso
from control_daemon.adapters import create_robot_adapter


def dispatch(adapter, payload: dict) -> dict:
    """Pure capability dispatch — identical to the ②a neutral seam, so it is transport-agnostic:
    a `{action, params}` payload in, a state dict out. Rejects unparseable envelopes and actions
    the adapter doesn't declare."""
    try:
        action = normalize_action_payload(payload, default_source="device-connect")
    except CapabilityIntentError as exc:
        return {"status": "rejected", "error": str(exc), "updated_at": now_iso()}
    name = action["action"]
    base = {"request_id": action["request_id"], "action": name, "updated_at": now_iso()}
    if name not in adapter.capabilities:
        return {**base, "status": "unsupported",
                "error": f"{adapter.name} does not support '{name}'"}
    result = adapter.execute(name, action["params"])
    return {**base, "status": "completed" if result.success else "failed",
            "detail": result.detail, "error": result.error}


class OpenPaveBodyDriver(DeviceDriver):
    """An OpenPAVE capability body over Device Connect. `execute` routes a capability
    `{action, params}` to the adapter via the same dispatch the ②a seam uses."""

    device_type = os.getenv("DEVICE_TYPE", "openpave-body")

    def __init__(self) -> None:
        super().__init__()
        self.adapter = create_robot_adapter(os.getenv("ROBOT_ADAPTER", "mock_arm"))

    @property
    def status(self) -> DeviceStatus:
        return DeviceStatus(availability="available")

    @rpc()
    async def list_capabilities(self) -> dict[str, Any]:
        """List the capabilities this body declares (named list_* to avoid DeviceDriver.capabilities)."""
        return {"adapter": self.adapter.name, "capabilities": sorted(self.adapter.capabilities)}

    @rpc(labels={"category": "robot", "safety": "actuation"})
    async def execute(self, action: str, params: dict | None = None) -> dict[str, Any]:
        """Run one capability action; returns the capability state dict
        (status completed/failed/unsupported/rejected + detail)."""
        return dispatch(self.adapter, {"action": action, "params": params or {}})


async def main() -> None:
    driver = OpenPaveBodyDriver()
    device_id = os.getenv("DEVICE_ID", f"openpave-{driver.adapter.name}-d2d")
    print(f"openpave device up · adapter={driver.adapter.name} · device_id={device_id} · "
          f"caps={sorted(driver.adapter.capabilities)} · transport=device-connect")
    await DeviceRuntime(driver=driver, device_id=device_id).run()


if __name__ == "__main__":
    asyncio.run(main())
