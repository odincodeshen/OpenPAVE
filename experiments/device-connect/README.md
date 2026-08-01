# device-connect — the neutral seam over Arm's Device Connect (todo ②, option b)

②(a) proved a **non-ROS body over a neutral seam** using **raw zenoh + capability JSON**. ②(b)
keeps the **exact same body-endpoint contract** and swaps the transport for **[Device Connect](https://github.com/arm)**
— Arm's open device↔agent framework (`DeviceDriver` + `@rpc`/`@emit`, backends: zenoh / NATS / MQTT).
That is the whole point of (b): *swap the transport, keep the contract*.

> Design: `neutral_seam_design.md` §6 (workspace root) — "只把 (a) 的 raw zenoh 換成 device-connect 的
> `@rpc`/`@emit`, 契約不變". The framework lives at `deviceconnect_mhs/` (workspace).

## What this adds vs the colleague's PuppyPi adapter

`deviceconnect_mhs/puppy-device-connect` is **read-only** (ROS inspection RPCs; walking/pose/motor
control explicitly out of scope). This experiment adds the missing half — **actuation** — by exposing
OpenPAVE's capability model as a Device Connect device. Same framework, complementary scope.

## Files

| File | Role |
|------|------|
| `openpave_device.py` | `OpenPaveBodyDriver(DeviceDriver)` — `@rpc execute(action, params)` + `list_capabilities()`; internally `create_robot_adapter` + the **same `dispatch()` as ②a** → `DeviceRuntime.run()` |
| `openpave_agent.py` | brain: `discover_devices(device_type="openpave-body")` → `invoke_device(id, "execute", params={action, params})` |
| `test_device.py` | 4 dispatch unit tests (identical cases to ②a — same contract) |

## Contract (unchanged from ②a / design §3)

```
invoke  execute(action, params)   ->  {status: completed|failed|unsupported|rejected, detail, ...}
```

Device Connect wraps the return as `{"success": true, "result": <the capability state>}`.

## Run (D2D, zero infra — zenoh multicast, no broker)

```bash
python3.11+ -m venv .venv && . .venv/bin/activate
pip install <deviceconnect_mhs>/device-connect/packages/device-connect-edge \
            <deviceconnect_mhs>/device-connect/packages/device-connect-agent-tools

# body (fully non-ROS with mock_arm):
DEVICE_CONNECT_ALLOW_INSECURE=true ROBOT_ADAPTER=mock_arm python3 openpave_device.py
# brain (another shell):
DEVICE_CONNECT_ALLOW_INSECURE=true python3 openpave_agent.py move_joint '{"joint":2,"position":0.5}'
DEVICE_CONNECT_ALLOW_INSECURE=true python3 openpave_agent.py trot     # -> unsupported
```

## Validated (2026-08-01, local, D2D zenoh, no broker, no ROS, no dog)

- `move_joint {joint:2,position:0.5}` → **completed**
- `grasp` → **completed**; `trot` → **unsupported** (`mock_arm does not support 'trot'`)
- dispatch unit tests: 4 pass

**The same capability contract and the same `dispatch` served a non-ROS body over a completely
different transport (Device Connect instead of raw zenoh) with zero contract changes** — the seam is
transport-agnostic, exactly as ②a's design predicted.

## Reused unchanged

- **capability contract** `pave_runtime.capability_schema` + adapters `control_daemon.adapters`.
- **the ②a dispatch** — copied verbatim; body endpoint logic is identical across transports.

## Next

1. **real dog** — run the driver with `ROBOT_ADAPTER=puppypi_bridge` on the PuppyPi (after
   `switch_puppypi_ros2.sh`); brain invokes `execute("home"/"trot"/…)`. Seam stays neutral; the
   adapter drives the B2 bridge internally, same as ②a's real-dog run.
2. **fabric mode** — swap D2D for a Device Connect server (registry + dashboard) to show the same
   device on a hosted fabric; contract still unchanged.
