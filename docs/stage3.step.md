# OpenPAVE Stage 3 Release Validation Guide

This guide is the primary release validation runbook for the current OpenPAVE Stage 3 runtime.

Stage 3 does not replace the distributed OpenPAVE architecture. It provides one command that starts the local developer-facing runtime processes from Stage 1 and Stage 2, plus the Stage 3 prompt/scenario and benchmark validation workflow.

Use this document as the source of truth for reproducing the current release on a DGX/control machine and, optionally, a physical PuppyPi ROS 2 endpoint.

## Release Scope

This release validates:

- repo-level Python environment setup
- `ui/` submodule installation for the OpenPAVE `/pave` console
- local vLLM/OpenAI-compatible VLM backend connectivity
- Stage 3 launcher startup and shutdown behavior
- mock adapter control-path benchmark
- PuppyPi adapter validation through Dockerized ROS 2 CLI calls
- runtime feedback files for command result and robot state

This release does not package vLLM, the robot-side ROS 2 controller, or the robot/sensor stream source. Those remain external dependencies.

## Managed Services

The launcher starts and supervises:

- Intent Ingress
- Control Daemon
- OpenPAVE UI server / `live-vlm-webui`

The launcher writes logs to:

```text
.openpave/logs/
```

## External Dependencies

These are still external dependencies in Stage 3:

- robot-side ROS 2 controller
- robot/sensor stream source
- vLLM or another OpenAI-compatible VLM backend
- Docker images used by `PuppyPiAdapter`, such as `ros:humble` and `puppy-ros2-cli:humble`

This keeps Stage 3 focused on developer runtime orchestration without hiding hardware or inference setup problems.

## Install live-vlm-webui Observability UI

The Stage 3 launcher starts the OpenPAVE console through the `ui/` submodule, which points to the OpenPAVE-maintained `live-vlm-webui` fork.

After cloning or pulling OpenPAVE, initialize the submodule and install it into the repo-level virtual environment:

```bash
cd /path/to/OpenPAVE

git submodule update --init --recursive

python3 -m venv .venv
source .venv/bin/activate

python3 -m pip install -U pip
python3 -m pip install -r intent_ingress/requirements.txt
python3 -m pip install -e ui
```

Confirm the installed module resolves to the checked-out submodule:

```bash
python3 -c "import live_vlm_webui.server as s; print(s.__file__)"
```

Expected path:

```text
/path/to/OpenPAVE/ui/src/live_vlm_webui/server.py
```

Confirm the OpenPAVE console route and text-inference endpoint exist in the submodule checkout:

```bash
grep -n 'app.router.add_get("/pave"' ui/src/live_vlm_webui/server.py
grep -n 'app.router.add_post("/api/pave/infer"' ui/src/live_vlm_webui/server.py
```

If `/` works but `/pave` returns `404`, update the submodule and reinstall the editable package:

```bash
git submodule update --init --recursive
python3 -m pip install -e ui
```

## Build the Custom ROS 2 CLI Docker Image

The PuppyPi adapter uses two ROS 2 CLI Docker images:

```text
ROS_SVC_IMAGE=ros:humble
ROS_PUB_IMAGE=puppy-ros2-cli:humble
```

`ros:humble` is enough for standard ROS 2 service calls such as `SetBool` and `Empty`.

`puppy-ros2-cli:humble` is required for PuppyPi custom message publishing, including:

```text
puppy_control_msgs/msg/Velocity
```

Build the custom image on the DGX/control machine before running physical PuppyPi `MOVE` validation or any scenario that publishes PuppyPi custom messages:

```bash
cd /path/to/OpenPAVE

./scripts/build_puppy_ros2_cli.sh
```

The script expects this repo path to exist:

```text
third_party/puppy_control_msgs
```

It builds and verifies:

```text
puppy-ros2-cli:humble
```

You can verify the image manually:

