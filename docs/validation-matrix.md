# OpenPAVE Validation Matrix

This matrix records what has been validated in OpenPAVE and at what depth.

It should be read as an evidence map, not a marketing compatibility table. A checked row means the project has a documented implementation, experiment, runbook, or measured result. The quality of evidence still depends on the integration level and notes.

## Status Labels

| Label | Meaning |
| --- | --- |
| Baseline | Primary reproducible path with a project runbook |
| Experimental | Implemented or tested, but not the default baseline |
| Partial | Validated at a limited level or outside the full baseline flow |
| Candidate | Intended target or useful future demo, not yet validated in this repo |

## Integration Levels

| Level | Meaning |
| --- | --- |
| Level 0 | Catalogue entry only |
| Level 1 | Launch, status, or result wrapper |
| Level 2 | State or result bridge |
| Level 3 | Normalized intent / capability control contract |
| Level 4 | Benchmark integration |

## Current Matrix

| Brain-side node | Body endpoint | Inference / application layer | Seam transport | Status | Level | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| DGX Spark | PuppyPi | vLLM / OpenAI-compatible VLM | Baseline ROS 2 / adapter path | Baseline | Level 3 / partial Level 4 | `docs/validated-baseline.md`, `docs/targets/puppypi-dgx.md`, `configs/puppypi.env` |
| DGX Spark | Mock robot | none or vLLM smoke test | Local file/runtime path | Baseline | Level 3 / Level 4 control path | `configs/mock.env`, `scripts/run_benchmark.py`, `scripts/summarize_benchmarks.py` |
| DGX Spark | RPi5 camera obs → mock robot | headless inference/application plugin: `vllm_openai` runtime + `gesture_commander` app | n/a (local dispatch to mock adapter) | Validated | Level 3 headless path | Real-DGX run 2026-09-03: RPi5 `/dev/video0` frame (640×480 JPEG) → DGX `llava-hf/llava-v1.6-mistral-7b-hf` (`INFERENCE_RUNTIME=vllm_openai`, HTTP 200, ~1187 ms) → `gesture_commander` proposal `stop` → capability normalize → dispatch `completed` to mock. Dispatch is mock-only in v1.7; real robot is v1.8. `scripts/run_inference.py`, `docs/v1.7_spec.md`, `configs/mock.env` |
| Radxa O6 (Armv9) | RPi5 camera obs → mock robot | headless inference/application plugin on Armv9: `gesture_commander` app + dispatch; `vllm_openai` client → **remote** DGX vLLM | n/a (local dispatch to mock adapter) | Validated (plugin path; remote inference) | Level 3 headless path | Real-brain run 2026-09-03: Radxa O6 (`orion-o6`, aarch64) ran the runtime plugin's brain duties (inference-runtime **client** + application + dispatch). `vllm_openai` is an OpenAI-compatible client, so it called DGX `.24`'s vLLM cross-host (`INFERENCE_API_BASE=http://192.168.0.24:8000/v1`, HTTP 200, ~1000 ms) — **Radxa has no local model server yet**. Same RPi5 frame → `gesture_commander` `stop` → dispatch `completed` to mock. Validates plugin portability + inference-runtime-as-client; **local inference on Radxa is v1.8 (2nd backend)**. `scripts/run_inference.py` |
| DGX Spark | PuppyPi | VLM prompt/result path | `/pave` console + OpenAI-compatible API | Baseline | Level 2 / Level 3 UI validation | `docs/pave-console.md`, `ui` submodule |
| DGX Spark | PuppyPi | capability actions | persistent bridge | Experimental | Level 3 / Level 4 latency | `experiments/persistent-bridge/`, `ROBOT_ADAPTER=puppypi_bridge` |
| DGX Spark | PuppyPi | capability actions | raw zenoh seam plugin | Experimental | Level 3 | Real-brain run 2026-09-02: DGX brain drove real PuppyPi, home 516 / trot 1015 / stop 515 ms (`path=bridge`). `pave_runtime/seam.py`, `pave_runtime/seam_backends/zenoh_seam.py`; origin `experiments/neutral-seam/` |
| DGX Spark | PuppyPi | capability actions | device-connect seam plugin | Experimental | Level 3 | Real-brain run 2026-09-02: DGX brain drove real PuppyPi via cross-host D2D discovery, home 511 / trot 1013 / stop 514 ms (`path=bridge`). `pave_runtime/seam_backends/dc_seam.py`; origin `experiments/device-connect/` |
| DGX Spark | mock arm | manipulation capability | raw zenoh seam | Experimental | Level 3 | `experiments/capability-mve/`, `ROBOT_ADAPTER=mock_arm` |
| DGX Spark | USB camera on RPi5 | sensing capability (`get_image`) | raw_zenoh / device_connect seam plugin | Experimental | Level 2 / Level 3 | Real-brain run 2026-09-02: DGX brain got `get_image` control-plane metadata (jpeg ~98 KB, 640x480, `/dev/video0`) over BOTH transports. `configs/dgx-rpicam.env`, `scripts/seam_run.sh`; frame data plane is separate, see `experiments/camera-mve/` |
| Radxa O6 | USB camera on RPi5 | sensing capability (`get_image`) | raw_zenoh / device_connect seam plugin | Experimental | Level 2 / Level 3 | Real-brain run 2026-09-02: Radxa O6 brain got `get_image` control-plane metadata (jpeg ~99 KB, 640x480) over BOTH transports. `configs/radxa-rpicam.env`, `scripts/seam_run.sh` |
| Jetson Thor | robot/sensor endpoints | VLM/VLA workflows | target-dependent | Partial | To be documented | Experimentally validated at different levels; needs baseline-style runbook |
| Radxa O6 | PuppyPi | capability actions | raw zenoh seam plugin | Experimental | Level 3 | First real-brain validation 2026-09-02: Radxa O6 (Armv9) brain drove real PuppyPi, home 512 / trot 1013 / stop 514 ms (`path=bridge`). `pave_runtime/seam.py`, `pave_runtime/seam_backends/zenoh_seam.py` |
| Radxa O6 | PuppyPi | capability actions | device-connect seam plugin | Experimental | Level 3 | First real-brain validation 2026-09-02: Radxa O6 brain drove real PuppyPi via cross-host D2D discovery, home 511 / trot 1014 / stop 514 ms (`path=bridge`). `pave_runtime/seam_backends/dc_seam.py` |
| Radxa O6 | robot/sensor endpoints | VLM/VLA workflows | target-dependent | Partial | To be documented | Seam control path validated (rows above); VLM/VLA inference workflow still needs a baseline-style runbook on this target |
| Other Arm-based edge nodes | robot/sensor endpoints | VLM/VLA workflows | target-dependent | Partial | To be documented | Experimentally validated at different levels; evidence should be added per target |
| SO-101 robot arm + camera | SO-101 | VLA manipulation / policy | To be selected | Candidate | Level 0 / Level 1 first | Planned demo catalogue and integration notes |
| Raspberry Pi ROS 2 car/camera | RPi car/camera | VLM/VLA or perception-to-action workflow | To be selected | Candidate | Level 0 / Level 1 first | Planned demo catalogue and integration notes |

