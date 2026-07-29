# OpenPAVE Further Work

## Project Positioning

OpenPAVE is a local-first validation workflow for edge Physical AI experiments and brain-body co-computing.

It is not intended to define a new LLM serving framework like vLLM or Ollama. Its value is to help developers rapidly validate how a brain-side local inference/control node connects to body-side robot or sensor endpoints, how the runtime can be observed, how scenarios can be benchmarked, and how hardware targets can be replaced over time.

The current repository state should be treated as:

```text
OpenPAVE Validated Baseline v1.0
```

The first validated target is:

```text
PuppyPi + DGX
```

Brain-side targets belong to the Armv9 platform family. DGX (Armv9 Grace CPU + Nvidia GPU) is the first validated representative; Thor and other Armv9 edge nodes are follow-on targets in the same family, not alternatives outside DGX.

Planned future validation targets include:

- SO-101 robot arm with camera + DGX
- Raspberry Pi ROS 2 car/camera + DGX or Thor
- Additional Armv9 brain-side platforms (Thor, other Armv9 edge inference/control nodes)
- Future robot/sensor endpoints using different ROS 2 communication patterns

## Current Baseline: Validated Baseline v1.0

### Status

- [x] Local-first runtime can be launched from one command.
- [x] PuppyPi + DGX physical validation path works.
- [x] Mock adapter path works without robot hardware.
- [x] `/pave` OpenPAVE console is available through the `live-vlm-webui` submodule.
- [x] vLLM/OpenAI-compatible backend can be used for text-only `/pave` inference validation.
- [x] Intent Ingress, Control Daemon, Robot Adapter, command result, and robot state feedback are integrated.
- [x] Prompt presets and scenario files are stored in the repo.
- [x] Benchmark harness can run mock and physical-control-path checks.
- [x] `docs/validated-baseline.md` documents the current reproduction flow.

### Current Baseline Components

- `intent_ingress/`: HTTP intent entry point.
- `pave_runtime/intent_schema.py`: normalized intent schema and validation helper.
- `control_daemon/`: intent watcher, command lifecycle, robot adapter orchestration, command result, and robot state output.
- `control_daemon/adapters.py`: `MockAdapter` and `PuppyPiAdapter`.
- `configs/mock.env`: software-only runtime profile.
- `configs/puppypi.env`: PuppyPi physical validation profile.
- `scripts/run_stage3_demo.sh`: runtime launcher.
- `scripts/build_puppy_ros2_cli.sh`: custom PuppyPi ROS 2 CLI image builder.
- `scripts/start_puppy_control.sh`: one-command PuppyPi `puppy_control` bring-up (detached, single-instance, health-checked); `scripts/check_puppy_control.sh`: `puppy_control` health check.
- `scripts/run_benchmark.py`: scenario benchmark runner.
- `scripts/summarize_benchmarks.py`: benchmark summary and gate checker.
- `prompts/`: reusable prompt presets.
- `scenarios/`: benchmark/demo scenario definitions.
- `ui/`: OpenPAVE-maintained `live-vlm-webui` fork as a submodule.

### Validated Documentation

- [x] `docs/validated-baseline.md` documents the current release validation path.
- [x] `docs/intent-schema.md` documents the current intent schema.
- [x] `docs/robot-adapters.md` documents the adapter boundary.
- [x] `docs/robot-feedback.md` documents command result and robot state feedback.
- [x] `docs/benchmark-harness.md` documents benchmark usage.
- [x] `docs/prompts-and-scenarios.md` documents prompt/scenario assets.

## Historical Stage Status

These stages are no longer the main project narrative, but their work is part of the current validated baseline.

### Stage 1: Core Runtime Maturity

- [x] Intent schema v0.1 implemented.
- [x] Intent validation shared by Intent Ingress and Control Daemon.
- [x] `STOP`, `TROT`, `HOME`, and `MOVE` are supported by the schema.
- [x] Robot Adapter boundary implemented.
- [x] `PuppyPiAdapter` implemented.
- [x] `MockAdapter` implemented.
- [x] Command result feedback implemented.
- [x] Robot state feedback implemented.
- [x] Runtime logs expose command lifecycle.
- [ ] Periodic robot heartbeat or liveness tracking is not implemented yet.

