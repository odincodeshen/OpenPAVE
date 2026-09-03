# OpenPAVE Architecture

## Purpose

OpenPAVE is an open reference workflow for Physical AI validation and experimentation.

The architecture helps developers validate how local inference, robot or sensor endpoints, middleware, runtime feedback, observability, and benchmark paths fit together.

PuppyPi + DGX is the first validated deep-integration target, not the project boundary. Other demos can join OpenPAVE at lighter integration levels, such as catalogue-only entries, launch/status wrappers, or result bridges.

## Current Architecture

```mermaid
flowchart LR
    subgraph Body["Body Side: Robot / Sensor Endpoint"]
        Sensor["Sensor stream\ncamera today, future raw USB / ROS 2 image / lidar / audio"]
        Controller["Robot-side controller\nROS 2 services/topics today"]
    end

    subgraph Brain["Brain Side: Local Inference / Control Node"]
        Console["OpenPAVE /pave Console"]
        VLM["OpenAI-compatible VLM/VLA backend\nvLLM today"]
        Ingress["Intent Ingress\nHTTP /intent"]
        Schema["Intent Schema\nv0.1"]
        Daemon["Control Daemon"]
        Adapter["Robot Adapter\nMockAdapter / PuppyPiAdapter"]
        Feedback["Command Result\nRobot State"]
        Bench["Benchmark Harness"]
    end

    Sensor --> Console
    Console --> VLM
    VLM --> Console
    Console --> Ingress
    Ingress --> Schema --> Daemon --> Adapter --> Controller
    Daemon --> Feedback --> Console
    Bench --> Ingress
    Feedback --> Bench
```

## Replaceable Roles

### Body Side: Robot / Sensor Endpoint

This role provides physical-world observations and accepts control commands.

Responsibilities:

- expose camera, raw USB, ROS 2 image, depth, audio, lidar, robot state, or other sensor streams
- run robot-side controllers, ROS 2 services/topics, or a persistent bridge process (experimental)
- receive commands from an OpenPAVE adapter (Docker-CLI path or the experimental persistent bridge)
- execute physical or simulated robot actions

Current validation:

- PuppyPi
- PuppyPi camera stream
- `puppy_control` ROS 2 services and topics

Planned targets:

- SO-101 robot arm with camera + DGX
- Raspberry Pi ROS 2 car/camera + DGX or Thor
- additional robot/sensor endpoints with OpenPAVE adapters

### Brain Side: Local Inference / Control Node

This role runs inference, runtime control services, observability, and benchmarks.

Responsibilities:

- run VLM/VLA inference through an OpenAI-compatible API
- display live robot/sensor streams
- manage prompts and observe model outputs
- normalize high-level intent
- dispatch validated commands through adapters
- expose command result and robot state feedback
- run benchmark scenarios

Brain-side hardware is not limited to DGX. DGX, Thor, and future targets share the Armv9 architecture family.

Current validation:

- DGX (Armv9 Grace CPU + Nvidia GPU)
- vLLM
- `llava-hf/llava-v1.6-mistral-7b-hf`
- OpenPAVE `/pave` console through the `ui/` submodule

Future targets (Armv9 family):

- Thor
- other Armv9-based edge inference/control nodes
- local VLM serving stacks compatible with OpenAI-style APIs
- future GPU/NPU/VPU inference runtimes

### OpenPAVE Runtime Control Layer

The runtime control layer turns high-level model or user intent into validated robot commands.

Current components:

- Intent Ingress API
- normalized intent schema
- Control Daemon
- `MockAdapter`
- `PuppyPiAdapter`
- command result feedback
- robot state feedback
- benchmark harness

## Current Baseline Path

Validated Baseline v1.0 uses a simple, inspectable command path:

```text
OpenPAVE /pave or benchmark
-> Intent Ingress
-> normalized intent
-> Control Daemon
-> Robot Adapter
-> Dockerized ROS 2 CLI
-> robot-side ROS 2 controller
```

This path favors reproducibility and debuggability over low-latency robot control.

## Demo Integration Levels

Not every Physical AI demo needs to use the full baseline path. OpenPAVE supports progressive integration:

```text
Level 0: Catalogue only
Level 1: Launch / status / result wrapper
Level 2: State or result bridge
Level 3: Normalized intent / control contract
Level 4: Benchmark integration
```

The PuppyPi + DGX baseline demonstrates the deep-integration path. Demos with their own runtime, model policy, control loop, or hardware workflow can start at Level 0 or Level 1 and deepen integration only where it is useful.

## Current Limitations

### Brain-Body Transport

The current PuppyPi target uses ROS 2 communication over the available network path. This is the baseline communication path, not the final optimized brain-body transport layer.

A **zenoh brain/body transport** has been explored as an MVE (`experiments/zenoh-mve/`, E1a/E1b/E2 + real PuppyPi). An upgraded transport is not yet the default runtime path; latency/reconnect benchmarking is still open.

### Robot Command Execution

The **default** `PuppyPiAdapter` uses one-shot Dockerized ROS 2 CLI calls — reproducible and easy to debug.

An experimental **low-latency path is now implemented and real-robot validated**: a persistent
body-side bridge (`ROBOT_ADAPTER=puppypi_bridge`) keeps ROS 2 service clients connected and executes
commands over a localhost socket, **falling back to the Docker-CLI path automatically**. On PuppyPi
it cut HOME −66% and STOP p95 −89%. It stays experimental (not the default; `puppypi_local` remains
the validated path). See `experiments/persistent-bridge/`.

## Interfaces

### Intent Ingress API

`POST /intent`:

```json
{ "text": "STOP" }
```

or:

```json
{
  "intent": "MOVE",
  "params": {
    "vx": 0.0,
    "yaw": 0.6,
    "duration_ms": 600
  },
  "source": "manual"
}
```

### Runtime Feedback

Default runtime feedback files:

```text
.openpave/runtime/vla_command_result.json
.openpave/runtime/vla_robot_state.json
```

Legacy or manually configured runs may still use:

```text
/tmp/vla_command_result.json
/tmp/vla_robot_state.json
```

### Inference Backend

The first inference backend contract is an OpenAI-compatible VLM API.

Current default:

```text
http://localhost:8000/v1
```

## Design Notes

- PuppyPi + DGX is the first validated deep-integration target, not the final hardware boundary.
- Demo integration levels let demos join OpenPAVE without adopting the full baseline runtime path.
- Robot adapters are the current contribution surface for new hardware.
- Sensor assumptions should be explicit in prompts, scenarios, and benchmarks.
- `ROS_DOMAIN_ID` and `RMW_IMPLEMENTATION` must match across ROS 2 participants.
- DDS/RMW behavior can vary by network, Docker image, firewall, and machine configuration.
- Current benchmark coverage focuses on control-path validation; full sensor/VLM/VLA quality replay is future work.