## Current Performance Evidence

| Path | Evidence | Notes |
| --- | --- | --- |
| PuppyPi Dockerized ROS 2 CLI | Validated baseline | Simple and reproducible; not optimized for high-rate control |
| PuppyPi persistent bridge | `experiments/persistent-bridge/b2_result.md` | Experimental path with measured real-robot latency improvements and fallback |
| Mock control-path benchmark | `scripts/run_benchmark.py`, `scripts/summarize_benchmarks.py` | Repeatable software-only validation and gate checks |
| `/pave` text-only inference | `POST /api/pave/infer` | Validates vLLM/OpenAI-compatible API and UI prompt/result path without camera input |
| Camera sensing MVE | `experiments/camera-mve/` | Validates control-plane / data-plane split for a USB camera |
| Seam plugin real-brain latency | Real-brain runs 2026-09-02 (see subsection below) | Across DGX and Radxa O6 brains and both transports, `latency_ms` is ~514 ms (home/stop) and ~1013 ms (trot), all `path=bridge`. Latency is dominated by the body-side bridge / `puppy_control`. |
| Seam latency breakdown | `docs/latency-model.md`, `scripts/seam_bench.py` | Three-segment model: steady-state seam wire ~0.6 ms/action; a ~0.5 s one-time session setup (per-call in the current CLI); execution bridge-dominated. |

## Real-Brain Seam Plugin Validation (2026-09-02)

To reproduce this section end to end, follow `docs/seam-validation-runbook.md` (install deps, deploy with `scripts/deploy_seam.sh`, run with `scripts/seam_run.sh`).

This run promoted the seam from experiment code to a transport plugin (`pave_runtime.seam.create_seam_transport`) and validated it with **real brains driving a real robot**. Two brains (DGX Spark, Radxa O6) each drove the physical PuppyPi over both transports, using the **same** `scripts/seam_cli.py` and the **same** `puppypi_bridge` adapter — only `SEAM_TRANSPORT` (and the brain host) changed. No body or brain code was modified between cells.

Body-side `latency_ms` per cell (`home` / `trot` / `stop`), all `path=bridge`:

| Brain (real) | `raw_zenoh` | `device_connect` (D2D) |
| --- | --- | --- |
| DGX Spark | 516 / 1015 / 515 ms | 511 / 1013 / 514 ms |
| Radxa O6 (Armv9, first validation) | 512 / 1013 / 514 ms | 511 / 1014 / 514 ms |