### Stage 2: Lightweight OpenPAVE Console

- [x] `/pave` console implemented in the `live-vlm-webui` fork.
- [x] Existing video/VLM/GPU monitoring backend is reused.
- [x] Prompt input, model/backend display, raw VLM result, parsed intent, command result, and robot state are exposed.
- [x] `/api/pave/runtime` provides runtime feedback.
- [x] `/api/pave/infer` supports text-only inference validation.
- [x] VLM-to-intent forwarding includes `TROT` confirmation safety.
- [ ] UI remains coupled to `live-vlm-webui` and should be decoupled later.

### Stage 3: Validated Baseline v1.0

- [x] One-command runtime launcher implemented.
- [x] Runtime profiles implemented through `configs/mock.env` and `configs/puppypi.env`.
- [x] Logs are written to `.openpave/logs/`.
- [x] Runtime files are configurable.
- [x] Launcher prints `/` and `/pave` URLs.
- [x] Launcher performs basic health checks.
- [x] Launcher sends a final `STOP` intent on shutdown for the PuppyPi adapter.
- [x] Prompt presets are repo-managed.
- [x] Scenario definitions are repo-managed.
- [x] Benchmark runner writes structured results.
- [x] Benchmark summarizer supports grouping and pass/latency gates.
- [x] Mock benchmark path validated.
- [x] PuppyPi runtime profile validated.
- [x] vLLM + `/pave` inference path validated.
- [x] Known ROS 2 DDS/RMW issue documented in `docs/validated-baseline.md`.
- [ ] Camera/sensor replay inputs for true end-to-end VLM/VLA latency and output-quality comparison are not implemented yet.
- [ ] Multi-robot or multi-sensor routing is not implemented yet.

## Known Limitations

### Brain-Body Transport

The current PuppyPi validation path uses ROS 2 communication over the available network path. This is useful as a reproducible baseline, but it is not the final optimized brain-body transport design.

- [x] Current ROS 2 DDS/RMW variability is documented as a known issue.
- [x] Default validated path remains `rmw_fastrtps_cpp`.
- [x] `rmw_cyclonedds_cpp` is documented as an environment-specific workaround, not the default validated path.
- [ ] Add a future transport layer option that improves reliability and performance beyond the current ROS 2 over Wi-Fi reference path.
- [ ] Define how alternate transport layers integrate with existing robot/sensor endpoint contracts.
- [ ] Add benchmark dimensions that separate transport latency, inference latency, and robot command execution latency.

### Dockerized ROS 2 Command Path

The current `PuppyPiAdapter` uses Dockerized one-shot ROS 2 CLI calls. This is easy to inspect and reproduce, but it is not efficient for high-rate or compound robot control.

- [x] Keep Dockerized ROS 2 CLI as the first reference validation path.
- [x] Document custom PuppyPi ROS 2 CLI image build flow.
- [x] Document image freshness and controller image verification checks.
- [ ] Replace one-shot `docker run` command execution with a persistent robot control bridge.
- [ ] Add lower-latency command execution for compound or repeated robot actions.
- [ ] Add bridge-side heartbeat, timeout, cancellation, and error propagation.
- [ ] Preserve Docker CLI adapter as a fallback/debug path after the bridge exists.

## Next Work

### Documentation Cleanup

- [x] Create a release cleanup branch from the current validated baseline.
- [x] Promote the previous Stage 3 guide as `docs/validated-baseline.md`.
- [x] Add a `docs/index.md` documentation map.
- [x] Move historical Stage 1, Stage 2, Ver1, and old runbook documents under `docs/archive/`.
- [x] Rewrite `README.md` around the current validated baseline instead of the Stage 1/2/3 evolution history.
- [ ] Clarify that PuppyPi + DGX is the first validated target, not the project boundary.
- [ ] Add future target placeholders for SO-101 + DGX and Raspberry Pi ROS 2 car/camera + DGX/Thor.

