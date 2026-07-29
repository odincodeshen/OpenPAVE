# camera MVE — sensing over the same seam (the uplink half)

The capability MVE (`../capability-mve/`) proved the capability model spans a **different
actuator** (an arm). This proves it also spans **sensing**: a camera declares a `get_image`
capability and runs over the **same zenoh seam + generic body**, adding only a new adapter — this
time producing data instead of acting. It closes the other half of the brain↔body loop (the
**sensor uplink**), the missing piece for real VLA use.

> **Scope:** experimental, mock-first. It reuses the validated zenoh transport (`../zenoh-mve/`)
> and the capability contract (`../capability-mve/`), and is not wired into the main runtime. If
> it proves out, the sensor/actuator split graduates into `pave_runtime`.

## Sensor vs actuator — same contract, two roles

| | actuator (`../capability-mve/`) | sensor (here) |
|---|---|---|
| example | `MockArmAdapter` | `CameraSensorAdapter` |
| `execute(action)` | *does* a thing → small status | *produces* data → small **metadata** |
| capabilities | `move_joint`, `grasp`, `stop`… | `get_image` |
| heavy payload | none | the image — **not** in the reply |

Both implement the same `CapabilityAdapter` interface. The difference the camera forces into the
open is the **control plane / data plane split**.

## Control plane / data plane

The image is far too big for the JSON reply, so it doesn't ride there:

```
control plane  (small, capability model, JSON)
  brain send {action:"get_image"}  ──▶  body: adapter.execute → metadata {encoding,bytes,w,h,seq}
                                                                 → /openpave/action_state
data plane  (large, dedicated)
  body grabs a frame → JPEG → sensor_msgs/CompressedImage on /openpave/image  ──▶  brain saves it
```

The adapter returns metadata in `ActionResult.detail` and hands the raw JPEG to the body via
`last_jpeg`; the body publishes that on the image topic. The actuator path (no `last_jpeg`) is
unchanged — nothing is published on the data plane for it.

## Files

| File | Role |
|------|------|
| `camera_source.py` | `CameraSource` protocol + `MockCameraSource` (synthetic, no HW) + `UsbCameraSource` (`/dev/videoN` via OpenCV) |
| `camera_sensor_adapter.py` | `CameraSensorAdapter` — `capabilities={"get_image"}`; `execute` → metadata + `last_jpeg` |
| `sensor_body_node.py` | generic sensor body: control (`/openpave/action` → metadata on `/openpave/action_state`) + data (`/openpave/image`) |
| `get_image.py` | brain: request one frame, receive metadata + frame, save the JPEG |
| `test_camera.py` | unit tests (fake source, no ROS/OpenCV/hardware) — 5 tests |

## Reused unchanged

- **Transport** — zenoh `client` → router on the DGX (same as `../zenoh-mve/`).
- **Contract** — `capability_schema` + `ActionResult` imported from `../capability-mve/`.
- **Deployment** — same container pattern; only the body program and one image topic are new.

## Requirements

The body needs **OpenCV** (`cv2`) for both mock and USB (`apt install python3-opencv`), and for
`camera_usb` the container needs the device: add `--device /dev/video0` to `docker run` (override
with `CAMERA_DEVICE`). The unit tests need none of this.

## Run (on the plain RPi5 at 192.168.0.13)

Same container setup as `../zenoh-mve/zenoh_test.md`, running `sensor_body_node.py`:

1. **Mock first (no camera)** — prove the whole plumbing:
   - **Body — RPi5**: zenoh `client` → DGX router, `ROBOT_ADAPTER=camera_mock`,
     run `experiments/camera-mve/sensor_body_node.py --ros-args -r __node:=openpave_body_sensor`
   - **Brain — DGX**: `python3 experiments/camera-mve/get_image.py --out /tmp/openpave_frame.jpg`
   - Expect a saved `/tmp/openpave_frame.jpg` (a gradient with `mock #N`) + metadata printed.
2. **Real USB camera** — plug it in, `--device /dev/video0`, `ROBOT_ADAPTER=camera_usb`, rerun the
   brain; the saved frame is a real photo.

## Validation checklist

- [ ] **discovery** — DGX sees `/openpave_body_sensor` (same seam as the other MVEs)
- [ ] **mock plumbing** — `get_image` → frame saved, metadata `{encoding:"jpeg", bytes, w, h, seq}`
- [ ] **control/data split** — metadata on `/openpave/action_state`, image on `/openpave/image`
- [ ] **USB camera** — `camera_usb` on `/dev/video0` → saved frame is a real photo
- [ ] **reuse proven** — transport + contract + deployment identical to the prior MVEs; only a new
      sensor adapter + one image topic

## What this proves

The capability model spans **sensing as well as actuation** over one unchanged brain↔body seam,
and sensing forces the right architectural line — **control plane (small, capability model) vs
data plane (large, dedicated channel)**. Together with the arm (actuation), a body is now a set of
capability adapters, some actuators, some sensors (see the workspace-root `todo_list.md`).
