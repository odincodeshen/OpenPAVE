"""Robot adapters for the OpenPAVE control daemon."""

from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from pave_runtime.intent_schema import now_iso


CommandRunner = Callable[[str], int]
# (cmd, stdin_text) -> (return_code, stdout); used for the batched gait runner (opt A) which
# needs to feed a script over stdin and read its JSON result back.
CaptureRunner = Callable[[str, str], "tuple[int, str]"]


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


def default_capture_runner(cmd: str, stdin_text: str) -> "tuple[int, str]":
    proc = subprocess.run(cmd, shell=True, input=stdin_text, capture_output=True, text=True)
    return proc.returncode, proc.stdout


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

    # service/message types reused across the step lists below
    _SETBOOL = "std_srvs/srv/SetBool"
    _EMPTY = "std_srvs/srv/Empty"

    def __init__(
        self,
        config: RosCliConfig | None = None,
        runner: CommandRunner | None = None,
        capture_runner: CaptureRunner | None = None,
    ):
        super().__init__(config=config, runner=runner)
        # captures stdout (the gait runner's JSON result); default shells out, injectable in tests
        self.capture_runner = capture_runner or default_capture_runner
        self.exec_container = os.environ.get("PUPPY_EXEC_CONTAINER", "puppypi_ros2")
        self.exec_user = os.environ.get("PUPPY_EXEC_USER", "ubuntu")
        self.ros_ws_setup = os.environ.get(
            "PUPPY_ROS_WS_SETUP", "/home/ubuntu/ros2_ws/install/setup.bash"
        )
        # pause between set_running and set_mark_time so the robot starts running before it
        # marks time (marking time immediately — e.g. right after go_home/rest — can leave it
        # not visibly stepping). Set 0 to disable.
        self.trot_settle_sec = float(os.environ.get("PUPPY_TROT_SETTLE_SEC", "0.5"))
        # cap each service call so a hung call fails fast instead of blocking the body's
        # (synchronous) on_intent forever. Note: a timed-out STOP does NOT stop the robot —
        # see the STOP-while-moving safety note in experiments/zenoh-mve/puppypi_test.md.
        self.call_timeout_sec = float(os.environ.get("PUPPY_CALL_TIMEOUT_SEC", "10"))
        # shorter timeout for the motion-stopping STOP calls so escalation to the hard-stop is
        # fast when the gait loop is starving the service callback.
        self.stop_timeout_sec = float(os.environ.get("PUPPY_STOP_TIMEOUT_SEC", "3"))
        self._runner_path = Path(__file__).resolve().parent / "puppy_gait_runner.py"

    # ---- batched gait runner (opt A) --------------------------------------------------------
    # One action = one ``docker exec`` running the rclpy gait runner ONCE (one node, service
    # clients reused across the steps), instead of one exec + one ros2 CLI per call. That pays
    # ``source`` + node startup + service discovery once per action rather than per call.
    def _run_gait(
        self, steps: list[dict], node_timeout: float | None = None
    ) -> "tuple[int, list[dict]]":
        payload = base64.b64encode(json.dumps({"steps": steps}).encode()).decode()
        # each step carries its own service timeout; the outer `timeout` is a backstop for a
        # wedged runner, so give it slack over the longest step.
        backstop = (node_timeout or self.call_timeout_sec) + 2
        inner = (
            f"source /opt/ros/humble/setup.bash && source {self.ros_ws_setup} && "
            f"timeout {backstop} python3 - {payload}"
        )
        cmd = (
            f"docker exec -i -u {self.exec_user} "
            f"-e ROS_DOMAIN_ID={self.config.ros_domain_id} "
            f"-e RMW_IMPLEMENTATION={self.config.rmw_implementation} "
            f"{self.exec_container} bash -lc {shlex.quote(inner)}"
        )
        rc, out = self.capture_runner(cmd, self._runner_path.read_text())
        parsed: list[dict] = []
        for line in reversed((out or "").strip().splitlines()):
            try:
                parsed = json.loads(line).get("steps", [])
                break
            except (json.JSONDecodeError, AttributeError):
                continue
        steps_out = [
            {"name": r.get("name", "step"), "return_code": r.get("rc", 1)} for r in parsed
        ]
        if not steps_out:  # no parseable result -> synthesize a failure carrying the exec rc
            steps_out = [{"name": "gait_runner", "return_code": rc or 1}]
        return rc, steps_out

    def _svc(self, service: str, srv_type: str, data: dict, timeout: float) -> dict:
        return {"op": "service", "service": service, "type": srv_type,
                "data": data, "timeout": timeout}

    def trot(self) -> AdapterActionResult:
        # set_running, then settle, then set_mark_time — all in one exec.
        print(f"[{now_iso()}] ACTION=TROT adapter={self.name}")
        _, steps = self._run_gait([
            self._svc("/puppy_control/set_running", self._SETBOOL, {"data": True}, self.call_timeout_sec),
            {"op": "sleep", "sec": self.trot_settle_sec},
            self._svc("/puppy_control/set_mark_time", self._SETBOOL, {"data": True}, self.call_timeout_sec),
        ])
        return self._result(steps)

    def home(self) -> AdapterActionResult:
        print(f"[{now_iso()}] ACTION=HOME adapter={self.name}")
        _, steps = self._run_gait([
            self._svc("/puppy_control/go_home", self._EMPTY, {}, self.call_timeout_sec),
        ])
        return self._result(steps)

    def move(self, vx: float, yaw: float, duration_ms: int) -> AdapterActionResult:
        print(f"[{now_iso()}] ACTION=MOVE adapter={self.name} vx={vx} yaw={yaw} duration_ms={duration_ms}")
        _, steps = self._run_gait([
            self._svc("/puppy_control/go_home", self._EMPTY, {}, self.call_timeout_sec),
            self._svc("/puppy_control/set_mark_time", self._SETBOOL, {"data": False}, self.call_timeout_sec),
            self._svc("/puppy_control/set_running", self._SETBOOL, {"data": True}, self.call_timeout_sec),
            {"op": "sleep", "sec": 0.3},
            {"op": "velocity", "x": vx, "y": 0.0, "yaw_rate": yaw},
        ])
        return self._result(steps)

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
        # motion-stop first (both calls in one exec). If it doesn't succeed the robot is likely
        # still moving (the gait loop starved the service callback) -> escalate to the guaranteed
        # hard-stop, and skip the graceful go_home.
        _, motion = self._run_gait(
            [
                self._svc("/puppy_control/set_mark_time", self._SETBOOL, {"data": False}, self.stop_timeout_sec),
                self._svc("/puppy_control/set_running", self._SETBOOL, {"data": False}, self.stop_timeout_sec),
            ],
            node_timeout=self.stop_timeout_sec,
        )
        if any(step["return_code"] != 0 for step in motion):
            print(f"[{now_iso()}] WARN: STOP motion-stop calls failed -> hard-stop (kill gait)")
            hard = self._step("hard_stop:kill_gait", self._hard_stop())
            steps = motion + [hard]
            if hard["return_code"] == 0:
                return AdapterActionResult.ok(steps)  # robot stopped despite the failed STOP
            return AdapterActionResult.failed("hard-stop failed", steps)

        _, home = self._run_gait(
            [self._svc("/puppy_control/go_home", self._EMPTY, {}, self.call_timeout_sec)]
        )
        return self._result(motion + home)


