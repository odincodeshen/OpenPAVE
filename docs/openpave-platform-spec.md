# OpenPAVE Platform Specification

OpenPAVE is an open Physical AI validation and experimentation workflow for Arm-based edge platforms.

It gives developers a reference base for connecting local VLM/VLA inference, robot or sensor endpoints, transport choices, runtime control contracts, UI observability, and benchmark paths into reproducible demos.

OpenPAVE is not an LLM serving framework, a full robot operating stack, or a commercial autonomous robotics product. It is a developer-oriented reference workflow that helps teams build, validate, compare, and extend Physical AI demos without making cloud connectivity the default assumption.

## Goals

OpenPAVE is designed to provide three concrete values:

- A fast way to assemble a local Arm edge Physical AI testbed.
- A reusable environment for VLM/VLA workflow validation and performance analysis.
- A go-to-market friendly reference base for demonstrating how Arm ecosystem software, hardware, models, middleware, and robot endpoints can work together.

The project is intentionally fork-friendly. External developers can fork OpenPAVE into their own demos or products, while the main repository selectively integrates plugins, targets, transports, demos, and benchmark paths that have strategic value for the reference workflow.

## Architecture: Two Layers and One Seam

OpenPAVE models the system as two layers connected by one primary seam:

```text
Brain side: local inference / control / observability node
    |
    | seam: the brain-body communication boundary
    |
Body side: robot or sensor endpoint
    |-- local controller, adapter, policy, or robot middleware
    |-- motors, servos, cameras, IMU, sensors, and other body hardware
```

The body hardware itself is inside the body-side endpoint. OpenPAVE does not try to define a protocol between a controller board and every motor or sensor. The project focuses on the brain-body seam, the control contract sent across it, and the observable results that come back.

This keeps the architecture small: OpenPAVE primarily owns one integration boundary, not every internal hardware connection.

## Four-Dimensional Model

A complete OpenPAVE validation configuration is a combination of four dimensions:

| Dimension | Role | Typical expression | Current state |
| --- | --- | --- | --- |
| Brain-side edge node | Local inference, orchestration, observability, benchmark runner | Config and deployment target | DGX Spark baseline; Jetson Thor, Radxa O6, and other Arm-based edge nodes validated at different levels |
| Body-side robot or sensor endpoint | Robot, arm, camera, sensor endpoint, or future body-side policy unit | Robot/sensor adapter | PuppyPi baseline; mock, mock arm, and camera adapters exist |
| Seam transport | Brain-body communication boundary | `SEAM_TRANSPORT` / `create_seam_transport(name)` | raw zenoh and device-connect backends exist as experimental transport plugins |
| Inference or upper-layer application | VLM/VLA runtime, planner, or policy-facing application layer | OpenAI-compatible API today; future `create_inference_runtime(name)` | vLLM/OpenAI-compatible API baseline; pluginization is roadmap |

The brain-side node is treated as a deployment target rather than a normal software plugin. The other three dimensions are expected to become registered plugin surfaces.

## Config as a Validated Recipe

A config file should bind the selected dimensions into a repeatable recipe:

```text
BRAIN_HOST=...
ROBOT_ADAPTER=...
SEAM_TRANSPORT=...
INFERENCE_RUNTIME=...
UI_API_BASE=...
UI_MODEL=...
```

Adapters are reusable parts. Configs are validated combinations of parts.

Current baseline configs:

- `configs/mock.env`: software-only validation.
- `configs/puppypi.env`: PuppyPi physical validation.

Future configs should use explicit names such as `configs/dgx-puppypi.env` when the matrix grows beyond one primary physical target.

## Integration Levels

Not every demo needs to use the full OpenPAVE runtime. A demo can join the project at different depths:

| Level | Meaning |
| --- | --- |
| Level 0 | Catalogue entry only |
| Level 1 | Launch, status, or result wrapper |
| Level 2 | State or result bridge |
| Level 3 | Normalized intent / capability control contract |
| Level 4 | Benchmark integration |

This lets a demo remain independently runnable while OpenPAVE provides shared documentation, validation notes, observability, control contracts, or benchmark tooling where useful.

## Runtime Contracts

OpenPAVE currently has two related runtime contracts:

- Normalized intent schema v0.1: the historical and validated baseline contract for `STOP`, `TROT`, `MOVE`, and `HOME`.
- Capability-declarative action schema: the generalized `{action, params}` contract for locomotion, manipulation, sensing, and future robot classes.

The fixed intent vocabulary remains useful as a compatibility layer. The capability contract is the direction for supporting more robot and sensor endpoint types without hard-coding every device into the core.

## Seam Transport

The seam is the brain-body communication boundary.

Current status:

- The validated baseline still uses the current ROS 2 / adapter path for the PuppyPi workflow.
- `pave_runtime.seam` introduces a pluggable transport registry.
- `raw_zenoh` and `device_connect` are experimental seam transport backends.
- `scripts/seam_cli.py` provides a simple body/brain CLI over the selected transport.

The transport plugin goal is to make the same body-side adapter and capability dispatch work over different communication backends.

## Performance and Benchmarking

The minimum useful benchmark model should measure:

- end-to-end latency
- brain-side inference latency
- seam transport latency
- body-side execution latency
- command success rate
- recovery or fail-safe behavior

The current benchmark harness already validates the control path and writes structured JSONL results. Full VLM/VLA model quality, sensor replay, power, memory, and cross-platform inference comparison remain future work.

Benchmark results should feed the validation matrix so users can see not only what is theoretically supported, but what has actually been reproduced and measured.

## Validation Matrix

OpenPAVE should maintain a matrix of validated combinations across:

```text
brain-side node x body endpoint x inference/application layer x seam transport
```

Each cell should record:

- validation status
- integration level
- config or runbook
- benchmark results, if available
- known limitations

See `docs/validation-matrix.md`.

## Main Repository Policy

The main repository is a reference base, not a mandatory upstream destination for every fork.

The project should selectively integrate contributions that improve one of these strategic surfaces:

- new VLM/VLA or inference runtime
- new seam transport
- new brain-side or body-side hardware validation
- new robot/sensor adapter
- strategically useful Physical AI demo or scenario
- benchmark or validation improvement

## Current Validated and Experimental State

Current baseline:

- PuppyPi + DGX is the first validated deep-integration target.
- DGX Spark is the primary brain-side baseline.
- Jetson Thor, Radxa O6, and other Arm-based edge nodes have been validated at different levels, but not all have baseline-quality runbooks in this repository yet.

Current experimental work:

- persistent PuppyPi bridge for lower-latency robot command execution
- neutral non-ROS seam over raw zenoh
- device-connect seam backend
- capability model spanning locomotion, manipulation, and sensing
- camera sensing MVE with a control-plane / data-plane split

## Roadmap

Near-term roadmap:

- Formalize the validation matrix.
- Graduate seam transport plugins from experiments into documented runtime paths.
- Four-dimensional config cleanup.
- Add basic three-segment performance reporting: brain inference, seam transport, body execution.
- Keep the validated baseline easy to reproduce.

Longer-term roadmap:

- Native OpenPAVE console independent from the `live-vlm-webui` fork.
- `create_inference_runtime(name)` or equivalent inference runtime plugin boundary.
- Sensor replay and full VLM/VLA output-quality benchmark support.
- Additional body endpoints such as SO-101 and Raspberry Pi ROS 2 car/camera.
- Additional brain-side Arm edge nodes with documented validation levels.
- Multi-device / fabric-style transport experiments.

