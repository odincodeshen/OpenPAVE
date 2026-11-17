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

- Key-based SSH to both devices, `rsync`, and Python 3.10 or later with venv support
  (`python3-venv` on Debian/Ubuntu).
- A full current OpenPAVE checkout on your workstation. Use this **same source version**
  for the DGX brain bundle and the full PuppyPi copy, including any local uncommitted
  changes. The raw Zenoh client requires the updated body to echo correlation IDs;
  the current body also provides the motion lease described below.
- Replace `<DGX_USER>`, `<DGX_IP>`, `<PUPPYPI_USER>` and `<PUPPYPI_IP>` in the commands
  with your SSH accounts and device addresses. Before copying or deploying, edit
  `BRAIN_HOST` and `BODY_HOST` in `configs/dgx-puppypi.env` to use those addresses.

From the workstation's repository root, copy the full source to the PuppyPi (the
real adapter needs `control_daemon/`; create the device's venv separately):

```bash
rsync -az --exclude='.venv*/' --exclude='venv/' --exclude='__pycache__/' --exclude='benchmark-results/' \
  ./ '<PUPPYPI_USER>@<PUPPYPI_IP>:~/OpenPAVE/'
```

## 1. Install dependencies

On the **DGX**, create the brain environment; step 2 installs its dependencies
from the deployed bundle:

```bash
python3 -m venv "$HOME/.venv-zenoh"
```

On the **PuppyPi**, install the seam dependencies from the full source copy:

```bash
cd ~/OpenPAVE
python3 -m venv "$HOME/.venv-dc"
"$HOME/.venv-dc/bin/python" -m pip install -r requirements-seam.txt
```

## 2. Deploy the seam bundle to the DGX brain

From a full checkout on your workstation:

```bash
scripts/deploy_seam.sh '<DGX_USER>@<DGX_IP>' '$HOME/openpave-seam' '$HOME/.venv-zenoh/bin/python'
```

This installs `~/openpave-seam` on the DGX (pave_runtime + seam_cli + seam_run + configs). The brain
needs no `control_daemon`.

## 3. Bring up the PuppyPi body

On the **PuppyPi** (`ssh '<PUPPYPI_USER>@<PUPPYPI_IP>'`), use the current full source
copy from the prerequisites, matching the DGX bundle. From `~/OpenPAVE`:

```bash
cd ~/OpenPAVE
# if a previous bridge is still running, free the port first: docker stop puppypi_ros2
bash scripts/switch_puppypi_ros2.sh                       # ROS 2 puppy_control + bridge (dog stands)
scripts/seam_run.sh configs/dgx-puppypi.env body          # serve puppypi_bridge over the seam
```

Leave the body running (a dedicated terminal, or `tmux`/`nohup`). Healthy output:
`[seam:raw_zenoh] body up · adapter=puppypi_bridge · caps=[...]`. For `raw_zenoh` the body also
listens on `:7447`.

## 4. Drive it from the DGX brain

On the **DGX** (`ssh '<DGX_USER>@<DGX_IP>'`), from `~/openpave-seam`:

```bash
scripts/seam_run.sh configs/dgx-puppypi.env brain send home
scripts/seam_run.sh configs/dgx-puppypi.env brain send trot
scripts/seam_run.sh configs/dgx-puppypi.env brain send stop
```

Each prints `state: {... "status": "completed", "detail": {"path": "bridge", "latency_ms": ...}}`.
The dog should home → trot (walk) → stop. Confirm with the RPi5 camera if available.

> **Since v1.8.2 the body stops a motion that is not renewed** — a `trot` / `move` lasts `BODY_MOTION_TTL_S` (default 5 s) unless the brain keeps renewing it. A one-shot `send trot` therefore marks time for about 5 s and then the body stops itself; still send `stop` to end it cleanly. (`run_live.py` renews automatically.)

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
ssh '<PUPPYPI_USER>@<PUPPYPI_IP>' 'pkill -f "seam_cli.py serve"; docker stop puppypi_ros2'   # stop body, rest the dog
```

## Troubleshooting

- `raw_zenoh` `send` occasionally returns `no_reply`/timeout (per-call discovery settle) — re-send.
- `device_connect` finds no device: ensure brain and body are on the same LAN and
  `DEVICE_CONNECT_ALLOW_INSECURE=true` (the launcher sets it).
- Bridge times out though services show in discovery: the bridge must run as the controller's
  user. Check the controller account used by `switch_puppypi_ros2.sh` for your installation.