class PuppyPiBridgeAdapter(PuppyPiLocalAdapter):
    """B2: PuppyPi over the persistent bridge, with automatic fallback to A (docker exec).

    Overrides only ``_run_gait``: try the bridge (socket + already-connected call()); on any bridge
    error, fall back to ``PuppyPiLocalAdapter``'s docker-exec runner (A) and enter a cooldown so we
    stop paying the bridge timeout for a while. ``stop/trot/home/move`` and the hard-stop
    escalation in ``stop()`` are inherited **unchanged** — so bridge and fallback go through the
    same actions, and hard-stop stays independent of the bridge.

    Experimental (``ROBOT_ADAPTER=puppypi_bridge``), **not a default**; the validated path is
    ``puppypi_local``. Env:
    - ``PUPPY_BRIDGE_SOCKET`` (unix path) OR ``PUPPY_BRIDGE_HOST`` / ``PUPPY_BRIDGE_PORT`` (tcp,
      default 127.0.0.1:8787) — picked per the socket-namespace decision.
    - ``PUPPY_BRIDGE_RETRY_SEC`` (cooldown after a failure, default 10)
    - ``PUPPY_BRIDGE_CALL_TIMEOUT_SEC`` (default 5) / ``PUPPY_BRIDGE_STOP_TIMEOUT_SEC`` (short,
      default 1 — STOP must not wait long on the bridge before falling back)
    - ``PUPPY_BRIDGE_PING_TIMEOUT_SEC`` (default 2)
    """

    name = "puppypi_bridge"

    def __init__(self, config=None, runner=None, capture_runner=None, bridge_client=None):
        super().__init__(config=config, runner=runner, capture_runner=capture_runner)
        self._client_obj = bridge_client  # injectable for tests
        self.retry_sec = float(os.environ.get("PUPPY_BRIDGE_RETRY_SEC", "10"))
        self.bridge_call_timeout = float(os.environ.get("PUPPY_BRIDGE_CALL_TIMEOUT_SEC", "5"))
        self.bridge_stop_timeout = float(os.environ.get("PUPPY_BRIDGE_STOP_TIMEOUT_SEC", "1"))
        self.bridge_ping_timeout = float(os.environ.get("PUPPY_BRIDGE_PING_TIMEOUT_SEC", "2"))
        self._bridge_ready: bool | None = None  # None=unprobed, True=usable, False=down/cooldown
        self._cooldown_until = 0.0
        self._last_reason = "bridge_unavailable"
        self._path_log: list[dict] = []

    def _client(self):
        if self._client_obj is None:
            from control_daemon.bridge_client import BridgeClient
            self._client_obj = BridgeClient(self._bridge_endpoint())
        return self._client_obj

    def _bridge_endpoint(self) -> tuple:
        sock = os.environ.get("PUPPY_BRIDGE_SOCKET")
        if sock:
            return ("unix", sock)
        return ("tcp", os.environ.get("PUPPY_BRIDGE_HOST", "127.0.0.1"),
                int(os.environ.get("PUPPY_BRIDGE_PORT", "8787")))

    # ---- readiness gate + cooldown (design §3.3) ----
    def _bridge_usable(self) -> bool:
        if time.monotonic() < self._cooldown_until:
            return False
        if self._bridge_ready:
            return True
        # probe (first use / after cooldown): usable only if ready AND services_ready (review #4)
        try:
            ready, detail = self._client().ping(timeout=self.bridge_ping_timeout)
        except (ConnectionError, OSError):
            self._bridge_down("bridge_unavailable")
            return False
        if ready and detail.get("services_ready"):
            self._bridge_ready = True
            return True
        self._bridge_down("bridge_not_ready")
        return False

    def _bridge_down(self, reason: str) -> None:
        self._bridge_ready = False
        self._cooldown_until = time.monotonic() + self.retry_sec
        self._last_reason = reason
        print(f"[{now_iso()}] bridge unavailable ({reason}) -> fallback A, cooldown {self.retry_sec}s")

    # ---- the one override: try bridge, else fall back to A ----
    def _run_gait(self, steps, node_timeout=None):
        is_stop = node_timeout is not None  # stop() passes its short stop_timeout_sec
        if self._bridge_usable():
            timeout = self.bridge_stop_timeout if is_stop else self.bridge_call_timeout
            t0 = time.perf_counter()
            try:
                from control_daemon.bridge_client import BridgeError
                ok, out = self._client().run_steps(steps, timeout=timeout)
                steps_out = [{"name": r.get("name", "step"), "return_code": r.get("rc", 1)} for r in out]
                self._path_log.append({"path": "bridge", "latency_ms": (time.perf_counter() - t0) * 1000})
                return (0 if ok else 1), steps_out
            except BridgeError as exc:
                self._bridge_down(exc.code or "bridge_error")
            except (ConnectionError, OSError):
                self._bridge_down("bridge_error")
        t0 = time.perf_counter()
        rc, out = super()._run_gait(steps, node_timeout)  # A path (docker exec runner)
        self._path_log.append({"path": "fallback_a", "latency_ms": (time.perf_counter() - t0) * 1000,
                               "reason": self._last_reason})
        return rc, out

    # ---- record which path each action used (review #3) ----
    def execute(self, action: str, params: "dict | None" = None) -> AdapterActionResult:
        self._path_log = []
        result = super().execute(action, params)
        if self._path_log:
            used_fallback = any(p["path"] == "fallback_a" for p in self._path_log)
            result.detail["path"] = "fallback_a" if used_fallback else "bridge"
            result.detail["latency_ms"] = round(sum(p["latency_ms"] for p in self._path_log), 1)
            if used_fallback:
                reasons = [p.get("reason") for p in self._path_log if p["path"] == "fallback_a"]
                result.detail["fallback_reason"] = next((r for r in reasons if r), "bridge_unavailable")
        return result


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
    if adapter_name in {"puppypi_bridge", "puppypi-bridge"}:
        return PuppyPiBridgeAdapter()  # experimental (B2): bridge with fallback to puppypi_local
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
