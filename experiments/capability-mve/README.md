# capability MVE — a different robot class over the same seam

Plan A: **generalize the command model** from fixed locomotion verbs (STOP/TROT/HOME/MOVE) to a
**capability-declarative** contract, and prove the architecture is reusable on *other robot
hardware* by running a **manipulation-class mock (an arm)** over the **same zenoh seam** — with
only a new adapter + capability set. No robot hardware needed (mock, zero risk).

> **Scope:** experimental. It reuses the validated zenoh transport (see
> `../zenoh-mve/`) but is not wired into the main runtime. If it proves out, the contract
> graduates into `pave_runtime`.

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
| `capability_schema.py` | normalize `{action, params}` (+ `COMMON_CAPABILITIES` = stop/estop/home) |
| `capability_adapter.py` | `CapabilityAdapter` Protocol + `ActionResult` |
| `mock_arm_adapter.py` | `MockArmAdapter` — manipulation caps (grasp/release/move_joint), logs only |
| `capability_body_node.py` | generic body: sub `/openpave/action` → capability check → `execute` → pub `/openpave/action_state` |
| `send_action.py` | brain: publish one `{action, params}` |
| `test_capability.py` | unit tests (schema + arm adapter) |

## Reused unchanged from the zenoh MVE

The **transport** (zenoh `client` → router on the DGX) and the **deployment pattern** are the
same as `../zenoh-mve/` — only the body program and the contract are new. That reuse *is* the
result being demonstrated.

## Run (on the plain RPi5 at 192.168.0.13 — mock, no hardware)

Same container setup as the zenoh MVE (see `../zenoh-mve/zenoh_test.md`), running
`capability_body_node.py` instead:

- **Body — RPi5**: zenoh `client` → DGX router, `ROBOT_ADAPTER=mock_arm`,
  run `experiments/capability-mve/capability_body_node.py --ros-args -r __node:=openpave_body_arm`
- **Brain — DGX**: `python3 experiments/capability-mve/send_action.py <action> [params_json]`

## Validation checklist

- [ ] **discovery** — DGX sees `/openpave_body_arm` (same seam as zenoh MVE)
- [ ] **capability action** — `send_action.py move_joint '{"joint":2,"position":0.5}'` →
      body logs `[mock_arm] move_joint params={...}`, state = `completed`
- [ ] **param check** — `send_action.py move_joint '{"joint":2}'` (no position) → `failed`
- [ ] **unsupported capability rejected** — `send_action.py trot` → `unsupported` (arm has no trot)
- [ ] **reuse proven** — transport + deployment identical to zenoh MVE; only the adapter + caps differ

## What this proves

A completely different robot class (an arm, manipulation capabilities) runs over the **same
brain↔body zenoh seam** with only a new adapter — validating cross-hardware genericity and the
capability-model generalization (see the workspace-root `todo_list.md`).
