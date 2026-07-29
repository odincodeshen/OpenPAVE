"""Tests for the graduated capability model in the runtime.

Covers the capability schema (``pave_runtime.capability_schema``) and the capability layer on
the locomotion adapters (``capabilities`` + ``execute`` on top of stop/trot/home/move). Pure
logic — a fake runner stands in for the ROS 2 CLI, no Docker/robot.
"""

from __future__ import annotations

import contextlib
import io
import unittest

from control_daemon.adapters import (
    AdapterActionResult,
    CapabilityAdapter,
    MockAdapter,
    MockArmAdapter,
    PuppyPiAdapter,
    RosCliConfig,
    create_robot_adapter,
)
from control_daemon.camera_adapter import CameraSensorAdapter
from pave_runtime.capability_schema import (
    COMMON_CAPABILITIES,
    CapabilityIntentError,
    normalize_action_payload,
)
from pave_runtime.intent_schema import intent_to_capability_action, normalize_intent_payload


def _puppy(runner):
    return PuppyPiAdapter(
        config=RosCliConfig(
            ros_domain_id="0",
            rmw_implementation="rmw_fastrtps_cpp",
            ros_svc_image="ros:humble",
            ros_pub_image="puppy-ros2-cli:humble",
        ),
        runner=runner,
    )


class CapabilitySchemaTests(unittest.TestCase):
    def test_normalize_lowercases_action_and_defaults_params(self):
        a = normalize_action_payload({"action": "MOVE"})
        self.assertEqual(a["action"], "move")
        self.assertEqual(a["params"], {})
        self.assertTrue(a["request_id"])
        self.assertEqual(a["schema_version"], "cap-0.1")

    def test_normalize_keeps_params_and_request_id(self):
        a = normalize_action_payload(
            {"action": "move", "params": {"vx": 0.1}, "request_id": "r1"}
        )
        self.assertEqual(a["params"], {"vx": 0.1})
        self.assertEqual(a["request_id"], "r1")

    def test_missing_action_raises(self):
        with self.assertRaises(CapabilityIntentError):
            normalize_action_payload({"params": {}})

    def test_params_not_object_raises(self):
        with self.assertRaises(CapabilityIntentError):
            normalize_action_payload({"action": "stop", "params": 5})


class AdapterActionResultTests(unittest.TestCase):
    def test_detail_defaults_empty_and_carries_payload(self):
        self.assertEqual(AdapterActionResult.ok().detail, {})
        self.assertEqual(AdapterActionResult.ok(detail={"bytes": 3}).detail, {"bytes": 3})
        self.assertEqual(AdapterActionResult.failed("x", detail={"a": 1}).detail, {"a": 1})


class LocomotionCapabilityTests(unittest.TestCase):
    def test_locomotion_adapters_are_capability_adapters(self):
        adapter = MockAdapter()
        self.assertIsInstance(adapter, CapabilityAdapter)  # runtime_checkable Protocol
        # common safe verbs + locomotion class verbs
        self.assertTrue(COMMON_CAPABILITIES <= adapter.capabilities)  # stop/estop/home
        self.assertIn("move", adapter.capabilities)
        self.assertIn("trot", adapter.capabilities)
        self.assertNotIn("grasp", adapter.capabilities)  # not a manipulation robot

    def test_execute_dispatches_stop(self):
        adapter = MockAdapter()
        with contextlib.redirect_stdout(io.StringIO()):
            result = adapter.execute("stop", {})
        self.assertTrue(result.success)
        self.assertEqual(result.steps, [{"name": "mock_stop", "return_code": 0}])

    def test_execute_estop_maps_to_stop(self):
        adapter = MockAdapter()
        with contextlib.redirect_stdout(io.StringIO()):
            result = adapter.execute("estop", {})
        self.assertTrue(result.success)
        self.assertEqual(result.steps, [{"name": "mock_stop", "return_code": 0}])

    def test_execute_move_passes_params_through(self):
        commands = []

        def runner(cmd):
            commands.append(cmd)
            return 0

        adapter = _puppy(runner)
        with contextlib.redirect_stdout(io.StringIO()):
            from unittest.mock import patch

            with patch("control_daemon.adapters.time.sleep"):
                result = adapter.execute("move", {"vx": 0.0, "yaw": 0.6, "duration_ms": 600})

        self.assertTrue(result.success)
        self.assertEqual(result.steps[-1]["name"], "velocity_move")
        self.assertIn("{x: 0.0, y: 0.0, yaw_rate: 0.6}", commands[-1])

    def test_execute_unsupported_action_fails(self):
        adapter = MockAdapter()
        with contextlib.redirect_stdout(io.StringIO()):
            result = adapter.execute("grasp", {})
        self.assertFalse(result.success)
        self.assertIn("unsupported action", result.error)

    def test_created_adapter_exposes_capabilities(self):
        adapter = create_robot_adapter("mock")
        self.assertIsInstance(adapter, CapabilityAdapter)
        self.assertIn("stop", adapter.capabilities)


