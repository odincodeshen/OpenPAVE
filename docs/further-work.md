# OpenPAVE Further Work

OpenPAVE is an early open reference workflow for Physical AI validation and experimentation. Its current value is to connect local inference, robot/sensor endpoints, middleware, runtime feedback, observability, and benchmark paths into verifiable demos.

This document tracks validated work, experimental work, and planned feature work. It avoids the historical stage narrative except where those stages are useful context for the current baseline.

## Validated Today

### Validated Baseline v1.0

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
- `scripts/start_puppy_control.sh`: one-command PuppyPi `puppy_control` bring-up.
- `scripts/check_puppy_control.sh`: `puppy_control` health check.
- `scripts/run_benchmark.py`: scenario benchmark runner.
- `scripts/summarize_benchmarks.py`: benchmark summary and gate checker.
- `prompts/`: reusable prompt presets.
- `scenarios/`: benchmark/demo scenario definitions.
- `ui/`: OpenPAVE-maintained `live-vlm-webui` fork as a submodule.

## Experimental Now

### Brain-Body Transport

- [x] zenoh MVE documents an experimental brain/body transport path.
- [x] `PuppyPiLocalAdapter` validates co-located body-side ROS 2 execution for the PuppyPi path.
- [x] STOP-while-moving safety timeout and escalation behavior are documented for the PuppyPi local adapter.
- [ ] zenoh is not yet the default OpenPAVE runtime transport.
- [ ] Transport latency, reconnect behavior, and failure reporting need benchmark coverage.

### Capability Model (graduated into the runtime)

- [x] The command model is now **capability-declarative** (`{action, params}` + adapters declare
  `capabilities`), graduated from experiments into `pave_runtime.capability_schema` and
  `control_daemon.adapters`. The fixed `STOP/TROT/HOME/MOVE` enum is kept as a translator.
- [x] One runtime model spans **locomotion, manipulation, and sensing** — validated on real
  hardware with `mock_arm` (manipulation) and a real USB `camera` (sensing) over the same seam,
  alongside PuppyPi locomotion.
- [x] Camera sensing uses a **control-plane / data-plane split** (small metadata on the command
  channel; the JPEG on a dedicated compressed topic).
- [ ] A machine-readable capability manifest per demo is still future work.

### Persistent Robot Control Plane (implemented; experimental, not default)

- [x] **A** — batch each PuppyPi action into one `docker exec` gait runner instead of N per-call
  `ros2` CLIs (real PuppyPi STOP −45%).
- [x] **B1** — a persistent bridge (long-running rclpy node + localhost socket, service clients
  reused); mock-validated ~190×.
- [x] **B2** — `ROBOT_ADAPTER=puppypi_bridge` (experimental, **not the default**; `puppypi_local`
  stays validated) tries the bridge, else falls back to the Docker-CLI path with a cooldown;
  real PuppyPi HOME −66%, STOP p50 −81% / p95 −89%, fallback verified. Bridge server and
  `start_bridge.sh` in `experiments/persistent-bridge/`; runs `-u ubuntu` (FastDDS SHM is per-user).
