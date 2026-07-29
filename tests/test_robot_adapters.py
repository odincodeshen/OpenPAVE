import contextlib
import io
import os
import unittest
from unittest.mock import patch

from control_daemon.adapters import (
    MockAdapter,
    PuppyPiAdapter,
    PuppyPiLocalAdapter,
    RosCliConfig,
    create_robot_adapter,
)


def _puppy_config() -> RosCliConfig:
    return RosCliConfig(
        ros_domain_id="0",
        rmw_implementation="rmw_fastrtps_cpp",
        ros_svc_image="ros:humble",
        ros_pub_image="puppy-ros2-cli:humble",
    )


class RobotAdapterTests(unittest.TestCase):
    def test_create_mock_adapter_from_name(self):
        adapter = create_robot_adapter("mock")

        self.assertIsInstance(adapter, MockAdapter)
        self.assertEqual(adapter.name, "mock")

    def test_create_mock_adapter_from_env(self):
        with patch.dict(os.environ, {"ROBOT_ADAPTER": "dry-run"}):
            adapter = create_robot_adapter()

        self.assertIsInstance(adapter, MockAdapter)

    def test_unknown_adapter_raises(self):
        with self.assertRaises(ValueError):
            create_robot_adapter("unknown")

    def test_puppypi_stop_generates_expected_ros_calls(self):
        commands = []

        def runner(cmd):
            commands.append(cmd)
            return 0

        adapter = PuppyPiAdapter(
            config=RosCliConfig(
                ros_domain_id="7",
                rmw_implementation="rmw_fastrtps_cpp",
                ros_svc_image="ros:humble",
                ros_pub_image="puppy-ros2-cli:humble",
            ),
            runner=runner,
        )

        with patch("control_daemon.adapters.time.sleep"), contextlib.redirect_stdout(io.StringIO()):
            result = adapter.stop()

        self.assertEqual(len(commands), 3)
        self.assertTrue(result.success)
        self.assertEqual([step["return_code"] for step in result.steps], [0, 0, 0])
        self.assertIn("-e ROS_DOMAIN_ID=7", commands[0])
        self.assertIn("/puppy_control/set_mark_time", commands[0])
        self.assertIn("{data: false}", commands[0])
        self.assertIn("/puppy_control/set_running", commands[1])
        self.assertIn("/puppy_control/go_home", commands[2])

    def test_puppypi_move_generates_velocity_publish(self):
        commands = []

        def runner(cmd):
            commands.append(cmd)
            return 0

        adapter = PuppyPiAdapter(
            config=RosCliConfig(
                ros_domain_id="0",
                rmw_implementation="rmw_fastrtps_cpp",
                ros_svc_image="ros:humble",
                ros_pub_image="puppy-ros2-cli:humble",
            ),
            runner=runner,
        )

        with patch("control_daemon.adapters.time.sleep"), contextlib.redirect_stdout(io.StringIO()):
            result = adapter.move(vx=0.0, yaw=0.6, duration_ms=600)

        self.assertEqual(len(commands), 4)
        self.assertTrue(result.success)
        self.assertEqual(result.steps[-1]["name"], "velocity_move")
        self.assertIn("/puppy_control/go_home", commands[0])
        self.assertIn("/puppy_control/set_mark_time", commands[1])
        self.assertIn("/puppy_control/set_running", commands[2])
        self.assertIn("/puppy_control/velocity_move", commands[3])
        self.assertIn("{x: 0.0, y: 0.0, yaw_rate: 0.6}", commands[3])

    def test_puppypi_result_fails_when_step_fails(self):
        def runner(cmd):
            return 9 if "/puppy_control/velocity_move" in cmd else 0

        adapter = PuppyPiAdapter(
            config=RosCliConfig(
                ros_domain_id="0",
                rmw_implementation="rmw_fastrtps_cpp",
                ros_svc_image="ros:humble",
                ros_pub_image="puppy-ros2-cli:humble",
            ),
            runner=runner,
        )

        with patch("control_daemon.adapters.time.sleep"), contextlib.redirect_stdout(io.StringIO()):
            result = adapter.move(vx=0.0, yaw=0.6, duration_ms=600)

        self.assertFalse(result.success)
        self.assertEqual(result.steps[-1]["return_code"], 9)
        self.assertEqual(result.error, "one or more adapter steps failed")

    def test_create_puppypi_local_adapter(self):
        adapter = create_robot_adapter("puppypi_local")

        self.assertIsInstance(adapter, PuppyPiLocalAdapter)
        self.assertEqual(adapter.name, "puppypi_local")

    def test_puppypi_local_stop_uses_docker_exec(self):
        commands = []

        def runner(cmd):
            commands.append(cmd)
            return 0

        with patch.dict(os.environ, {"PUPPY_EXEC_CONTAINER": "puppypi_ros2"}):
            adapter = PuppyPiLocalAdapter(config=_puppy_config(), runner=runner)

        with patch("control_daemon.adapters.time.sleep"), contextlib.redirect_stdout(io.StringIO()):
            result = adapter.stop()

        self.assertTrue(result.success)
        self.assertEqual(len(commands), 3)
        for cmd in commands:
            self.assertIn("docker exec", cmd)
            self.assertIn("puppypi_ros2", cmd)
            self.assertIn("timeout", cmd)  # hung call fails fast, doesn't block the body
            self.assertNotIn("docker run", cmd)
        self.assertIn("/puppy_control/go_home", commands[2])

    def test_puppypi_local_stop_escalates_to_hard_stop(self):
        commands = []

        def runner(cmd):
            commands.append(cmd)
            # motion-stop service calls time out (as when the gait loop starves the callback);
            # the hard-stop (pkill) succeeds.
            if "set_mark_time" in cmd or "set_running" in cmd:
                return 124
            return 0

        adapter = PuppyPiLocalAdapter(config=_puppy_config(), runner=runner)

        with patch("control_daemon.adapters.time.sleep"), contextlib.redirect_stdout(io.StringIO()):
            result = adapter.stop()

        joined = " ".join(commands)
        self.assertIn("pkill", joined)              # escalated to hard-stop
        self.assertNotIn("go_home", joined)         # graceful posture skipped on escalation
        self.assertTrue(result.success)             # robot stopped via hard-stop
        self.assertEqual(result.steps[-1]["name"], "hard_stop:kill_gait")

    def test_puppypi_local_trot_settles_between_calls(self):
        commands = []

        def runner(cmd):
            commands.append(cmd)
            return 0

        adapter = PuppyPiLocalAdapter(config=_puppy_config(), runner=runner)

        with patch("control_daemon.adapters.time.sleep") as sleep_mock, contextlib.redirect_stdout(io.StringIO()):
            result = adapter.trot()

        self.assertTrue(result.success)
        self.assertEqual(len(commands), 2)
        self.assertIn("/puppy_control/set_running", commands[0])
        self.assertIn("{data: true}", commands[0])
        self.assertIn("/puppy_control/set_mark_time", commands[1])
        sleep_mock.assert_called()  # settle delay applied between the two calls

    def test_puppypi_local_move_velocity_via_exec(self):
        commands = []

        def runner(cmd):
            commands.append(cmd)
            return 0

        adapter = PuppyPiLocalAdapter(config=_puppy_config(), runner=runner)

        with patch("control_daemon.adapters.time.sleep"), contextlib.redirect_stdout(io.StringIO()):
            result = adapter.move(vx=0.0, yaw=0.6, duration_ms=600)

        self.assertTrue(result.success)
        self.assertEqual(result.steps[-1]["name"], "velocity_move")
        self.assertIn("docker exec", commands[-1])
        self.assertIn("puppy_control_msgs/msg/Velocity", commands[-1])
        self.assertIn("{x: 0.0, y: 0.0, yaw_rate: 0.6}", commands[-1])

    def test_mock_adapter_returns_success_result(self):
        adapter = MockAdapter()

        with contextlib.redirect_stdout(io.StringIO()):
            result = adapter.stop()

        self.assertTrue(result.success)
        self.assertEqual(result.steps, [{"name": "mock_stop", "return_code": 0}])


if __name__ == "__main__":
    unittest.main()
