# device-connect — the neutral seam over Arm's Device Connect (todo ②, option b · **B: labeled RPCs**)

②(a) proved a **non-ROS body over a neutral seam** with raw zenoh + capability JSON. ②(b) keeps the
**same body-endpoint contract** and swaps the transport for **[Device Connect](https://github.com/arm/device-connect)**
— Arm's open device↔agent framework (`DeviceDriver` + `@rpc`/`@emit`, backends zenoh / NATS / MQTT).

> This is the **device-connect integration *path***, not a core change. Strategy + concept mapping:
> `openpave_deviceconnect.md` (workspace root). OpenPAVE's core stays transport-neutral; this path is
> an optional plugin.

## Option B: every capability is its own **labeled** RPC

The first cut (A) exposed a single `execute(action, params)`. That works, but the agent only sees one
RPC — it can't use device-connect's **selector grammar** to address individual capabilities. **B** fixes
that: each capability from `adapter.capabilities` becomes its **own labeled `@rpc`**, generated
dynamically, so the agent speaks device-connect natively:

```
device(<id>).function(home)          invoke one capability by name
function(estop)                       fleet-wide e-stop, label-addressed (no device id)
function(safety:critical)             every dangerous op across the fleet
device(category:robot).function(*)    every RPC on the robots
```

**Dynamic generation is real** (not a workaround): the SDK collects RPCs by scanning `dir(self)` for
`_is_device_function` and offers `_invalidate_caches()`, so instance-level methods added in `__init__`
are first-class. Each capability's labels come from its semantics (`estop`/`stop` → `safety:critical`,
actuation → `direction:write`, sensing → `direction:read`).

## Files

| File | Role |
|------|------|
| `openpave_device.py` | `OpenPaveBodyDriver` — dynamically mounts one labeled `@rpc` per capability (`types.MethodType`), same `dispatch()` as ②a; `DeviceRuntime.run()` |
| `openpave_agent.py` | brain: `invoke("device(<id>).function(<action>)")`, `broadcast("function(estop)")`, `--discover` |
| `test_device.py` | 7 tests: dispatch (3) + label mapping (2) + dynamic labeled-RPC generation (2) |

## Contract (unchanged from ②a / strategy §3)

Each capability RPC takes `params` (a dict; the adapter validates its own `_required`) and returns the
capability state. Device Connect wraps it as `{"success": true, "result": <state>}`.

## Run (D2D, zero infra — zenoh multicast, no broker)

```bash
python3.11+ -m venv .venv && . .venv/bin/activate
pip install <deviceconnect_mhs>/device-connect/packages/device-connect-edge \
            <deviceconnect_mhs>/device-connect/packages/device-connect-agent-tools

DEVICE_CONNECT_ALLOW_INSECURE=true ROBOT_ADAPTER=mock_arm python3 openpave_device.py   # body
DEVICE_CONNECT_ALLOW_INSECURE=true python3 openpave_agent.py home                       # brain
DEVICE_CONNECT_ALLOW_INSECURE=true python3 openpave_agent.py move_joint '{"joint":2,"position":0.5}'
DEVICE_CONNECT_ALLOW_INSECURE=true python3 openpave_agent.py --estop                    # fleet e-stop
```

## Validated (2026-08-02, local, D2D zenoh, no broker, no ROS, no dog)

- SDK collected **7 labeled RPCs** from `mock_arm` (estop/stop = `safety:critical`, rest = `informational`;
  all `direction:write`); device `category:actuator`.
- `invoke device(...).function(home)` → **completed**; `function(move_joint)` `{joint:2,position:0.5}` → **completed**.
- **`broadcast("function(estop)")` → candidates=1, reply completed** — fleet e-stop by label, no device id.
- unit tests: 7 pass.

**Same capability contract, same `dispatch`, now device-connect-native** — each capability selector-addressable,
fleet e-stop by `function(estop)`. That is B's payoff over A.

## Validated on the real dog (2026-08-02, PuppyPi `192.168.0.17`, `ROBOT_ADAPTER=puppypi_bridge`, external camera)

Same driver with `ROBOT_ADAPTER=puppypi_bridge` on the PuppyPi (after `switch_puppypi_ros2.sh`), brain in
D2D on the box. All `path=bridge`, latency identical to ②a / B2, each confirmed by an external camera (RPi `.13`):

| brain | addressing | result |
|-------|-----------|--------|
| home | `invoke device(...).function(home)` | completed · 516 ms · stood to home pose |
| estop | **`broadcast("function(estop)")`** | completed · 515 ms · **label-addressed, no device id** |
| trot | `invoke device(...).function(trot)` | completed · 1013 ms · walked (gait) |
| stop | `invoke device(...).function(stop)` | completed · 514 ms · stood |

**Same body + bridge + adapter as ②a's real dog — only the upper seam changed (raw zenoh → device-connect);
contract and latency unchanged.** `broadcast("function(estop)")` drove the real dog's e-stop **by label**,
which the A-version single `execute` cannot do.

## Next

1. ~~**real dog**~~ — ✅ done (home / estop / trot / stop on the real PuppyPi, `path=bridge`,
   camera-confirmed; see *Validated on the real dog* above).
2. **multi-robot** — a 2nd body + `broadcast(..., fire_at=)` for synchronized actuation (5-10 ms).
3. **fabric** — device-connect server (registry + commissioning + dashboard); contract unchanged.
4. **fine-grained signatures** (optional) — generate per-capability param schemas from the adapter's
   `_required` instead of a generic `params` dict.
