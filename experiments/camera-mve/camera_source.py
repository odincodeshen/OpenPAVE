"""Camera frame sources for the sensing MVE — the *data plane* producer.

A ``CameraSource`` grabs one **compressed (JPEG)** frame on demand. Two implementations:

* ``MockCameraSource`` — a synthetic frame (gradient + frame counter), **no hardware**, so the
  whole control/data-plane plumbing can be verified before a real camera is attached.
* ``UsbCameraSource`` — a real USB camera via ``/dev/videoN`` (OpenCV ``VideoCapture``).

OpenCV (``cv2``) is imported lazily inside the methods so this module stays importable for unit
tests on a machine without OpenCV (the tests drive the adapter with a fake source).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


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
        # horizontal gradient + a moving band so frames are visibly distinct
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
            # accept "/dev/video0" or a bare index
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
