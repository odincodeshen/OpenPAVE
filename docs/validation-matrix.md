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
| DGX Spark | PuppyPi | VLM prompt/result path | `/pave` console + OpenAI-compatible API | Baseline | Level 2 / Level 3 UI validation | `docs/pave-console.md`, `ui` submodule |
| DGX Spark | PuppyPi | capability actions | persistent bridge | Experimental | Level 3 / Level 4 latency | `experiments/persistent-bridge/`, `ROBOT_ADAPTER=puppypi_bridge` |
| DGX Spark | PuppyPi | capability actions | raw zenoh seam plugin | Experimental | Level 3 | Real-brain run 2026-09-02: DGX brain drove real PuppyPi, home 516 / trot 1015 / stop 515 ms (`path=bridge`). `pave_runtime/seam.py`, `pave_runtime/seam_backends/zenoh_seam.py`; origin `experiments/neutral-seam/` |
| DGX Spark | PuppyPi | capability actions | device-connect seam plugin | Experimental | Level 3 | Real-brain run 2026-09-02: DGX brain drove real PuppyPi via cross-host D2D discovery, home 511 / trot 1013 / stop 514 ms (`path=bridge`). `pave_runtime/seam_backends/dc_seam.py`; origin `experiments/device-connect/` |
| DGX Spark | mock arm | manipulation capability | raw zenoh seam | Experimental | Level 3 | `experiments/capability-mve/`, `ROBOT_ADAPTER=mock_arm` |
| DGX Spark | USB camera on RPi5 | sensing capability | zenoh control/data plane split | Experimental | Level 2 / Level 3 | `experiments/camera-mve/`, `ROBOT_ADAPTER=camera_usb` |
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
| Seam plugin real-brain latency | Real-brain runs 2026-09-02 (see subsection below) | Across DGX and Radxa O6 brains and both transports, `latency_ms` is ~514 ms (home/stop) and ~1013 ms (trot), all `path=bridge`. The seam and brain add negligible cost; latency is dominated by the body-side bridge / `puppy_control`. |

## Real-Brain Seam Plugin Validation (2026-09-02)

This run promoted the seam from experiment code to a transport plugin (`pave_runtime.seam.create_seam_transport`) and validated it with **real brains driving a real robot**. Two brains (DGX Spark, Radxa O6) each drove the physical PuppyPi over both transports, using the **same** `scripts/seam_cli.py` and the **same** `puppypi_bridge` adapter — only `SEAM_TRANSPORT` (and the brain host) changed. No body or brain code was modified between cells.

Body-side `latency_ms` per cell (`home` / `trot` / `stop`), all `path=bridge`:

| Brain (real) | `raw_zenoh` | `device_connect` (D2D) |
| --- | --- | --- |
| DGX Spark | 516 / 1015 / 515 ms | 511 / 1013 / 514 ms |
| Radxa O6 (Armv9, first validation) | 512 / 1013 / 514 ms | 511 / 1014 / 514 ms |

Every cell returned `status=completed`, `path=bridge`, and was camera-confirmed (trot gait → stop stance) via the RPi5 USB camera.

Findings:

- **The seam is insensitive to both brain and transport.** All four cells land within a few ms of each other; latency is set by the body-side bridge / `puppy_control`, not the seam or the brain. The effective three-segment split is `inference (out of scope here) + seam (~0) + execution (~514 ms home/stop, ~1013 ms trot)`.
- **Cross-host `device_connect` D2D works with zero infrastructure.** DGX and Radxa brains discovered the PuppyPi `openpave-body` over zenoh multicast presence on the LAN — no fabric server, no registry.
- **Radxa O6 (Armv9) is validated as a real brain** over both transports for the seam control path.
- **Brain-side deployment is light:** the brain needs only `pave_runtime/` (~9 KB) plus `zenoh` / `device-connect-agent-tools`; `scripts/seam_cli.py` imports the adapter lazily, so the brain does not need `control_daemon`.
- **Known behavior:** `raw_zenoh` opens a fresh zenoh session per `send`, so discovery can occasionally miss within the settle window (observed once on `stop`); an immediate resend succeeds. A long-lived brain session would remove this.

## Matrix Maintenance Rules

- Add a row when a new hardware, transport, adapter, inference runtime, or demo path is validated.
- Prefer explicit status labels over vague claims.
- Link each row to a runbook, config, experiment note, benchmark output, or reproducible script.
- Do not mark a platform as Baseline until it has a clear reproduction guide in this repository.
- Keep external or collaborator validation as Partial until the validation depth and environment are documented.

