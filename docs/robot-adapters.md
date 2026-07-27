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

## Adding a Future Adapter

Future robot adapters should:

- implement `stop`, `trot`, `home`, and `move`
- keep robot-specific services, topics, SDK calls, or transport details out of the daemon core
- accept configuration through environment variables or a future config file
- preserve safe behavior for unsupported commands where possible
- include a mockable command path for tests

PuppyPi remains the first working adapter, not the final hardware boundary.
