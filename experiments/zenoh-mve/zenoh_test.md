# zenoh MVE — Hardware Bring-Up Runbook

Operational guide to run the brain ↔ body transport test on real hosts
(DGX = brain, RPi = body), in containers. See [README.md](README.md) for the design
and the validation plan/status.

**Goal:** DGX sends an intent → RPi receives it → RPi returns state → DGX measures
round-trip; fail-safe fires when the link goes quiet. **No robot motion** (mock adapter).

> **✅ Validated** on DGX (`spark`, 192.168.0.24) ↔ RPi (`pi5`, 192.168.0.12) over Wi-Fi,
> both on `odinlmshen/ros2-zenoh-arm:jazzy-edge`.
> **E1a** (pub/sub) 2026-07-27 — checks a–e pass, round-trip avg **9.9 ms**.
> **E1b** (`@rpc`) 2026-07-28 — request/reply, steady-state **~5–6 ms**.

Everything runs in containers named `openpave-*` (additive, easy to remove). Replace
`<DGX-IP>` with the DGX LAN IP (e.g. `192.168.0.24`).

---

## Pre-flight

### 1. Both hosts have the repo

`body_node.py` / `body_rpc.py` import `pave_runtime` and `control_daemon` (they locate the
repo root via `parents[2]`), so the repo must be cloned on each host and mounted into the
container at `/ws`. In the validated runs: RPi `~/OpenPAVE`, DGX `~/openpave-zenoh`.

### 2. Identical environment

Use the **same `ros2-zenoh-arm` image tag on both hosts** — version skew between the two
zenoh stacks is the most common silent failure. The container commands below set
`RMW_IMPLEMENTATION=rmw_zenoh_cpp` and `ROS_DOMAIN_ID=0`.

### 3. Session mode must be `client` (cross-host)

A zenoh session runs in one of three modes:

| mode | role | reaches others via |
|------|------|--------------------|
| `router` (`zenohd`) | relay daemon; interconnects sessions and other routers | listens on `:7447` |
| `peer` | full mesh member; discovers peers and connects to them **directly**, advertising its own locators | direct peer-to-peer |
| `client` | connects **only to a router**; never listens or advertises a locator; all traffic is **relayed through the router** | the router |

**Both nodes use `client`.** This is cross-host (DGX ↔ RPi over Wi-Fi) with `--net=host`.
In `peer` mode (the rmw_zenoh default) each node advertises its own locator and tries to
connect to the other *directly*; under `--net=host` that locator is `tcp/127.0.0.1:<port>`,
which the other host cannot reach (`Unable to connect to any locator of scouted peer
[tcp/127.0.0.1:…]`). In `client` mode neither node connects to the other directly — both
attach to the router, which relays all traffic, so the unreachable-address problem
disappears and the link works across machines.

> Peer mode is fine when every node is on the same host / subnet with directly reachable
> addresses. **Across machines, use `client` and let the router relay.**

