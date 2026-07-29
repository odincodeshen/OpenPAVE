"""Robot adapters for the OpenPAVE control daemon."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from pave_runtime.intent_schema import now_iso


CommandRunner = Callable[[str], int]


@dataclass(frozen=True)
class AdapterActionResult:
    success: bool
    steps: list[dict[str, object]]
    error: str | None = None
    # optional payload for capabilities that *return data* rather than act (e.g. a sensor's
    # frame metadata). Actuators leave it empty; the control/data-plane split keeps large
    # payloads (an image) out of here — see CameraSensorAdapter.
    detail: dict[str, object] = field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        steps: list[dict[str, object]] | None = None,
        detail: dict[str, object] | None = None,
    ) -> "AdapterActionResult":
        return cls(success=True, steps=steps or [], detail=detail or {})

    @classmethod
    def failed(
        cls,
        error: str,
        steps: list[dict[str, object]] | None = None,
        detail: dict[str, object] | None = None,
    ) -> "AdapterActionResult":
        return cls(success=False, steps=steps or [], error=error, detail=detail or {})


@runtime_checkable
class CapabilityAdapter(Protocol):
    """Capability-declarative robot interface — the canonical contract.

    An adapter declares which actions it supports (``capabilities``) and executes any of them
    (``execute``). The generic dispatch routes an action to the adapter only if the adapter
    declares it, so a new robot class is a new adapter and nothing else changes.
    """

    name: str
    capabilities: frozenset[str]

    def execute(self, action: str, params: dict[str, Any]) -> AdapterActionResult:
        """Run one declared action with its params."""


class RobotAdapter(Protocol):
    """Legacy locomotion interface (stop/trot/home/move).

    Retained for the locomotion adapters and their tests; the capability layer
    (``LocomotionCapabilityMixin``) exposes these verbs as a ``CapabilityAdapter``.
    """

    name: str

    def stop(self) -> AdapterActionResult:
        """Stop robot motion and return to a safe posture when supported."""

    def trot(self) -> AdapterActionResult:
        """Start the adapter's trot or mark-time behavior."""

    def home(self) -> AdapterActionResult:
        """Return the robot to its home posture."""

    def move(self, vx: float, yaw: float, duration_ms: int) -> AdapterActionResult:
        """Run a short velocity-style movement command."""


class LocomotionCapabilityMixin:
    """Capability layer over the locomotion verbs (stop/trot/home/move).

    Exposes the capability-declarative interface (``capabilities`` + ``execute``) on top of a
    class's ``stop()/trot()/home()/move()`` methods, so a locomotion robot is just another
    ``CapabilityAdapter`` — the transport and generic dispatch stay robot-agnostic. ``estop``
    maps to ``stop`` (which, on ``PuppyPiLocalAdapter``, escalates to a hard-stop when the
    graceful stop times out).
    """

    # common safe verbs + locomotion class-specific verbs
    capabilities = frozenset({"stop", "estop", "home", "trot", "move"})

    def execute(self, action: str, params: dict[str, Any] | None = None) -> AdapterActionResult:
        params = params or {}
        if action in ("stop", "estop"):
            return self.stop()
        if action == "home":
            return self.home()
        if action == "trot":
            return self.trot()
        if action == "move":
            return self.move(
                vx=float(params.get("vx", 0.0)),
                yaw=float(params.get("yaw", 0.0)),
                duration_ms=int(params.get("duration_ms", 500)),
            )
        # generic dispatch checks capabilities first, so this is defensive only
        return AdapterActionResult.failed(f"unsupported action: {action}")


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


