# Demo Integration Levels

OpenPAVE supports Physical AI demos at different integration depths. A demo can remain independently runnable while OpenPAVE provides a common place to catalogue, observe, validate, and optionally benchmark it.

## Level 0: Catalogue Only

The demo is listed in OpenPAVE with high-level metadata.

Typical fields:

- demo name
- short description
- robot or sensor endpoint
- model type
- brain-side compute target
- middleware or transport
- current status
- links to available videos, runbooks, or validation notes

Use this level when the demo should be discoverable from OpenPAVE, but does not expose launch hooks or runtime status to OpenPAVE yet.

## Level 1: Launch / Status / Result Wrapper

The demo remains independently runnable and provides optional hooks that OpenPAVE can call or document.

Typical fields:

- launch command or runbook
- status check command or endpoint
- high-level result file or endpoint
- logs or output summary location

Use this level when the demo already has its own runtime, but OpenPAVE should help start it, check whether it is alive, or show high-level results.

## Level 2: State or Result Bridge

The demo emits state or result information in a format OpenPAVE can consume.

Typical outputs:

- demo status
- command result
- robot state
- task result
- model output summary
- health or heartbeat

Use this level when OpenPAVE should observe the demo consistently without owning the demo's control loop.

## Level 3: Normalized Intent / Control Contract

The demo accepts normalized intent from OpenPAVE and maps it to its own robot-specific controller, policy, or middleware path.

Typical flow:

```text
OpenPAVE source
-> normalized intent
-> demo control bridge or robot adapter
-> robot-specific controller
-> state/result feedback
```

Use this level when the demo wants to share a common control contract with other OpenPAVE demos.

## Level 4: Benchmark Integration

The demo provides scenarios and result records that OpenPAVE benchmark tooling can compare.

Typical fields:

- scenario definition
- expected outcome
- result JSONL or equivalent structured result
- latency measurements
- pass/fail criteria
- model, endpoint, adapter, and hardware metadata

Use this level when the demo is ready for repeatable validation or comparison.

## Current Reference

PuppyPi + DGX is the first validated deep-integration example. It demonstrates Level 3 behavior and partial Level 4 benchmarking through normalized intent, robot adapter execution, command/state feedback, and scenario result files.

Other demos can start at Level 0 or Level 1 and deepen integration over time.
