# Seam Validation Runbook

Reproduce the real-brain seam matrix: a **brain** node driving a physical **body** endpoint over the
seam transport plugin (`pave_runtime.seam`), across both transports (`raw_zenoh`, `device_connect`).
This is the runbook the `docs/validation-matrix.md` seam rows point to. The results it reproduces are
recorded in that file's "Real-Brain Seam Plugin Validation (2026-09-02)" section.

Everything is driven by a **four-dimension recipe** (`configs/*.env`) and one launcher
(`scripts/seam_run.sh`); swapping a transport is a one-line change to `SEAM_TRANSPORT`.

## Topology

Example hosts from the 2026-09-02 run (the real values live in each `configs/*.env`):

| Role | Host (example) | What runs there |
| --- | --- | --- |
| Brain | DGX Spark `192.168.0.24`, Radxa O6 `192.168.0.5` | `seam_run.sh <recipe> brain send <action>` |
| Body — actuator | PuppyPi `192.168.0.6` | ROS 2 `puppy_control` + persistent bridge + `seam_run.sh <recipe> body` |
| Body — sensor | RPi5 + USB camera `192.168.0.21` | `seam_run.sh <recipe> body` (`ROBOT_ADAPTER=camera_usb`) |

A recipe pins brain + body + transport + inference layer; see `docs/openpave-platform-spec.md`.

## Prerequisites

- SSH access to each host (key-based).
- A Python venv per host (any recent Python 3.11+).
- The **body** hosts carry the full repo (a serving body needs `control_daemon/`); **brains** need
  only the seam bundle (`scripts/deploy_seam.sh` installs it).
- For the PuppyPi actuator body: the ROS 2 controller + bridge (`scripts/switch_puppypi_ros2.sh`).

## Step 1 — Install dependencies

Install the seam deps into each host's venv (pinned versions in the requirements files):

```bash
# brain and body (all hosts on the seam path)
<venv>/bin/pip install -r requirements-seam.txt
# camera sensor body only (adds OpenCV, headless)
<venv>/bin/pip install -r requirements-seam-camera.txt
```

Role split (each side only imports what it needs): the brain uses `eclipse-zenoh` (raw_zenoh) and
`device-connect-agent-tools` (device_connect); a serving body uses `eclipse-zenoh` and
`device-connect-edge`. Installing all three everywhere is harmless.

## Step 2 — Deploy the seam bundle to each brain

```bash
# from a full checkout, on your workstation:
scripts/deploy_seam.sh odin@192.168.0.24  '$HOME/openpave-seam'  '$HOME/.venv-zenoh/bin/python'
scripts/deploy_seam.sh radxa@192.168.0.5  '$HOME/openpave-seam'  '$HOME/.venv/bin/python'
```

This ships `pave_runtime/` + `scripts/{seam_cli.py,seam_run.sh}` + `configs/` + the requirements
files, and (given the third arg) pip-installs `requirements-seam.txt` on the remote. The brain needs
no `control_daemon` — `seam_cli.py` imports the adapter lazily.

## Step 3 — Bring up the body

**Actuator (PuppyPi)** — on the PuppyPi, from the repo:

```bash
bash scripts/switch_puppypi_ros2.sh            # ROS 2 puppy_control + bridge (dog stands)
scripts/seam_run.sh configs/dgx-puppypi.env body    # serve the puppypi_bridge adapter over the seam
```

**Sensor (RPi5 camera)** — on the RPi5, from the repo:

```bash
scripts/seam_run.sh configs/dgx-camera.env body     # serve get_image (camera_usb) over the seam
```

Leave the body running in a dedicated terminal (or under `tmux` / `nohup` for a detached run — a
process backgrounded through a one-shot SSH command may not persist). A healthy body prints
`[seam:<transport>] body up · adapter=<name> · caps=[...]`. For `raw_zenoh` it also listens on
`:7447` (the launcher sets `ZENOH_LISTEN` on the body).

## Step 4 — Drive it from the brain

On the brain (in `~/openpave-seam`):

```bash
scripts/seam_run.sh configs/dgx-puppypi.env brain send home
scripts/seam_run.sh configs/dgx-puppypi.env brain send trot
scripts/seam_run.sh configs/dgx-puppypi.env brain send stop
# sensor:
scripts/seam_run.sh configs/dgx-camera.env  brain send get_image
```

Each prints `state: {... "status": "completed" ...}`. Actuator actions carry
`detail.path=bridge` and `detail.latency_ms`; `get_image` returns control-plane metadata
(`{encoding, bytes, width, height, source, seq}`) — the frame itself rides a separate data plane
(see `experiments/camera-mve/`).

## Step 5 — Swap the transport

Change one line in the recipe and re-run both endpoints — nothing else changes:

```bash
# configs/<recipe>.env
SEAM_TRANSPORT=device_connect    # was: raw_zenoh
```

`raw_zenoh` uses `ZENOH_LISTEN`/`ZENOH_CONNECT` (derived from `BODY_HOST` by the launcher);
`device_connect` uses D2D discovery over zenoh multicast presence (the launcher sets
`DEVICE_CONNECT_ALLOW_INSECURE`), so brain and body find each other on the LAN with no server.

## Expected results

See `docs/validation-matrix.md` → "Real-Brain Seam Plugin Validation (2026-09-02)". In short: across
both brains and both transports, actuator `latency_ms` is ~514 ms (home/stop) / ~1013 ms (trot), all
`path=bridge`; camera `get_image` returns a ~98 KB 640×480 JPEG's metadata. The seam and brain add
negligible cost — latency is dominated by the body-side bridge / controller.

## Cleanup

```bash
# stop any body
ssh <body-host> 'pkill -f "seam_cli.py serve"'
# rest the dog (stop the ROS 2 controller + bridge)
ssh <puppypi> 'docker stop puppypi_ros2'
```

## Troubleshooting

- **`raw_zenoh` `send` returns `no_reply`/timeout occasionally.** The brain opens a fresh zenoh
  session per `send`, so discovery can miss within the 0.5 s settle window. Re-send; it succeeds. A
  long-lived brain session would remove this.
- **`device_connect` finds no device.** Ensure brain and body are on the same LAN (D2D uses zenoh
  multicast presence) and both have `DEVICE_CONNECT_ALLOW_INSECURE=true` (the launcher sets it).
- **PuppyPi bridge times out even though services show in discovery.** Run the bridge as the
  controller's user (`-u ubuntu`): FastDDS shared memory is per-user. This is handled by
  `switch_puppypi_ros2.sh`.
- **Camera body fails to import `cv2`.** Install `requirements-seam-camera.txt` (headless OpenCV) on
  the camera host; the GUI build needs X11 libs a headless RPi5 lacks.
