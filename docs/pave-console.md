# OpenPAVE Console

## Purpose

The OpenPAVE console is available at:

```text
/pave
```

It is designed for Physical AI validation workflows, not as a general-purpose VLM web UI. The original `live-vlm-webui` interface remains available at `/`.

## Current Implementation

The current console lives in the OpenPAVE-maintained `live-vlm-webui` fork under the `ui/` submodule.

It reuses existing backend capabilities:

- WebSocket updates from `/ws`
- WebRTC offer handling through `/offer`
- RTSP stream handling through the existing video backend
- GPU/system metrics from the existing monitor loop
- VLM responses from the existing backend path
- OpenAI-compatible VLM API configuration

This keeps the baseline focused on workflow validation instead of rewriting the video and VLM backend too early.

## OpenPAVE Runtime APIs

The console reads runtime state through:

```text
GET /api/pave/runtime
```

The endpoint reads command and state feedback from:

```text
COMMAND_RESULT_PATH
ROBOT_STATE_PATH
```

The console can run a text-only inference request through:

```text
POST /api/pave/infer
```

This validates the prompt/result path against the configured OpenAI-compatible backend without requiring a live camera stream or physical robot.

## Console Sections

The current console includes:

- live stream view
- stream connection status
- CPU usage
- memory usage
- GPU usage when available
- GPU memory usage when available
- prompt input
- active model and backend endpoint
- raw VLM output
- parsed intent summary
- command result JSON
- robot state JSON

## Intent Forwarding Safety

The UI can forward selected VLM outputs to Intent Ingress through:

```text
INTENT_INGRESS_URL
```

Runtime switches:

```text
INTENT_FORWARDING_ENABLED=1
TROT_CONFIRMATIONS=2
TROT_CONFIRMATION_WINDOW_MS=1500
```

`STOP` is forwarded immediately. `TROT` requires repeated confirmation by default.

## Running

The recommended path is to use the validated baseline launcher:

```bash
OPENPAVE_CONFIG=configs/mock.env ./scripts/run_stage3_demo.sh
```

Then open:

```text
http://127.0.0.1:8090/pave
```

The original upstream-style UI remains available at:

```text
http://127.0.0.1:8090/
```

## Future Work

The console is still coupled to `live-vlm-webui`. Future work will move the default OpenPAVE console into an OpenPAVE-owned frontend/backend surface while keeping `live-vlm-webui` available as an optional full VLM debugging UI during the transition.