class PuppyPiAdapter(LocomotionCapabilityMixin):
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
        # pause between set_running and set_mark_time so the robot starts running before it
        # marks time (marking time immediately — e.g. right after go_home/rest — can leave it
        # not visibly stepping). Set 0 to disable.
        self.trot_settle_sec = float(os.environ.get("PUPPY_TROT_SETTLE_SEC", "0.5"))
        # cap each ros2 CLI call so a hung call fails fast instead of blocking the body's
        # (synchronous) on_intent forever. Note: a timed-out STOP does NOT stop the robot —
        # see the STOP-while-moving safety note in experiments/zenoh-mve/puppypi_test.md.
        self.call_timeout_sec = float(os.environ.get("PUPPY_CALL_TIMEOUT_SEC", "10"))
        # shorter timeout for the motion-stopping STOP calls so escalation to the hard-stop is
        # fast when the gait loop is starving the service callback.
        self.stop_timeout_sec = float(os.environ.get("PUPPY_STOP_TIMEOUT_SEC", "3"))

    def _exec_prefix(self) -> str:
        return (
            f"docker exec -u {self.exec_user} "
            f"-e ROS_DOMAIN_ID={self.config.ros_domain_id} "
            f"-e RMW_IMPLEMENTATION={self.config.rmw_implementation} "
            f"{self.exec_container} bash -lc "
        )

    def _ros2_service_call(
        self, service: str, srv_type: str, payload: str, timeout_sec: float | None = None
    ) -> int:
        t = self.call_timeout_sec if timeout_sec is None else timeout_sec
        inner = (
            f"source /opt/ros/humble/setup.bash && source {self.ros_ws_setup} && "
            f"timeout {t} "
            f"ros2 service call {service} {srv_type} '{payload}' >/dev/null 2>&1"
        )
        return self._run(self._exec_prefix() + f'"{inner}"')

    def _ros2_topic_pub_velocity_move(self, vx: float, yaw: float) -> int:
        inner = (
            f"source /opt/ros/humble/setup.bash && source {self.ros_ws_setup} && "
            f"timeout {self.call_timeout_sec} "
            f"ros2 topic pub -1 /puppy_control/velocity_move puppy_control_msgs/msg/Velocity "
            f"'{{x: {vx}, y: 0.0, yaw_rate: {yaw}}}'"
        )
        return self._run(self._exec_prefix() + f'"{inner}"')

    def trot(self) -> AdapterActionResult:
        # Like PuppyPiAdapter.trot, but pause between set_running and set_mark_time so the robot
        # starts running before it marks time (marking time immediately after go_home/rest can
        # leave it not visibly stepping).
        print(f"[{now_iso()}] ACTION=TROT adapter={self.name}")
        running = self._step(
            "set_running:true",
            self._ros2_service_call("/puppy_control/set_running", "std_srvs/srv/SetBool", "{data: true}"),
        )
        time.sleep(self.trot_settle_sec)
        mark = self._step(
            "set_mark_time:true",
            self._ros2_service_call("/puppy_control/set_mark_time", "std_srvs/srv/SetBool", "{data: true}"),
        )
        return self._result([running, mark])

    def _hard_stop(self) -> int:
        # Guaranteed stop: kill the gait loop directly. Needed because puppy_control's service
        # callbacks are starved while it is running, so set_mark_time:false / set_running:false
        # can hang exactly when the robot is moving. Recovery: relaunch puppy_control afterwards.
        cmd = (
            f"docker exec {self.exec_container} bash -lc "
            f"\"pkill -9 -f 'puppy_control/lib/puppy_control/puppy_control'\""
        )
        return self._run(cmd)

    def stop(self) -> AdapterActionResult:
        print(f"[{now_iso()}] ACTION=STOP adapter={self.name}")
        mark = self._step(
            "set_mark_time:false",
            self._ros2_service_call(
                "/puppy_control/set_mark_time", "std_srvs/srv/SetBool", "{data: false}",
                timeout_sec=self.stop_timeout_sec,
            ),
        )
        running = self._step(
            "set_running:false",
            self._ros2_service_call(
                "/puppy_control/set_running", "std_srvs/srv/SetBool", "{data: false}",
                timeout_sec=self.stop_timeout_sec,
            ),
        )
        # If the motion-stopping calls didn't succeed the robot is likely still moving (the gait
        # loop starved the service callback) -> escalate to the guaranteed hard-stop.
        if mark["return_code"] != 0 or running["return_code"] != 0:
            print(
                f"[{now_iso()}] WARN: STOP service calls failed "
                f"(rc={mark['return_code']}/{running['return_code']}) -> hard-stop (kill gait)"
            )
            hard = self._step("hard_stop:kill_gait", self._hard_stop())
            steps = [mark, running, hard]
            if hard["return_code"] == 0:
                return AdapterActionResult.ok(steps)  # robot stopped despite the failed STOP
            return AdapterActionResult.failed("hard-stop failed", steps)

        home = self._step(
            "go_home",
            self._ros2_service_call("/puppy_control/go_home", "std_srvs/srv/Empty", "{}"),
        )
        time.sleep(0.3)
        return self._result([mark, running, home])


class MockAdapter(LocomotionCapabilityMixin):
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


class MockArmAdapter:
    """Manipulation-class mock adapter (graduated from experiments/capability-mve).

    Proves the capability model spans a *different robot class* (an arm) over the same seam and
    dispatch with only a new adapter + capability set. It declares manipulation capabilities
    (not locomotion) and logs each action; no hardware. Swap for a real arm adapter later — the
    transport and dispatch do not change.
    """

    name = "mock_arm"
    # manipulation capabilities + the common safe verbs (stop/estop/home)
    capabilities = frozenset({"estop", "stop", "home", "grasp", "release", "move_joint"})
    # per-capability required params (the adapter's own contract; absent = no params required)
    _required: dict[str, tuple[str, ...]] = {"move_joint": ("joint", "position")}

    def execute(self, action: str, params: dict[str, Any] | None = None) -> AdapterActionResult:
        params = params or {}
        missing = [k for k in self._required.get(action, ()) if k not in params]
        if missing:
            return AdapterActionResult.failed(
                f"'{action}' requires params {missing}", detail={"action": action}
            )
        print(f"[{now_iso()}] [mock_arm] {action} params={params}")
        return AdapterActionResult.ok(detail={"action": action, "params": params})


def create_robot_adapter(name: str | None = None) -> CapabilityAdapter:
    adapter_name = (name or os.environ.get("ROBOT_ADAPTER", "puppypi")).strip().lower()

    if adapter_name in {"mock", "dry-run", "dry_run"}:
        return MockAdapter()
    if adapter_name == "puppypi":
        return PuppyPiAdapter()
    if adapter_name in {"puppypi_local", "puppypi-local"}:
        return PuppyPiLocalAdapter()
    if adapter_name in {"mock_arm", "mock-arm"}:
        return MockArmAdapter()
    # camera adapters are lazy-imported: control_daemon.camera_adapter pulls in OpenCV only when
    # a frame is actually grabbed, and this keeps adapters.py free of that dependency at import.
    if adapter_name in {"camera_mock", "camera-mock", "camera"}:
        from control_daemon.camera_adapter import CameraSensorAdapter, MockCameraSource

        return CameraSensorAdapter(MockCameraSource(), name="camera_mock")
    if adapter_name in {"camera_usb", "camera-usb"}:
        from control_daemon.camera_adapter import CameraSensorAdapter, UsbCameraSource

        device = os.environ.get("CAMERA_DEVICE", "/dev/video0")
        return CameraSensorAdapter(UsbCameraSource(device), name="camera_usb")

    raise ValueError(f"unsupported ROBOT_ADAPTER: {adapter_name}")
