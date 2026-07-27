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

The current adapter interface exposes four common capabilities:

- `stop()`
- `trot()`
- `home()`
- `move(vx, yaw, duration_ms)`

These match the current MVP intent set from intent schema v0.1:

- `STOP`
- `TROT`
- `HOME`
- `MOVE`

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

- implement `stop`, `trot`, `home`, and `move`
- keep robot-specific services, topics, SDK calls, or transport details out of the daemon core
- accept configuration through environment variables or a future config file
- preserve safe behavior for unsupported commands where possible
- include a mockable command path for tests
- follow the trust-boundary guidance above when building command strings: do not rely on
  schema validation alone to keep interpolated values shell-safe

PuppyPi remains the first working adapter, not the final hardware boundary.
