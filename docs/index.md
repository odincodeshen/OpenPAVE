# OpenPAVE Documentation Index

OpenPAVE documentation is organized around the current validated baseline, reusable runtime contracts, target-specific validation notes, and historical archive material.

## Start Here

- [Validated Baseline](validated-baseline.md): primary runbook for reproducing OpenPAVE Validated Baseline v1.0.
- [PuppyPi + DGX Target](targets/puppypi-dgx.md): hardware-specific notes for the first validated target.
- [Further Work](further-work.md): roadmap, known limitations, and planned target/transport/runtime upgrades.

## Architecture and Positioning

- [Architecture](architecture.md): current brain-side, body-side, runtime, feedback, and benchmark roles.
- [Brain-Body Architecture](architecture-brain-body.md): latest high-level brain/body split, transport diagram, and glossary for intent, RPC, state, and the control contract.
- [Arm Physical AI Reference Workflow](arm-physical-ai-ref-workflow.md): non-official Arm/Linux ecosystem reference perspective.

## Runtime Contracts

- [Intent Schema](intent-schema.md): normalized intent schema v0.1.
- [Robot Adapters](robot-adapters.md): adapter boundary and current `MockAdapter` / `PuppyPiAdapter`.
- [Robot Feedback](robot-feedback.md): command result and robot state feedback files.

## Experiment Assets

- [Benchmark Harness](benchmark-harness.md): control-path benchmark runner and summary tooling.
- [Prompts and Scenarios](prompts-and-scenarios.md): repo-managed prompt presets and scenario definitions.
- [OpenPAVE Console](pave-console.md): `/pave` console, runtime feedback, and live-vlm-webui reuse boundary.

## Experimental Brain-Body Transport

- [zenoh MVE](../experiments/zenoh-mve/README.md): experimental brain-body transport smoke test.
- [zenoh Hardware Runbook](../experiments/zenoh-mve/zenoh_test.md): DGX/RPi bring-up commands and validation notes.
- [PuppyPi Real-Adapter Run](../experiments/zenoh-mve/puppypi_test.md): real PuppyPi validation over zenoh with the local PuppyPi adapter.

## Notices

- [Third-Party Notices](third-party-notices.md): third-party source and attribution notes.

## Historical Archive

Historical files are kept under `docs/archive/` for reference. They are not the primary entry point for the current repository.

- [Ver1 README](archive/pave_ver1_readme.md)
- [Stage 1 Validation Steps](archive/stage1.step.md)
- [Stage 2 Installation and Validation Steps](archive/stage2.step.md)
- [live-vlm-webui Hook Notes](archive/live-vlm-webui-hook.md)
- [Legacy Runbook](archive/runbook.md)