### Target Expansion

- [ ] Define a target documentation template under `docs/targets/`.
- [ ] Add `docs/targets/puppypi-dgx.md` for the current validated target.
- [ ] Add an SO-101 + camera + DGX target plan.
- [ ] Add a Raspberry Pi ROS 2 car/camera + DGX/Thor target plan.
- [ ] Extend the adapter contract for target-specific capabilities beyond `STOP`, `TROT`, `HOME`, and `MOVE`.
- [ ] Add target metadata to scenarios and benchmark outputs.
- [ ] Document the Armv9 platform family positioning (DGX, Thor, future Armv9 edge nodes) across `docs/architecture.md` and `docs/arm-physical-ai-ref-workflow.md`.

### Sensor and VLA Input Path

- [ ] Define a sensor endpoint contract that is not camera-only.
- [ ] Support raw USB camera input for robot-arm validation.
- [ ] Support ROS 2 image stream input for Raspberry Pi car/camera validation.
- [ ] Add scenario support for replayed sensor input.
- [ ] Add benchmark support for VLM/VLA output quality, not just command-path success.

### UI Independence

- [ ] Keep Apache-2.0 license and attribution notices for code derived from `NVIDIA-AI-IOT/live-vlm-webui`.
- [ ] Clearly document which UI/runtime components are derived from `live-vlm-webui`.
- [ ] Avoid implying NVIDIA endorsement or official product alignment.
- [ ] Move the `/pave` console into an OpenPAVE-owned frontend module.
- [ ] Define stable OpenPAVE backend APIs for runtime state, prompt control, stream configuration, and experiment metadata.
- [ ] Keep `live-vlm-webui` available as an optional full VLM debugging UI during the transition.
- [ ] Validate the OpenPAVE-native console against PuppyPi and at least one additional hardware target.

### Persistent Robot Control Plane

- [ ] Define a persistent robot bridge contract for lower-latency robot command execution.
- [ ] Implement a long-running ROS 2 bridge process or container that owns ROS 2 service clients, publishers, and command state.
- [ ] Add a new adapter mode such as `ROBOT_ADAPTER=puppypi_ros2_bridge`.
- [ ] Route Control Daemon commands to the bridge over a stable local transport such as HTTP, gRPC, or Unix socket.
- [ ] Avoid spawning a new Docker container for every ROS 2 command in the bridge path.
- [ ] Add timeout, cancellation, heartbeat, and error propagation semantics to the bridge contract.
- [ ] Report bridge-side command timestamps so benchmarks can separate OpenPAVE dispatch latency from ROS 2 execution latency.
- [ ] Support compound command sequences without shelling out for every step.
- [ ] Document when to use Docker CLI adapter versus persistent bridge adapter.
- [ ] Validate the persistent bridge against PuppyPi first, then generalize the contract for other ROS 2 robot/sensor endpoints.

### Brain-Body Transport Upgrade

- [ ] Integrate the alternate open-source transport approach that has already been validated in a separate repo.
- [ ] Define where the transport layer sits relative to ROS 2 robot/sensor endpoints and OpenPAVE adapters.
- [ ] Keep the current ROS 2 path as a baseline comparison.
- [ ] Add transport-level health, latency, reconnect, and failure reporting.
- [ ] Add benchmark scenarios that compare ROS 2 over Wi-Fi with the upgraded transport path.
- [ ] Document which application patterns should use the baseline ROS 2 path versus the upgraded transport path.

## Release Notes

- `v1.4.0-pre-cleanup` preserves the pre-cleanup full-history baseline.
- `v1.4.0-pre-cleanup.1` includes the updated Stage 3 release validation guide and known ROS 2 DDS/RMW issue documentation.
- The `release/v1.4-validated-baseline` cleanup branch makes the current validated baseline the default project entry point.