- [x] Result metadata records `path` (bridge / fallback_a) + per-path latency, separating dispatch
  latency from ROS 2 execution latency (the residual ~512 ms is puppy_control's physical re-pose).
- [ ] Not yet the default; async / long-running (AMR) is a reserved-but-unimplemented protocol path.

### Demo Integration Model

- [x] OpenPAVE now defines demo integration levels from catalogue-only to benchmark integration.
- [x] PuppyPi + DGX is documented as the first validated deep-integration reference path.
- [ ] Additional demos need catalogue entries and integration notes.
- [ ] Demo metadata is currently documented as text; a machine-readable demo manifest is future work.

## Planned Feature Work

### Demo Catalogue and Integration

- [ ] Add more catalogue entries for robot arm, mobile robot, camera, and sensor demos.
- [ ] Add a target/demo documentation template.
- [ ] Add optional launch/status/result wrapper examples.
- [ ] Add a machine-readable demo manifest format.
- [ ] Add simple tooling to list demos by status, endpoint, model type, and integration level.

### Target Expansion

- [ ] Add an SO-101 + camera demo entry and integration plan.
- [ ] Add a Raspberry Pi ROS 2 car/camera demo entry and integration plan.
- [ ] Add target metadata to scenarios and benchmark outputs.
- [x] Extend the adapter contract for target-specific capabilities beyond `STOP`, `TROT`, `HOME`, and `MOVE`. (capability model)

### Capability Model

> **Core implemented and graduated into the runtime** — see *Experimental Now*. Status:

- [x] Define how robot/sensor endpoints declare capabilities. (adapters expose `capabilities`)
- [x] Capture motion, manipulation, sensing, and safety stop. (locomotion / manipulation / sensing + common stop/estop/home)
- [x] Map normalized intent to target-specific capabilities. (`intent_to_capability_action`)
- [ ] Use capabilities to decide which scenarios are valid for each demo.

### Sensor and VLA Input Path

- [ ] Define a sensor endpoint contract that is not camera-only.
- [x] Support raw USB camera input for robot-arm validation. (camera MVE: `get_image` over the seam)
- [ ] Support ROS 2 image stream input for Raspberry Pi car/camera validation.
- [x] Add high-bandwidth sensor/data plane documentation. (control-plane / data-plane split, camera MVE)
- [ ] Add scenario support for replayed sensor input.
- [ ] Add benchmark support for VLM/VLA output quality, not just command-path success.

### Persistent Robot Control Plane

> **Implemented and real-robot validated (A / B1 / B2)** — see the summary under *Experimental Now*.
> Status of the original items:

- [x] Define a persistent robot bridge contract for lower-latency robot command execution.
- [x] Implement a long-running ROS 2 bridge process that owns ROS 2 service clients and command state.
- [x] Add a new adapter mode (`ROBOT_ADAPTER=puppypi_bridge`).
- [x] Route Control Daemon commands to the bridge over a stable local transport (TCP localhost; Unix socket supported).
- [x] Avoid spawning a new Docker container for every ROS 2 command in the bridge path.
- [x] Add timeout, cooldown, and error propagation to the bridge contract. (cancellation / heartbeat still reserved)
- [x] Report path + per-path latency so benchmarks separate dispatch latency from ROS 2 execution latency.
- [x] Support compound command sequences without shelling out for every step.
- [x] Validate the persistent bridge against PuppyPi first (real robot, `.17`).
- [ ] Document when to use the Docker-CLI adapter versus the persistent bridge adapter; generalize the contract to other ROS 2 endpoints.

### Brain-Body Transport Upgrade

- [ ] Integrate an alternate open-source transport path into the OpenPAVE runtime when ready.
- [ ] Define where the transport layer sits relative to ROS 2 robot/sensor endpoints and OpenPAVE adapters.
- [ ] Keep the current ROS 2 path as a baseline comparison.
- [ ] Add transport-level health, latency, reconnect, and failure reporting.
- [ ] Add benchmark scenarios that compare ROS 2 over Wi-Fi with upgraded transport paths.
- [ ] Document which application patterns should use the baseline ROS 2 path versus an upgraded transport path.

### UI Independence

- [ ] Keep Apache-2.0 license and attribution notices for code derived from `NVIDIA-AI-IOT/live-vlm-webui`.
- [ ] Clearly document which UI/runtime components are derived from `live-vlm-webui`.
- [ ] Avoid implying NVIDIA endorsement or official product alignment.
- [ ] Move the `/pave` console into an OpenPAVE-owned frontend module.
- [ ] Define stable OpenPAVE backend APIs for runtime state, prompt control, stream configuration, and experiment metadata.
- [ ] Keep `live-vlm-webui` available as an optional full VLM debugging UI during the transition.
- [ ] Validate the OpenPAVE-native console against PuppyPi and at least one additional hardware target.

## Known Limitations

- The current **default** PuppyPi command path uses Dockerized one-shot ROS 2 CLI calls — simple and
  reproducible. An experimental **low-latency path now exists** (`ROBOT_ADAPTER=puppypi_bridge`,
  persistent bridge; see *Experimental Now*) with automatic fallback to the CLI path, but it is not
  yet the default.
- ROS 2 over Wi-Fi and DDS/RMW behavior can vary by machine, network, container image, and firewall settings.
- The validated default RMW path remains `rmw_fastrtps_cpp`; `rmw_cyclonedds_cpp` is documented as an environment-specific workaround.
- Current benchmark coverage focuses on control-path validation; full sensor/VLM/VLA quality replay is future work.
- Multi-robot and multi-sensor routing are not implemented in the validated baseline yet.

## Release Notes

- `v1.4.0-pre-cleanup` preserves the pre-cleanup full-history baseline.
- `v1.4.0-pre-cleanup.1` includes the updated Stage 3 release validation guide and known ROS 2 DDS/RMW issue documentation.
- The `release/v1.4-validated-baseline` cleanup branch makes the current validated baseline the default project entry point.
