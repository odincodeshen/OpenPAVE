# neutral-seam — a non-ROS brain↔body seam (todo ②, option a)

Makes the brain↔body seam **neutral** so a **non-ROS** robot can join without pretending to be a
ROS node. Option **(a)**: keep zenoh, but use **raw zenoh** (zenoh-python, *not* rmw_zenoh) and
exchange the capability contract as JSON — no ROS message types, no rclpy on the body.

> Design + the three options (a raw zenoh / b device-connect-bus / c RPC) are in
> `neutral_seam_design.md` at the workspace root. We do (a) first, then (b); (c) is skipped.

## Why this is small

The capability contract (`{action, params}` + `capabilities`) is already neutral, and most
adapters are already pure Python (`mock_arm`, camera, `puppypi_bridge` — none import rclpy). So a
neutral body is just **"zenoh-python sub → `create_robot_adapter` → `execute` → pub state"**. With
`ROBOT_ADAPTER=mock_arm` the whole body is pure Python + zenoh, **no ROS at all**.

## Files

| File | Role |
|------|------|
| `neutral_body.py` | raw-zenoh sub `openpave/action` → `dispatch()` → pub `openpave/action_state`. `dispatch(adapter, payload)` is a **pure, testable, transport-agnostic** function — the same logic a device-connect / bus seam (option b) will reuse. |
| `neutral_brain.py` | send one `{action, params}`, print the state reply |
| `test_seam.py` | 4 dispatch unit tests (no zenoh, no ROS) |

## Contract

Same capability contract as the ROS seam; only the transport is neutral:

```
down  openpave/action        {"action": <name>, "params": {...}}
up    openpave/action_state   {"status": "completed|failed|unsupported|rejected", "detail": {...}, ...}
```

## Run

```bash
pip install eclipse-zenoh
# body (a fully non-ROS body):
ROBOT_ADAPTER=mock_arm python3 neutral_body.py
# brain (another shell):
python3 neutral_brain.py move_joint '{"joint": 2, "position": 0.5}'
python3 neutral_brain.py trot        # mock_arm rejects it
```

Single machine uses zenoh peer (multicast) by default. **Cross-host** without multicast: point
the two sides at each other via env — body listens, brain connects.

```bash
# body host (e.g. 192.168.0.13):
ZENOH_LISTEN=tcp/0.0.0.0:7447 ROBOT_ADAPTER=mock_arm python3 neutral_body.py
# brain host (e.g. 192.168.0.24):
ZENOH_CONNECT=tcp/192.168.0.13:7447 python3 neutral_brain.py move_joint '{"joint":2,"position":0.5}'
```

## Validated

**Local** (2026-07-31, single machine, zenoh peer, no router, no ROS, no dog)
- `move_joint {joint:2,position:0.5}` → **completed** (`detail` echoes the action)
- `grasp` → **completed**; `trot` → **unsupported** (`mock_arm does not support 'trot'`)
- dispatch unit tests: 4 pass

**Cross-host** (2026-07-31, two machines, raw-zenoh TCP direct connect, no router, no ROS, no dog)
- **brain** on DGX `192.168.0.24` (Python 3.12) → **body** on RPi5 `192.168.0.13` (Python 3.13,
  `mock_arm`), `ZENOH_CONNECT` / `ZENOH_LISTEN`
- same three results: `move_joint` / `grasp` → **completed**, `trot` → **unsupported**

**A pure-Python, no-ROS body served the capability contract over raw zenoh — across two different
machines and two different Python versions.** That is the ② result: a non-ROS robot is a
first-class OpenPAVE body, and the seam is genuinely neutral across hosts.

## Reused unchanged

- **capability contract** `pave_runtime.capability_schema` + adapters `control_daemon.adapters`.
- **zenoh** (already in use for the ROS seam) — here as raw zenoh, not rmw_zenoh.

## Next

1. ~~**cross-host**~~ — ✅ done (DGX `.24` brain → RPi5 `.13` body, raw-zenoh TCP).
2. **real dog** — `neutral_body` with `ROBOT_ADAPTER=puppypi_bridge` → PuppyPi (seam stays neutral;
   the adapter talks to the B2 bridge internally).
3. **option (b)** — swap the transport for device-connect / a neutral bus; `dispatch` + the
   contract stay the same, so it is a transport change, not a rewrite.
