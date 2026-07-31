# OpenPAVE Demo Catalogue

This catalogue tracks Physical AI demos that are validated, experimental, or planned for OpenPAVE integration. It is intentionally organized by integration level so demos can join OpenPAVE through catalogue entries, launch/status wrappers, result bridges, control contracts, or benchmark paths.

## Status Labels

- **Validated**: reproduced with documented runbooks and known limitations.
- **Experimental**: implemented or tested as an MVE, but not part of the default validated baseline.
- **Candidate**: identified as a useful future demo or integration target.

## Validated Demos

### PuppyPi + DGX Brain-Control Reference Path

```text
Status: Validated
Integration level: Level 3 / partial Level 4
Brain-side compute: DGX (Armv9 Grace CPU + Nvidia GPU)
Robot endpoint: PuppyPi quadruped
Model/backend: vLLM with OpenAI-compatible VLM API
Middleware/control: ROS 2 puppy_control through OpenPAVE robot adapters
Primary runbook: docs/validated-baseline.md
Target notes: docs/targets/puppypi-dgx.md
```

What it demonstrates:

- local VLM/VLA workflow
- `/pave` observability console
- normalized intent
- Intent Ingress and Control Daemon
- PuppyPi robot adapter
- command result and robot state feedback
- mock and physical-control-path benchmark flows

## Experimental Demos and Transport MVEs

### zenoh Brain-Body Transport MVE

```text
Status: Experimental
Integration level: Level 2 / transport MVE
Brain-side compute: DGX
Body-side endpoint: Raspberry Pi / PuppyPi body node
Transport: zenoh / rmw_zenoh
Runbook: experiments/zenoh-mve/README.md
Hardware notes: experiments/zenoh-mve/zenoh_test.md
PuppyPi notes: experiments/zenoh-mve/puppypi_test.md
```

What it demonstrates:

- separated brain/body seam
- intent downlink and state uplink
- body-side fail-safe pattern
- experimental transport path beyond the current validated baseline

## Candidate Demos

### SO-101 VLA Manipulation

```text
Status: Candidate
Suggested starting level: Level 0 or Level 1
Robot endpoint: SO-101 robot arm with camera
Model type: VLA / manipulation policy
Possible integration: catalogue entry, runbook, launch/status wrapper, high-level result summary
```

Possible OpenPAVE value:

- catalogue the demo alongside other Physical AI examples
- document hardware, model, middleware, and validation status
- optionally expose launch/status/result hooks
- optionally add state/result bridge or benchmark integration later

### Raspberry Pi ROS 2 Car / Camera

```text
Status: Candidate
Suggested starting level: Level 0 or Level 1
Robot endpoint: Raspberry Pi ROS 2 car with camera
Model type: VLM/VLA or perception-to-action policy
Possible integration: catalogue entry, sensor path notes, launch/status wrapper, result summary
```

Possible OpenPAVE value:

- validate ROS 2 image or sensor stream paths
- compare baseline ROS 2 communication with future transport options
- add motion, perception, and command-result scenarios over time

## Adding a Demo

See [Contributing Demos](contributing-demos.md) and [Demo Integration Levels](demo-integration-levels.md).