```bash
docker run -it --rm puppy-ros2-cli:humble bash -lc \
"source /opt/ros/humble/setup.bash && source /ws/install/setup.bash && ros2 interface show puppy_control_msgs/msg/Velocity"
```

This custom image is not required for `ROBOT_ADAPTER=mock`.

For PuppyPi `STOP`, `TROT`, and `HOME`, the adapter primarily uses `ros:humble` service calls. For PuppyPi `MOVE`, the adapter uses `ROS_PUB_IMAGE`, which defaults to `puppy-ros2-cli:humble`.

### Refresh ROS 2 Docker Images

Before validating a physical robot release, refresh the base ROS 2 image on the DGX/control machine. This avoids debugging against stale ROS 2 packages when the robot-side controller image has already been updated.

```bash
docker pull ros:humble

docker run -it --rm ros:humble bash -lc \
"apt-get update && apt-get -y upgrade && apt-cache policy ros-humble-rmw-fastrtps-cpp"
```

If you maintain a locally versioned ROS 2 CLI image, tag it explicitly and pass the matching image names to OpenPAVE:

```bash
IMAGE_TAG=puppy-ros2-cli:humble-<release-id> ./scripts/build_puppy_ros2_cli.sh

export ROS_SVC_IMAGE=ros:humble
export ROS_PUB_IMAGE=puppy-ros2-cli:humble-<release-id>
```

Make sure the robot-side controller process also references the current local image names if you rebuilt or retagged its containers.

## ROS 2 Middleware Selection

All ROS 2 participants in the physical validation path must use the same domain and the same validated middleware:

```text
ROS_DOMAIN_ID=<same value on DGX/control side and robot side>
RMW_IMPLEMENTATION=<same RMW on DGX/control side and robot side>
```

The default OpenPAVE profile uses:

```text
ROS_DOMAIN_ID=0
RMW_IMPLEMENTATION=rmw_fastrtps_cpp
```

Do not mix middleware settings between the robot-side controller container and the DGX/control-side ROS 2 CLI containers. If you validate a different RMW implementation for your environment, update the robot-side container, the DGX/control-side Docker images, and `configs/puppypi.env` together.

### Known ROS 2 DDS / RMW Issues

The current default validated PuppyPi setup uses Fast DDS:

```text
RMW_IMPLEMENTATION=rmw_fastrtps_cpp
ros-humble-rmw-fastrtps-cpp=6.2.10-1jammy.20260416.070458
ros-humble-rmw-cyclonedds-cpp=not installed
```

This was validated with the `puppy-ros2-cli:humble` image created on:

```text
2026-05-15T21:49:12.448386125Z
```

Some environments may still require a different ROS 2 RMW implementation, such as `rmw_cyclonedds_cpp`, to achieve reliable discovery or service calls. This can happen when LAN multicast behavior, Docker host networking, firewall rules, ROS 2 package versions, or robot-side controller image tags differ between machines.

If Fast DDS discovery or service calls are unreliable, check the environment before changing OpenPAVE code:

```bash
docker image inspect puppy-ros2-cli:humble \
  --format 'image={{.RepoTags}} id={{.Id}} created={{.Created}}'

docker run --rm puppy-ros2-cli:humble bash -lc \
"source /opt/ros/humble/setup.bash && \
 apt-cache policy ros-humble-rmw-fastrtps-cpp ros-humble-rmw-cyclonedds-cpp || true"
```

On the robot-side controller machine, confirm the running container and image:

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'

docker inspect <controller-container-name> \
  --format 'name={{.Name}} image={{.Config.Image}} id={{.Image}} created={{.Created}}'
```

Then confirm both sides use the same ROS 2 settings:

```bash
echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-unset}"
echo "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-unset}"
```

Only test an alternative RMW after confirming:

- both sides use the same `ROS_DOMAIN_ID`
- both sides use the same `RMW_IMPLEMENTATION`
- the selected RMW package is installed in every ROS 2 environment involved in the command path
- the robot-side controller process references the intended, current Docker image
- the DGX/control-side `ROS_SVC_IMAGE` and `ROS_PUB_IMAGE` point to the intended images

CycloneDDS is currently treated as an environment-specific workaround, not the default validated OpenPAVE release path.

## Basic Usage

From the repo root:

```bash
cd /path/to/OpenPAVE
source .venv/bin/activate

