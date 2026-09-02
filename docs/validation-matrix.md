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
| DGX Spark | PuppyPi | capability actions | raw zenoh neutral seam | Experimental | Level 3 | `experiments/neutral-seam/` |
| DGX Spark | PuppyPi | capability actions | device-connect seam | Experimental | Level 3 | `experiments/device-connect/` |
| DGX Spark | mock arm | manipulation capability | raw zenoh seam | Experimental | Level 3 | `experiments/capability-mve/`, `ROBOT_ADAPTER=mock_arm` |
| DGX Spark | USB camera on RPi5 | sensing capability | zenoh control/data plane split | Experimental | Level 2 / Level 3 | `experiments/camera-mve/`, `ROBOT_ADAPTER=camera_usb` |
| Jetson Thor | robot/sensor endpoints | VLM/VLA workflows | target-dependent | Partial | To be documented | Experimentally validated at different levels; needs baseline-style runbook |
| Radxa O6 | robot/sensor endpoints | VLM/VLA workflows | target-dependent | Partial | To be documented | Experimentally validated at different levels; needs baseline-style runbook |
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

## Matrix Maintenance Rules

- Add a row when a new hardware, transport, adapter, inference runtime, or demo path is validated.
- Prefer explicit status labels over vague claims.
- Link each row to a runbook, config, experiment note, benchmark output, or reproducible script.
- Do not mark a platform as Baseline until it has a clear reproduction guide in this repository.
- Keep external or collaborator validation as Partial until the validation depth and environment are documented.

