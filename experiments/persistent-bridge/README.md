# persistent-bridge — lower-latency body→robot control (todo ③)

Cutting the latency of the last hop inside the body: **how the body node calls the robot's
controller (puppy_control)**. Two steps, both here:

- **A — batched gait exec** (done, real-robot validated): one action = one `docker exec` running a
  one-shot rclpy runner (one node, clients reused within the call) instead of N per-call `ros2`
  CLIs. PuppyPi `.12`: STOP 4939→2740ms (−45%). See [`latency.md`](latency.md).
- **B — Persistent Body-Side Bridge** (B1 done, mock-validated): a **long-lived** rclpy node keeps
  its service clients connected and answers requests over a localhost socket, so each action is
  `socket + already-connected call()`. Mock on `.13`: STOP cold 320ms → bridge ~1.9ms (**~190×**).
  See [`bridge_test.md`](bridge_test.md).

The B1/B2 design (positioning, socket-namespace boundary, safety, protocol) is in
`persistent_bridge_b1_design.md` at the workspace root.

## Files

| File | Belongs to | Role |
|------|-----------|------|
| `latency.md` | A | before/after result + method |
| `bench_action.py` | A | times `PuppyPiLocalAdapter` actions on the real robot |
| `bridge_protocol.py` | B | wire protocol (newline-JSON); sync + reserved async; `ping/pong`, `version`, error `code` |
| `gait_steps.py` | B | shared step executor; caller-owned client cache (reuse) |
| `mock_controller.py` | B1 | std_srvs stand-in for puppy_control (no dog) |
| `bridge_node.py` | B | persistent node + socket server |
| `bridge_client.py` | B | body-side client (+ `ping()`, STOP benchmark) |
| `bench_cold.py` | B1 | cold baseline (discovery per action) |
| `test_bridge_protocol.py` | B | protocol unit tests (16, pure JSON) |
| `bridge_test.md` | B1 | mock runbook + result |

## Status

- A: done, merged behind `PuppyPiLocalAdapter`, real-robot validated.
- B1: done, mock-validated on `.13` (no dog). Protocol reserves async (`mode:"async"`, `op:"action"`,
  `progress`/`cancel`) for AMR-style long-running actions — no wire-format change to add later.
- **B2 (next):** run the bridge next to real puppy_control, integrate an adapter mode
  (`puppypi_bridge`) with **fallback to A** (via `ping`), add `start_bridge.sh` + health check, and
  measure real HOME/STOP before(A)/after(B) plus hard-stop behaviour.

> Experimental — do not move into `control_daemon/` until B2 has real-robot validation and the
> adapter fallback behaviour (same experiment→graduate path as the capability model).
