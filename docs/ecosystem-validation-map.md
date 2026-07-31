# Ecosystem Validation Map

OpenPAVE helps validate, showcase, compare, and port Physical AI software components across Arm-based edge computing platforms and real robot/sensor endpoints.

The project is not a replacement for each component's native runtime. Its role is to provide a repeatable integration workflow around demos, middleware, control contracts, feedback, and benchmarks.

## Component Areas

### Inference Backend

Current baseline:

- OpenAI-compatible VLM API
- vLLM
- local model serving on the brain-side node

Validation questions:

- Can the backend run locally on the target brain-side platform?
- Can it produce outputs that can be normalized into intent or result summaries?
- Can latency and runtime behavior be observed?
- Can scenarios record model/backend metadata?

### Robot and Sensor Endpoint

Current baseline:

- PuppyPi quadruped
- PuppyPi camera stream
- ROS 2 `puppy_control`

Future targets:

- SO-101 robot arm with camera
- Raspberry Pi ROS 2 car/camera
- additional robot or sensor endpoints

Validation questions:

- What sensors are available?
- What commands or skills can the endpoint execute?
- What state or result feedback can it expose?
- What middleware or transport does it use?

### Robot Middleware

Current baseline:

- ROS 2 services and topics
- DDS/RMW configuration notes
- Dockerized ROS 2 CLI reference path

Experimental:

- zenoh brain/body transport MVE
- local PuppyPi adapter over co-located ROS 2 execution

Validation questions:

- Can commands reach the robot endpoint reliably?
- How does behavior change across RMW, network, image, and firewall configurations?
- Can command execution latency be separated from inference and dispatch latency?
- Can the middleware path be replaced while preserving OpenPAVE-level contracts?

### Control Contract

Current baseline:

- normalized intent schema
- Intent Ingress
- Control Daemon
- robot adapters
- command result and robot state feedback

Validation questions:

- Can different model, UI, benchmark, or planner sources produce the same intent format?
- Can robot-specific adapters map that intent into concrete controller calls?
- Can state and command results return through a common feedback path?

### Observability and Benchmarking

Current baseline:

- `/pave` console
- command result and robot state files
- scenario runner
- benchmark summarizer

Future work:

- sensor replay
- VLM/VLA output-quality checks
- transport latency breakdown
- multi-target comparisons
- demo catalogue tooling

Validation questions:

- Can a developer inspect what the model produced?
- Can a developer see what command was sent and whether it succeeded?
- Can a scenario be repeated across models, endpoints, or middleware paths?
- Can results be compared using structured records?
