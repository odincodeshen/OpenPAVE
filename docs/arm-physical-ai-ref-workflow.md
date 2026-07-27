# Arm Physical AI Reference Workflow

## Purpose

This document describes OpenPAVE from an Arm/Linux Physical AI ecosystem perspective.

It is a project-level reference workflow note. It is not an official Arm position, product statement, endorsement, or architecture specification.

## Positioning

OpenPAVE is a local-first validation workflow for edge Physical AI experiments and brain-body co-computing.

The workflow connects:

```text
body-side robot/sensor endpoint
-> brain-side local inference/control node
-> VLM/VLA reasoning
-> normalized intent
-> robot adapter
-> robot command path
-> state, command result, and benchmark feedback
```

The current validated target is PuppyPi + DGX. That target proves the workflow, but it is not the project boundary.

## Why This Matters for the Arm Ecosystem

Arm-based Linux systems are widely used as robot endpoints, embedded controllers, edge gateways, and developer-accessible robotics platforms.

DGX (Armv9 Grace CPU + Nvidia GPU) and Thor are both Armv9 platforms. OpenPAVE validates the feasibility of the Armv9 brain-side platform family, not a single piece of hardware: DGX is the first validated representative, and Thor and other Armv9 edge nodes are follow-on targets in the same family.

OpenPAVE aims to show how these systems can participate in local Physical AI workflows using open-source software and local inference infrastructure.

The value is not only that a robot can be controlled by VLM/VLA output. The value is that the full workflow becomes understandable, replaceable, and repeatable:

- robot/sensor endpoint integration
- local inference/control node integration
- prompt and scenario management
- intent normalization
- adapter-based robot command execution
- command result and robot state feedback
- lightweight observability UI
- benchmark and scenario replay

## Workflow Layers

### 1. Body-Side Robot / Sensor Endpoint

The body-side endpoint provides sensors, local control, and robot-specific interfaces.

Current validated target:

- PuppyPi

Planned targets:

- SO-101 robot arm with camera
- Raspberry Pi ROS 2 car/camera
- additional robots, sensors, or simulation endpoints

### 2. Brain-Side Local Inference / Control Node

The brain-side node runs local VLM/VLA inference, runtime services, UI, and benchmark tooling.

Brain-side hardware is not limited to DGX. DGX, Thor, and future targets share the Armv9 architecture family.

Current validated target:

- DGX (Armv9 Grace CPU + Nvidia GPU) running vLLM and OpenPAVE runtime services

Planned targets (Armv9 family):

- Thor
- additional Armv9-based edge inference/control nodes
- other OpenAI-compatible local VLM serving stacks

### 3. Intent Contract Layer

The intent contract translates model/user output into a stable runtime command format.

Current status:

- intent schema v0.1 implemented
- `STOP`, `TROT`, `HOME`, and `MOVE` supported
- metadata and validation rules implemented
- unsafe or unknown output maps toward safe behavior

### 4. Robot Adapter Layer

The robot adapter maps normalized intents to target-specific control calls.

Current status:

- `MockAdapter`
- `PuppyPiAdapter`
- Dockerized ROS 2 CLI path for PuppyPi validation

Expected evolution:

- target-specific adapters for SO-101 and Raspberry Pi ROS 2 car/camera
- richer capability contracts
- persistent robot bridge for lower-latency command execution

### 5. Observability Layer

The observability layer helps developers see what the system is doing.

Current status:

- `/pave` console
- live stream area
- prompt/result panels
- parsed intent
- command result
- robot state
- system metrics

Expected evolution:

- OpenPAVE-native console decoupled from `live-vlm-webui`
- richer target metadata
- transport health and latency visibility

### 6. Experimentation Layer

The experimentation layer makes validation repeatable.

Current status:

- prompt presets
- scenario definitions
- control-path benchmark harness
- JSONL benchmark outputs
- summary and gate checks

Expected evolution:

- sensor replay
- VLM/VLA output quality benchmarks
- transport latency benchmarks
- multi-target comparison

## Current Baseline and Future Work

Validated Baseline v1.0 is intentionally simple and reproducible. It validates the integration path before optimizing brain-body transport, control latency, and hardware coverage.

Known future work:

- improve brain-body transport beyond the current ROS 2 over Wi-Fi reference path
- replace one-shot Dockerized ROS 2 CLI command execution with a persistent robot bridge
- add SO-101 and Raspberry Pi ROS 2 car/camera targets
- add sensor replay and end-to-end VLM/VLA quality benchmarks
- decouple the OpenPAVE console from `live-vlm-webui`

## Non-Goals

OpenPAVE is not intended to be:

- an official Arm reference design
- a commercial robot control stack
- a complete autonomous robotics platform
- a replacement for vendor-specific robotics SDKs
- an LLM serving framework like vLLM or Ollama

OpenPAVE is intended to be a practical, open, local-first validation workflow for developers exploring edge Physical AI systems.
