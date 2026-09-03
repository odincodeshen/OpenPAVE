"""Tests for file and PuppyPi HTTP/MJPEG observation sources."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pave_runtime.observation import (
    ObservationSourceError,
    create_observation_source,
)
from scripts.run_inference import load_observation


JPEG = b"\xff\xd8frame-data\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\npng-data"


class _Response:
    def __init__(self, chunks, content_type):
        self.chunks = list(chunks)
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class FileObservationSourceTests(unittest.TestCase):
    def test_reads_static_jpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frame.jpg"
            path.write_bytes(JPEG)
            observation = asyncio.run(
                create_observation_source("file", path=path).capture()
            )
        self.assertEqual(observation.media_type, "image/jpeg")
        self.assertEqual(observation.data, JPEG)
        self.assertEqual(observation.source, str(path))

    def test_rejects_empty_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.png"
            path.write_bytes(b"")
            with self.assertRaises(ObservationSourceError):
                asyncio.run(create_observation_source("file", path=path).capture())

    def test_explicit_file_takes_precedence_over_environment_url(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frame.jpg"
            path.write_bytes(JPEG)
            with patch.dict("os.environ", {"OBSERVATION_URL": "http://wrong.test/stream"}):
                observation = asyncio.run(load_observation(path))
        self.assertEqual(observation.data, JPEG)
        self.assertEqual(observation.source, str(path))


class HttpMjpegObservationSourceTests(unittest.TestCase):
    def capture(self, response, **opts):
        source = create_observation_source(
            "http_mjpeg", url="http://puppypi:8080/stream?topic=/usb_cam/image_raw", **opts
        )
        with patch("pave_runtime.observation.request.urlopen", return_value=response) as urlopen:
            observation = asyncio.run(source.capture())
        return observation, urlopen

    def test_reads_direct_jpeg_snapshot(self):
        observation, urlopen = self.capture(_Response([JPEG], "image/jpeg"))
        self.assertEqual(observation.media_type, "image/jpeg")
        self.assertEqual(observation.data, JPEG)
        self.assertEqual(observation.metadata["source_type"], "http_mjpeg")
        request_arg = urlopen.call_args.args[0]
        self.assertIn("image/jpeg", request_arg.get_header("Accept"))
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10.0)

    def test_reads_direct_png_snapshot(self):
        observation, _ = self.capture(_Response([PNG], "image/png"))
        self.assertEqual(observation.media_type, "image/png")
        self.assertEqual(observation.data, PNG)

    def test_extracts_first_jpeg_from_multipart_stream(self):
        response = _Response(
            [
                b"--boundary\r\nContent-Type: image/jpeg\r\n\r\nnoise",
                JPEG[:5],
                JPEG[5:] + b"\r\n--boundary",
            ],
            "multipart/x-mixed-replace; boundary=boundary",
        )
        observation, _ = self.capture(response, chunk_bytes=8)
        self.assertEqual(observation.media_type, "image/jpeg")
        self.assertEqual(observation.data, JPEG)

    def test_rejects_stream_without_complete_frame(self):
        response = _Response(
            [b"--boundary\r\n", b"\xff\xd8incomplete", b""],
            "multipart/x-mixed-replace; boundary=boundary",
        )
        with self.assertRaisesRegex(ObservationSourceError, "complete JPEG"):
            self.capture(response)

    def test_rejects_bad_url_and_unknown_source(self):
        with self.assertRaises(ValueError):
            create_observation_source("http_mjpeg", url="file:///tmp/frame.jpg")
        with self.assertRaises(ValueError):
            create_observation_source("missing")


if __name__ == "__main__":
    unittest.main()
