"""Robot adapters for the OpenPAVE control daemon."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from pave_runtime.intent_schema import now_iso


CommandRunner = Callable[[str], int]


@dataclass(frozen=True)
class AdapterActionResult:
    success: bool
    steps: list[dict[str, object]]
    error: str | None = None

    @classmethod
    def ok(cls, steps: list[dict[str, object]] | None = None) -> "AdapterActionResult":
        return cls(success=True, steps=steps or [])

    @classmethod
    def failed(
        cls,
        error: str,
        steps: list[dict[str, object]] | None = None,
    ) -> "AdapterActionResult":
        return cls(success=False, steps=steps or [], error=error)


class RobotAdapter(Protocol):
    """Common robot capability interface consumed by the control daemon."""

    name: str

    def stop(self) -> AdapterActionResult:
        """Stop robot motion and return to a safe posture when supported."""

    def trot(self) -> AdapterActionResult:
        """Start the adapter's trot or mark-time behavior."""

    def home(self) -> AdapterActionResult:
        """Return the robot to its home posture."""

    def move(self, vx: float, yaw: float, duration_ms: int) -> AdapterActionResult:
        """Run a short velocity-style movement command."""


@dataclass(frozen=True)
class RosCliConfig:
    ros_domain_id: str
    rmw_implementation: str
    ros_svc_image: str
    ros_pub_image: str

    @classmethod
    def from_env(cls) -> "RosCliConfig":
        return cls(
            ros_domain_id=os.environ.get("ROS_DOMAIN_ID", "0"),
            # PUPPY_RMW_IMPLEMENTATION lets the adapter's ROS 2 CLI use a different RMW than
            # the host process — e.g. when the brain-body seam runs on rmw_zenoh but
            # puppy_control speaks FastDDS. Falls back to RMW_IMPLEMENTATION, then the
            # FastDDS default, so existing single-RMW deployments are unchanged.
            rmw_implementation=os.environ.get(
                "PUPPY_RMW_IMPLEMENTATION",
                os.environ.get("RMW_IMPLEMENTATION", "rmw_fastrtps_cpp"),
            ),
            ros_svc_image=os.environ.get("ROS_SVC_IMAGE", "ros:humble"),
            ros_pub_image=os.environ.get("ROS_PUB_IMAGE", "puppy-ros2-cli:humble"),
        )


def default_runner(cmd: str) -> int:
    return subprocess.run(cmd, shell=True).returncode


