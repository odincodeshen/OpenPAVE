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
| Brain-side edge node | Local inference, orchestration, observability, benchmark runner | Config and deployment target | DGX Spark baseline; Radxa O6 exercised as a seam brain and as a client of a remote vLLM; no evidence yet for Jetson Thor or other nodes |
| Body-side robot or sensor endpoint | Robot, arm, camera, sensor endpoint, or future body-side policy unit | Robot/sensor adapter (`create_robot_adapter`) | PuppyPi (ROS 2) baseline and seam body; ROS-free `gpio_servo` (real hardware) and `led`; RPi 5 USB camera sensor; mock and mock arm |
| Seam transport | Brain-body communication boundary | `SEAM_TRANSPORT` / `create_seam_transport(name)` | `raw_zenoh` and `device_connect` plugins, exercised on real hardware from DGX Spark and Radxa O6; body-side dead-man lease |
| Inference or upper-layer application | VLM/VLA runtime, planner, or policy-facing application layer | `create_inference_runtime(name)`, `create_application_runtime(name)`, `create_observation_source(name)` | Registries exist; one real inference backend (`vllm_openai`) and one application (`gesture_commander`); the v1.0 `/pave` baseline still runs inference inside the UI |

The brain-side node is treated as a deployment target rather than a normal software plugin. The other three dimensions are registered plugin surfaces (`create_robot_adapter`, `create_seam_transport`, and the inference / application / observation registries); what is still thin is the number of real backends behind the newer ones.

### The inference / application dimension is domain-general

The fourth dimension is where OpenPAVE's breadth lives, and it is easy to under-read. **Gesture
control (camera → VLM → intent → robot) is only one example** of this dimension — a demo that shows
the concept end to end — not the point of the platform. The same slot holds very different
applications:

- a **VLM** turning observations into normalized intents (the gesture demo);
- an **end-to-end VLA policy** driving a robot arm — e.g. SmolVLA + SO-101, per the Arm learning paths;
- a **planner, an agent, or an external developer's own project** that emits capability commands.

`create_inference_runtime(name)` and `create_application_runtime(name)` make this a registered plugin
surface like the seam, so a new application is a registered backend rather than a fork. Today the
registries hold `vllm_openai` and `gesture_commander` (plus mock backends); a second real backend — for
example a local model server, or a VLA policy — is what would prove the slot is as general as described.
The v1.0 `/pave` baseline path still performs its inference inside the UI rather than through these
registries.

### The body dimension is protocol-neutral: adopting a controller is an adapter

Adopting a new body-side controller — the "small brain" that owns actuation — is a **robot adapter**,
not a framework choice. An adapter maps the capability contract (`{action, params}`: `stop`, `trot`,
`move`, `home`, …) to whatever that controller natively speaks. The seam carries only `{action,
params}` (over zenoh), so **both the boundary and the contract are framework-neutral**; OpenPAVE
deliberately does not standardize the body-internal protocol.

**ROS 2 is one such native interface, not a requirement.** The PuppyPi adapter shells out to ROS 2
because PuppyPi's controller (`puppy_control`) is a ROS 2 stack — but that lives *inside* the adapter,
below the seam, and nothing above it knows or cares. Three consequences:

- **The integration point is the adapter, not ROS 2.** A controller reached over serial / CAN, GPIO, a
  vendor SDK, or HTTP is adopted the same way — and is often simpler, with no ROS 2 stack to bring up.
- **ROS 2 compatibility is not plug-and-play.** Each ROS 2 robot exposes its own topics, services, and
  messages, so a ROS 2 controller still needs its own capability mapping.
- **The real "easy to adopt" criterion** is a clean, callable control interface whose verbs map to
  `{action, params}` — regardless of protocol. `pave_runtime` itself has no ROS 2 dependency.

Because ROS 2 is common in robotics, a reusable ROS 2 adapter template is a worthwhile *accelerator*
(turning "copy the PuppyPi adapter" into "fill in a few topic / message names"). It stays an option
below the seam, never a required layer.

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

Current configs:

- `configs/mock.env`: software-only validation (also carries the v1.7 inference/application keys).
- `configs/puppypi.env`: PuppyPi physical validation on the baseline ROS 2 path.
- `configs/<brain>-<body>.env` seam recipes — `dgx-puppypi`, `radxa-puppypi` (actuator) and `dgx-rpicam`, `radxa-rpicam` (sensor) — each pinning the brain, body, `SEAM_TRANSPORT` and inference settings; run them with `scripts/seam_run.sh` (`docs/seam-validation-runbook.md`).

