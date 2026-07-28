# zenoh MVE — Hardware Bring-Up Runbook

Step-by-step to run the brain ↔ body transport smoke test on real hosts
(DGX = brain, RPi = body). Each step has a **checkpoint** so a failure is easy to
localize as either *transport* or *application*.

See [README.md](README.md) for the design; this file is the operational guide.

**Goal:** DGX sends an intent → RPi receives it → RPi returns state → DGX measures
round-trip. Fail-safe fires when the heartbeat stops. **No robot motion.**

> **✅ Validated 2026-07-27** on DGX (`spark`, 192.168.0.24) ↔ RPi (`pi5`, 192.168.0.12)
> over Wi-Fi, both running `odinlmshen/ros2-zenoh-arm:jazzy-edge`. All checks a–e pass;
> round-trip **avg 9.9 ms** (8.9–10.4). See [Validated container commands](#validated-container-commands-2026-07-27).
>
> **Key finding:** for cross-host, every node's zenoh session **must be `mode: "client"`,
> not the default `mode: "peer"`.** See [Pre-flight #3](#3-session-mode-must-be-client-cross-host).

---

## Pre-flight (before running anything)

### 1. RPi must have the repo

`body_node.py` imports `pave_runtime` and `control_daemon` (it locates the repo
root via `parents[2]`). So the repo must be present inside the RPi's ROS 2
container — `git clone` the `feat/brain-body-zenoh` branch or mount the repo in.

> `brain_probe.py` has no repo imports (only `rclpy`), so the DGX side needs just
> the script plus ROS 2.

### 2. Identical environment on both hosts

```bash
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
export ROS_DOMAIN_ID=0
```

Confirm rmw_zenoh is installed:

```bash
ros2 pkg list | grep rmw_zenoh
```

Use the **same `ros2-zenoh-arm` image tag on both hosts** — version skew between
the two zenoh stacks is the most common silent failure.

### 3. Session mode must be `client` (cross-host)

A zenoh session runs in one of three modes:

| mode | role | reaches others via |
|------|------|--------------------|
| `router` (`zenohd`) | relay daemon; interconnects sessions and other routers | listens on `:7447` |
| `peer` | full mesh member; discovers peers and connects to them **directly**, advertising its own locators | direct peer-to-peer |
| `client` | connects **only to a router**; never listens or advertises a locator; all traffic is **relayed through the router** | the router |

**This experiment uses `client` for both nodes.** It is cross-host (DGX ↔ RPi over
Wi-Fi) with `--net=host`. In `peer` mode (the rmw_zenoh default) each node advertises
its own locator and tries to connect to the other *directly*; under `--net=host` that
locator is `tcp/127.0.0.1:<port>`, which the other host cannot reach (`Unable to connect
to any locator of scouted peer [tcp/127.0.0.1:…]`). In `client` mode neither node
connects to the other directly — both attach to the router, which relays all pub/sub, so
the unreachable-address problem disappears and the link works across machines.

> Peer mode is fine when every node is on the same host / subnet with directly reachable
> addresses. **Across machines, use `client` and let the router relay.**

Set **every** node to `mode: "client"`. On each node, copy the default session config and
edit it before launching:

```bash
cp /opt/ros/jazzy/share/rmw_zenoh_cpp/config/DEFAULT_RMW_ZENOH_SESSION_CONFIG.json5 /tmp/sess.json5
sed -i 's/mode: "peer"/mode: "client"/' /tmp/sess.json5
# body only: point the connect endpoint at the router on the DGX
sed -i 's#tcp/localhost:7447#tcp/<DGX-IP>:7447#g' /tmp/sess.json5
export ZENOH_SESSION_CONFIG_URI=/tmp/sess.json5
```

The brain shares the router's host, so it keeps the default `tcp/localhost:7447` endpoint
and only needs the `mode` change.

---

## Run steps

### Step 1 — Router (exactly one)

If you already have a running `ros2-zenoh-arm` central router, **reuse it** and
point both hosts at it — do not start a second one. Otherwise start it on the DGX:

```bash
ros2 run rmw_zenoh_cpp rmw_zenohd
```

Make sure port `7447` on the DGX is not blocked by a firewall.

### Step 2 — Body node (on the RPi)

```bash
python3 experiments/zenoh-mve/body_node.py
```

**Checkpoint:** logs `body node up · adapter=mock · listening /openpave/intent`.

### Step 3 — Discovery check (on the DGX, before the probe)

```bash
ros2 node list
```

**Checkpoint (a. discovery):**
- ✅ `/openpave_body_mock` appears → zenoh crosses hosts. Continue.
- ❌ only local nodes → **stop here.** Transport is not connected — see
  [Troubleshooting](#troubleshooting-step-3-discovery-fails).

### Step 4 — Brain probe (on the DGX)

```bash
python3 experiments/zenoh-mve/brain_probe.py
```

**Checkpoint (b / c / d):**
- Probe logs `-> sent STOP/TROT/MOVE/HOME` then `<- completed … round-trip N ms`.
- Body logs each `intent … req=…` and the mock action.
- Probe prints a `SUMMARY` line (avg/min/max round-trip) once all four reply.

### Step 5 — Fail-safe test (e)

Ctrl-C the probe (or kill the router). Within ~2 s the body logs:

```
heartbeat lost -> FAIL-SAFE STOP (stub)
```

---

## Troubleshooting: Step 3 discovery fails

Almost always the RPi's zenoh session is not reaching the DGX router. Check in order:

0. **Node still in peer mode** (most common) — if a body log shows `Unable to connect to
   any locator of scouted peer [tcp/127.0.0.1:…]`, the node is `mode: "peer"`. Switch it to
   `mode: "client"` per [Pre-flight #3](#3-session-mode-must-be-client-cross-host).
1. **Connect endpoint** — the RPi client must point at `tcp/<DGX-IP>:7447`. Reuse
   the client config you already validated in `ros2-zenoh-arm`; the DGX is just
   one more client alongside the RPi.
2. **Reachability** — from the RPi:

   ```bash
   nc -vz <DGX-IP> 7447
   ```

3. **Version match** — both hosts on the same rmw_zenoh / image tag.
4. **Same env for CLI tools** — `ros2 node list` is itself a zenoh session; run it
   with the same `RMW_IMPLEMENTATION` and `ROS_DOMAIN_ID`.

## If you get stuck, capture this

- Which step, and the full terminal output at that point
- `ros2 node list` and `ros2 topic list` from **both** hosts
- How the RPi is configured to reach the router (where the endpoint is set, and its value)
- Output of `nc -vz <DGX-IP> 7447` from the RPi

---

## Validation checklist

- [x] **a. discovery** — both nodes visible across hosts (validated 2026-07-27)
- [x] **b. downlink** — DGX intent logged by the body on the RPi
- [x] **c. uplink** — body state received by the probe on the DGX
- [x] **d. latency** — round-trip avg 9.9 ms (8.9–10.4) over Wi-Fi
- [x] **e. fail-safe** — heartbeat loss makes the body log the STOP stub (~2.4 s)

---

## Validated container commands (2026-07-27)

The runbook above is native-shell oriented; this is the exact **containerized** flow that
passed, using `odinlmshen/ros2-zenoh-arm:jazzy-edge`. Containers are named `openpave-*`
(additive, easy to remove). Replace `<DGX-IP>` with the DGX's LAN IP (e.g. 192.168.0.24).

**Router — DGX:**

```bash
docker run -d --name openpave-router --net=host \
  --shm-size=640m --ulimit memlock=-1:-1 --cap-add NET_ADMIN --security-opt seccomp=unconfined \
  --entrypoint bash odinlmshen/ros2-zenoh-arm:jazzy-edge \
  -lc 'source /opt/ros/jazzy/setup.bash && exec ros2 run rmw_zenoh_cpp rmw_zenohd'
```

**Body — RPi** (repo cloned at `~/OpenPAVE`; `mode: client` + endpoint → DGX):

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

**Brain — DGX** (repo cloned at `~/openpave-zenoh`; `mode: client`, local router):

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

**Watch / test / clean up:**

```bash
docker logs -f openpave-brain          # DGX: sent / completed / SUMMARY
docker logs -f openpave-body           # RPi: intents received
docker stop openpave-brain             # -> body logs FAIL-SAFE STOP within ~2 s
docker rm -f openpave-router openpave-brain   # DGX cleanup
docker rm -f openpave-body                     # RPi cleanup
```

### E1b — `@rpc` request/reply variant (2026-07-28)

Same router, same `client`-mode config; the intent path is a ROS 2 **service**
(`openpave_interfaces/srv/SubmitIntent`) instead of two topics. Each container builds
the interface package once (`colcon build`, ~8 s) before launching the node. Validated
round-trip: steady-state **~5–6 ms** (first call ~38 ms for service discovery warm-up).

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

docker logs openpave-brain-rpc         # -> INTENT <- completed round-trip N ms, then SUMMARY
docker rm -f openpave-body-rpc openpave-brain-rpc   # cleanup (RPi / DGX)
```