class PuppyPiAdapter:
    """PuppyPi robot adapter backed by Dockerized ROS2 CLI calls."""

    name = "puppypi"

    def __init__(self, config: RosCliConfig | None = None, runner: CommandRunner | None = None):
        self.config = config or RosCliConfig.from_env()
        self.runner = runner or default_runner

    def _run(self, cmd: str) -> int:
        return self.runner(cmd)

    def _step(self, name: str, rc: int) -> dict[str, object]:
        return {"name": name, "return_code": rc}

    def _result(self, steps: list[dict[str, object]]) -> AdapterActionResult:
        failed_steps = [step for step in steps if step.get("return_code") != 0]
        if failed_steps:
            return AdapterActionResult.failed("one or more adapter steps failed", steps)
        return AdapterActionResult.ok(steps)

    def _ros2_service_call(self, service: str, srv_type: str, payload: str) -> int:
        cmd = (
            f"docker run --rm --net=host "
            f"-e ROS_DOMAIN_ID={self.config.ros_domain_id} "
            f"-e RMW_IMPLEMENTATION={self.config.rmw_implementation} "
            f"{self.config.ros_svc_image} bash -lc "
            f"\"source /opt/ros/humble/setup.bash && "
            f"ros2 service call {service} {srv_type} '{payload}' >/dev/null 2>&1\""
        )
        return self._run(cmd)

    def _ros2_topic_pub_velocity_move(self, vx: float, yaw: float) -> int:
        cmd = (
            f"docker run --rm --net=host "
            f"-e ROS_DOMAIN_ID={self.config.ros_domain_id} "
            f"-e RMW_IMPLEMENTATION={self.config.rmw_implementation} "
            f"{self.config.ros_pub_image} bash -lc "
            f"\"source /opt/ros/humble/setup.bash && source /ws/install/setup.bash && "
            f"ros2 topic pub -1 /puppy_control/velocity_move puppy_control_msgs/msg/Velocity "
            f"'{{x: {vx}, y: 0.0, yaw_rate: {yaw}}}'\""
        )
        return self._run(cmd)

    def trot(self) -> AdapterActionResult:
        print(f"[{now_iso()}] ACTION=TROT adapter={self.name}")
        steps = [
            self._step(
                "set_running:true",
                self._ros2_service_call(
                    "/puppy_control/set_running",
                    "std_srvs/srv/SetBool",
                    "{data: true}",
                ),
            ),
            self._step(
                "set_mark_time:true",
                self._ros2_service_call(
                    "/puppy_control/set_mark_time",
                    "std_srvs/srv/SetBool",
                    "{data: true}",
                ),
            ),
        ]
        return self._result(steps)

    def stop(self) -> AdapterActionResult:
        print(f"[{now_iso()}] ACTION=STOP adapter={self.name}")
        steps = [
            self._step(
                "set_mark_time:false",
                self._ros2_service_call(
                    "/puppy_control/set_mark_time",
                    "std_srvs/srv/SetBool",
                    "{data: false}",
                ),
            ),
            self._step(
                "set_running:false",
                self._ros2_service_call(
                    "/puppy_control/set_running",
                    "std_srvs/srv/SetBool",
                    "{data: false}",
                ),
            ),
            self._step(
                "go_home",
                self._ros2_service_call("/puppy_control/go_home", "std_srvs/srv/Empty", "{}"),
            ),
        ]
        time.sleep(0.3)
        return self._result(steps)

    def home(self) -> AdapterActionResult:
        print(f"[{now_iso()}] ACTION=HOME adapter={self.name}")
        steps = [
            self._step(
                "go_home",
                self._ros2_service_call("/puppy_control/go_home", "std_srvs/srv/Empty", "{}"),
            )
        ]
        return self._result(steps)

    def move(self, vx: float, yaw: float, duration_ms: int) -> AdapterActionResult:
        print(f"[{now_iso()}] ACTION=MOVE adapter={self.name} vx={vx} yaw={yaw} duration_ms={duration_ms}")
        steps = [
            self._step(
                "go_home",
                self._ros2_service_call("/puppy_control/go_home", "std_srvs/srv/Empty", "{}"),
            ),
            self._step(
                "set_mark_time:false",
                self._ros2_service_call(
                    "/puppy_control/set_mark_time",
                    "std_srvs/srv/SetBool",
                    "{data: false}",
                ),
            ),
            self._step(
                "set_running:true",
                self._ros2_service_call(
                    "/puppy_control/set_running",
                    "std_srvs/srv/SetBool",
                    "{data: true}",
                ),
            ),
        ]
        time.sleep(0.3)
        rc = self._ros2_topic_pub_velocity_move(vx=vx, yaw=yaw)
        steps.append(self._step("velocity_move", rc))
        if rc != 0:
            print(f"[{now_iso()}] WARN: velocity_move pub rc={rc}")
        return self._result(steps)


