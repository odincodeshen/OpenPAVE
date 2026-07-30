# Optimization A — batched gait exec: latency result

**A** collapses each `PuppyPiLocalAdapter` action from *N* `docker exec` + `ros2` CLI calls (each
paying `source` + a fresh rclpy node + service discovery) into **one** `docker exec` running
`control_daemon/puppy_gait_runner.py` once: one node, service clients created once and reused
across the steps. See the commit for the implementation.

## Method

`bench_action.py` times one action end-to-end N times via `PuppyPiLocalAdapter`, on the real
robot. Keep it outside the git tree (e.g. `/tmp`) so `git checkout` doesn't swap it between the
before/after runs:

```bash
cp experiments/persistent-bridge/bench_action.py /tmp/bench_action.py
# before:
git checkout main
ROBOT_ADAPTER=puppypi_local PUPPY_EXEC_CONTAINER=puppypi_ros2 python3 /tmp/bench_action.py home 5
ROBOT_ADAPTER=puppypi_local PUPPY_EXEC_CONTAINER=puppypi_ros2 python3 /tmp/bench_action.py stop 5
# after:
git checkout feat/persistent-bridge   # (then rerun the two commands)
```

`home`/`stop` only re-pose the robot (no travel) — safe to bench. One warm-up per run (not
counted); 1.5 s between runs.

## Result (PuppyPi `.12`, `puppypi_ros2` / FastDDS, n=5, 2026-07-30)

| action | calls | before (per-call) | after (batch A) | saved |
|--------|:-----:|------------------:|----------------:|:-----:|
| HOME   | 1     | 1893 ms (1739–2138) | **1492 ms** (1468–1507) | **−21%** |
| STOP   | 3     | 4939 ms (4625–5359) | **2740 ms** (2541–3047) | **−45%** (~2.2 s) |

## Reading

1. **STOP nearly halved** — the main win: 3 execs → 2 (the two motion-stop calls now share one
   exec's node + discovery), plus go_home.
2. **HOME dropped 21% too** — a 1-call action has nothing to batch, so this is the rclpy runner
   being lighter than the `ros2` CLI itself (no arg parsing / CLI node scaffolding).
3. **Variance shrank a lot** — after HOME 1468–1507 vs before 1739–2138; after STOP 2541–3047 vs
   before 4625–5359. The runner is far more consistent than spawning a CLI per call.

## Ceiling → B

A still pays **one `docker exec` + node + discovery per action** (~1.4 s fixed cost). That ~1.4 s
is what **B (persistent bridge)** targets: a long-running node in the puppy_control container with
clients kept connected, actions delivered over a socket — expected to reach the ~10–50 ms range
(another 1–2 orders of magnitude). B is the next step; A is the safe, already-validated win.
