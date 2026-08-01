# Robot Adapters

## Purpose

Robot adapters keep the OpenPAVE control daemon focused on intent handling while robot-specific command logic lives behind a small capability interface.

The current control flow is:

```text
normalized intent
-> control daemon dispatch
-> robot adapter
-> robot-specific ROS 2 command path
```

## Adapter Interface

Adapters are **capability-declarative**. An adapter declares which actions it supports and
executes any of them:

- `name: str`
- `capabilities: frozenset[str]` — the actions this adapter supports (e.g. `stop`, `estop`,
  `home`, `trot`, `move`, `grasp`, `move_joint`, `get_image`)
- `execute(action, params) -> AdapterActionResult`

The generic dispatch routes an action to the adapter **only if the adapter declares it**, so a
new robot class is a new adapter and nothing else changes (locomotion, manipulation, and sensing
all share this contract). The contract + helpers live in `pave_runtime/capability_schema.py`
(`{action, params}` normalization) and `control_daemon/adapters.py` (`CapabilityAdapter`).

**Legacy locomotion verbs** (`stop/trot/home/move`) are retained via `LocomotionCapabilityMixin`,
which exposes them as capabilities and maps the old `STOP/TROT/HOME/MOVE` intent — translated by
`intent_to_capability_action` — onto `execute`. So existing intent-schema-v0.1 payloads keep
working unchanged.

## Available Adapters

### PuppyPiAdapter

`PuppyPiAdapter` is the first physical target adapter. It preserves the existing PuppyPi behavior by issuing Dockerized ROS 2 CLI calls.

Relevant environment variables:

```bash
export ROBOT_ADAPTER=puppypi
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_SVC_IMAGE=ros:humble
export ROS_PUB_IMAGE=puppy-ros2-cli:humble
```

`ROS_PUB_IMAGE` must include `puppy_control_msgs` for publishing:

```text
/puppy_control/velocity_move
puppy_control_msgs/msg/Velocity
```

### MockAdapter

`MockAdapter` is a dry-run adapter for local development without robot hardware, Docker, or ROS 2 network access.

Use it with:

```bash
export ROBOT_ADAPTER=mock
python3 -m control_daemon.daemon
```

Aliases:

- `mock`
- `dry-run`
- `dry_run`

### PuppyPiLocalAdapter

`PuppyPiLocalAdapter` (`ROBOT_ADAPTER=puppypi_local`) is for a body node **co-located with
puppy_control on the robot**. Instead of `docker run`, it `docker exec`s into the running
puppy_control container (shared IPC namespace so FastDDS shared memory works), batches each
action into **one** exec running an rclpy gait runner, and escalates STOP to a hard-stop
(`pkill` the gait loop) if the graceful STOP times out.

### PuppyPiBridgeAdapter (experimental)

`PuppyPiBridgeAdapter` (`ROBOT_ADAPTER=puppypi_bridge`) is a **low-latency, experimental**
adapter: it tries a persistent body-side bridge (long-running ROS 2 service clients over a
localhost socket) and **falls back to the `puppypi_local` path automatically** (with a cooldown)
if the bridge is unavailable. STOP uses a short bridge timeout; results record `path`
(`bridge` / `fallback_a`) + latency. Real PuppyPi: HOME −66%, STOP p95 −89%. **Not the default** —
`puppypi_local` stays the validated path. See `experiments/persistent-bridge/`.

**Robot bring-up:** the bridge needs the PuppyPi on **ROS 2** first — the box boots into ROS 1, so
run `scripts/switch_puppypi_ros2.sh` on the robot to switch. See
[PuppyPi + DGX target → ROS 1 / ROS 2 switching](targets/puppypi-dgx.md#ros-1--ros-2-switching--boot-default-is-ros-1).

### MockArmAdapter

`MockArmAdapter` (`ROBOT_ADAPTER=mock_arm`) is a **manipulation-class** mock: it declares
`grasp / release / move_joint` (plus the common `stop/estop/home`) and logs each action. It
proves the capability model spans a different robot class over the same seam with only a new
adapter — no hardware.

### CameraSensorAdapter

`CameraSensorAdapter` (`ROBOT_ADAPTER=camera_mock` / `camera_usb`) is a **sensing-class** adapter
declaring `get_image`. `execute` returns small metadata (the control plane) and hands the JPEG to
the body node for a dedicated compressed-image topic (the data plane) — the control-plane /
data-plane split. `camera_mock` needs no hardware; `camera_usb` reads a real USB camera. See
`control_daemon/camera_adapter.py`.

## Command Construction and Trust Boundary

`PuppyPiAdapter` builds each ROS 2 call as a single shell string and runs it through
`subprocess.run(..., shell=True)` (see `default_runner` in `control_daemon/adapters.py`).
Intent parameters such as `vx` and `yaw` are interpolated directly into that string, for
example in `_ros2_topic_pub_velocity_move`:

```python
f"'{{x: {vx}, y: 0.0, yaw_rate: {yaw}}}'"
```

This is currently safe **only because of an upstream guarantee, not because of anything the
adapter does**. Before these values reach the adapter, `pave_runtime/intent_schema.py`
coerces them with `_as_float` (which rejects non-numbers, `inf`, and `nan`) and clamps them
with `_range` (`vx` in `[-0.5, 0.5]`, `yaw` in `[-1.0, 1.0]`). The daemon casts them to
`float` again before dispatch. As a result, only plain numeric strings are ever
interpolated, so no shell metacharacters (`;`, `$()`, quotes, `&&`, `|`, backticks) can
reach the command line.

The risk is not the current code; it is the **implicit trust boundary**. The command
assembly layer performs no sanitization of its own and simply assumes every interpolated
value has already been numeric-validated and range-checked. That assumption can silently
break when the code evolves, for example:

- a new **string-typed** field (`frame_id`, `label`, `mode`, …) is interpolated into a
  command the same way — a string can carry an injection payload
- a **new adapter or command path** builds its own `docker run ... ros2 ...` string but does
  not route its inputs through the same schema validation
- the **schema is relaxed** (a range check removed, or a field allowed to be an arbitrary
  string) to support a new command

Guidance for anyone extending an adapter:

- treat schema validation as an upstream convenience, **not** as the adapter's own defense
- never interpolate an unvalidated or string-typed field into a `shell=True` command
- for numeric fields, re-assert the type inside the adapter (`vx = float(vx)`) and/or format
  with an explicit numeric spec (`f"{vx:.6f}"`) so the output shape is guaranteed
- prefer an argument-list invocation (`subprocess.run([...])` without `shell=True`) over a
  shell string wherever the command structure allows it, so argv boundaries are decided by
  Python rather than parsed by the shell

## Adding a Future Adapter

Future robot adapters should:

- **declare `capabilities` and implement `execute(action, params)`** (or reuse
  `LocomotionCapabilityMixin` for a locomotion robot that speaks stop/trot/home/move)
- keep robot-specific services, topics, SDK calls, or transport details out of the daemon core
- accept configuration through environment variables or a future config file
- rely on the generic dispatch to return `unsupported` for actions not in `capabilities`
- include a mockable command path for tests
- follow the trust-boundary guidance above when building command strings: do not rely on
  schema validation alone to keep interpolated values shell-safe

PuppyPi remains the first working adapter, not the final hardware boundary.
