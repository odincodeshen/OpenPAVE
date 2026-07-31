# Robot State and Command Result Feedback

## Purpose

OpenPAVE uses a lightweight feedback channel for the control daemon. The goal is to make robot command execution observable without introducing a database, message broker, or new HTTP service.

The feedback channel currently writes the latest command result and robot state as JSON files.

## Default Files

```text
/tmp/vla_command_result.json
/tmp/vla_robot_state.json
```

Override them with:

```bash
export COMMAND_RESULT_PATH=/tmp/vla_command_result.json
export ROBOT_STATE_PATH=/tmp/vla_robot_state.json
```

## Command Lifecycle

Supported command states:

- `received`: daemon read and normalized the intent
- `accepted`: daemon accepted the intent for adapter dispatch
- `executing`: daemon is calling the selected robot adapter
- `completed`: adapter completed successfully
- `failed`: adapter returned an error or raised an exception
- `rejected`: daemon rejected an invalid payload

Typical successful flow:

```text
received -> accepted -> executing -> completed
```

Invalid payload flow:

```text
rejected
```

Adapter failure flow:

```text
received -> accepted -> executing -> failed
```

## Command Result Shape

Example:

```json
{
  "schema_version": "0.1",
  "request_id": "req-1",
  "intent": "MOVE",
  "params": {
    "vx": 0.0,
    "yaw": 0.6,
    "duration_ms": 600
  },
  "source": "webui",
  "adapter": "mock",
  "status": "completed",
  "updated_at": "2026-05-16T10:30:00.000000+00:00",
  "started_at": "2026-05-16T10:29:59.900000+00:00",
  "completed_at": "2026-05-16T10:30:00.000000+00:00",
  "steps": [
    {
      "name": "mock_move",
      "return_code": 0
    }
  ]
}
```

For `PuppyPiAdapter`, `steps` records ROS 2 CLI call return codes, such as:

- `set_running:true`
- `set_mark_time:false`
- `go_home`
- `velocity_move`

Capability adapters use the same result shape and may add a `detail` object: the `puppypi_bridge`
adapter records `path` (`bridge` / `fallback_a`) + latency; a sensor adapter (`camera`) records
frame metadata (`encoding`, `bytes`, `width`, `height`).

## Robot State Shape

Example:

```json
{
  "schema_version": "0.1",
  "adapter": "mock",
  "status": "idle",
  "updated_at": "2026-05-16T10:30:00.000000+00:00",
  "last_command": {
    "request_id": "req-1",
    "intent": "MOVE",
    "status": "completed"
  }
}
```

Current state values are intentionally simple:

- `idle`
- `received`
- `accepted`
- `executing`
- `error`

## Notes

- The feedback files represent the latest state, not a historical event log.
- The command result is suitable for OpenPAVE console display.
- The benchmark harness can sample or archive these files into JSONL output.
- Future implementations may replace or supplement this file channel with HTTP, WebSocket, ROS topics, MQTT, or a lightweight event queue.
