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

Two variants of the brain→body path, both mock, both validated on DGX + RPi:

**E1a — pub/sub topics** (correlated by `request_id`):

| File | Host | Role |
|------|------|------|
| `body_node.py` | RPi | sub `/openpave/intent` → MockAdapter → pub `/openpave/robot_state`; heartbeat watchdog → STOP stub |
| `brain_probe.py` | DGX | pub intents + 1 Hz heartbeat; sub state; measures round-trip latency |

**E1b — `@rpc` request/reply** (ROS 2 service; the result returns on the same call):

| File | Host | Role |
|------|------|------|
| `openpave_interfaces/` | both | tiny ROS interface pkg — `srv/SubmitIntent.srv` (`string payload` → `string result`) |
| `body_rpc.py` | RPi | serves `/openpave/submit_intent` → MockAdapter → replies with `command_result` JSON |
| `brain_rpc.py` | DGX | calls the service for each intent; measures request/reply round-trip |

All reuse the validated repo modules unchanged (`pave_runtime.intent_schema`,
`control_daemon.feedback`, `control_daemon.adapters`).

> **Validated** on DGX ↔ RPi over Wi-Fi (2026-07-28):
> E1a round-trip avg **9.9 ms**; E1b `@rpc` steady-state **~5–6 ms** (first call ~38 ms
> for service discovery warm-up). Request/reply is a single hop — faster and simpler than
> correlated pub/sub. See [zenoh_test.md](zenoh_test.md) for the exact container commands.

## Validation plan & status

| stage | what | status |
|-------|------|--------|
| **E1a** | brain↔body transport, pub/sub topics (mock, no motion) | ✅ validated 2026-07-27 · avg 9.9 ms |
| **E1b** | request/reply `@rpc` via ROS service (mock, no motion) | ✅ validated 2026-07-28 · ~5–6 ms |
| **E2** | multi-node fan-out — one router, many bodies (mock) | ✅ validated 2026-07-28 · 2 RPis |
| E2 | real `PuppyPiAdapter` — drives the physical robot | planned |
| — | neutral device-connect binding at the seam | later |

E1 (transport) and multi-node fan-out are proven end-to-end on real hardware — mock only,
zero robot motion. Next up: the real adapter.

## How to run

Everything runs in containers on the two hosts. See the **[hardware runbook](zenoh_test.md)**
for the exact, validated `docker run` commands (E1a and E1b), the pre-flight, and the
`client`-mode requirement — plus the a–e checklist.

At a glance: one `rmw_zenohd` **router** on the DGX (`:7447`), then a **body** container on
the RPi and a **brain** container on the DGX, both as zenoh `client`s. Same
`ros2-zenoh-arm` image tag on both hosts; `RMW_IMPLEMENTATION=rmw_zenoh_cpp`,
`ROS_DOMAIN_ID=0`.

## Not in scope (deliberately)

Real robot motion and the neutral device-connect binding — those come later.
(E1b already covers request/reply `@rpc` via a small custom ROS service.)
