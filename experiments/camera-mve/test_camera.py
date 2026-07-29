"""Unit tests for the camera sensor adapter (pure logic, no ROS, no OpenCV, no hardware).

The adapter is driven with a fake source that returns fixed bytes, so these run anywhere. The
real cv2 encode + USB read paths are exercised on the hardware run (see README).

Run: python3 -m unittest   (from this dir)
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "capability-mve"))
from camera_sensor_adapter import CameraSensorAdapter  # noqa: E402


class FakeSource:
    """A CameraSource stand-in: returns fixed bytes, no OpenCV/hardware."""

    def __init__(self, payload=b"\xff\xd8\xff\xd9"):  # minimal JPEG SOI/EOI
        self.payload = payload
        self.grabs = 0

    @property
    def info(self):
        return {"width": 4, "height": 2, "source": "fake"}

    def grab_jpeg(self):
        self.grabs += 1
        return self.payload


class BrokenSource(FakeSource):
    def grab_jpeg(self):
        raise RuntimeError("camera unplugged")


class CameraSensorAdapterTests(unittest.TestCase):
    def setUp(self):
        self.src = FakeSource()
        self.adapter = CameraSensorAdapter(self.src, name="camera_test")

    def test_declares_sensing_not_actuation(self):
        self.assertIn("get_image", self.adapter.capabilities)
        # deliberately NOT the actuator verbs — sensor, not actuator
        for verb in ("stop", "home", "estop", "move_joint", "grasp"):
            self.assertNotIn(verb, self.adapter.capabilities)

    def test_get_image_returns_metadata_and_stashes_frame(self):
        result = self.adapter.execute("get_image", {})
        self.assertTrue(result.success)
        # control plane: metadata only, frame is NOT in the reply detail
        self.assertEqual(result.detail["encoding"], "jpeg")
        self.assertEqual(result.detail["bytes"], len(self.src.payload))
        self.assertEqual(result.detail["width"], 4)
        self.assertNotIn("data", result.detail)
        self.assertNotIn("jpeg", result.detail)
        # data plane: the raw frame is handed off via last_jpeg
        self.assertEqual(self.adapter.last_jpeg, self.src.payload)

    def test_seq_increments_across_snapshots(self):
        self.adapter.execute("get_image", {})
        first = self.adapter.execute("get_image", {}).detail["seq"]
        self.assertEqual(first, 2)
        self.assertEqual(self.src.grabs, 2)

    def test_non_sensing_action_fails(self):
        result = self.adapter.execute("move_joint", {})
        self.assertFalse(result.success)

    def test_grab_failure_reports_failed_and_no_frame(self):
        adapter = CameraSensorAdapter(BrokenSource(), name="camera_broken")
        result = adapter.execute("get_image", {})
        self.assertFalse(result.success)
        self.assertIn("grab failed", result.error)
        self.assertIsNone(adapter.last_jpeg)


if __name__ == "__main__":
    unittest.main()