class MockArmAdapterTests(unittest.TestCase):
    """Manipulation class over the same contract (actuation, different from locomotion)."""

    def setUp(self):
        self.adapter = MockArmAdapter()

    def test_is_capability_adapter_declaring_manipulation(self):
        self.assertIsInstance(self.adapter, CapabilityAdapter)
        self.assertTrue(COMMON_CAPABILITIES <= self.adapter.capabilities)  # stop/estop/home
        self.assertIn("move_joint", self.adapter.capabilities)
        self.assertNotIn("trot", self.adapter.capabilities)  # not a locomotion robot

    def test_execute_ok_returns_detail(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = self.adapter.execute("grasp", {})
        self.assertTrue(result.success)
        self.assertEqual(result.detail["action"], "grasp")

    def test_move_joint_requires_params(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = self.adapter.execute("move_joint", {"joint": 2})  # missing 'position'
        self.assertFalse(result.success)
        self.assertIn("position", result.error)

    def test_created_from_registry(self):
        adapter = create_robot_adapter("mock_arm")
        self.assertIsInstance(adapter, MockArmAdapter)


class _FakeSource:
    """A CameraSource stand-in: fixed bytes, no OpenCV/hardware."""

    def __init__(self, payload=b"\xff\xd8\xff\xd9"):
        self.payload = payload
        self.grabs = 0

    @property
    def info(self):
        return {"width": 4, "height": 2, "source": "fake"}

    def grab_jpeg(self):
        self.grabs += 1
        return self.payload


class CameraSensorAdapterTests(unittest.TestCase):
    """Sensing class over the same contract; control/data-plane split."""

    def setUp(self):
        self.src = _FakeSource()
        self.adapter = CameraSensorAdapter(self.src, name="camera_test")

    def test_is_capability_adapter_declaring_sensing_only(self):
        self.assertIsInstance(self.adapter, CapabilityAdapter)
        self.assertIn("get_image", self.adapter.capabilities)
        for verb in ("stop", "home", "estop", "move_joint", "grasp"):
            self.assertNotIn(verb, self.adapter.capabilities)  # sensor, not actuator

    def test_get_image_returns_metadata_and_stashes_frame(self):
        result = self.adapter.execute("get_image", {})
        self.assertTrue(result.success)
        # control plane: metadata only, frame is NOT in the result detail
        self.assertEqual(result.detail["encoding"], "jpeg")
        self.assertEqual(result.detail["bytes"], len(self.src.payload))
        self.assertNotIn("data", result.detail)
        # data plane: the raw frame is handed off via last_jpeg
        self.assertEqual(self.adapter.last_jpeg, self.src.payload)

    def test_non_sensing_action_fails(self):
        result = self.adapter.execute("move_joint", {})
        self.assertFalse(result.success)

    def test_created_from_registry_without_opencv(self):
        # create_robot_adapter("camera_mock") must not require OpenCV (lazy import); it only
        # builds the adapter + mock source, no frame grab here.
        adapter = create_robot_adapter("camera_mock")
        self.assertIsInstance(adapter, CameraSensorAdapter)
        self.assertEqual(adapter.capabilities, frozenset({"get_image"}))


class IntentTranslatorTests(unittest.TestCase):
    """Legacy locomotion intent (v0.1) -> capability action translation (the compat layer)."""

    def test_simple_verbs_map_without_params(self):
        for intent, action in (("STOP", "stop"), ("TROT", "trot"), ("HOME", "home")):
            req = intent_to_capability_action({"intent": intent})
            self.assertEqual(req["action"], action)
            self.assertEqual(req["params"], {})

    def test_move_carries_velocity_params(self):
        normalized = normalize_intent_payload(
            {"intent": "MOVE", "vx": 0.0, "yaw": 0.6, "duration_ms": 600}
        )
        req = intent_to_capability_action(normalized)
        self.assertEqual(req["action"], "move")
        self.assertEqual(req["params"]["yaw"], 0.6)
        self.assertEqual(req["params"]["duration_ms"], 600)

    def test_translated_action_is_supported_by_locomotion_adapter(self):
        # end-to-end contract: every legacy intent translates to a capability the
        # locomotion adapter declares (so generic dispatch never rejects a valid intent)
        adapter = MockAdapter()
        for intent in ("STOP", "TROT", "HOME", "MOVE"):
            req = intent_to_capability_action(normalize_intent_payload({"intent": intent}))
            self.assertIn(req["action"], adapter.capabilities)

    def test_unknown_intent_falls_back_to_stop(self):
        req = intent_to_capability_action({"intent": "FLIP"})
        self.assertEqual(req["action"], "stop")


if __name__ == "__main__":
    unittest.main()