./scripts/run_stage3_demo.sh
```

To use an explicit software-only profile:

```bash
OPENPAVE_CONFIG=configs/mock.env ./scripts/run_stage3_demo.sh
```

The launcher defaults to:

```text
ROBOT_ADAPTER=mock
UI_PORT=8090
UI_API_BASE=http://localhost:8000/v1
UI_MODEL=llava-hf/llava-v1.6-mistral-7b-hf
ROBOT_IP_ADDRESS=192.168.0.8
```

`ROBOT_ADAPTER=mock` is the default to avoid accidental physical robot motion.

## Start a vLLM Backend

Stage 3 can start the OpenPAVE runtime without vLLM, but real VLM inference requires an OpenAI-compatible backend at the configured `UI_API_BASE`.

Use a separate vLLM virtual environment to avoid dependency conflicts with the OpenPAVE repo-level `.venv`.

OpenPAVE Stage 3 currently pins vLLM to `0.21.0` for demo stability. Newer vLLM releases may change engine defaults, memory behavior, dependency behavior, or API handling.

```bash
cd /path/to/OpenPAVE

python3 -m venv .venv-vllm
source .venv-vllm/bin/activate

python3 -m pip install -U pip
python3 -m pip install "vllm==0.21.0"
python3 -m pip check

vllm --version
```

Expected version:

```text
0.21.0
```

### Start vLLM with Local Hugging Face Cache

For demo runs, prefer using the model that has already been downloaded into the local Hugging Face cache. This avoids startup failures caused by network timeouts while vLLM checks Hugging Face Hub metadata.

```bash
cd /path/to/OpenPAVE
source .venv-vllm/bin/activate

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

vllm serve llava-hf/llava-v1.6-mistral-7b-hf \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype float16 \
  --max-model-len 3072 \
  --gpu-memory-utilization 0.55 \
  --enforce-eager
```

If the model has not been downloaded before, offline mode will fail. In that case, temporarily disable offline mode, download the model once, and then re-enable offline mode for future demo runs:

```bash
unset HF_HUB_OFFLINE
unset TRANSFORMERS_OFFLINE

vllm serve llava-hf/llava-v1.6-mistral-7b-hf \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype float16 \
  --max-model-len 3072 \
  --gpu-memory-utilization 0.55 \
  --enforce-eager
```

After the model is cached locally, restart vLLM with:

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

You can check whether the model exists in the Hugging Face cache with:

```bash
find ~/.cache/huggingface/hub -maxdepth 1 -type d | grep "models--llava-hf--llava-v1.6-mistral-7b-hf" || true
```

If the cache is owned by another user or a previous root process, fix the ownership:

```bash
sudo chown -R "$USER:$USER" ~/.cache/huggingface
```

### Verify the vLLM Endpoint

From another terminal:

```bash
curl -s http://127.0.0.1:8000/v1/models | head
```

If the WebUI is opened from another machine, make sure vLLM is started with:

```bash
--host 0.0.0.0
```

Then configure the WebUI API base to:

```text
http://<DGX_OR_CONTROL_MACHINE_IP>:8000/v1
```

### vLLM Troubleshooting

If vLLM fails with a Hugging Face handshake timeout, use the local cache mode:

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

If vLLM reports CUDA out of memory, first stop old vLLM processes and check GPU usage:

```bash
pkill -f vllm || true
pkill -f "api_server" || true
pkill -f "EngineCore" || true

nvidia-smi
```

Then restart with more conservative settings:

```bash
vllm serve llava-hf/llava-v1.6-mistral-7b-hf \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype float16 \
  --max-model-len 2048 \
  --gpu-memory-utilization 0.50 \
  --enforce-eager