class PuppyPiLocalAdapter(PuppyPiAdapter):
    """PuppyPi adapter for a body node co-located with puppy_control on the robot.

    Same actions as ``PuppyPiAdapter``, but instead of ``docker run`` (a fresh container that
    cannot reach puppy_control's FastDDS shared-memory segment across IPC namespaces), it
    ``docker exec``s into the already-running puppy_control container. The ROS 2 CLI then
    shares that container's IPC namespace (so same-host SHM works) and its workspace (which
    provides ``puppy_control_msgs`` for velocity_move — no separate ``puppy-ros2-cli`` image
    needed).

    Use it when the body runs ON the robot (brain-body-zenoh deployment). The original
    ``PuppyPiAdapter`` (``docker run``, for a remote control host) is unchanged.

    Env config:
    - ``PUPPY_EXEC_CONTAINER`` (default ``puppypi_ros2``): container running puppy_control
    - ``PUPPY_EXEC_USER`` (default ``ubuntu``): user to exec as
    - ``PUPPY_ROS_WS_SETUP`` (default ``/home/ubuntu/ros2_ws/install/setup.bash``): workspace setup
    """

    name = "puppypi_local"

    def __init__(self, config: RosCliConfig | None = None, runner: CommandRunner | None = None):
        super().__init__(config=config, runner=runner)
        self.exec_container = os.environ.get("PUPPY_EXEC_CONTAINER", "puppypi_ros2")
        self.exec_user = os.environ.get("PUPPY_EXEC_USER", "ubuntu")
        self.ros_ws_setup = os.environ.get(
            "PUPPY_ROS_WS_SETUP", "/home/ubuntu/ros2_ws/install/setup.bash"
        )

    def _exec_prefix(self) -> str:
        return (
            f"docker exec -u {self.exec_user} "
            f"-e ROS_DOMAIN_ID={self.config.ros_domain_id} "
            f"-e RMW_IMPLEMENTATION={self.config.rmw_implementation} "
            f"{self.exec_container} bash -lc "
        )

    def _ros2_service_call(self, service: str, srv_type: str, payload: str) -> int:
        inner = (
            f"source /opt/ros/humble/setup.bash && source {self.ros_ws_setup} && "
            f"ros2 service call {service} {srv_type} '{payload}' >/dev/null 2>&1"
        )
        return self._run(self._exec_prefix() + f'"{inner}"')

    def _ros2_topic_pub_velocity_move(self, vx: float, yaw: float) -> int:
        inner = (
            f"source /opt/ros/humble/setup.bash && source {self.ros_ws_setup} && "
            f"ros2 topic pub -1 /puppy_control/velocity_move puppy_control_msgs/msg/Velocity "
            f"'{{x: {vx}, y: 0.0, yaw_rate: {yaw}}}'"
        )
        return self._run(self._exec_prefix() + f'"{inner}"')


class MockAdapter:
    """Dry-run adapter for local development without robot hardware."""

    name = "mock"

    def stop(self) -> AdapterActionResult:
        print(f"[{now_iso()}] MOCK ACTION=STOP")
        return AdapterActionResult.ok([{"name": "mock_stop", "return_code": 0}])

    def trot(self) -> AdapterActionResult:
        print(f"[{now_iso()}] MOCK ACTION=TROT")
        return AdapterActionResult.ok([{"name": "mock_trot", "return_code": 0}])

    def home(self) -> AdapterActionResult:
        print(f"[{now_iso()}] MOCK ACTION=HOME")
        return AdapterActionResult.ok([{"name": "mock_home", "return_code": 0}])

    def move(self, vx: float, yaw: float, duration_ms: int) -> AdapterActionResult:
        print(f"[{now_iso()}] MOCK ACTION=MOVE vx={vx} yaw={yaw} duration_ms={duration_ms}")
        return AdapterActionResult.ok([{"name": "mock_move", "return_code": 0}])


def create_robot_adapter(name: str | None = None) -> RobotAdapter:
    adapter_name = (name or os.environ.get("ROBOT_ADAPTER", "puppypi")).strip().lower()

    if adapter_name in {"mock", "dry-run", "dry_run"}:
        return MockAdapter()
    if adapter_name == "puppypi":
        return PuppyPiAdapter()
    if adapter_name in {"puppypi_local", "puppypi-local"}:
        return PuppyPiLocalAdapter()

    raise ValueError(f"unsupported ROBOT_ADAPTER: {adapter_name}")
