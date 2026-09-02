# Runbook: DGX Spark → PuppyPi (seam)

Drive the **real PuppyPi** from a **DGX Spark** brain over the seam plugin, on both transports.
Self-contained for a first-time developer. Config: [`configs/dgx-puppypi.env`](../../configs/dgx-puppypi.env).

| Dimension | Value |
| --- | --- |
| Brain | DGX Spark |
| Body | PuppyPi, adapter `puppypi_bridge` |
| Transport | `raw_zenoh` and `device_connect` (one-line swap) |
| Camera (for confirming motion) | RPi5 + USB cam (optional) |

## Prerequisites

- SSH (key-based) to the DGX and the PuppyPi.
- The PuppyPi carries the full repo at `~/OpenPAVE` with the `.venv-dc` venv (zenoh +
  device-connect-edge); a body serves a real adapter and needs `control_daemon/`.
- The DGX has a venv (`~/.venv-zenoh`) for the brain.

## 1. Install dependencies

```bash
# DGX brain
~/.venv-zenoh/bin/pip install -r requirements-seam.txt
# PuppyPi body (already present on the validated unit; run if missing)
~/.venv-dc/bin/pip install -r requirements-seam.txt
```

## 2. Deploy the seam bundle to the DGX brain

From a full checkout on your workstation:

```bash
scripts/deploy_seam.sh odin@192.168.0.24 '$HOME/openpave-seam' '$HOME/.venv-zenoh/bin/python'
```

This installs `~/openpave-seam` on the DGX (pave_runtime + seam_cli + seam_run + configs). The brain
needs no `control_daemon`.

## 3. Bring up the PuppyPi body

On the **PuppyPi** (`ssh pi@192.168.0.6`), first make sure the repo is a **clean checkout of this
release** (a stale branch will be missing `seam_run.sh` and the seam configs):

```bash
git clone https://github.com/odincodeshen/OpenPAVE.git ~/OpenPAVE   # first time only
cd ~/OpenPAVE && git fetch --tags && git checkout v1.5.0-seam
```

Then, from `~/OpenPAVE`:

```bash
# if a previous bridge is still running, free the port first: docker stop puppypi_ros2
bash scripts/switch_puppypi_ros2.sh                       # ROS 2 puppy_control + bridge (dog stands)
scripts/seam_run.sh configs/dgx-puppypi.env body          # serve puppypi_bridge over the seam
```

Leave the body running (a dedicated terminal, or `tmux`/`nohup`). Healthy output:
`[seam:raw_zenoh] body up · adapter=puppypi_bridge · caps=[...]`. For `raw_zenoh` the body also
listens on `:7447`.

## 4. Drive it from the DGX brain

On the **DGX** (`ssh odin@192.168.0.24`), from `~/openpave-seam`:

```bash
scripts/seam_run.sh configs/dgx-puppypi.env brain send home
scripts/seam_run.sh configs/dgx-puppypi.env brain send trot
scripts/seam_run.sh configs/dgx-puppypi.env brain send stop
```

Each prints `state: {... "status": "completed", "detail": {"path": "bridge", "latency_ms": ...}}`.
The dog should home → trot (walk) → stop. Confirm with the RPi5 camera if available.

## 5. Swap the transport

Change one line in `configs/dgx-puppypi.env` (on both the body's repo and the brain's bundle):

```bash
SEAM_TRANSPORT=device_connect    # was: raw_zenoh
```

Restart the body (step 3) and re-send (step 4). `device_connect` finds the body by D2D discovery over
zenoh multicast — no server. `home`/`trot`/`stop` behave identically.

## Expected results

| Transport | home | trot | stop | path |
| --- | --- | --- | --- | --- |
| `raw_zenoh` | completed ~516 ms | completed ~1015 ms | completed ~515 ms | bridge |
| `device_connect` | completed ~511 ms | completed ~1013 ms | completed ~514 ms | bridge |

Latency is body-side (`detail.latency_ms`); see [`docs/latency-model.md`](../latency-model.md). Record
the outcome in [`docs/validation-matrix.md`](../validation-matrix.md).

## Cleanup

```bash
ssh pi@192.168.0.6 'pkill -f "seam_cli.py serve"; docker stop puppypi_ros2'   # stop body, rest the dog
```

## Troubleshooting

- `raw_zenoh` `send` occasionally returns `no_reply`/timeout (per-call discovery settle) — re-send.
- `device_connect` finds no device: ensure brain and body are on the same LAN and
  `DEVICE_CONNECT_ALLOW_INSECURE=true` (the launcher sets it).
- Bridge times out though services show in discovery: run the bridge as the controller's user
  (`-u ubuntu`); handled by `switch_puppypi_ros2.sh`.
