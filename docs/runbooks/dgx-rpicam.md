# Runbook: DGX Spark → RPi5 USB Camera (seam, sensing)

Read a frame from a **RPi5 USB camera** from a **DGX Spark** brain over the seam plugin, on both
transports. This is a **sensing** capability (`get_image`), the sensor counterpart of the actuator
runbooks. Config: [`configs/dgx-rpicam.env`](../../configs/dgx-rpicam.env).

| Dimension | Value |
| --- | --- |
| Brain | DGX Spark |
| Body | RPi5 + USB camera, adapter `camera_usb`, `/dev/video0` |
| Transport | `raw_zenoh` and `device_connect` (one-line swap) |
| Capability | `get_image` (control-plane metadata; the JPEG rides a separate data plane) |

## Control / data plane split

`get_image` over the seam returns **control-plane metadata only**: `{encoding, bytes, width, height,
source, seq}` for a freshly grabbed frame. The **JPEG bytes travel on a separate data plane** (see
`experiments/camera-mve/`); `seam_run.sh` carries the control plane only.

## Prerequisites

- SSH (key-based) to the DGX and the RPi5.
- The RPi5 carries a clean checkout of this release at `~/OpenPAVE` (see step 3) with a venv
  (`~/.venv-zenoh`) holding `opencv-python-headless` + `eclipse-zenoh` (+ `device-connect-edge` for
  `device_connect`).

## 1. Install dependencies

```bash
# DGX brain
~/.venv-zenoh/bin/pip install -r requirements-seam.txt
# RPi5 camera body
~/.venv-zenoh/bin/pip install -r requirements-seam.txt -r requirements-seam-camera.txt
```

## 2. Deploy the seam bundle to the DGX brain

```bash
scripts/deploy_seam.sh odin@<dgx-ip> '$HOME/openpave-seam' '$HOME/.venv-zenoh/bin/python'
```

## 3. Bring up the RPi5 camera body

On the **RPi5**, first ensure a clean checkout of this release (a stale branch is missing `seam_run.sh`
and the camera configs):

```bash
git clone https://github.com/odincodeshen/OpenPAVE.git ~/OpenPAVE   # first time only
cd ~/OpenPAVE && git fetch --tags && git checkout v1.5.0-seam
```

Then, from `~/OpenPAVE`:

```bash
scripts/seam_run.sh configs/dgx-rpicam.env body      # serve get_image (camera_usb) over the seam
```

Healthy: `[seam:raw_zenoh] body up · adapter=camera_usb · caps=['get_image']`. For `raw_zenoh` the
body also listens on `:7447`.

## 4. Read a frame from the DGX brain

On the **DGX**, from `~/openpave-seam`:

```bash
scripts/seam_run.sh configs/dgx-rpicam.env brain send get_image
```

Prints `state: {... "status": "completed", "detail": {"encoding": "jpeg", "bytes": …, "width": 640,
"height": 480, "source": "/dev/video0", "seq": …}}`.

## 5. Swap the transport

Change one line in `configs/dgx-rpicam.env` (on both the body's repo and the brain's bundle):

```bash
SEAM_TRANSPORT=device_connect    # was: raw_zenoh
```

Restart the body (step 3) and re-send (step 4).

## Expected results

| Transport | get_image | frame |
| --- | --- | --- |
| `raw_zenoh` | completed | jpeg ~130 KB, 640×480, `/dev/video0` |
| `device_connect` | completed | jpeg ~130 KB, 640×480, `/dev/video0` |

Record the outcome in [`docs/validation-matrix.md`](../validation-matrix.md).

## Cleanup

```bash
ssh odin@<rpi5-ip> 'pkill -f "seam_cli.py serve"'   # stop the camera body
```
