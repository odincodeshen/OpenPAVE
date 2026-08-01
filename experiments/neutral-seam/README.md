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

**Real-hardware pipeline** (2026-08-01, PuppyPi `192.168.0.17`, `ROBOT_ADAPTER=puppypi_bridge`)
- brain on DGX `.24` → `neutral_body` on the PuppyPi → `puppypi_bridge` adapter → the B2 bridge
  (`ping` → ready, `services_ready`, `controller=puppy_control`) → real puppy_control.
- The whole **seam → adapter → bridge → controller** path carried the command end-to-end: the STOP
  request reached the live controller and was executed (bridge log: `client connected · req · steps`).
- The dog did **not** actually re-pose, for a reason **orthogonal to the seam**: the robot had been
  rebuilt and its motion driver changed — B2's `velocity_move` interface is gone; the box now ships a
  ROS2 `puppy_control` package (+ a ROS1 one). The gait steps no longer match the driver, so the step
  returned `ok=False`, and the adapter **correctly fell back and reported `failed / path / reason`**.
  The seam's contract, fallback, and state reporting all behaved correctly *while a lower layer
  failed* — wiring the adapter to the new driver is tracked as separate work (see Next #2).

**A pure-Python, no-ROS body served the capability contract over raw zenoh — on a single host, across
two machines (two Python versions), and end-to-end into a real robot's controller.** That is the ②
result: a non-ROS robot is a first-class OpenPAVE body, and the seam is genuinely neutral — across
hosts, and independent of what the body drives underneath.

## Reused unchanged

- **capability contract** `pave_runtime.capability_schema` + adapters `control_daemon.adapters`.
- **zenoh** (already in use for the ROS seam) — here as raw zenoh, not rmw_zenoh.

## Status: ②(a) complete

The seam is validated at all three levels — single-host, cross-host, and end-to-end into a real
robot's controller. **The core ② goal (a non-ROS body over a neutral seam) is met.**

## Next

1. ~~**cross-host**~~ — ✅ done (DGX `.24` brain → RPi5 `.13` body, raw-zenoh TCP).
2. **real dog — actual motion** *(separate work, orthogonal to the seam)* — the pipeline is proven
   (command reached the live controller); the remaining piece is re-wiring the bridge's gait steps
   to the PuppyPi's **new ROS2 `puppy_control`** driver (the old `velocity_move` interface is gone).
   This is an *adapter ↔ driver* task, not a seam change.
3. **option (b)** — swap the transport for device-connect / a neutral bus; `dispatch` + the
   contract stay the same, so it is a transport change, not a rewrite.