```

If vLLM returns:

```text
Input length (...) exceeds model's maximum context length (...)
```

increase `--max-model-len` if GPU memory allows, or reduce the WebUI prompt length. For physical PuppyPi demos, keep the prompt short and strict:

```text
Reply exactly one word: TROT or STOP.
Use TROT only when clearly safe to start stepping. Otherwise STOP.
```

If vLLM fails with an `openai.types.responses` import error, the vLLM environment has an incompatible `openai` package version. Recreate `.venv-vllm` or reinstall vLLM and the OpenAI SDK together in that separate environment.

## Physical PuppyPi Validation

Start the PuppyPi ROS 2 controller on the PuppyPi side.

Recommended container entry method:

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

Keep this terminal open while running the physical robot demo.

If you use the helper script instead:

```bash
cd /path/to/OpenPAVE

export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

./scripts/start_puppypi_controller.sh
```

The script uses these defaults:

```text
PUPPYPI_CONTAINER=puppypi_ros2
PUPPYPI_USER=ubuntu
PUPPYPI_WORKDIR=/home/ubuntu
ROS_DOMAIN_ID=0
RMW_IMPLEMENTATION=rmw_fastrtps_cpp
PUPPYPI_RESTART_ROS_DAEMON=1
PUPPYPI_LAUNCH_CMD=ros2 launch puppy_control puppy_control.launch.py
```

If your PuppyPi controller container was rebuilt or retagged, make sure `PUPPYPI_CONTAINER` points to the currently validated container name before starting the helper script:

```bash
PUPPYPI_CONTAINER=<current-controller-container-name> ./scripts/start_puppypi_controller.sh
```

Start the vLLM backend first, then run the OpenPAVE runtime on the DGX/control side.

From the OpenPAVE repo root:

```bash
cd /path/to/OpenPAVE
source .venv/bin/activate

mkdir -p .openpave/runtime .openpave/logs

export ROBOT_ADAPTER=puppypi
export ROBOT_IP_ADDRESS="172.20.10.<PUPPYPI_IP>"

export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

export INTENT_PATH="$PWD/.openpave/runtime/vla_intent.json"
export COMMAND_RESULT_PATH="$PWD/.openpave/runtime/vla_command_result.json"
export ROBOT_STATE_PATH="$PWD/.openpave/runtime/vla_robot_state.json"

OPENPAVE_CONFIG=configs/puppypi.env ./scripts/run_stage3_demo.sh
```

`configs/puppypi.env` contains the PuppyPi adapter, robot IP address, VLM model/backend, ROS domain, RMW implementation, and ROS CLI Docker image settings. Environment variables exported in the shell can override profile values.

For physical robot safety, VLM-driven `TROT` forwarding requires repeated confirmation by default:

```text
INTENT_FORWARDING_ENABLED=1
TROT_CONFIRMATIONS=2
TROT_CONFIRMATION_WINDOW_MS=1500
```

`STOP` is still forwarded immediately.

To disable VLM-to-robot forwarding during debugging:

```bash
OPENPAVE_CONFIG=configs/puppypi.env INTENT_FORWARDING_ENABLED=0 ./scripts/run_stage3_demo.sh
```

You can still override a profile value from the shell:

```bash
OPENPAVE_CONFIG=configs/puppypi.env ROBOT_IP_ADDRESS=<PUPPYPI_IP> ./scripts/run_stage3_demo.sh
```

## Open URLs

The launcher prints both UI entry points:

```text
http://127.0.0.1:8090/
http://127.0.0.1:8090/pave
```

Use `/` for the full upstream `live-vlm-webui`.

Use `/pave` for the lightweight OpenPAVE console when the checked-out `ui` submodule includes the Stage 2 console patch. If `/` works but `/pave` returns `404`, the current `live-vlm-webui` checkout does not include the OpenPAVE console route.

The `/pave` console can also run a text-only prompt inference through:

```text
POST /api/pave/infer
```

Use this to validate the vLLM/OpenAI-compatible backend and UI prompt/result path before connecting a live camera stream or physical robot.

## Runtime Files

For physical PuppyPi demos, use repo-local runtime files instead of `/tmp`. This avoids stale files and permission conflicts when the demo is run by different users or after previous root-owned processes.

From the repo root:

```bash
cd /path/to/OpenPAVE

