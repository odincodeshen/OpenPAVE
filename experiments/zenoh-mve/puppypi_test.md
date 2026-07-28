# PuppyPi real-adapter run — DGX brain → real PuppyPi over zenoh

> ⚠️ **This drives a REAL robot.** Follow the safety ladder in Step 5 — send `STOP`/`HOME`
> and confirm the path before any locomotion. Keep the robot in a clear area with a hand on
> the kill switch.

Extends the [zenoh MVE](README.md): the **same brain↔body zenoh seam** as E1a, but the
body runs the real `PuppyPiAdapter` (not the mock), which commands `puppy_control` on the
PuppyPi. Only the adapter changes; the transport is unchanged.

## Architecture — two independent hops

```
DGX (brain) ──zenoh · Jazzy · rmw_zenoh──▶ body node (on the PuppyPi)
                                              │  PuppyPiAdapter
                                              ▼  docker run ros:humble / puppy-ros2-cli
                                           puppy_control (Humble · FastDDS, LOCAL)
                                              ▼
                                           servos / motion  (real)
```

- **Seam** (brain↔body): zenoh, `client` mode, via the router on the DGX — as validated in E1.
- **Body-internal** (body→robot): `PuppyPiAdapter` shells out to Dockerized ROS 2 Humble CLI
  (`/puppy_control/set_running`, `go_home`, `velocity_move`, …). This hop is FastDDS and stays
  **local to the PuppyPi**. The two hops use different RMWs and do not interfere.

## Roles

| host | runs |
|------|------|
| **DGX** | zenoh router + brain (`brain_probe.py` or `brain_rpc.py`) |
| **PuppyPi** | `puppy_control` (robot controller) **and** the body node with `ROBOT_ADAPTER=puppypi` |
| RPi5 | optional mock body for mixed fan-out — **add later**, not in the first run |

## Prerequisites — confirm before running

- [ ] **PuppyPi IP**: `__________`
- [ ] **`puppy_control` launched** on the PuppyPi (`ros2 launch puppy_control puppy_control.launch.py`)
- [ ] **Humble images present on the PuppyPi**: `ros:humble` and `puppy-ros2-cli:humble`
      (build the latter with `scripts/build_puppy_ros2_cli.sh`)
- [ ] **Body container can reach docker** to spawn the Humble containers — mount the socket
      (`-v /var/run/docker.sock:/var/run/docker.sock`) and provide the `docker` CLI inside
      (mount the host binary or install it). *(Deployment detail to confirm on the PuppyPi.)*
- [ ] **Safe area** ready; kill switch reachable.

## Step 1 — Code: adapter selection (done)

`body_node.py` / `body_rpc.py` now pick the adapter from the `ROBOT_ADAPTER` env var, default
`mock`:

```python
self.adapter = create_robot_adapter(os.environ.get("ROBOT_ADAPTER", "mock"))
```

So the real robot is driven **only** when `ROBOT_ADAPTER=puppypi` is set explicitly.

## Step 2 — Robot side: launch `puppy_control` (on the PuppyPi)

```bash
docker start puppypi_ros2
docker exec -it -u ubuntu -w /home/ubuntu puppypi_ros2 /bin/bash
# inside:
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
source /opt/ros/humble/setup.bash
source /home/ubuntu/ros2_ws/install/setup.bash
ros2 launch puppy_control puppy_control.launch.py
```

**Checkpoint:** `ros2 service list | grep puppy_control` shows `/puppy_control/set_running`,
`/puppy_control/go_home`, etc.

## Step 3 — Body node on the PuppyPi (`ROBOT_ADAPTER=puppypi`)

Runs the zenoh body node (Jazzy/rmw_zenoh for the seam) with the real adapter enabled and
docker access so `PuppyPiAdapter` can spawn the Humble CLI containers:

> ⚠️ **Resolve the RMW collision first (needed code tweak).** The body node's own process
> env must be `RMW_IMPLEMENTATION=rmw_zenoh_cpp` (for the zenoh seam). But
> `PuppyPiAdapter`'s `RosCliConfig.from_env()` reads the **same** `RMW_IMPLEMENTATION` to set
> the RMW of the Humble containers it spawns — those need `rmw_fastrtps_cpp` to reach
> `puppy_control`. One env var cannot be both. Before the real run, make the adapter's RMW
> independent of the seam — e.g. give `RosCliConfig` a dedicated `PUPPY_RMW_IMPLEMENTATION`
> that falls back to today's `RMW_IMPLEMENTATION` default, so the existing baseline is
> unchanged. Small and backward-compatible, but **required** for this deployment.

```bash
docker run -d --name openpave-body --net=host \
  -e RMW_IMPLEMENTATION=rmw_zenoh_cpp -e ROS_DOMAIN_ID=0 \
  -e ROBOT_ADAPTER=puppypi \
  -e PUPPY_RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
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

Notes:
- `PUPPY_RMW_IMPLEMENTATION` above assumes the `RosCliConfig` tweak from the warning is in
  place; without it the adapter would (wrongly) use `rmw_zenoh_cpp` for the Humble containers.
- `docker.sock` + `docker` CLI let the adapter's `docker run ros:humble …` work from inside
  the body container. Confirm the mounted `docker` binary runs (`docker version`) — if not,
  install the CLI in the image or run the body node natively on the PuppyPi.

**Checkpoint:** `docker logs openpave-body` shows `body node up · adapter=puppypi · …`.

## Step 4 — Brain on the DGX

Start the router and the brain exactly as in E1a (see [zenoh_test.md](zenoh_test.md) → E1a).
Keep the intent sequence short for the first real run.

## Step 5 — Safety ladder (real motion — go slowly)

Drive one rung at a time; only advance after the previous rung is clean. At any point, send
`STOP` or stop the brain container (fail-safe) to halt.

1. **STOP** — send `STOP` only. Adapter runs `set_mark_time:false`, `set_running:false`,
   `go_home`. The robot resets posture; **no locomotion**. Confirm every step's
   `return_code = 0` in the body log.
2. **HOME** — `go_home` only. Safe posture reset. Confirms the service path end-to-end.
3. **TROT** — mark-time / in-place stepping. Watch `TROT_CONFIRMATIONS` (keep = 2). No travel.
4. **MOVE** — actual locomotion. **Last.** Start with small `vx`/`yaw` and short
   `duration_ms`, in the safe area, ready to STOP.

## Cleanup / rollback

```bash
# PuppyPi
docker rm -f openpave-body          # STOP_ROBOT_ON_EXIT sends a final STOP for puppypi
# DGX
docker rm -f openpave-router openpave-brain
```

`puppy_control` can keep running or be stopped separately.

## Open decisions (confirm with the environment)

- **Where the body node runs.** Target (this doc): **on the PuppyPi** — ROS stays local, only
  the zenoh seam crosses the network. Alternative (baseline-style): body + adapter on the
  control side, reaching `puppy_control` over ROS 2/DDS on Wi-Fi. The first is preferred for
  the brain-body co-computing goal, provided the PuppyPi can run the body container + docker.
- **docker-in-body vs native.** Socket + CLI mount (above) vs running the body node natively
  on the PuppyPi. Depends on what the PuppyPi has installed.
