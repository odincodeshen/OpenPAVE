"""Observation sources for brain-side inference inputs."""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib import request
from urllib.parse import urlparse

from pave_runtime.inference import Observation


class ObservationSourceError(RuntimeError):
    """Raised when an observation source cannot produce a valid observation."""


@runtime_checkable
class ObservationSource(Protocol):
    name: str

    async def capture(self) -> Observation:
        """Capture one observation for an inference request."""


class FileObservationSource:
    name = "file"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    async def capture(self) -> Observation:
        return await asyncio.to_thread(self._capture_sync)

    def _capture_sync(self) -> Observation:
        media_type = mimetypes.guess_type(self.path.name)[0] or "application/octet-stream"
        try:
            data = self.path.read_bytes()
        except OSError as exc:
            raise ObservationSourceError(f"cannot read observation file {self.path}: {exc}") from exc
        if not data:
            raise ObservationSourceError(f"observation file is empty: {self.path}")
        return Observation(media_type=media_type, data=data, source=str(self.path))


class HttpMjpegObservationSource:
    """Capture one JPEG from an HTTP snapshot or multipart MJPEG stream."""

    name = "http_mjpeg"
    _JPEG_START = b"\xff\xd8"
    _JPEG_END = b"\xff\xd9"

    def __init__(
        self,
        url: str,
        *,
        timeout_sec: float = 10.0,
        max_frame_bytes: int = 10 * 1024 * 1024,
        chunk_bytes: int = 16 * 1024,
    ) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("HTTP observation URL must use http:// or https://")
        if timeout_sec <= 0:
            raise ValueError("observation timeout must be positive")
        if max_frame_bytes <= 0 or chunk_bytes <= 0:
            raise ValueError("observation byte limits must be positive")
        self.url = url
        self.timeout_sec = float(timeout_sec)
        self.max_frame_bytes = int(max_frame_bytes)
        self.chunk_bytes = int(chunk_bytes)

    async def capture(self) -> Observation:
        return await asyncio.to_thread(self._capture_sync)

    def _capture_sync(self) -> Observation:
        http_request = request.Request(
            self.url,
            headers={"Accept": "image/jpeg,image/png,multipart/x-mixed-replace"},
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_sec) as response:
                content_type = str(response.headers.get("Content-Type", "")).lower()
                if content_type.startswith("image/jpeg"):
                    data = self._read_bounded(response)
                    self._validate_jpeg(data)
                    return self._observation(data, "image/jpeg", content_type)
                if content_type.startswith("image/png"):
                    data = self._read_bounded(response)
                    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                        raise ObservationSourceError("HTTP response is not a valid PNG")
                    return self._observation(data, "image/png", content_type)
                data = self._read_first_mjpeg_frame(response)
                return self._observation(data, "image/jpeg", content_type)
        except ObservationSourceError:
            raise
        except OSError as exc:
            raise ObservationSourceError(f"HTTP observation capture failed: {exc}") from exc

    def _read_bounded(self, response) -> bytes:
        data = response.read(self.max_frame_bytes + 1)
        if len(data) > self.max_frame_bytes:
            raise ObservationSourceError("observation exceeds maximum frame size")
        if not data:
            raise ObservationSourceError("HTTP observation response is empty")
        return data

    def _read_first_mjpeg_frame(self, response) -> bytes:
        buffer = bytearray()
        found_start = False
        while True:
            chunk = response.read(self.chunk_bytes)
            if not chunk:
                raise ObservationSourceError("MJPEG stream ended before a complete JPEG frame")
            buffer.extend(chunk)
            if not found_start:
                start = buffer.find(self._JPEG_START)
                if start < 0:
                    if len(buffer) > self.chunk_bytes * 2:
                        del buffer[:-1]
                    continue
                del buffer[:start]
                found_start = True
            end = buffer.find(self._JPEG_END, 2)
            if end >= 0:
                frame = bytes(buffer[: end + len(self._JPEG_END)])
                self._validate_jpeg(frame)
                return frame
            if len(buffer) > self.max_frame_bytes:
                raise ObservationSourceError("MJPEG frame exceeds maximum frame size")

    def _validate_jpeg(self, data: bytes) -> None:
        if not data.startswith(self._JPEG_START) or not data.endswith(self._JPEG_END):
            raise ObservationSourceError("HTTP response is not a complete JPEG")

    def _observation(self, data: bytes, media_type: str, response_type: str) -> Observation:
        return Observation(
            media_type=media_type,
            data=data,
            source=self.url,
            metadata={"source_type": self.name, "response_content_type": response_type},
        )


_SOURCES = {
    "file": FileObservationSource,
    "http_mjpeg": HttpMjpegObservationSource,
}


def create_observation_source(name: str, **opts) -> ObservationSource:
    key = name.strip().lower()
    if key not in _SOURCES:
        raise ValueError(f"unknown observation source {key!r}; known: {sorted(_SOURCES)}")
    return _SOURCES[key](**opts)