The run commands below already apply this (they `sed` the copied session config to
`mode: "client"` and point the body's connect endpoint at the DGX router).

---

## E1a — pub/sub topics (validated)

Intent on `/openpave/intent`, state on `/openpave/robot_state`, heartbeat on
`/openpave/heartbeat`; the brain correlates replies by `request_id`.

**1. Router — DGX:**

```bash
docker run -d --name openpave-router --net=host \
  --shm-size=640m --ulimit memlock=-1:-1 --cap-add NET_ADMIN --security-opt seccomp=unconfined \
  --entrypoint bash odinlmshen/ros2-zenoh-arm:jazzy-edge \
  -lc 'source /opt/ros/jazzy/setup.bash && exec ros2 run rmw_zenoh_cpp rmw_zenohd'
```

**2. Body — RPi** (repo at `~/OpenPAVE`; `client` mode + endpoint → DGX):

```bash
docker run -d --name openpave-body --net=host \
  -e RMW_IMPLEMENTATION=rmw_zenoh_cpp -e ROS_DOMAIN_ID=0 -v ~/OpenPAVE:/ws \
  --shm-size=640m --ulimit memlock=-1:-1 --cap-add NET_ADMIN --security-opt seccomp=unconfined \
  --entrypoint bash odinlmshen/ros2-zenoh-arm:jazzy-edge \
  -lc 'source /opt/ros/jazzy/setup.bash \
    && cp /opt/ros/jazzy/share/rmw_zenoh_cpp/config/DEFAULT_RMW_ZENOH_SESSION_CONFIG.json5 /tmp/sess.json5 \
    && sed -i "s#tcp/localhost:7447#tcp/<DGX-IP>:7447#g" /tmp/sess.json5 \
    && sed -i "s/mode: \"peer\"/mode: \"client\"/" /tmp/sess.json5 \
    && export ZENOH_SESSION_CONFIG_URI=/tmp/sess.json5 \
    && exec python3 /ws/experiments/zenoh-mve/body_node.py'
```

Checkpoint: `docker logs openpave-body` → `body node up · adapter=mock · listening /openpave/intent`.

**3. Brain — DGX** (repo at `~/openpave-zenoh`; `client` mode, local router):

```bash
docker run -d --name openpave-brain --net=host \
  -e RMW_IMPLEMENTATION=rmw_zenoh_cpp -e ROS_DOMAIN_ID=0 -v ~/openpave-zenoh:/ws \
  --shm-size=640m --ulimit memlock=-1:-1 \
  --entrypoint bash odinlmshen/ros2-zenoh-arm:jazzy-edge \
  -lc 'source /opt/ros/jazzy/setup.bash \
    && cp /opt/ros/jazzy/share/rmw_zenoh_cpp/config/DEFAULT_RMW_ZENOH_SESSION_CONFIG.json5 /tmp/sess.json5 \
    && sed -i "s/mode: \"peer\"/mode: \"client\"/" /tmp/sess.json5 \
    && export ZENOH_SESSION_CONFIG_URI=/tmp/sess.json5 \
    && exec python3 /ws/experiments/zenoh-mve/brain_probe.py'
```

**Verify a–e:**

```bash
docker logs -f openpave-brain    # (c/d) <- completed … round-trip N ms, then SUMMARY
docker logs -f openpave-body     # (b)   intent STOP/TROT/MOVE/HOME req=…
docker stop openpave-brain       # (e)   body logs FAIL-SAFE STOP within ~2 s
```

- **a. discovery** — proven implicitly once b/c succeed (the two nodes found each other via
  the router); check explicitly with `docker exec openpave-body bash -lc "source /opt/ros/jazzy/setup.bash && ros2 node list"`.
- **b. downlink** — body log shows each `intent … req=…`.
- **c. uplink** — brain log shows `<- completed req=…`.
- **d. latency** — brain `SUMMARY` line (avg/min/max round-trip).
- **e. fail-safe** — stopping the brain (heartbeat stops) makes the body log the STOP stub.

**Cleanup:**

```bash
docker rm -f openpave-router openpave-brain   # DGX
docker rm -f openpave-body                     # RPi
```

---

## E1b — `@rpc` request/reply (validated)

Same router + `client` config; the intent path is a ROS 2 **service**
(`openpave_interfaces/srv/SubmitIntent`) instead of two topics, so the result returns on
the same call. Each container builds the interface package once (`colcon build`, ~8 s)
before launching the node. (Reuse the E1a router, or start it the same way.)

**Body service — RPi** (build interface → serve `/openpave/submit_intent`):

```bash
docker run -d --name openpave-body-rpc --net=host \
  -e RMW_IMPLEMENTATION=rmw_zenoh_cpp -e ROS_DOMAIN_ID=0 -v ~/OpenPAVE:/ws \
  --shm-size=640m --ulimit memlock=-1:-1 --cap-add NET_ADMIN --security-opt seccomp=unconfined \
  --entrypoint bash odinlmshen/ros2-zenoh-arm:jazzy-edge \
  -lc 'source /opt/ros/jazzy/setup.bash \
    && mkdir -p /tmp/ws/src && cp -r /ws/experiments/zenoh-mve/openpave_interfaces /tmp/ws/src/ \
    && cd /tmp/ws && colcon build --packages-select openpave_interfaces \
    && source /tmp/ws/install/setup.bash \
    && cp /opt/ros/jazzy/share/rmw_zenoh_cpp/config/DEFAULT_RMW_ZENOH_SESSION_CONFIG.json5 /tmp/sess.json5 \
    && sed -i "s#tcp/localhost:7447#tcp/<DGX-IP>:7447#g" /tmp/sess.json5 \
    && sed -i "s/mode: \"peer\"/mode: \"client\"/" /tmp/sess.json5 \
    && export ZENOH_SESSION_CONFIG_URI=/tmp/sess.json5 \
    && exec python3 /ws/experiments/zenoh-mve/body_rpc.py'
```

Checkpoint: `docker logs openpave-body-rpc` → `body @rpc up · … · serving /openpave/submit_intent`.

**Brain client — DGX** (build interface → call the sequence, then exits):

```bash
docker run -d --name openpave-brain-rpc --net=host \
  -e RMW_IMPLEMENTATION=rmw_zenoh_cpp -e ROS_DOMAIN_ID=0 -v ~/openpave-zenoh:/ws \
  --shm-size=640m --ulimit memlock=-1:-1 \
  --entrypoint bash odinlmshen/ros2-zenoh-arm:jazzy-edge \
  -lc 'source /opt/ros/jazzy/setup.bash \
    && mkdir -p /tmp/ws/src && cp -r /ws/experiments/zenoh-mve/openpave_interfaces /tmp/ws/src/ \
    && cd /tmp/ws && colcon build --packages-select openpave_interfaces \
    && source /tmp/ws/install/setup.bash \
    && cp /opt/ros/jazzy/share/rmw_zenoh_cpp/config/DEFAULT_RMW_ZENOH_SESSION_CONFIG.json5 /tmp/sess.json5 \
    && sed -i "s/mode: \"peer\"/mode: \"client\"/" /tmp/sess.json5 \
    && export ZENOH_SESSION_CONFIG_URI=/tmp/sess.json5 \
    && exec python3 /ws/experiments/zenoh-mve/brain_rpc.py'
```

**Verify:**

```bash
docker logs openpave-brain-rpc   # -> INTENT <- completed round-trip N ms, then SUMMARY
docker logs openpave-body-rpc    # @rpc intent STOP/TROT/MOVE/HOME req=…
```

**Cleanup:**

```bash
docker rm -f openpave-body-rpc openpave-brain-rpc   # RPi / DGX
```

---

## E2 — multi-node fan-out (validated)

One router relays to N bodies: the same intent reaches **every** body, and every body
self-protects if the brain link drops. Validated 2026-07-28 with two RPis (`.12`, `.13`)
plus the DGX router/brain.

Reuses `body_node.py` unchanged — each body just gets a **unique node name** at launch via
a ROS remap (no code change): append `--ros-args -r __node:=openpave_body_N` to the
`python3 … body_node.py` call in the E1a **Body** command, and run it on each host:

```bash
# RPi-A (192.168.0.12): ...body_node.py --ros-args -r __node:=openpave_body_1
# RPi-B (192.168.0.13): ...body_node.py --ros-args -r __node:=openpave_body_2
```

Then start the E1a **brain** on the DGX as usual.

**Verify fan-out:**

- Each body log shows all four intents with the **same** `req=…` ids — one intent reached
  both bodies (downlink fan-out):

  ```bash
  # on each RPi
  docker logs openpave-body | grep "intent "
  ```

- Brain `SUMMARY` shows 4/4 round-trips (it records the first reply per id).
- `docker stop openpave-brain` → **both** body logs show `FAIL-SAFE STOP` within ~2 s —
  each body self-protects independently.

**Cleanup:** `docker rm -f openpave-body` on each RPi; `docker rm -f openpave-brain openpave-router` on the DGX.

---

## Troubleshooting: nodes don't exchange

Almost always a node's zenoh session is not reaching the router. Check in order:

0. **Node still in peer mode** (most common) — a body log showing `Unable to connect to any
   locator of scouted peer [tcp/127.0.0.1:…]` means the node is `mode: "peer"`. Switch it to
   `client` per [Pre-flight #3](#3-session-mode-must-be-client-cross-host).
1. **Connect endpoint** — the body's session must point at `tcp/<DGX-IP>:7447`.
2. **Reachability** — from the RPi: `nc -vz <DGX-IP> 7447`.
3. **Version match** — both hosts on the same rmw_zenoh / image tag.
4. **Same env for CLI tools** — `ros2 node list` is itself a zenoh session; run it inside a
   container with the same `RMW_IMPLEMENTATION`, `ROS_DOMAIN_ID`, and session config.

**If you get stuck, capture:** which step + full output; `ros2 node list` / `ros2 topic list`
from both hosts; how the body is configured to reach the router; `nc -vz <DGX-IP> 7447`.

---

## Validation checklist

E1a (pub/sub):

- [x] **a. discovery** — both nodes visible across hosts (2026-07-27)
- [x] **b. downlink** — DGX intent logged by the body on the RPi
- [x] **c. uplink** — body state received by the probe on the DGX
- [x] **d. latency** — round-trip avg 9.9 ms (8.9–10.4) over Wi-Fi
- [x] **e. fail-safe** — heartbeat loss makes the body log the STOP stub (~2.4 s)

E1b (`@rpc`):

- [x] **request/reply** — each service call returns its `command_result` on the same call
- [x] **latency** — steady-state ~5–6 ms round-trip (first call ~38 ms, service warm-up)

E2 (multi-node, 2 RPis + DGX):

- [x] **fan-out** — one intent reaches every body (matching `req` ids)
- [x] **fail-safe fan-out** — brain loss makes every body STOP independently (~2.1 s)
