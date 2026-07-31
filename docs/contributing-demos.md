# Contributing Physical AI Demos

OpenPAVE welcomes Physical AI demos at different integration levels. A demo can remain independently runnable while OpenPAVE provides a common catalogue, validation notes, optional launch/status hooks, and deeper runtime or benchmark integration when useful.

## Good Demo Candidates

OpenPAVE is a good fit for demos that involve one or more of:

- local VLM/VLA inference
- robot or sensor endpoints
- ROS 2 or other robot middleware
- camera, depth, audio, lidar, or raw sensor paths
- physical robot control
- brain/body or edge/cloud split experiments
- runtime feedback or benchmark scenarios

## Choose an Integration Level

Start by choosing the lightest useful level:

- **Level 0**: catalogue entry
- **Level 1**: launch / status / result wrapper
- **Level 2**: state or result bridge
- **Level 3**: normalized intent / control contract
- **Level 4**: benchmark integration

See [Demo Integration Levels](demo-integration-levels.md) for details.

## Suggested Demo Entry

A demo entry can start with:

```text
Name:
Short description:
Status: validated / experimental / candidate
Integration level:
Robot or sensor endpoint:
Brain-side compute:
Model/backend:
Middleware or transport:
Runbook:
Validation notes:
Known limitations:
```

## Optional Launch / Status / Result Hooks

Level 1 demos can provide lightweight hooks such as:

```text
launch command
status command or endpoint
result file or endpoint
log location
```

These hooks should report high-level demo behavior. They do not need to replace the demo's own runtime.

## Optional Runtime Integration

Level 2 and Level 3 demos can integrate with OpenPAVE runtime contracts:

- command result
- robot state
- normalized intent
- robot adapter
- body-side control bridge

The recommended control direction is:

```text
model / planner / UI / benchmark
-> normalized intent
-> demo bridge or robot adapter
-> robot-specific controller
-> command result and state feedback
```

## Optional Benchmark Integration

Level 4 demos can add:

- scenario files
- expected results
- result records
- latency fields
- pass/fail criteria
- model and hardware metadata

OpenPAVE benchmark support is currently strongest for control-path validation. Sensor replay, model-output quality checks, and full end-to-end VLM/VLA task evaluation are planned future work.
