# PuppyPi + DGX Target

PuppyPi + DGX is the first validated OpenPAVE target. It demonstrates the current local brain-body Physical AI workflow:

```text
PuppyPi ROS 2 endpoint
-> DGX local inference/control node
-> OpenPAVE intent runtime
-> PuppyPiAdapter
-> Dockerized ROS 2 CLI
-> robot action and feedback
```

This target validates the OpenPAVE workflow. It is not the project boundary.

The brain side here is DGX, the first validated representative of the Armv9 brain-side platform family. Target documents for other Armv9 brain-side platforms (such as Thor) will reuse this same template.

## Target Roles

### Body Side

- Hardware: PuppyPi
- Robot-side runtime: ROS 2 Humble controller container
- Control package: `puppy_control`
- Custom message package: `puppy_control_msgs`
- Current supported commands: `STOP`, `TROT`, `HOME`, `MOVE`

### Brain Side

- Hardware: DGX/control machine (Armv9 Grace CPU + Nvidia GPU)
- Inference backend: vLLM or another OpenAI-compatible VLM API
- UI/runtime: OpenPAVE `/pave` console through the `ui/` submodule
- Runtime services: Intent Ingress, Control Daemon, Robot Adapter, benchmark harness

## Runtime Profile

Use:

```text
configs/puppypi.env
```

The profile configures:

```text
ROBOT_ADAPTER=puppypi
ROBOT_IP_ADDRESS=192.168.0.8
ROS_DOMAIN_ID=0
RMW_IMPLEMENTATION=rmw_fastrtps_cpp
ROS_SVC_IMAGE=ros:humble
ROS_PUB_IMAGE=puppy-ros2-cli:humble
```

Override values from the shell when your robot IP, Docker image tags, or ROS 2 settings differ:

```bash
OPENPAVE_CONFIG=configs/puppypi.env \
ROBOT_IP_ADDRESS=<PUPPYPI_IP> \
./scripts/run_stage3_demo.sh
```

## ROS 2 CLI Images

The PuppyPi adapter uses Dockerized ROS 2 CLI calls:

```text
ROS_SVC_IMAGE=ros:humble
ROS_PUB_IMAGE=puppy-ros2-cli:humble
```

`ros:humble` is used for standard ROS 2 service calls.

`puppy-ros2-cli:humble` includes `puppy_control_msgs/msg/Velocity` and is required for PuppyPi custom message publishing.

Build it with:

```bash
./scripts/build_puppy_ros2_cli.sh
```

Verify:

```bash
docker run -it --rm puppy-ros2-cli:humble bash -lc \
"source /opt/ros/humble/setup.bash && source /ws/install/setup.bash && ros2 interface show puppy_control_msgs/msg/Velocity"
```

## Robot-Side Controller

Start the PuppyPi ROS 2 controller on the robot side:

```bash
docker start puppypi_ros2
docker exec -it -u ubuntu -w /home/ubuntu puppypi_ros2 /bin/bash
```

Inside the container:

```bash
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

source /opt/ros/humble/setup.bash
source /home/ubuntu/ros2_ws/install/setup.bash

ros2 launch puppy_control puppy_control.launch.py
```

Or use the helper (run it on the PuppyPi — starts the container, launches `puppy_control`
detached, and verifies it responds):

```bash
./scripts/start_puppy_control.sh
```

### ROS 1 / ROS 2 switching — boot default is ROS 1

The PuppyPi **boots into ROS 1** (noetic `puppy_control`, `puppypi` container, auto-start).
Its **ROS 2** controller (`puppypi_ros2`, humble) is **not** started at boot. Both drive the
same servo board over one serial bus, so **only one can run at a time** — using ROS 2 first
requires stopping ROS 1.

OpenPAVE's control plane (rmw_zenoh, the `puppypi_bridge` rclpy bridge) targets **ROS 2**, so
switch the robot to ROS 2 before an OpenPAVE run. One command does the whole bring-up:

```bash
./scripts/switch_puppypi_ros2.sh
```

It runs the validated bring-up: stop ROS 1 (`puppypi`, frees the serial bus) → stop the
hiwonder `test` stack (frees the bridge's `:8787` and de-noises DDS domain 0) → start ROS 2
`puppy_control` (`start_puppy_control.sh`) → start the OpenPAVE bridge inside `puppypi_ros2`
→ health-ping it. **The dog stands up when the controller takes over — place it safely first.**

**Go back to ROS 1**: reboot (boot default is ROS 1), or
`docker stop puppypi_ros2 && docker start puppypi`.

Why "boot ROS 1, switch on demand" (option 乙): keep the box's out-of-the-box ROS 1 demos
(e.g. the joystick node) working by default, while OpenPAVE runs on the still-supported ROS 2
line (noetic is EOL 2025-05) — without deleting either stack. Validated 2026-08-01: over this
ROS 2 path the neutral seam drove `HOME` / `STOP` / `trot` / `move` / `estop` on the real
robot, `path=bridge`, gait steps unchanged. The earlier failure was only the bridge running in
the wrong container (`test`); the fix is starting it in `puppypi_ros2` (this script does that).

## Physical Safety

For physical robot runs:

- Start with `STOP` validation.
- Keep the robot in a safe test area.
- Use `TROT` only after confirming ROS 2 discovery, service calls, and adapter logs.
- Keep `TROT_CONFIRMATIONS=2` unless intentionally debugging.
- The launcher sends a final `STOP` intent on shutdown when `ROBOT_ADAPTER=puppypi`.

## Known ROS 2 DDS / RMW Issue

The current default validated PuppyPi setup uses Fast DDS:

```text
RMW_IMPLEMENTATION=rmw_fastrtps_cpp
ros-humble-rmw-fastrtps-cpp=6.2.10-1jammy.20260416.070458
ros-humble-rmw-cyclonedds-cpp=not installed
```

The current `puppy-ros2-cli:humble` image used for validation was created on:

```text
2026-05-15T21:49:12.448386125Z
```

Some environments may require a different ROS 2 RMW implementation, such as `rmw_cyclonedds_cpp`, for reliable discovery or service calls. Treat this as an environment-specific workaround until validated as a default path.

Before changing OpenPAVE code, verify:

- both sides use the same `ROS_DOMAIN_ID`
- both sides use the same `RMW_IMPLEMENTATION`
- the selected RMW package is installed in every ROS 2 environment involved in the command path
- the robot-side controller process references the intended Docker image
- `ROS_SVC_IMAGE` and `ROS_PUB_IMAGE` point to the intended images

## Current Limitations

- The **default** adapter uses one-shot Dockerized ROS 2 CLI calls — reproducible and inspectable. An experimental low-latency path is now implemented and real-robot validated (`ROBOT_ADAPTER=puppypi_bridge`, a persistent body-side bridge with automatic fallback to the CLI path; HOME −66%, STOP p95 −89%), but it is not yet the default. See `experiments/persistent-bridge/`.
- ROS 2 over Wi-Fi is a baseline communication path, not the final optimized brain-body transport design (a zenoh MVE has been explored; a neutral non-ROS seam is planned).
