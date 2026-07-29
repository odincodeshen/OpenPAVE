# PuppyPi real-adapter run — DGX brain → real PuppyPi over zenoh

> ⚠️ **This drives a REAL robot.** Send `STOP`/`HOME`/`TROT` before any locomotion. Keep the
> robot in a clear area with a hand on the kill switch.

Extends the [zenoh MVE](README.md): the **same brain↔body zenoh seam** as E1a, but the body
runs the real `PuppyPiLocalAdapter`, which commands `puppy_control` on the PuppyPi. Only the
adapter changes; the transport is unchanged.

> **✅ Validated 2026-07-29** on DGX (`192.168.0.24`, brain+router) ↔ PuppyPi (`192.168.0.12`,
> body+puppy_control). `STOP` (→ go_home) and `TROT` (→ mark-time stepping) drove the real
> servos end-to-end over zenoh. See [Key findings](#key-findings).

## Architecture — two independent hops

```
DGX (brain) ──zenoh · Jazzy · rmw_zenoh──▶ body node (on the PuppyPi)
                                              │  PuppyPiLocalAdapter
                                              ▼  docker exec puppypi_ros2  (same container)
                                           puppy_control (Humble · FastDDS, LOCAL)
                                              ▼
                                           servos / motion  (real)
```

- **Seam** (brain↔body): zenoh, `client` mode, via the router on the DGX — as validated in E1.
- **Body-internal** (body→robot): `PuppyPiLocalAdapter` runs the ROS 2 CLI **inside** the
  `puppypi_ros2` container (via `docker exec`), where puppy_control lives. This keeps FastDDS
  same-container (shared-memory works) and reuses its workspace (`puppy_control_msgs` for
  velocity_move). The two hops use different RMWs and do not interfere.

Why `docker exec`, not `docker run`: puppy_control's FastDDS uses **shared memory** for
same-host transport, and SHM lives in the container's IPC namespace. A separate `docker run`
container has its own IPC namespace → discovery works but responses over SHM never arrive →
the call hangs. `docker exec` into `puppypi_ros2` shares its namespace, so it works. (The
original `PuppyPiAdapter` — `docker run`, for a *remote* control host reaching the robot over
UDP — is unchanged and still correct for that deployment.)

## Roles

| host | runs |
|------|------|
| **DGX** (192.168.0.24) | zenoh router + intent sender (`send_intent.py`) |
| **PuppyPi** (192.168.0.12) | `puppy_control` **and** the body node with `ROBOT_ADAPTER=puppypi_local` |
| RPi5 | optional mock body for mixed fan-out — later |

## Prerequisites

- [x] Body/adapter code selects adapter from `ROBOT_ADAPTER` (default `mock`); real robot only
      when `ROBOT_ADAPTER=puppypi_local`.
- [ ] `puppy_control` running on the PuppyPi (single instance; see Step 1 — **don't ctrl-c** it).
- [ ] `ros:humble` image on the PuppyPi (only this — the exec reuses the container's workspace,
      so `puppy-ros2-cli:humble` is **not** needed).
- [ ] Body container can reach docker: `-v /var/run/docker.sock:/var/run/docker.sock -v /usr/bin/docker:/usr/bin/docker`.
- [ ] Safe area; kill switch reachable.

## Step 1 — `puppy_control` on the PuppyPi (leave it running)

**Shortcut:** on the PuppyPi, run **`scripts/start_puppy_control.sh`** — it starts the container,
ensures a single instance, launches puppy_control **detached**, and verifies it responds. The
manual steps below are what it automates.

`ros2 launch` is a **foreground** process — **do not ctrl-c it** (SIGINT kills puppy_control).
Launch it detached and use a separate shell for anything else:

```bash
docker exec -d -u ubuntu -w /home/ubuntu puppypi_ros2 bash -lc \
 'source /opt/ros/humble/setup.bash; source /home/ubuntu/ros2_ws/install/setup.bash; \
  export ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp; \
  ros2 launch puppy_control puppy_control.launch.py'
```

**Health check** (same container, should return a response — not hang):

```bash
docker exec -u ubuntu puppypi_ros2 bash -lc \
 'source /opt/ros/humble/setup.bash; source /home/ubuntu/ros2_ws/install/setup.bash; \
  export ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp; \
  ros2 service call /puppy_control/set_mark_time std_srvs/srv/SetBool "{data: false}"'
# -> std_srvs.srv.SetBool_Response(success=True, ...)
```

Or just run **`scripts/check_puppy_control.sh`** on the PuppyPi — it runs this check and
auto-restarts the ros2 daemon once on a hang, then reports OK / FAILED.

If it hangs: the ros2 daemon may be stale (`ros2 daemon stop`), or puppy_control was
ctrl-c'd / duplicated — get to a single healthy instance first.

## Step 2 — Router on the DGX

Same as E1a (see [zenoh_test.md](zenoh_test.md)): `openpave-router` on the DGX, `:7447`.

## Step 3 — Body node on the PuppyPi (`ROBOT_ADAPTER=puppypi_local`)

```bash
docker run -d --name openpave-body --net=host \
  -e RMW_IMPLEMENTATION=rmw_zenoh_cpp -e ROS_DOMAIN_ID=0 \
  -e ROBOT_ADAPTER=puppypi_local \
  -e PUPPY_RMW_IMPLEMENTATION=rmw_fastrtps_cpp -e PUPPY_EXEC_CONTAINER=puppypi_ros2 \
  -v ~/OpenPAVE:/ws \
  -v /var/run/docker.sock:/var/run/docker.sock -v /usr/bin/docker:/usr/bin/docker \
  --shm-size=640m --ulimit memlock=-1:-1 --cap-add NET_ADMIN --security-opt seccomp=unconfined \
  --entrypoint bash odinlmshen/ros2-zenoh-arm:jazzy-edge \
  -lc 'source /opt/ros/jazzy/setup.bash \
    && cp /opt/ros/jazzy/share/rmw_zenoh_cpp/config/DEFAULT_RMW_ZENOH_SESSION_CONFIG.json5 /tmp/sess.json5 \
    && sed -i "s#tcp/localhost:7447#tcp/<DGX-IP>:7447#g" /tmp/sess.json5 \
    && sed -i "s/mode: \"peer\"/mode: \"client\"/" /tmp/sess.json5 \
    && export ZENOH_SESSION_CONFIG_URI=/tmp/sess.json5 \
    && exec python3 /ws/experiments/zenoh-mve/body_node.py --ros-args -r __node:=openpave_body_puppy'
```

**Checkpoint:** `docker logs openpave-body` → `body node up · adapter=puppypi_local · …`.
(`PuppyPiLocalAdapter` execs into `PUPPY_EXEC_CONTAINER` with `PUPPY_RMW_IMPLEMENTATION` for
the puppy_control hop; the seam stays on `rmw_zenoh_cpp`.)

## Step 4 — Send intents from the DGX (safety ladder)

Send one intent at a time with `send_intent.py` (from a zenoh `client` container on the DGX):

```bash
docker run --rm --net=host -e RMW_IMPLEMENTATION=rmw_zenoh_cpp -e ROS_DOMAIN_ID=0 \
  -v ~/openpave-zenoh:/ws --entrypoint bash odinlmshen/ros2-zenoh-arm:jazzy-edge \
  -lc 'cp /opt/ros/jazzy/share/rmw_zenoh_cpp/config/DEFAULT_RMW_ZENOH_SESSION_CONFIG.json5 /tmp/s.json5 \
    && sed -i "s/mode: \"peer\"/mode: \"client\"/" /tmp/s.json5 \
    && export ZENOH_SESSION_CONFIG_URI=/tmp/s.json5 && source /opt/ros/jazzy/setup.bash \
    && python3 /ws/experiments/zenoh-mve/send_intent.py STOP'
```

Go one rung at a time; only advance after the previous is clean:

1. **STOP** ✅ — `set_mark_time:false` → `set_running:false` → `go_home`. Robot returns to its
   home/rest posture; **no locomotion**.
2. **HOME** — `go_home` only.
3. **TROT** ✅ — mark-time / in-place stepping. **Continuous** — it keeps stepping until stopped.
   ⚠️ **`STOP` via service call is unreliable *while trotting*** (see Safety below) — have the
   hardware E-STOP and the emergency hard-stop ready **before** you trot.
4. **MOVE** — actual locomotion. **Last.** Small `vx`/`yaw`, short `duration_ms`, ready to STOP.

## ⚠️ Safety — `STOP` does NOT reliably stop a *moving* robot

**Learned the hard way (2026-07-29):** while the robot was trotting, **every `STOP` via service
call hung** — the chain STOP, and even a direct same-container `set_mark_time:false`. The robot
kept trotting; the only thing that stopped it was **killing puppy_control**.

**Root cause:** puppy_control's service callbacks are **starved while the gait loop runs**
(single-threaded executor). Idle → services respond instantly; trotting → the busy control loop
never services the stop request. So the high-level `STOP` is least reliable exactly when the
robot is moving — the opposite of what a safety-stop needs.

**Never rely on the software `STOP` alone. Layered stop:**

1. **Hardware E-STOP** (kill switch / power) — always in reach; the real safety net.
2. **Emergency hard-stop** (software, guaranteed) — kill the gait loop directly:
   ```bash
   ssh pi@<PuppyPi-IP> 'docker exec puppypi_ros2 bash -lc "pkill -9 -f puppy_control/lib"'
   ```
   Stepping stops immediately; then relaunch puppy_control (Step 1) to regain control.
3. **Adapter timeout + auto-escalation** (implemented) — `PuppyPiLocalAdapter.stop()` runs the
   motion-stopping calls with a short timeout (`PUPPY_STOP_TIMEOUT_SEC`, default 3s); if they fail
   (starved callback), it **automatically escalates to the hard-stop** (kills the gait) so the
   robot stops even when the graceful STOP can't get through. Every call is also `timeout`-capped
   (`PUPPY_CALL_TIMEOUT_SEC`, default 10s) so a hang never freezes the body.

   > After an escalated hard-stop, puppy_control is dead — **relaunch it (Step 1)** to regain control.

**Still TODO (robot-side):** puppy_control needs a multi-threaded executor / high-priority stop
(Hiwonder code) so the *graceful* STOP works while moving. The hardware E-STOP remains the
primary safety net regardless.

## Key findings

- **Cross-container FastDDS SHM** is why the co-located body needs `PuppyPiLocalAdapter`
  (`docker exec`), not `docker run`. Same-container call responds; a fresh container hangs.
- **Don't ctrl-c the `ros2 launch`** — SIGINT kills puppy_control. Launch detached.
- **RMW split**: seam = `rmw_zenoh_cpp`; puppy hop = `rmw_fastrtps_cpp` (via
  `PUPPY_RMW_IMPLEMENTATION`). One process loads one RMW, hence the separate exec.
- **TROT from rest**: `set_running:true` then `set_mark_time:true` back-to-back can leave the
  robot not stepping; `PuppyPiLocalAdapter.trot()` adds a settle delay (`PUPPY_TROT_SETTLE_SEC`).
- **Reliability**: each adapter call does fresh FastDDS discovery, which can be slow or hang, and
  the body's `on_intent` is synchronous. Each call is now `timeout`-capped so a hang fails fast
  (see Safety). A **persistent robot bridge** (see [docs/further-work.md](../../docs/further-work.md))
  would replace per-call CLI entirely.

## Cleanup / rollback

```bash
# PuppyPi
docker rm -f openpave-body
# DGX
docker rm -f openpave-router
```

`puppy_control` and the stock containers keep running; nothing else is touched.
