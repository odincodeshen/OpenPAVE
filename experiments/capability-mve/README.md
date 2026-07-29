# capability MVE — a different robot class over the same seam

Plan A: **generalize the command model** from fixed locomotion verbs (STOP/TROT/HOME/MOVE) to a
**capability-declarative** contract, and prove the architecture is reusable on *other robot
hardware* by running a **manipulation-class mock (an arm)** over the **same zenoh seam** — with
only a new adapter + capability set. No robot hardware needed (mock, zero risk).

> **Graduated (2026-07-29):** the capability model has moved into the runtime —
> `pave_runtime/capability_schema.py` (the `{action, params}` contract) and
> `control_daemon/adapters.py` (`CapabilityAdapter`, `LocomotionCapabilityMixin`, `MockArmAdapter`,
> `create_robot_adapter`). What remains here is the ROS/zenoh execution layer (a runnable body
> node + a send script) that exercises it over the validated zenoh seam.

## The generalization

| | locomotion (today) | capability model (here) |
|---|---|---|
| message | `{intent:"MOVE", params:{vx,yaw,duration_ms}}` | `{action:"move_joint", params:{joint,position}}` |
| support | fixed enum `STOP/TROT/HOME/MOVE` | adapter declares `capabilities={...}` |
| dispatch | `if intent=="MOVE": adapter.move(...)` | `adapter.execute(action, params)` if `action ∈ capabilities` |

The body node no longer knows any robot verbs — it only routes an action to the adapter that
**declares** it. A new robot class = a new adapter, nothing else.

## Files

| File | Role |
|------|------|
| `capability_body_node.py` | generic body: sub `/openpave/action` → capability check → `execute` → pub `/openpave/action_state` (adapter from `create_robot_adapter`) |
| `send_action.py` | brain: publish one `{action, params}` |

The contract, adapters, and unit tests now live in the runtime:
`pave_runtime/capability_schema.py`, `control_daemon/adapters.py` (`MockArmAdapter`,
`LocomotionCapabilityMixin`, `create_robot_adapter`), and `tests/test_capability_runtime.py`.

## Reused unchanged from the zenoh MVE

The **transport** (zenoh `client` → router on the DGX) and the **deployment pattern** are the
same as `../zenoh-mve/`; the body node now dispatches through the **runtime** capability model.
That reuse — a new robot class over an unchanged seam + runtime — *is* the result being demonstrated.

## Run (on the plain RPi5 at 192.168.0.13 — mock, no hardware)

Same container setup as the zenoh MVE (see `../zenoh-mve/zenoh_test.md`), running
`capability_body_node.py` instead:

- **Body — RPi5**: zenoh `client` → DGX router, `ROBOT_ADAPTER=mock_arm`,
  run `experiments/capability-mve/capability_body_node.py --ros-args -r __node:=openpave_body_arm`
- **Brain — DGX**: `python3 experiments/capability-mve/send_action.py <action> [params_json]`

## Validation checklist

> **✅ Validated 2026-07-29** on DGX (`192.168.0.24`, router) ↔ plain RPi5 (`192.168.0.13`,
> `mock_arm` body) over zenoh — same transport as the zenoh MVE, only a new adapter + capability
> set. The arm body dispatched `move_joint` and **rejected `trot`** (not a declared capability).

- [x] **discovery** — DGX saw `/openpave_body_arm` (same seam as zenoh MVE)
- [x] **capability action** — `move_joint {"joint":2,"position":0.5}` → body logged
      `action move_joint params={'joint': 2, 'position': 0.5}` and dispatched to the adapter
- [x] **param check** — `move_joint {"joint":2}` (no position) → adapter returns `failed`
- [x] **unsupported capability rejected** — `trot` → `[WARN] unsupported capability: trot (adapter=mock_arm)`
- [x] **reuse proven** — transport + deployment identical to the zenoh MVE; only the adapter + caps differ

### Reliability observation

The body's `rmw_zenoh` node **does not survive the zenoh router being restarted** — the session
drops and the node exits (seen as `Exited (255)`). Same trait as the zenoh MVE. Future work: the
body should reconnect to the router rather than crash (see `docs/further-work.md`).

## What this proves

A completely different robot class (an arm, manipulation capabilities) runs over the **same
brain↔body zenoh seam** with only a new adapter — validating cross-hardware genericity and the
capability-model generalization (see the workspace-root `todo_list.md`).
