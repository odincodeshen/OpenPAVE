# camera MVE — Hardware Bring-Up Runbook

Operational guide to run the sensing test on real hosts (DGX = brain, RPi = sensor body),
in containers. See [README.md](README.md) for the design (sensor vs actuator, control/data
plane split) and the validation status.

**Goal:** DGX requests one frame (`get_image`) → RPi grabs it from a USB camera → the JPEG
returns over the zenoh **data plane** while the small metadata returns over the **control
plane** → DGX saves the frame. Mock first (no camera), then a real USB camera.

> **✅ Validated 2026-07-29** on DGX (`spark`, 192.168.0.24, router + brain) ↔ plain RPi5
> (`osrpi5-2`, 192.168.0.13, sensor body) over Wi-Fi. `camera_mock` saved a synthetic
> 640×480 JPEG; a real **Lenovo USB camera** on `/dev/video0` returned a real photo.

Everything runs in containers named `openpave-*` (additive, easy to remove). Replace
`<DGX-IP>` with the DGX LAN IP (e.g. `192.168.0.24`). Validated hosts use `odin@` on both.

---

## Pre-flight

### 1. Both hosts have the repo

The nodes import the capability contract from `../capability-mve/` (via `sys.path`), so the
repo must be cloned on each host and mounted at `/ws`. In the validated runs: RPi
`~/OpenPAVE`, DGX `~/openpave-zenoh`. The `camera-mve/` and `capability-mve/` dirs must both
be present in the clone.

### 2. The body image needs OpenCV (`cv2`)

The base `ros2-zenoh-arm` image has **no `cv2`** — the sensor body needs it to encode the
mock gradient and to read the USB camera. Bake a derived image **once** on the RPi and reuse
it:

```bash
# on the RPi (body host) — one-time
docker run -d --name openpave-cvbuild --entrypoint bash odinlmshen/ros2-zenoh-arm:jazzy-edge -lc "sleep 600"
docker exec openpave-cvbuild bash -lc "apt-get update -qq && apt-get install -y -qq python3-opencv"
docker exec openpave-cvbuild bash -lc "python3 -c 'import cv2,numpy; print(cv2.__version__, numpy.__version__)'"
docker commit openpave-cvbuild openpave/body-cv:jazzy    # -> reuse this image for the body
docker rm -f openpave-cvbuild
```

The **brain** (`get_image.py`) needs no `cv2` — it only decodes nothing and writes bytes — so
it runs on the stock `odinlmshen/ros2-zenoh-arm:jazzy-edge`.

### 3. Session mode must be `client` (cross-host)

