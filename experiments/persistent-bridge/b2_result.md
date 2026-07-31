# B2 — persistent bridge on the real robot: result

B2 connects the B1 bridge to **real puppy_control** and integrates it into an adapter
(`puppypi_bridge`) that **falls back to A** when the bridge is unavailable. The validated A path
(`puppypi_local`) is untouched. See `persistent_bridge_b2_design.md` (workspace root) for the design.

## Result (PuppyPi `.17`, real puppy_control, n=10, 2026-07-31)

| action | before `puppypi_local` (A) p50 / p95 | after `puppypi_bridge` (B) p50 / p95 | path |
|--------|-------------------------------------:|-------------------------------------:|------|
| HOME   | 1514 / 1801 ms | **512 / 513 ms** | bridge ×10 |
| STOP (from idle) | 2661 / **4781** ms | **515 / 516 ms** | bridge ×10 |

- **HOME −66%**, **STOP p50 −81%**, **STOP p95 −89%**; bridge variance is tiny (512–517 ms) vs A's
  wide STOP spread (2441–5445 ms).
- The remaining ~512 ms is puppy_control's **physical time to re-pose** (real service execution),
  not dispatch overhead — the bridge has removed the per-action docker exec + node + discovery cost
  (the mock's 1.9 ms had a trivial fake service).
- **Fallback**: with the bridge killed, `puppypi_bridge` HOME went `path=fallback_a`
  (`bridge_unavailable`), robot still moved at A speed (~1475 ms). Non-destructive.

## Key real-robot finding: bridge must run as the controller's user

Started as **root**, the bridge saw the services in discovery (`wait_for_service` → True) but every
call **timed out** (rc=3). Root cause: **FastDDS shared-memory segments are per-user**; puppy_control
runs as `ubuntu`, so a root bridge can't reach its SHM data channel — discovery works, data doesn't.

**Fix: start the bridge with `-u ubuntu`** (same user as puppy_control), matching `RMW_IMPLEMENTATION`
and `ROS_DOMAIN_ID`. See `start_bridge.sh`.

## Deployment (this robot)

- `puppypi_ros2` container is `NetworkMode=host` → bridge listens `127.0.0.1:8787`, the host-side
  adapter connects over **TCP localhost** (design §3.1 option 1).
- Bridge runs **inside** the puppy_control container (`docker exec -d -u ubuntu`, FastDDS, same graph).
- Adapter: `ROBOT_ADAPTER=puppypi_bridge`, `PUPPY_BRIDGE_HOST=127.0.0.1`, `PUPPY_BRIDGE_PORT=8787`.

## Success criteria — met

- [x] bridge runs next to real puppy_control; `ping` → ready + services_ready
- [x] HOME + STOP-from-idle over `puppypi_bridge` succeed on the real robot, `path=bridge`
- [x] p50 **and** p95 clearly below `puppypi_local` for both
- [x] bridge killed → bounded fallback to A, `path=fallback_a` + reason, robot still moves
- [x] `puppypi_local` behavior unchanged (it's the "before")
- [x] `puppypi_bridge` is experimental, not a default

## Not covered here (as designed)

- STOP-while-moving / controller starvation (review #8): needs the robot elevated + E-stop, and is
  first exercised against a delay-injecting mock. hard-stop escalation is inherited + unit-tested,
  independent of the bridge.
- async / long-running (AMR): protocol fields reserved, not implemented.