Every cell returned `status=completed`, `path=bridge`, and was camera-confirmed (trot gait → stop stance) via the RPi5 USB camera.

Findings:

- **The seam is insensitive to both brain and transport.** All four cells land within a few ms of each other; latency is set by the body-side bridge / `puppy_control`, not the seam or the brain. The three-segment split (`inference + seam + execution`, see `docs/latency-model.md`) is: inference out of scope here; **seam steady-state ~0.6 ms** per action, but a **~0.5 s one-time session setup** that the per-call `seam_cli.py send` pays every call (removable with a persistent brain session); execution ~514 ms home/stop, ~1013 ms trot (bridge-dominated).
- **Cross-host `device_connect` D2D works with zero infrastructure.** DGX and Radxa brains discovered the PuppyPi `openpave-body` over zenoh multicast presence on the LAN — no fabric server, no registry.
- **Radxa O6 (Armv9) is validated as a real brain** over both transports for the seam control path.
- **Brain-side deployment is light:** the brain needs only `pave_runtime/` (~9 KB) plus `zenoh` / `device-connect-agent-tools`; `scripts/seam_cli.py` imports the adapter lazily, so the brain does not need `control_daemon`.
- **Known behavior:** `raw_zenoh` opens a fresh zenoh session per `send`, so discovery can occasionally miss within the settle window (observed once on `stop`); an immediate resend succeeds. A long-lived brain session would remove this.

### Sensing endpoint over the seam (RPi5 USB camera)

The same plugin also carries a **sensing** capability. Using four-dimension recipes (`configs/dgx-rpicam.env`, `configs/radxa-rpicam.env`) with the one-command launcher `scripts/seam_run.sh`, both brains drove the RPi5 USB camera (`ROBOT_ADAPTER=camera_usb`) over both transports. `get_image` returned real **control-plane metadata** for a freshly grabbed 640×480 JPEG:

| Brain (real) | `raw_zenoh` | `device_connect` (D2D) |
| --- | --- | --- |
| DGX Spark | jpeg 98,223 B | jpeg 97,070 B |
| Radxa O6 | jpeg 99,935 B | jpeg 98,694 B |

Every cell returned `status=completed` with `{encoding: jpeg, width: 640, height: 480, source: /dev/video0, seq}`. The **frame bytes travel on a separate data plane** (see `experiments/camera-mve/`); the seam plugin and `seam_run.sh` carry only the control plane — the intended control/data-plane split for sensing. This confirms the seam spans **actuator and sensor** body endpoints, across both brains and both transports, driven entirely by config recipes.

### Per-config runbook re-validation (2026-09-02)

Every seam config was re-validated end to end through the **documented** path (`deploy_seam.sh` +
`seam_run.sh`, per-config runbooks under `docs/runbooks/`) on **clean release checkouts** — the
PuppyPi (`.6`) and RPi5 (`.21`) were re-cloned to `v1.5.0-seam` first, confirming a fresh clone
reproduces. Each combo passed on both transports:

| Config | Runbook | raw_zenoh | device_connect |
| --- | --- | --- | --- |
| `dgx-puppypi` (actuator) | `docs/runbooks/dgx-puppypi.md` | ✅ home/trot/stop, `path=bridge` | ✅ |
| `radxa-puppypi` (actuator) | `docs/runbooks/radxa-puppypi.md` | ✅ home/trot/stop, `path=bridge` | ✅ |
| `dgx-rpicam` (sensor) | `docs/runbooks/dgx-rpicam.md` | ✅ `get_image` jpeg ~130 KB | ✅ |
| `radxa-rpicam` (sensor) | `docs/runbooks/radxa-rpicam.md` | ✅ `get_image` jpeg ~130 KB | ✅ |

**Gesture control (baseline, `docs/runbooks/puppypi-gesture-control.md`)**: the DGX runtime (`run_openpave.sh` →
`intent_ingress` + `control_daemon` + `/pave`) came up; vLLM inference works; DGX drove the real dog
by ROS 2 cross-host (`TROT`/`STOP` intent → `adapter=puppypi` → completed). The **live end-to-end
gesture is pending a robot-camera stream** — the scenario references `http://<robot>:8080/stream` but
the repo ships no `web_video_server` / camera-stream launch (open gap); a browser webcam works as an
interim source.

## Matrix Maintenance Rules

- Add a row when a new hardware, transport, adapter, inference runtime, or demo path is validated.
- Prefer explicit status labels over vague claims.
- Link each row to a runbook, config, experiment note, benchmark output, or reproducible script.
- Do not mark a platform as Baseline until it has a clear reproduction guide in this repository.
- Keep external or collaborator validation as Partial until the validation depth and environment are documented.