Same as the zenoh MVE — see
[zenoh_test.md #3](../zenoh-mve/zenoh_test.md#3-session-mode-must-be-client-cross-host). Both
nodes attach to the router in `client` mode; the run commands `sed` the copied session config
to `mode: "client"` and point the body's connect endpoint at the DGX router.

### 4. Identify the USB camera device

A UVC camera exposes several `/dev/videoN` nodes; the Pi also exposes many ISP/codec nodes.
Find the capture device by name:

```bash
v4l2-ctl --list-devices        # or: for d in /sys/class/video4linux/video*; do echo "$d: $(cat $d/name)"; done
```

The capture node is usually the **lowest-numbered** one for the USB camera (e.g. `/dev/video0`
for `Lenovo Performance Camera`). Pass it with `--device` and `CAMERA_DEVICE`.

---

## Topics

| plane | topic | type | direction |
|-------|-------|------|-----------|
| control | `/openpave/action` | `std_msgs/String` (`{action:"get_image"}`) | brain → body |
| control | `/openpave/action_state` | `std_msgs/String` (metadata JSON) | body → brain |
| **data** | `/openpave/image` | `sensor_msgs/CompressedImage` (JPEG) | body → brain |

---

## Step 1 — Router (DGX)

```bash
docker run -d --name openpave-router --net=host \
  -e RMW_IMPLEMENTATION=rmw_zenoh_cpp -e ROS_DOMAIN_ID=0 \
  --shm-size=640m --ulimit memlock=-1:-1 \
  --entrypoint bash odinlmshen/ros2-zenoh-arm:jazzy-edge \
  -lc 'source /opt/ros/jazzy/setup.bash && exec ros2 run rmw_zenoh_cpp rmw_zenohd'
```

Checkpoint: `docker logs openpave-router` → `Started Zenoh router …`, and
`ss -ltn | grep 7447` shows it listening.

## Step 2 — Sensor body (RPi) — mock first

```bash
docker run -d --name openpave-body --net=host \
  -e RMW_IMPLEMENTATION=rmw_zenoh_cpp -e ROS_DOMAIN_ID=0 -e ROBOT_ADAPTER=camera_mock \
  -v ~/OpenPAVE:/ws \
  --shm-size=640m --ulimit memlock=-1:-1 --cap-add NET_ADMIN --security-opt seccomp=unconfined \
  --entrypoint bash openpave/body-cv:jazzy \
  -lc 'source /opt/ros/jazzy/setup.bash \
    && cp /opt/ros/jazzy/share/rmw_zenoh_cpp/config/DEFAULT_RMW_ZENOH_SESSION_CONFIG.json5 /tmp/sess.json5 \
    && sed -i "s#tcp/localhost:7447#tcp/<DGX-IP>:7447#g" /tmp/sess.json5 \
    && sed -i "s/mode: \"peer\"/mode: \"client\"/" /tmp/sess.json5 \
    && export ZENOH_SESSION_CONFIG_URI=/tmp/sess.json5 \
    && exec python3 /ws/experiments/camera-mve/sensor_body_node.py --ros-args -r __node:=openpave_body_sensor'
```

Checkpoint: `docker logs openpave-body` →
`sensor body up · adapter=camera_mock · capabilities=['get_image'] · control /openpave/action · data /openpave/image`.

## Step 3 — Brain: request one frame (DGX)

The brain writes the JPEG to `/out` (mount a host dir so you can retrieve it):

```bash
mkdir -p /tmp/openpave-out
docker run --rm --net=host \
  -e RMW_IMPLEMENTATION=rmw_zenoh_cpp -e ROS_DOMAIN_ID=0 \
  -v ~/openpave-zenoh:/ws -v /tmp/openpave-out:/out \
  --shm-size=640m --ulimit memlock=-1:-1 \
  --entrypoint bash odinlmshen/ros2-zenoh-arm:jazzy-edge \
  -lc 'source /opt/ros/jazzy/setup.bash \
    && cp /opt/ros/jazzy/share/rmw_zenoh_cpp/config/DEFAULT_RMW_ZENOH_SESSION_CONFIG.json5 /tmp/sess.json5 \
    && sed -i "s/mode: \"peer\"/mode: \"client\"/" /tmp/sess.json5 \
    && export ZENOH_SESSION_CONFIG_URI=/tmp/sess.json5 \
    && exec python3 /ws/experiments/camera-mve/get_image.py --out /out/frame.jpg --timeout 12'
```

Expected: `metadata: {"action":"get_image","encoding":"jpeg","bytes":…,"width":640,"height":480,"source":"mock","seq":1} status=completed`
and `saved … bytes (jpeg) -> /out/frame.jpg`. `file /tmp/openpave-out/frame.jpg` → a 640×480
JPEG (a gradient with `mock #1`). `docker logs openpave-body` shows
`published frame … bytes on /openpave/image`.

## Step 4 — Real USB camera

Recreate the body with the USB adapter, passing the device (see Pre-flight #4):

```bash
docker rm -f openpave-body
docker run -d --name openpave-body --net=host \
  -e RMW_IMPLEMENTATION=rmw_zenoh_cpp -e ROS_DOMAIN_ID=0 -e ROBOT_ADAPTER=camera_usb -e CAMERA_DEVICE=/dev/video0 \
  -v ~/OpenPAVE:/ws \
  --shm-size=640m --ulimit memlock=-1:-1 --cap-add NET_ADMIN --security-opt seccomp=unconfined \
  --device /dev/video0 \
  --entrypoint bash openpave/body-cv:jazzy \
  -lc 'source /opt/ros/jazzy/setup.bash \
    && cp /opt/ros/jazzy/share/rmw_zenoh_cpp/config/DEFAULT_RMW_ZENOH_SESSION_CONFIG.json5 /tmp/sess.json5 \
    && sed -i "s#tcp/localhost:7447#tcp/<DGX-IP>:7447#g" /tmp/sess.json5 \
    && sed -i "s/mode: \"peer\"/mode: \"client\"/" /tmp/sess.json5 \
    && export ZENOH_SESSION_CONFIG_URI=/tmp/sess.json5 \
    && exec python3 /ws/experiments/camera-mve/sensor_body_node.py --ros-args -r __node:=openpave_body_sensor'
```

Re-run **Step 3**. The metadata now shows `"source":"/dev/video0"`, and the saved frame is a
real photo. Retrieve it: `scp odin@<DGX-IP>:/tmp/openpave-out/frame.jpg .`

## Cleanup

```bash
docker rm -f openpave-router          # DGX
docker rm -f openpave-body            # RPi
rm -rf /tmp/openpave-out              # DGX (optional)
```

Keep the `openpave/body-cv:jazzy` image — it's the reusable artifact from Pre-flight #2.

---

## Troubleshooting

- **`ModuleNotFoundError: No module named 'cv2'`** — the body is on the stock image, not the
  derived one. Use `openpave/body-cv:jazzy` (Pre-flight #2).
- **First USB frame is black / tiny** — UVC cold-start: auto-exposure/gain hasn't settled on
  the very first read after opening. `UsbCameraSource` discards `warmup_frames` (8) on open to
  avoid this; if it persists, increase it, or the scene is genuinely dark.
- **`cannot open camera '/dev/video0'`** — device not passed (`--device /dev/video0` missing),
  or the wrong node (a UVC camera's higher `/dev/videoN` may be metadata-only). Re-check
  Pre-flight #4.
- **No frame received (timeout)** — control plane didn't reach the body, or the body's session
  isn't on the router. Same checks as
  [zenoh_test.md troubleshooting](../zenoh-mve/zenoh_test.md#troubleshooting-nodes-dont-exchange).

---

## Validation checklist

- [x] **discovery** — DGX brain reached `/openpave_body_sensor` (2026-07-29)
- [x] **mock plumbing** — `get_image` → 28970 B gradient saved; metadata
      `{jpeg,640×480,source:mock,seq:1}`
- [x] **control/data split** — metadata on `/openpave/action_state`; body logged
      `published frame 28970 bytes on /openpave/image`
- [x] **USB camera** — `camera_usb` on `/dev/video0` (Lenovo) → real photo (`source:/dev/video0`)
- [x] **warm-up fix** — first frame settled after discarding 8 cold-start frames
      (24 KB black → 57 KB exposed)
- [x] **reuse proven** — transport + contract + deployment identical to the prior MVEs
