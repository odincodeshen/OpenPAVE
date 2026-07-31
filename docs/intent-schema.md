# Intent Schema v0.1

> **Now generalized:** the fixed v0.1 set (`STOP/TROT/HOME/MOVE`) has been generalized into a
> **capability-declarative** contract (`{action, params}` + adapters declaring `capabilities`,
> schema `cap-0.1`). This v0.1 remains the **locomotion vocabulary** and is translated onto
> capabilities by `intent_to_capability_action`, so existing payloads keep working unchanged.
> See [Robot Adapters](robot-adapters.md).

## Purpose

OpenPAVE uses a small intent schema to separate VLM/VLA output from robot-specific control code. The schema is the runtime contract between:

- VLM/WebUI output
- `intent_ingress`
- the intent file bus
- `control_daemon`
- future robot adapters

The first schema version is intentionally small. It covers the current MVP actions while leaving room for additional robot targets and compute devices.

## Normalized Payload

Every accepted intent is normalized to this shape before being written to the intent file bus:

```json
{
  "schema_version": "0.1",
  "request_id": "7e92d68d-17dc-4d6b-a334-9227f7ee9294",
  "intent": "MOVE",
  "params": {
    "vx": 0.0,
    "yaw": 0.6,
    "duration_ms": 600
  },
  "source": "webui",
  "timestamp": "2026-05-16T09:30:00.000000+00:00",
  "confidence": 0.87,
  "raw_text": "TURN_RIGHT"
}
```

## Required Fields

- `schema_version`: currently `0.1`
- `request_id`: unique ID for tracing a command through the pipeline
- `intent`: one of the supported intent types
- `params`: intent-specific parameters, or an empty object
- `source`: component that produced the intent
- `timestamp`: ISO-8601 timestamp

## Optional Fields

- `confidence`: model or parser confidence, between `0.0` and `1.0`
- `raw_text`: original text output when the intent was parsed from text
- `safety_fallback`: `true` when an unknown text or unsupported intent was mapped to `STOP`

## Supported Intents

### STOP

Stop robot motion and reset to a safe standing posture when the adapter supports it.

```json
{
  "intent": "STOP",
  "params": {}
}
```

### TROT

Enable the current PuppyPi mark-time/trot behavior.

```json
{
  "intent": "TROT",
  "params": {}
}
```

### HOME

Reset robot posture to the adapter's home posture.

```json
{
  "intent": "HOME",
  "params": {}
}
```

### MOVE

Send a short velocity-style movement command.

```json
{
  "intent": "MOVE",
  "params": {
    "vx": 0.0,
    "yaw": 0.6,
    "duration_ms": 600
  }
}
```

Parameter limits in v0.1:

- `params.vx`: `-0.5` to `0.5`
- `params.yaw`: `-1.0` to `1.0`
- `params.duration_ms`: `100` to `5000`

These limits are conservative for the current PuppyPi target and can be revised when additional robot adapters are added.

## Text Aliases

`intent_ingress` accepts simple text payloads for compatibility with the current WebUI hook:

```json
{ "text": "STOP" }
```

Supported text mappings:

- `STOP` -> `STOP`
- `TROT` -> `TROT`
- `HOME` -> `HOME`
- `LEFT` or `TURN_LEFT` -> `MOVE` with `yaw = -0.4`
- `RIGHT` or `TURN_RIGHT` -> `MOVE` with `yaw = 0.6`

Unknown text is mapped to `STOP` with `safety_fallback: true`.

For legacy compatibility, these aliases are also accepted when sent in the `intent` field, such as:

```json
{ "intent": "RIGHT" }
```

## Legacy Compatibility

The control daemon still accepts the previous flat file-bus format:

```json
{"intent": "MOVE", "vx": 0.0, "yaw": 0.6, "duration_ms": 600}
```

It normalizes the legacy payload into schema v0.1 internally before dispatching robot actions.

## Invalid Examples

Invalid numeric type:

```json
{
  "intent": "MOVE",
  "params": {
    "vx": "fast",
    "yaw": 0.0,
    "duration_ms": 600
  }
}
```

Out-of-range yaw:

```json
{
  "intent": "MOVE",
  "params": {
    "vx": 0.0,
    "yaw": 2.5,
    "duration_ms": 600
  }
}
```

Invalid confidence:

```json
{
  "text": "STOP",
  "confidence": 1.5
}
```
