"""device-connect seam backend — graduates ②b (experiments/device-connect).

Body = an Arm Device Connect `DeviceDriver` with **one labeled `@rpc` per capability** (generated
dynamically from `adapter.capabilities`); brain = `discover` + `invoke` by selector. Body-endpoint
logic is `pave_runtime.seam.dispatch` (single source).

Fleet-level features (`broadcast`) are **backend-specific** and deliberately NOT part of the common
`SeamTransport` interface (Q2 = 乙) — reach for them on this concrete backend.
"""

from __future__ import annotations

import os
import types

from pave_runtime.seam import dispatch

_SAFETY_CRITICAL = frozenset({"estop", "stop"})
_SENSING = frozenset({"get_image"})
_CATEGORY = {
    "puppypi": "robot", "puppypi_local": "robot", "puppypi_bridge": "robot", "mock": "robot",
    "mock_arm": "actuator",
    "camera_mock": "sensor", "camera_usb": "sensor",
}


def _function_labels(action: str) -> dict[str, str]:
    return {
        "safety": "critical" if action in _SAFETY_CRITICAL else "informational",
        "direction": "read" if action in _SENSING else "write",
    }


class DeviceConnectSeam:
    name = "device_connect"
    device_type = "openpave-body"

    async def serve(self, adapter) -> None:
        from device_connect_edge import DeviceRuntime
        from device_connect_edge.drivers import DeviceDriver, rpc
        from device_connect_edge.types import DeviceIdentity, DeviceStatus

        cat = _CATEGORY.get(adapter.name, "actuator")
        dtype = os.getenv("DEVICE_TYPE", self.device_type)

        def _make_rpc(action: str):
            async def method(self, params: dict | None = None) -> dict:
                return dispatch(adapter, action, params)
            method.__name__ = action
            method.__doc__ = f"Run the '{action}' capability.\n\nArgs:\n    params: capability params dict."
            return rpc(name=action, labels=_function_labels(action))(method)

        class _OpenPaveDriver(DeviceDriver):
            def __init__(self) -> None:
                super().__init__()
                self.device_type = dtype
                self.labels = {"category": cat}
                for a in sorted(adapter.capabilities):
                    self.__dict__[a] = types.MethodType(_make_rpc(a), self)
                self._invalidate_caches()

            @property
            def identity(self) -> "DeviceIdentity":
                return DeviceIdentity(device_type=dtype, manufacturer="OpenPAVE", model=adapter.name)

            @property
            def status(self) -> "DeviceStatus":
                return DeviceStatus(availability="available")

            @rpc()
            async def list_capabilities(self) -> dict:
                """List the capabilities (each is also its own labeled RPC)."""
                return {"adapter": adapter.name, "category": cat,
                        "capabilities": sorted(adapter.capabilities)}

        driver = _OpenPaveDriver()
        device_id = os.getenv("DEVICE_ID", f"openpave-{adapter.name}-d2d")
        print(f"[seam:device_connect] body up · adapter={adapter.name} · "
              f"caps={sorted(adapter.capabilities)}")
        await DeviceRuntime(driver=driver, device_id=device_id).run()

    async def send(self, action: str, params: dict | None = None,
                   *, target: str | None = None, timeout: float = 5.0) -> dict:
        from device_connect_agent_tools import connect, discover_devices, invoke
        connect()
        dev = target
        if not dev:
            devices = discover_devices(device_type=self.device_type)
            if not devices:
                return {"status": "no_device", "error": f"no {self.device_type} found", "action": action}
            if len(devices) > 1:
                # F4: never silently pick the first of several bodies — that could drive the wrong
                # robot. Require an explicit target when the discovery is ambiguous.
                ids = [d.get("device_id") or d.get("id") for d in devices]
                return {
                    "status": "rejected",
                    "action": action,
                    "error": (
                        f"ambiguous target: {len(devices)} {self.device_type} devices online "
                        f"({ids}); pass --action-target / ACTION_TARGET to choose one"
                    ),
                }
            dev = devices[0].get("device_id") or devices[0].get("id")
        res = invoke(f"device({dev}).function({action})", params={"params": params or {}})
        return res.get("result", res) if isinstance(res, dict) else res

    # --- backend-specific (Q2 = 乙: not in the common SeamTransport interface) ---
    async def broadcast(self, action: str, *, timeout: float = 5.0) -> dict:
        """Fleet-wide invoke by function label, e.g. broadcast('estop'). device-connect only."""
        from device_connect_agent_tools import connect, broadcast, await_replies
        connect()
        res = broadcast(f"function({action})")
        cid = res.get("correlation_id")
        replies = await_replies(cid, timeout=timeout) if cid else []
        return {"candidates": res.get("candidates"), "correlation_id": cid, "replies": replies}
