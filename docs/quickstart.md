# OpenPAVE Quickstart

> New to OpenPAVE? Start here. · 中文版:[quickstart.zh-TW.md](quickstart.zh-TW.md)

OpenPAVE is an open-source **brain–body** Physical AI validation platform for Arm edge ecosystems.
This is the first-timer's guide: what it is, how to run it, and which doc to read next.

## 1. What OpenPAVE is

In one line: a **reference base** you plug your own hardware, models, transport, and use case into.
It focuses on **one thing** — carrying "what the brain wants" reliably to "the body (robot) that does
it", then reporting and measuring the result.

**What it is not:** not an LLM serving framework (like vLLM / Ollama), and not a full commercial
robotics stack. It is one *verifiable, measurable* brain↔body workflow.

## 2. Mental model: two layers, one seam

The whole system is two layers with a single **seam** between them — the seam is the only boundary
OpenPAVE owns.

![Brain–Body Architecture](architecture-brain-body.svg)

On top sits a **four-dimension** model; one complete setup is a choice of these four, and a `config`
file binds them into a ready-to-run recipe:

| Dimension | What it is | How you pick it |
| --- | --- | --- |
| Brain | which compute host | pick one host |
| Body | which robot / sensor | `ROBOT_ADAPTER=` puppypi / camera_usb … |
| Transport | the wire the seam runs over | `SEAM_TRANSPORT=` raw_zenoh / device_connect |
| Application | what runs on top | vLLM / gesture prompt … |

## 3. Run it in five minutes (no hardware)

The `mock` profile exercises the whole runtime without a robot:

```bash
git clone --recurse-submodules https://github.com/odincodeshen/OpenPAVE.git
cd OpenPAVE
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip -r intent_ingress/requirements.txt -e ui
OPENPAVE_CONFIG=configs/mock.env ./scripts/run_openpave.sh
```

Open `http://127.0.0.1:8090/pave`. If the console loads, the full runtime (intent → control →
feedback) is working.

## 4. Pick your path

OpenPAVE has **two ways to "run" — don't mix them up.** Start from your goal:

| Your goal | Path | Start here |
| --- | --- | --- |
| Just try it, no hardware | baseline | Section 3 (mock) |
| Understand the design | read | [openpave-platform-spec.md](openpave-platform-spec.md) |
| Drive a real robot over the seam (send home / trot / stop) | **seam** | `docs/runbooks/<brain>-<body>.md` |
| Full gesture-control demo (camera → VLM → robot) | baseline | [runbooks/puppypi-gesture-control.md](runbooks/puppypi-gesture-control.md) |
| See what's validated + performance | read | [validation-matrix.md](validation-matrix.md) · [latency-model.md](latency-model.md) |

**The two paths (key difference):** the **seam** path (`seam_run.sh`) is the swappable transport —
it sends discrete capability commands. The **baseline** path (`run_openpave.sh`) is the full
application runtime (VLM / UI / gesture). The gesture demo uses baseline, **not** the seam.

## 5. Drive real hardware

Every brain × body combination has a self-contained runbook (deps → deploy → body → send → expected
→ cleanup):

| Combination | Path | Runbook |
| --- | --- | --- |
| DGX → PuppyPi (dog) | seam | [dgx-puppypi.md](runbooks/dgx-puppypi.md) |
| Radxa O6 → PuppyPi (dog) | seam | [radxa-puppypi.md](runbooks/radxa-puppypi.md) |
| DGX → RPi5 camera | seam | [dgx-rpicam.md](runbooks/dgx-rpicam.md) |
| Radxa O6 → RPi5 camera | seam | [radxa-rpicam.md](runbooks/radxa-rpicam.md) |
| Gesture control (DGX brain) | baseline | [puppypi-gesture-control.md](runbooks/puppypi-gesture-control.md) |

The seam path is three steps (details in the runbook; switching transport is a one-line
`SEAM_TRANSPORT` change):

```bash
# 1. deploy the seam bundle to the brain
scripts/deploy_seam.sh <user>@<brain-ip> '$HOME/openpave-seam' '<venv>/bin/python'
# 2. bring up the body (on the robot host)
scripts/seam_run.sh configs/dgx-puppypi.env body
# 3. drive it from the brain
scripts/seam_run.sh configs/dgx-puppypi.env brain send home
```

## 6. Glossary

| Term | Meaning |
| --- | --- |
| seam | the single protocol boundary between brain and body — OpenPAVE's core |
| capability | the unified body contract: `{action, params}` in, a state dict out (run by dispatch) |
| adapter | the part that talks to a given body: `puppypi_bridge`, `camera_usb`, … |
| transport | the wire the seam runs over: `raw_zenoh`, `device_connect` |
| config | an `.env` recipe binding the four dimensions into one validated combination |
| /pave | the observability console (prompt / result / feedback), from a `live-vlm-webui` fork |

## 7. What to read next

1. [README.md](../README.md) / [README_cn.md](../README_cn.md) — full overview (EN / 中文)
2. [openpave-platform-spec.md](openpave-platform-spec.md) — positioning, four-dimension model, architecture
3. [validation-matrix.md](validation-matrix.md) — what's validated, and to what depth
4. [runbooks/](runbooks/) — pick your combination and follow it
5. [latency-model.md](latency-model.md) — the three-segment latency breakdown

**Stuck?** Check the **Troubleshooting** section of the matching runbook. The common traps are
written down: occasional raw_zenoh resend, device_connect needs the same subnet, the PuppyPi bridge
must run as `-u ubuntu`, and the camera needs headless OpenCV.