mkdir -p .openpave/runtime .openpave/logs

export INTENT_PATH="$PWD/.openpave/runtime/vla_intent.json"
export COMMAND_RESULT_PATH="$PWD/.openpave/runtime/vla_command_result.json"
export ROBOT_STATE_PATH="$PWD/.openpave/runtime/vla_robot_state.json"
```

The runtime files are created by the services when commands are processed:

```text
.openpave/runtime/vla_intent.json
.openpave/runtime/vla_command_result.json
.openpave/runtime/vla_robot_state.json
```

If you previously used `/tmp`, remove stale files before starting a physical demo:

```bash
sudo rm -f /tmp/vla_intent.json /tmp/vla_intent.json.tmp
sudo rm -f /tmp/vla_command_result.json /tmp/vla_command_result.json.tmp
sudo rm -f /tmp/vla_robot_state.json /tmp/vla_robot_state.json.tmp
```

To inspect the repo-local runtime state:

```bash
cat .openpave/runtime/vla_intent.json
cat .openpave/runtime/vla_command_result.json
cat .openpave/runtime/vla_robot_state.json
```

## Manual Intent Test

Use this to validate the Intent Ingress and Control Daemon path without using the WebUI.

Start the runtime, then run:

```bash
curl -s -X POST http://127.0.0.1:7071/intent \
  -H 'Content-Type: application/json' \
  -d '{"text":"TROT"}'
```

If `TROT` safety confirmation is enabled, the first request may return:

```json
{
  "ok": true,
  "accepted": false,
  "reason": "waiting_trot_confirmation_1/2"
}
```

Send the same command again within the confirmation window:

```bash
curl -s -X POST http://127.0.0.1:7071/intent \
  -H 'Content-Type: application/json' \
  -d '{"text":"TROT"}'
```

`STOP` is always accepted immediately:

```bash
curl -s -X POST http://127.0.0.1:7071/intent \
  -H 'Content-Type: application/json' \
  -d '{"text":"STOP"}'
```

Check the intent file:

```bash
cat .openpave/runtime/vla_intent.json
```

Watch the daemon logs:

```bash
tail -f .openpave/logs/control_daemon.log
```

Expected control path:

```text
COMMAND status=received intent=TROT
COMMAND status=accepted intent=TROT
COMMAND status=executing intent=TROT
ACTION=TROT adapter=puppypi
COMMAND status=succeeded intent=TROT
```

## Debug Unexpected Robot Motion

If the robot executes `TROT` when you did not intentionally send a new command, first determine whether it came from a stale intent file or from a fresh VLM/UI output.

Inspect the current intent:

```bash
cat .openpave/runtime/vla_intent.json
```

Inspect command lifecycle feedback:

```bash
cat .openpave/runtime/vla_command_result.json
cat .openpave/runtime/vla_robot_state.json
```

Watch the managed runtime logs:

```bash
tail -f .openpave/logs/intent_ingress.log
tail -f .openpave/logs/control_daemon.log
tail -f .openpave/logs/openpave-ui.log
```

The control daemon ignores an intent file that already exists before daemon startup. It only processes that file after it changes. This prevents a stale intent containing `TROT` from being replayed when the runtime restarts.

To intentionally replay an existing intent file during development:

```bash
PROCESS_EXISTING_INTENT_ON_START=1 ./scripts/run_stage3_demo.sh
```

If the intent file changes to `TROT` while the UI is running, the likely source is a VLM output being forwarded by `live-vlm-webui`. In that case, check `openpave-ui.log` and the UI prompt/result panel.

For physical robot validation, keep the prompt strict and prefer `STOP` as the fallback output.

Recommended prompt:

```text
Reply exactly one word: TROT or STOP.
Use TROT only when clearly safe to start stepping. Otherwise STOP.
```

## Logs

Inspect logs with:

```bash
tail -f .openpave/logs/intent_ingress.log
tail -f .openpave/logs/control_daemon.log
tail -f .openpave/logs/openpave-ui.log
```

## Health Checks

The launcher checks:

```text
http://127.0.0.1:7071/healthz
http://127.0.0.1:8090/
```

It also probes the configured OpenAI-compatible VLM endpoint:

```text
http://localhost:8000/v1/models
```

If the VLM endpoint is not reachable, the launcher still starts the UI. Layout, WebSocket connectivity, runtime feedback, and manual intent testing can still be validated without model inference.

Manual checks:

```bash
curl -s http://127.0.0.1:7071/healthz
curl -s http://127.0.0.1:8000/v1/models | head
```

## Stage 3C Benchmark Validation

The benchmark harness runs from a second terminal while the Stage 3 runtime is already running.

### Mock Control-Path Benchmark

Terminal 1:

```bash
cd /path/to/OpenPAVE
source .venv/bin/activate

