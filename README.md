# OpenPAVE: Open Physical AI Validation and Experimentation

## An open reference workflow for Physical AI demos on Arm-based edge platforms

OpenPAVE helps developers assemble, run, observe, and compare local Physical AI demos.

It connects pieces that are often evaluated separately:

- local VLM/VLA inference
- robot or sensor endpoints
- robot middleware
- brain-body transport
- normalized intent and capability contracts
- command and state feedback
- observability UI
- demo runbooks
- benchmark and validation paths

OpenPAVE is not an LLM serving framework like vLLM or Ollama, and it is not a full commercial robotics stack. It is a fork-friendly reference base for validating Physical AI workflows on Arm-based edge platforms.

## Demo References

These early demos show the original direction that OpenPAVE builds on:

- [Physical AI edge VLA demo short](https://youtube.com/shorts/QwUnFLIUNe4?si=P6FuZvVzHTzYnd57)
- [Physical AI robot workflow demo](https://youtu.be/kRiXri0te0g?si=ijmNqtQX8cuCoHHs)

## What OpenPAVE Provides

OpenPAVE gives developers three practical building blocks:

1. **A local Arm edge Physical AI testbed**
   - Start from a validated PuppyPi + DGX baseline.
   - Swap in new robot/sensor endpoints, edge nodes, transports, or inference backends over time.

2. **A repeatable validation workflow**
   - Describe demos with integration levels, scenarios, configs, and runbooks.
   - Observe runtime state through the `/pave` console.
   - Record command results, robot state, and benchmark outputs.

3. **A plugin-oriented extension model**
   - Add a robot/sensor adapter.
   - Add a seam transport.
   - Add a config recipe for a validated hardware combination.
   - Add demo scenarios and benchmark paths.

## Architecture: Brain, Body, Seam

OpenPAVE models a Physical AI demo as two layers connected by one primary seam:

```text
Brain side: local inference / control / observability node
    |
    | seam: brain-body communication boundary
    |
Body side: robot or sensor endpoint
    |-- local controller, adapter, policy, or middleware
    |-- motors, servos, cameras, IMU, and sensors
```

OpenPAVE focuses on the brain-body seam, the control contract sent across it, and the observable state that comes back. It does not try to define every internal connection between a body controller and the physical motors or sensors.

Current validated baseline:

```text
PuppyPi + DGX Spark
```

This is the first validated deep-integration target, not the project boundary.

## Four-Dimensional Model

A complete OpenPAVE validation configuration combines four dimensions:

| Dimension | Role | Current state |
| --- | --- | --- |
| Brain-side edge node | Local inference, orchestration, UI, benchmark runner | DGX Spark baseline; Jetson Thor, Radxa O6, and other Arm-based edge nodes validated at different levels |
| Body-side robot/sensor endpoint | Robot, arm, camera, sensor endpoint, or future body-side policy unit | PuppyPi baseline; mock, mock arm, and camera adapters exist |
| Seam transport | Brain-body communication boundary | baseline adapter path; raw zenoh and device-connect are experimental |
| Inference / upper-layer application | VLM/VLA backend, planner, or policy layer | vLLM/OpenAI-compatible API today; pluginization is roadmap |

Configs bind these dimensions into reproducible recipes. For example:

```text
configs/mock.env
configs/puppypi.env
```

## Demo Integration Levels

Not every demo needs to use the full OpenPAVE runtime. A demo can join at different depths:

```text
Level 0: Catalogue only
Level 1: Launch / status / result wrapper
Level 2: State or result bridge
Level 3: Normalized intent / capability control contract
Level 4: Benchmark integration
```

This lets a demo remain independently runnable while OpenPAVE provides shared documentation, observability, control contracts, or benchmark tooling where useful.

## Quick Start

Use the validated baseline guide as the primary runbook:

```text
docs/validated-baseline.md
```

Minimal software-only validation:

```bash
cd /path/to/OpenPAVE

git submodule update --init --recursive

python3 -m venv .venv
source .venv/bin/activate

python3 -m pip install -U pip
python3 -m pip install -r intent_ingress/requirements.txt
python3 -m pip install -e ui

OPENPAVE_CONFIG=configs/mock.env ./scripts/run_openpave.sh
```

Open:

```text
http://127.0.0.1:8090/pave
```

The mock profile validates the runtime path without robot hardware.

## Validated Baseline

The current baseline demonstrates:

```text
local VLM/VLA inference
-> normalized intent
-> Control Daemon
-> Robot Adapter
-> ROS 2 execution
-> command/state feedback
-> benchmark validation
```

Baseline components:

- Intent Ingress: `intent_ingress/server.py`
- Intent schema: `pave_runtime/intent_schema.py`
- Capability schema: `pave_runtime/capability_schema.py`
- Control daemon and adapters: `control_daemon/`
- Runtime launcher: `scripts/run_openpave.sh`
- Prompt presets: `prompts/`
- Scenarios: `scenarios/`
- Benchmark runner: `scripts/run_benchmark.py`
- Benchmark summarizer: `scripts/summarize_benchmarks.py`
- OpenPAVE console: `ui/` submodule, currently based on an OpenPAVE-maintained `live-vlm-webui` fork

## Validation Matrix

OpenPAVE tracks support as a validation matrix, not as a blanket compatibility claim.

Start here:

- [Validation Matrix](docs/validation-matrix.md)
- [Validated Baseline](docs/validated-baseline.md)
- [PuppyPi + DGX Target](docs/targets/puppypi-dgx.md)

Current status summary:

- **Baseline**: DGX Spark + PuppyPi through the validated runtime path.
- **Experimental**: persistent PuppyPi bridge, raw zenoh neutral seam, device-connect seam, capability and camera MVEs.
- **Partial**: Jetson Thor, Radxa O6, and other Arm-based edge nodes have been validated at different levels, but still need baseline-style matrix rows and runbooks.
- **Candidate**: SO-101 robot arm + camera and Raspberry Pi ROS 2 car/camera.

## Reproduce the Seam Validation

The real-brain seam matrix — a brain node driving a physical body over the seam plugin, across both
transports — is reproducible from four-dimension config recipes plus two scripts. Full guide:
[Seam Validation Runbook](docs/seam-validation-runbook.md).

```bash
# 1. Install the seam dependencies into each host's venv (pinned versions)
<venv>/bin/pip install -r requirements-seam.txt          # brain + body
<venv>/bin/pip install -r requirements-seam-camera.txt   # camera sensor body only

# 2. Deploy the seam bundle to a brain (ships pave_runtime + seam_cli + seam_run + configs)
scripts/deploy_seam.sh odin@192.168.0.24 '$HOME/openpave-seam' '$HOME/.venv-zenoh/bin/python'

# 3. Bring up the body, then drive it from the brain — same launcher, any recipe
scripts/seam_run.sh configs/dgx-puppypi.env body             # on the body (PuppyPi)
scripts/seam_run.sh configs/dgx-puppypi.env brain send home  # on the brain (DGX)
```

A recipe (`configs/<brain>-<body>.env`) pins the four dimensions; swapping the transport is a
one-line change to `SEAM_TRANSPORT` (`raw_zenoh` | `device_connect`). Recipes available today:
`dgx-puppypi`, `radxa-puppypi` (actuator), `dgx-camera`, `radxa-camera` (sensor).

## Benchmarking

Start the runtime, then run:

```bash
python3 scripts/run_benchmark.py scenarios/mock-intent-stop-trot.json
python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl
```

The current benchmark harness validates the control path and can summarize results by scenario metadata. Future work will add sensor replay, VLM/VLA output quality checks, transport latency breakdown, and multi-target comparison.

## Documentation

Start here:

- [Documentation Index](docs/index.md)
- [OpenPAVE Platform Specification](docs/openpave-platform-spec.md)
- [Validation Matrix](docs/validation-matrix.md)
- [Validated Baseline Guide](docs/validated-baseline.md)
- [Further Work](docs/further-work.md)

Core references:

- [Architecture](docs/architecture.md)
- [Brain-Body Architecture](docs/architecture-brain-body.md)
- [Demo Integration Levels](docs/demo-integration-levels.md)
- [Demo Catalogue](docs/demo-catalog.md)
- [Contributing Demos](docs/contributing-demos.md)
- [Intent Schema](docs/intent-schema.md)
- [Robot Adapters](docs/robot-adapters.md)
- [Robot Feedback](docs/robot-feedback.md)
- [Benchmark Harness](docs/benchmark-harness.md)
- [Ecosystem Validation Map](docs/ecosystem-validation-map.md)
- [Third-Party Notices](docs/third-party-notices.md)

Historical material is kept under:

```text
docs/archive/
```

## Current Limitations

- The default PuppyPi command path uses Dockerized one-shot ROS 2 CLI calls. An experimental persistent bridge exists, but it is not yet the default.
- The default brain-body path remains the validated baseline adapter path. Raw zenoh and device-connect seam transports are experimental.
- `/pave` currently lives in an OpenPAVE-maintained `live-vlm-webui` fork. A native OpenPAVE console is planned.
- Current benchmark coverage focuses on control-path validation. Full sensor replay and VLM/VLA quality benchmarks are future work.
- Additional Arm-based edge nodes have been validated at different levels, but most still need baseline-quality runbooks and matrix entries.

## Third-Party Notice

OpenPAVE currently uses an OpenPAVE-maintained fork of `NVIDIA-AI-IOT/live-vlm-webui` as a submodule for the UI/backend path. This does not imply NVIDIA endorsement or official product alignment. See [Third-Party Notices](docs/third-party-notices.md).
