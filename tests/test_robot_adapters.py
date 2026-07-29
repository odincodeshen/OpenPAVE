import base64
import contextlib
import io
import json
import os
import re
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


def _decode_steps(cmd: str) -> list[dict]:
    """Pull the base64 step list back out of a gait-runner docker-exec command."""
    match = re.search(r"python3 - ([A-Za-z0-9+/=]+)", cmd)
    assert match, f"no base64 steps payload in: {cmd}"
    return json.loads(base64.b64decode(match.group(1)).decode())["steps"]


def _fake_capture(fail_services: tuple[str, ...] = ()):
    """A capture-runner stand-in for PuppyPiLocalAdapter._run_gait.

    Records each call and returns a runner-shaped JSON result derived from the decoded steps,
    marking any service whose path contains an entry in ``fail_services`` as timed out (rc 124).
    """
    calls: list[dict] = []

    def cap(cmd: str, stdin_text: str):
        steps = _decode_steps(cmd)
        calls.append({"cmd": cmd, "stdin": stdin_text, "steps": steps})
        results = []
        for step in steps:
            op = step.get("op")
            if op == "service":
                rc = 124 if any(f in step["service"] for f in fail_services) else 0
                results.append({"name": f"service:{step['service']}", "rc": rc})
            elif op == "velocity":
                results.append({"name": "velocity_move", "rc": 0})
            elif op == "sleep":
                results.append({"name": "sleep", "rc": 0})
        overall = 0 if all(r["rc"] == 0 for r in results) else 1
        return overall, json.dumps({"steps": results})

    return cap, calls


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

    # ---- opt A: batched gait runner (one docker exec per action) ----------------------------
    def test_puppypi_local_stop_batches_motion_then_go_home(self):
        cap, calls = _fake_capture()
        adapter = PuppyPiLocalAdapter(config=_puppy_config(), capture_runner=cap)

        with contextlib.redirect_stdout(io.StringIO()):
            result = adapter.stop()

        self.assertTrue(result.success)
        # success path = 2 execs: motion-stop (both calls in ONE exec), then go_home
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [s["service"] for s in calls[0]["steps"]],
            ["/puppy_control/set_mark_time", "/puppy_control/set_running"],
        )
        self.assertEqual(calls[1]["steps"][0]["service"], "/puppy_control/go_home")
        for c in calls:
            self.assertIn("docker exec -i", c["cmd"])
            self.assertIn("puppypi_ros2", c["cmd"])
            self.assertNotIn("docker run", c["cmd"])
            self.assertNotIn("ros2 service call", c["cmd"])  # no per-call CLI anymore
            self.assertEqual(c["stdin"], adapter._runner_path.read_text())  # runner fed via stdin

    def test_puppypi_local_stop_escalates_to_hard_stop(self):
        # motion-stop service calls time out (gait loop starves the callback); the pkill succeeds.
        cap, calls = _fake_capture(fail_services=("set_mark_time", "set_running"))
        pkills = []

        def runner(cmd):  # used only by _hard_stop
            pkills.append(cmd)
            return 0

        adapter = PuppyPiLocalAdapter(config=_puppy_config(), runner=runner, capture_runner=cap)

        with contextlib.redirect_stdout(io.StringIO()):
            result = adapter.stop()

        self.assertTrue(result.success)  # robot stopped via hard-stop
        self.assertEqual(len(calls), 1)  # only the motion-stop exec; go_home skipped on escalation
        self.assertTrue(any("pkill" in c for c in pkills))
        self.assertEqual(result.steps[-1]["name"], "hard_stop:kill_gait")

    def test_puppypi_local_trot_batches_with_settle_step(self):
        cap, calls = _fake_capture()
        adapter = PuppyPiLocalAdapter(config=_puppy_config(), capture_runner=cap)

        with contextlib.redirect_stdout(io.StringIO()):
            result = adapter.trot()

        self.assertTrue(result.success)
        self.assertEqual(len(calls), 1)  # one exec for the whole trot
        ops = [(s.get("op"), s.get("service", s.get("sec"))) for s in calls[0]["steps"]]
        self.assertEqual(
            ops,
            [
                ("service", "/puppy_control/set_running"),
                ("sleep", adapter.trot_settle_sec),  # settle is a step inside the runner now
                ("service", "/puppy_control/set_mark_time"),
            ],
        )

    def test_puppypi_local_move_velocity_via_gait(self):
        cap, calls = _fake_capture()
        adapter = PuppyPiLocalAdapter(config=_puppy_config(), capture_runner=cap)

        with contextlib.redirect_stdout(io.StringIO()):
            result = adapter.move(vx=0.0, yaw=0.6, duration_ms=600)

        self.assertTrue(result.success)
        self.assertEqual(len(calls), 1)  # one exec for the whole move
        velocity = [s for s in calls[0]["steps"] if s.get("op") == "velocity"]
        self.assertEqual(len(velocity), 1)
        self.assertEqual(velocity[0]["x"], 0.0)
        self.assertEqual(velocity[0]["yaw_rate"], 0.6)
        self.assertEqual(result.steps[-1]["name"], "velocity_move")

    def test_mock_adapter_returns_success_result(self):
        adapter = MockAdapter()

        with contextlib.redirect_stdout(io.StringIO()):
            result = adapter.stop()

        self.assertTrue(result.success)
        self.assertEqual(result.steps, [{"name": "mock_stop", "return_code": 0}])


if __name__ == "__main__":
    unittest.main()