OPENPAVE_CONFIG=configs/mock.env ./scripts/run_stage3_demo.sh
```

Confirm the launcher prints:

```text
ROBOT_ADAPTER=mock
```

Terminal 2:

```bash
cd /path/to/OpenPAVE
source .venv/bin/activate

python3 scripts/run_benchmark.py scenarios/mock-intent-stop-trot.json
```

Expected summary:

```text
summary=total=2 passed=2 failed=0 avg_latency_ms=...
```

Benchmark results are written to:

```text
benchmark-results/
```

Summarize one or more benchmark result files:

```bash
python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl
```

Compare model, endpoint, or inference-node dimensions by changing the grouping. This compares benchmark result files by their scenario metadata; Stage 3C.1 does not replay camera frames or measure VLM output quality yet.

```bash
python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl \
  --group-by scenario.id \
  --group-by inference_node.default_model

python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl \
  --group-by scenario.id \
  --group-by runtime_env.UI_MODEL

python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl \
  --group-by scenario.id \
  --group-by robot_sensor_endpoint.validated_target

python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl \
  --group-by scenario.id \
  --group-by inference_node.validated_target
```

Use threshold gates when validating a release candidate:

```bash
python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl \
  --min-pass-rate 1.0 \
  --max-avg-latency-ms 1500
```

The command returns a non-zero exit code if any grouped result violates the gate.

### Physical PuppyPi Benchmark

Only run this after the PuppyPi ROS2 controller is running and the robot is in a safe test area.

Terminal 1:

```bash
cd /path/to/OpenPAVE
source .venv/bin/activate

mkdir -p .openpave/runtime .openpave/logs

export ROBOT_ADAPTER=puppypi
export ROBOT_IP_ADDRESS="<PUPPYPI_IP>"

export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

export INTENT_PATH="$PWD/.openpave/runtime/vla_intent.json"
export COMMAND_RESULT_PATH="$PWD/.openpave/runtime/vla_command_result.json"
export ROBOT_STATE_PATH="$PWD/.openpave/runtime/vla_robot_state.json"

OPENPAVE_CONFIG=configs/puppypi.env ./scripts/run_stage3_demo.sh
```

Terminal 2:

```bash
cd /path/to/OpenPAVE
source .venv/bin/activate

python3 scripts/run_benchmark.py scenarios/puppypi-gesture-stop-trot.json --allow-physical
```

Physical-motion scenarios are blocked unless `--allow-physical` is passed.

### STOP-Only Physical Check

Use this when you want to validate the physical control path without sending `TROT`:

```bash
python3 scripts/run_benchmark.py scenarios/puppypi-gesture-stop-trot.json \
  --allow-physical \
  --intent STOP
