# zenoh MVE — Hardware Bring-Up Runbook

Step-by-step to run the brain ↔ body transport smoke test on real hosts
(DGX = brain, RPi = body). Each step has a **checkpoint** so a failure is easy to
localize as either *transport* or *application*.

See [README.md](README.md) for the design; this file is the operational guide.

**Goal:** DGX sends an intent → RPi receives it → RPi returns state → DGX measures
round-trip. Fail-safe fires when the heartbeat stops. **No robot motion.**

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

- [ ] **a. discovery** — both nodes visible in `ros2 node list` across hosts
- [ ] **b. downlink** — DGX intent logged by the body on the RPi
- [ ] **c. uplink** — body state received by the probe on the DGX
- [ ] **d. latency** — probe reports a round-trip time per request
- [ ] **e. fail-safe** — killing the probe/router makes the body log the STOP stub
