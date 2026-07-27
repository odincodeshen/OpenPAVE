# OpenPAVE Documentation Index

OpenPAVE documentation is organized around the current validated baseline, reusable runtime contracts, target-specific validation notes, and historical archive material.

## Start Here

- [Validated Baseline](validated-baseline.md): primary runbook for reproducing OpenPAVE Validated Baseline v1.0.
- [PuppyPi + DGX Target](targets/puppypi-dgx.md): hardware-specific notes for the first validated target.
- [Further Work](further-work.md): roadmap, known limitations, and planned target/transport/runtime upgrades.

## Architecture and Positioning

- [Architecture](architecture.md): current brain-side, body-side, runtime, feedback, and benchmark roles.
- [Arm Physical AI Reference Workflow](arm-physical-ai-ref-workflow.md): non-official Arm/Linux ecosystem reference perspective.

## Runtime Contracts

- [Intent Schema](intent-schema.md): normalized intent schema v0.1.
- [Robot Adapters](robot-adapters.md): adapter boundary and current `MockAdapter` / `PuppyPiAdapter`.
- [Robot Feedback](robot-feedback.md): command result and robot state feedback files.

## Experiment Assets

- [Benchmark Harness](benchmark-harness.md): control-path benchmark runner and summary tooling.
- [Prompts and Scenarios](prompts-and-scenarios.md): repo-managed prompt presets and scenario definitions.
- [OpenPAVE Console](pave-console.md): `/pave` console, runtime feedback, and live-vlm-webui reuse boundary.

## Notices

- [Third-Party Notices](third-party-notices.md): third-party source and attribution notes.

## Historical Archive

Historical files are kept under `docs/archive/` for reference. They are not the primary entry point for the current repository.

- [Ver1 README](archive/pave_ver1_readme.md)
- [Stage 1 Validation Steps](archive/stage1.step.md)
- [Stage 2 Installation and Validation Steps](archive/stage2.step.md)
- [live-vlm-webui Hook Notes](archive/live-vlm-webui-hook.md)
- [Legacy Runbook](archive/runbook.md)