```

Inspect the latest command result:

```bash
cat .openpave/runtime/vla_command_result.json
```

## Release Candidate Validation Checklist

Before tagging a Stage 3 release, validate the following items on the target DGX/control machine:

1. Submodule and UI routes:

```bash
git submodule update --init --recursive
python3 -m pip install -e ui
grep -n 'app.router.add_get("/pave"' ui/src/live_vlm_webui/server.py
grep -n 'app.router.add_post("/api/pave/infer"' ui/src/live_vlm_webui/server.py
```

2. Unit tests:

```bash
python3 -B -m unittest discover
```

3. Mock runtime and benchmark:

```bash
OPENPAVE_CONFIG=configs/mock.env ./scripts/run_stage3_demo.sh
python3 scripts/run_benchmark.py scenarios/mock-intent-stop-trot.json
python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl \
  --min-pass-rate 1.0 \
  --max-avg-latency-ms 1500
```

4. vLLM endpoint and `/pave` inference path:

```bash
curl -s http://127.0.0.1:8000/v1/models | head
curl -i http://127.0.0.1:8090/pave
```

Then open:

```text
http://127.0.0.1:8090/pave
```

Run a text-only inference prompt and confirm that the VLM result panel updates.

5. Physical PuppyPi validation:

```bash
OPENPAVE_CONFIG=configs/puppypi.env ./scripts/run_stage3_demo.sh

curl -s -X POST http://127.0.0.1:7071/intent \
  -H 'Content-Type: application/json' \
  -d '{"text":"STOP"}'

tail -n 80 .openpave/logs/control_daemon.log
cat .openpave/runtime/vla_command_result.json
cat .openpave/runtime/vla_robot_state.json
```

Only run `TROT` validation after confirming that the robot-side controller, ROS 2 middleware, and Docker image versions match the tested setup.

## Stop

Press `Ctrl+C` in the launcher terminal.

The launcher shuts down the managed child processes:

- Intent Ingress
- Control Daemon
- OpenPAVE UI server

When `ROBOT_ADAPTER=puppypi`, the launcher sends a final `STOP` intent before stopping managed processes. This helps return PuppyPi to a safe state if the demo is interrupted while the robot is moving.

Disable this only for debugging:

```bash
STOP_ROBOT_ON_EXIT=0 OPENPAVE_CONFIG=configs/puppypi.env ./scripts/run_stage3_demo.sh
```

It does not stop external dependencies such as vLLM or the robot-side ROS 2 controller.

## Suggested Demo Startup Checklist

Use this condensed checklist for a physical PuppyPi demo.

### Terminal 1: PuppyPi ROS 2 Controller

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

### Terminal 2: vLLM Backend

```bash
cd /path/to/OpenPAVE
source .venv-vllm/bin/activate

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

vllm serve llava-hf/llava-v1.6-mistral-7b-hf \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype float16 \
  --max-model-len 3072 \
  --gpu-memory-utilization 0.55 \
  --enforce-eager
```

### Terminal 3: OpenPAVE Runtime

```bash
cd /path/to/OpenPAVE
source .venv/bin/activate

mkdir -p .openpave/runtime .openpave/logs

export ROBOT_ADAPTER=puppypi
export ROBOT_IP_ADDRESS="172.20.10.<PUPPYPI_IP>"

export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

export INTENT_PATH="$PWD/.openpave/runtime/vla_intent.json"
export COMMAND_RESULT_PATH="$PWD/.openpave/runtime/vla_command_result.json"
export ROBOT_STATE_PATH="$PWD/.openpave/runtime/vla_robot_state.json"

OPENPAVE_CONFIG=configs/puppypi.env ./scripts/run_stage3_demo.sh
```

### Terminal 4: Smoke Test

```bash
curl -s http://127.0.0.1:7071/healthz
curl -s http://127.0.0.1:8000/v1/models | head

curl -s -X POST http://127.0.0.1:7071/intent \
  -H 'Content-Type: application/json' \
  -d '{"text":"STOP"}'

tail -n 80 .openpave/logs/control_daemon.log
```
