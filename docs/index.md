# OpenPAVE Documentation Index

OpenPAVE documentation is organized around the current validated baseline, demo integration levels, reusable runtime contracts, experimental transport work, and historical archive material.

## Start Here

- [Quickstart](quickstart.md) · [快速上手](quickstart.zh-TW.md): **new here? start with this** — five minutes to what OpenPAVE is, how to run it, and which doc to read next.
- [OpenPAVE Platform Specification](openpave-platform-spec.md): project specification, goals, four-dimensional model, repository policy, and roadmap.
- [v1.7 Inference/Application Runtime Plugin Specification](v1.7_spec.md): construction specification for the headless inference and application plugin boundary.
- [v1.8 Live Body](v1.8-live-body.md): experimental PuppyPi HTTP/MJPEG observation input and live-body integration status.
- [Validation Matrix](validation-matrix.md): evidence map for validated, experimental, partial, and candidate hardware/workflow combinations.
- [Seam Validation Runbook](seam-validation-runbook.md): reproduce the real-brain seam matrix (brain × body × transport) with the four-dimension config recipes, `deploy_seam.sh`, and `seam_run.sh`.
- [Seam Latency Model](latency-model.md): three-segment (inference / seam / execution) latency breakdown with measured numbers and `seam_bench.py`.
- [Validated Baseline](validated-baseline.md): primary runbook for reproducing OpenPAVE Validated Baseline v1.0.
- [Demo Integration Levels](demo-integration-levels.md): how Physical AI demos can join OpenPAVE at different depths.
- [Demo Catalogue](demo-catalog.md): current validated, experimental, and candidate demos.
- [Further Work](further-work.md): roadmap, known limitations, and contribution opportunities.

## For Demo Contributors

- [Contributing Demos](contributing-demos.md): how to describe a demo, choose an integration level, and add optional launch/status/result hooks.
- [Demo Integration Levels](demo-integration-levels.md): Level 0 catalogue entries through Level 4 benchmark integration.
- [Robot Adapters](robot-adapters.md): capability-declarative adapter boundary (locomotion / manipulation / sensing), including `PuppyPiLocalAdapter` and the experimental `puppypi_bridge`.
- [Benchmark Harness](benchmark-harness.md): control-path benchmark runner and summary tooling.

## Architecture and Positioning

- [OpenPAVE Platform Specification](openpave-platform-spec.md): two-layer brain/body architecture, one seam, four-dimensional model, and roadmap.
- [Brain-Body Architecture](architecture-brain-body.md): the brain/body split, the seam diagram, and the glossary for intent, capability, state, and the control contract.
- [Validation Matrix](validation-matrix.md): validation status by brain-side node, body endpoint, inference/application layer, and seam transport.
- [Ecosystem Validation Map](ecosystem-validation-map.md): how OpenPAVE helps validate, showcase, compare, and port Physical AI software components.
- [Physical AI Validation Workflow](physical-ai-validation-workflow.md): project-level positioning for OpenPAVE across local inference, robot/sensor endpoints, middleware, and Arm-based edge platforms.

## Runtime Contracts

- [Intent Schema](intent-schema.md): normalized intent schema v0.1, now generalized into a capability-declarative contract.
- [Robot Feedback](robot-feedback.md): command result and robot state feedback files.
- [Prompts and Scenarios](prompts-and-scenarios.md): repo-managed prompt presets and scenario definitions.
- [OpenPAVE Console](pave-console.md): `/pave` console, runtime feedback, and live-vlm-webui reuse boundary.

## Target and Demo Notes

- [PuppyPi + DGX Target](targets/puppypi-dgx.md): hardware-specific notes for the first validated target.
- [zenoh MVE](../experiments/zenoh-mve/README.md): experimental brain-body transport smoke test.
- [zenoh Hardware Runbook](../experiments/zenoh-mve/zenoh_test.md): DGX/RPi bring-up commands and validation notes.
- [PuppyPi Real-Adapter Run](../experiments/zenoh-mve/puppypi_test.md): real PuppyPi validation over zenoh with the local PuppyPi adapter.
- [Capability MVE](../experiments/capability-mve/README.md): capability-declarative model over the same seam (manipulation `mock_arm`).
- [Camera MVE](../experiments/camera-mve/README.md): sensing over the seam with a control-plane / data-plane split.
- [Persistent Bridge](../experiments/persistent-bridge/README.md): low-latency body-side bridge (A / B1 / B2) with fallback; real-robot before/after in `b2_result.md`.

## Runbooks (per config)

Self-contained, first-timer-friendly runbooks — one per validated config combination:

- [DGX → PuppyPi (seam)](runbooks/dgx-puppypi.md) · [Radxa → PuppyPi (seam)](runbooks/radxa-puppypi.md)
- [DGX → RPi5 camera (seam)](runbooks/dgx-rpicam.md) · [Radxa → RPi5 camera (seam)](runbooks/radxa-rpicam.md)
- [Gesture control (DGX brain → PuppyPi baseline, ROS 2 path — not the seam)](runbooks/puppypi-gesture-control.md)
- [v1.8 Quick Demo (general, ROS-free body: RPi 5 camera + servo, dry-run → live loop → swap to PuppyPi)](runbooks/v1.8-quick-demo.md)

## Releases

- [v1.8.1](releases/v1.8.1.md): General ROS-free body — `gpio_servo` (real-hardware validated) and `led` actuator adapters, the [v1.8 Quick Demo](runbooks/v1.8-quick-demo.md) runbook, and the protocol-neutral / adapter-is-the-integration-point spec positioning.
- [v1.8.0](releases/v1.8.0.md): Live Body — ObservationSource plugin (`--input-url`), real-body dispatch over the seam (`run_inference.py --seam`) with a motion safety gate / lease / outcome exit codes / `--action-target`, and the persistent `scripts/run_live.py` loop (multi-observation confirmation, watchdog, fail-safe STOP); real-dog validated (single-shot + live loop).
- [v1.7.0](releases/v1.7.0.md): Inference/Application runtime plugin — headless `create_inference_runtime` + `vllm_openai` backend, `gesture_commander` application, capability + safety, and `scripts/run_inference.py`; real-DGX validated (RPi5 camera → vLLM → dispatch to mock).
- [v1.6.0](releases/v1.6.0.md): Quickstart & docs — bilingual Quickstart, per-config runbooks, redesigned architecture diagram, doc reorg, and the domain-general inference-dimension positioning.
- [v1.5.0-seam](releases/v1.5.0-seam.md): seam transport plugin milestone — plugin + real-brain validation matrix (DGX + Radxa O6 × PuppyPi/camera) + config recipes, tooling, latency model, and single-source dispatch.

## Notices

- [Third-Party Notices](third-party-notices.md): third-party source and attribution notes.

## Historical Archive

Historical files are kept under `docs/archive/` for reference. They are not the primary entry point for the current repository.

- [Architecture (superseded)](archive/architecture.md) — folded into the Platform Specification + Brain-Body Architecture
- [Ver1 README](archive/pave_ver1_readme.md)
- [Stage 1 Validation Steps](archive/stage1.step.md)
- [Stage 2 Installation and Validation Steps](archive/stage2.step.md)
- [live-vlm-webui Hook Notes](archive/live-vlm-webui-hook.md)
- [Legacy Runbook](archive/runbook.md)
