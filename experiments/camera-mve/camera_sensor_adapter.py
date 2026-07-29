"""CameraSensorAdapter — a *sensing* capability under the same capability contract.

This is the counterpart to ``MockArmAdapter`` (an actuator): the arm proved the model spans
*actuation*, this proves it spans *sensing*. It declares one query capability, ``get_image``, and
its ``execute`` **returns metadata** (small — the control plane) while stashing the raw JPEG in
``last_jpeg`` for the body node to publish on a **dedicated compressed-image topic** (large — the
data plane). Keeping the frame out of the JSON reply *is* the control/data-plane split.

Actuator vs sensor, both under the same ``CapabilityAdapter`` interface:

    ActuatorAdapter.execute(action)  -> ActionResult(detail=status)          # does a thing
    CameraSensorAdapter.execute("get_image") -> ActionResult(detail=meta)    # + last_jpeg=frame
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# reuse the validated capability contract from the actuation MVE (Plan A)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "capability-mve"))
from capability_adapter import ActionResult  # noqa: E402

from camera_source import CameraSource  # noqa: E402


class CameraSensorAdapter:
    """A camera behind the capability interface. ``get_image`` is a *query* capability: it
    produces data rather than acting on the world. The frame itself travels on the data plane
    (see ``last_jpeg``), never inside the control-plane reply."""

    def __init__(self, source: CameraSource, name: str = "camera") -> None:
        self.name = name
        self.source = source
        # sensing capability only — deliberately *not* the actuator verbs (stop/home/estop),
        # to make the sensor/actuator distinction explicit.
        self.capabilities = frozenset({"get_image"})
        self.last_jpeg: bytes | None = None  # data-plane hand-off for the body node
        self._seq = 0

    def execute(self, action: str, params: dict[str, Any]) -> ActionResult:
        if action != "get_image":
            return ActionResult.failed(f"'{action}' not a sensing capability", {"action": action})

        try:
            jpeg = self.source.grab_jpeg()
        except Exception as exc:  # hardware/read failure -> failed result, no frame
            self.last_jpeg = None
            return ActionResult.failed(f"grab failed: {exc}", {"action": action})

        self._seq += 1
        self.last_jpeg = jpeg  # the body publishes this on the compressed-image topic
        info = self.source.info
        # control plane = small metadata only (the frame is NOT in here)
        return ActionResult.ok({
            "action": action,
            "encoding": "jpeg",
            "bytes": len(jpeg),
            "width": info.get("width"),
            "height": info.get("height"),
            "source": info.get("source"),
            "seq": self._seq,
        })
