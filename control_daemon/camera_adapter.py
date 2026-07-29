"""Camera sensor adapter (graduated from experiments/camera-mve).

A *sensing* CapabilityAdapter, the counterpart to the actuator adapters: the arm proved the
capability model spans a different actuator, this proves it spans **sensing**. It declares one
query capability, ``get_image``, whose ``execute`` returns small **metadata** (the control plane,
in ``AdapterActionResult.detail``) while stashing the raw JPEG in ``last_jpeg`` for a body node to
publish on a dedicated compressed-image topic (the **data plane**). Keeping the frame out of the
result *is* the control/data-plane split.

OpenCV (``cv2``) is imported lazily inside the frame sources, so importing this module never
requires OpenCV — only actually grabbing a frame does.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from control_daemon.adapters import AdapterActionResult
from pave_runtime.intent_schema import now_iso


@runtime_checkable
class CameraSource(Protocol):
    """A source of on-demand compressed frames (the sensor's data plane)."""

    def grab_jpeg(self) -> bytes:
        """Return exactly one JPEG-compressed frame."""

    @property
    def info(self) -> dict[str, Any]:
        """Static descriptor: ``{width, height, source}``."""


class MockCameraSource:
    """Synthetic frames — no camera. Each call returns a new gradient with a frame counter,
    so successive snapshots differ (useful to confirm the brain is getting fresh frames)."""

    def __init__(self, width: int = 640, height: int = 480) -> None:
        self._w, self._h = width, height
        self._seq = 0

    @property
    def info(self) -> dict[str, Any]:
        return {"width": self._w, "height": self._h, "source": "mock"}

    def grab_jpeg(self) -> bytes:
        import cv2  # lazy: only needed when actually producing a frame
        import numpy as np

        self._seq += 1
        row = np.linspace(0, 255, self._w, dtype=np.uint8)
        frame = np.repeat(row[None, :], self._h, axis=0)
        frame = np.stack([frame, np.roll(frame, self._seq * 4, axis=1), 255 - frame], axis=2)
        cv2.putText(frame, f"mock #{self._seq}", (16, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            raise RuntimeError("cv2.imencode failed for the mock frame")
        return buf.tobytes()


class UsbCameraSource:
    """A real USB camera via V4L2 (``/dev/videoN``). Opens the device once and reuses it."""

    def __init__(self, device: str = "/dev/video0", width: int = 640, height: int = 480,
                 warmup_frames: int = 8) -> None:
        self._device = device
        self._w, self._h = width, height
        self._warmup = warmup_frames  # UVC cold-start: discard a few frames so auto-exposure settles
        self._cap = None

    @property
    def info(self) -> dict[str, Any]:
        return {"width": self._w, "height": self._h, "source": self._device}

    def _ensure_open(self):
        import cv2

        if self._cap is None:
            target: Any = self._device
            if isinstance(target, str) and target.startswith("/dev/video"):
                target = int(target.removeprefix("/dev/video"))
            cap = cv2.VideoCapture(target)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._h)
            if not cap.isOpened():
                raise RuntimeError(f"cannot open camera {self._device!r} (is --device passed in?)")
            for _ in range(self._warmup):  # let auto-exposure/gain settle before the first real grab
                cap.read()
            self._cap = cap
        return self._cap

    def grab_jpeg(self) -> bytes:
        import cv2

        cap = self._ensure_open()
        ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError(f"failed to read a frame from {self._device!r}")
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            raise RuntimeError("cv2.imencode failed for the camera frame")
        return buf.tobytes()

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class CameraSensorAdapter:
    """A camera behind the capability interface. ``get_image`` is a *query* capability: it
    produces data rather than acting on the world. The frame itself travels on the data plane
    (see ``last_jpeg``), never inside the control-plane result."""

    def __init__(self, source: CameraSource, name: str = "camera") -> None:
        self.name = name
        self.source = source
        # sensing capability only — deliberately *not* the actuator verbs, to keep the
        # sensor/actuator distinction explicit.
        self.capabilities = frozenset({"get_image"})
        self.last_jpeg: bytes | None = None  # data-plane hand-off for the body node
        self._seq = 0

    def execute(self, action: str, params: dict[str, Any] | None = None) -> AdapterActionResult:
        if action != "get_image":
            return AdapterActionResult.failed(
                f"'{action}' not a sensing capability", detail={"action": action}
            )

        try:
            jpeg = self.source.grab_jpeg()
        except Exception as exc:  # hardware/read failure -> failed result, no frame
            self.last_jpeg = None
            return AdapterActionResult.failed(f"grab failed: {exc}", detail={"action": action})

        self._seq += 1
        self.last_jpeg = jpeg  # the body publishes this on the compressed-image topic
        info = self.source.info
        # control plane = small metadata only (the frame is NOT in here)
        return AdapterActionResult.ok(detail={
            "action": action,
            "encoding": "jpeg",
            "bytes": len(jpeg),
            "width": info.get("width"),
            "height": info.get("height"),
            "source": info.get("source"),
            "seq": self._seq,
            "updated_at": now_iso(),
        })
