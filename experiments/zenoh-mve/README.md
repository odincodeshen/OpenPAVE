# zenoh MVE — brain ↔ body transport smoke test

Minimal viable experiment for the OpenPAVE brain–body seam over zenoh.

**Goal:** prove the DGX (brain) can send an intent to the RPi (body) and receive
state back over one zenoh fabric — **with zero robot motion.** The body node runs
every intent through the existing `MockAdapter`, so only the transport is new.

```
DGX ── /openpave/intent  ▸ ──┐
        ◂ /openpave/robot_state ┤   zenoh router (zenohd, on DGX)
        ⟳ /openpave/heartbeat  ─┘
RPi ── dummy body node (MockAdapter) — no puppy_control
```

## Pieces

| File | Host | Role |
|------|------|------|
| `body_node.py` | RPi | sub `/openpave/intent` → MockAdapter → pub `/openpave/robot_state`; heartbeat watchdog → STOP stub |
| `brain_probe.py` | DGX | pub intents + 1 Hz heartbeat; sub state; measures round-trip latency |

Both reuse the validated repo modules unchanged (`pave_runtime.intent_schema`,
`control_daemon.feedback`, `control_daemon.adapters`).

## Prerequisites

- ROS 2 Jazzy with **`rmw_zenoh`** on both hosts. Use the **same image tag** on
  both (e.g. the `ros2-zenoh-arm` `jazzy-*` ARM64 images) to avoid version skew.
- On both hosts:

```bash
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
export ROS_DOMAIN_ID=0
```

- One **zenoh router** reachable by both hosts. Run it on the DGX and point the
  RPi's zenoh session at it (`tcp/<DGX-IP>:7447`). Reuse the router / connect
  config you already validated in `ros2-zenoh-arm`; the only change here is
  adding the DGX as one more client next to the RPi.

## Run

**1. Router — on the DGX:**

```bash
ros2 run rmw_zenoh_cpp rmw_zenohd
```

**2. Body node — on the RPi (inside the ROS 2 docker):**

```bash
python3 experiments/zenoh-mve/body_node.py
```

**3. Brain probe — on the DGX:**

```bash
python3 experiments/zenoh-mve/brain_probe.py
```

## What you should see

- Probe logs `-> sent STOP/TROT/MOVE/HOME` and then `<- completed … round-trip N ms`.
- Body logs each `intent … req=…` and the mock action.
- Probe prints a `SUMMARY` line with avg/min/max round-trip once all four reply.

## Validation checklist

- [ ] **a. discovery** — `ros2 node list` on either host shows both
      `openpave_brain_probe` and `openpave_body_mock`
- [ ] **b. downlink** — an intent sent on DGX is logged by the body on the RPi
- [ ] **c. uplink** — the body's state is received by the probe on the DGX
- [ ] **d. latency** — the probe reports a round-trip time per request
- [ ] **e. fail-safe** — Ctrl-C the probe (or kill the router); within ~2 s the
      body logs `heartbeat lost -> FAIL-SAFE STOP (stub)`

## Not in scope (deliberately)

Request/reply (`@rpc`) services, custom ROS messages, real robot motion, and the
neutral device-connect binding. Those come after this transport path is green.