The ROS-free servo and LED bodies have no recipe yet; their runbook (`docs/runbooks/v1.8-quick-demo.md`) sets the variables inline.

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

- The v1.0 baseline gesture runtime (`run_openpave.sh`) still uses the ROS 2 / adapter path for the PuppyPi workflow; it does not go through the seam.
- `pave_runtime.seam` is a pluggable transport registry (`create_seam_transport`). `raw_zenoh` and `device_connect` are the two backends, exercised on real hardware from DGX Spark and Radxa O6 against a real PuppyPi and an RPi 5 camera (`docs/validation-matrix.md`).
- `scripts/seam_cli.py` is the body/brain CLI over the selected transport; `scripts/run_inference.py --seam` and `scripts/run_live.py` drive a real body through it (`docs/v1.8-live-body.md`).
- The seam carries low-rate semantic capability actions (`{action, params}`), not a high-rate control stream: each `raw_zenoh` send currently opens a fresh session (~0.5 s, see `docs/latency-model.md`).
- The body keeps a **dead-man motion lease** (`BODY_MOTION_TTL_S`, default 5 s): a `trot` / `move` the brain stops renewing is stopped by the body itself, over either backend.

The transport plugin goal is to make the same body-side adapter and capability dispatch work over different communication backends — and the same brain command drives a ROS 2 body or a ROS-free one.

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

- validation status — Candidate, Experimental, Supported or Validated, plus whether the evidence is `software` or `hardware`
- integration level
- config or runbook
- benchmark results, if available
- known limitations

A combination is only Supported or Validated on evidence from running that combination on its real hardware; an upstream project's own hardware claims do not count. See `docs/validation-matrix.md` for the definitions and the current grading.

## Main Repository Policy

The main repository is a reference base, not a mandatory upstream destination for every fork.

The project should selectively integrate contributions that improve one of these strategic surfaces:

- new VLM/VLA or inference runtime
- new seam transport
- new brain-side or body-side hardware validation
- new robot/sensor adapter
- strategically useful Physical AI demo or scenario
- benchmark or validation improvement

## Current State

Current baseline:

- PuppyPi + DGX is the first validated deep-integration target (the v1.0 baseline path).
- DGX Spark is the primary brain-side baseline.
- Radxa O6 has been exercised as a seam brain, with PuppyPi and the RPi 5 camera as bodies, and as a client of a remote vLLM; it has no local-inference runbook yet. Jetson Thor and other Arm-based edge nodes have no evidence in this repository.

Implemented, with real-hardware runs but short of the Validated bar (see the matrix for the exact grading):

- seam transport plugin (`raw_zenoh`, `device_connect`) with PuppyPi and camera bodies
- headless inference/application runtime, the live-body loop, and the body-side safety lease
- ROS-free `gpio_servo` body
- persistent PuppyPi bridge for lower-latency robot command execution
- capability model spanning locomotion, manipulation, and sensing
- camera sensing with a control-plane / data-plane split

## Roadmap

Done since the first roadmap:

- The validation matrix exists and is graded against explicit status definitions.
- Seam transport plugins graduated from experiments into `pave_runtime.seam`, with runbooks and recipes.
- Four-dimensional config recipes (`configs/<brain>-<body>.env`).
- Three-segment latency reporting (`docs/latency-model.md`, `scripts/seam_bench.py`, and the latency block of `run_inference.py`).
- The inference / application / observation plugin registries and the live-body loop.
- A body-side safety lease and signal-safe STOP on the brain drivers.

Next:

- A second real inference backend (for example a local model server) and a second application, to show those registries are as swappable as the seam; this would also give Radxa O6 a self-contained local-inference path.
- Move the v1.0 `/pave` gesture path onto the inference / application registries, so the UI stops owning inference.
- Repeat the live-body and ROS-free body runs often enough, with structured results, to reach Validated; verify the safety lease against a physical actuator and the real dog, and close its body-process-crash gap.
- Keep the validated baseline easy to reproduce.

Longer-term roadmap:

- Native OpenPAVE console independent from the `live-vlm-webui` fork.
- Sensor replay and full VLM/VLA output-quality benchmark support.
- Additional body endpoints such as SO-101 and Raspberry Pi ROS 2 car/camera.
- Additional brain-side Arm edge nodes with documented evidence (Jetson Thor has none yet).
- Multi-device / fabric-style transport experiments.

