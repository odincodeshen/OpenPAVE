# Runbook: Gesture Control (DGX brain → PuppyPi baseline)

Drive the **real PuppyPi** by **hand gesture** through the OpenPAVE baseline runtime: a camera feed →
VLM (gesture prompt) → normalized intent → control daemon → robot. This is the `configs/puppypi.env`
baseline path (`ROBOT_ADAPTER=puppypi`), not the seam plugin.

| Dimension | Value |
| --- | --- |
| Brain | DGX Spark — vLLM + OpenPAVE runtime + `/pave` console |
| Body | PuppyPi (ROS 2 `puppy_control`), controlled cross-host over ROS 2 |
| Inference | vLLM / OpenAI-compatible VLM (`llava-hf/llava-v1.6-mistral-7b-hf`) |
| Prompt | `prompts/robot-commander-gesture.json` (👍 → TROT, open palm → STOP, else STOP) |

## Architecture (confirmed)

`scripts/run_openpave.sh` starts **three co-located processes on the brain host**: `intent_ingress`
(Flask, binds `127.0.0.1:7071`), `control_daemon` (talks to ingress via a local file
`/tmp/vla_intent.json`), and `live-vlm-webui` (`:8090`, serves `/pave`). Because the ingress binds
localhost and the ingress↔daemon IPC is a local file, **all three must run on one host** — the DGX.
The DGX then controls the PuppyPi **cross-host over ROS 2** (`ROBOT_ADAPTER=puppypi` → `docker ros2
service call /puppy_control/...`), which is verified working (DGX sees `/puppy_control/*` on
`ROS_DOMAIN_ID=0`). Only the camera feed differs (see step 4).

## 1. Repo + UI submodule on the DGX

The UI is the `ui/` submodule (an OpenPAVE-maintained `live-vlm-webui` fork). Get a checkout **with the
submodule** and install it:

```bash
git clone --recurse-submodules https://github.com/odincodeshen/OpenPAVE.git ~/openpave
cd ~/openpave && git checkout v1.5.0-seam && git submodule update --init --recursive
python3 -m venv ~/.venv-pave
~/.venv-pave/bin/pip install -U pip -r intent_ingress/requirements.txt -e ui
```

(Installs Flask + `live-vlm-webui` + `openai` + WebRTC deps.)

## 2. vLLM on the DGX

Serve the VLM (OpenAI-compatible) on `:8000`. **Use the exact model id** — a typo in the model name
is a common startup failure:

```bash
~/OpenPAVE/.venv/bin/vllm serve llava-hf/llava-v1.6-mistral-7b-hf \
  --host 0.0.0.0 --port 8000 --dtype float16 --max-model-len 3072 \
  --gpu-memory-utilization 0.55 --enforce-eager
```

Ready when `curl http://127.0.0.1:8000/v1/models` lists the model.

## 3. Start the OpenPAVE runtime

From `~/openpave`:

```bash
OPENPAVE_CONFIG=configs/puppypi.env \
OPENPAVE_PYTHON=$HOME/.venv-pave/bin/python \
UI_API_BASE=http://localhost:8000/v1 \
ROBOT_IP_ADDRESS=<puppypi-ip> \
INTENT_FORWARDING_ENABLED=1 ROS_DOMAIN_ID=0 \
bash scripts/run_openpave.sh
```

Ready when the log prints `OpenPAVE console ready: http://127.0.0.1:8090/pave`. Prereq: the PuppyPi's
ROS 2 `puppy_control` is already up (`scripts/switch_puppypi_ros2.sh` or `scripts/start_puppy_control.sh`
on the PuppyPi), and the DGX can reach it on `ROS_DOMAIN_ID=0`.

## 4. Camera feed

The `/pave` console (WebRTC) takes video from one of:

- **Browser webcam** (simplest, works today) — the camera of whatever machine opens `/pave`. Because
  webcams need a secure context, reach the console over an SSH tunnel so the page is `localhost`:
  ```bash
  ssh -L 8090:localhost:8090 odin@<dgx-ip>      # then open http://localhost:8090/pave
  ```
- **Robot camera** (the scenario's intent — the robot "sees" you) — the PuppyPi has a USB camera
  (`/dev/video0`) and the `puppypi_ros2` container has `usb_cam`, but **not** `web_video_server`, and
  no repo script starts the stream yet. To use it you must produce
  `http://<puppypi-ip>:8080/stream?topic=/usb_cam/image_raw` (install `web_video_server` + launch
  `usb_cam`, or serve `/dev/video0` as RTSP) and point the UI's RTSP/stream input at it. **This is an
  open gap** — the gesture scenario references `:8080` but the repo ships nothing to produce it.

## 5. Do the gesture

1. Open `/pave` (see step 4).
2. Grant the camera; under **Prompt** choose the **`robot_commander`** preset (the gesture prompt).
3. Start the stream. Show 👍 → the dog **TROT**s; show an open palm 🖐 → the dog **STOP**s. `TROT`
   requires two confirmations within the window (safety); anything ambiguous is `STOP`.

## Validated (2026-09-02)

- ✅ **Runtime**: `run_openpave.sh` brings up ingress + control_daemon + `/pave` on the DGX.
- ✅ **Inference**: vLLM chat-completion returns the instructed word (gesture prompt works).
- ✅ **Cross-host control**: DGX sees `/puppy_control/*` over ROS 2; a `TROT`/`STOP` intent POSTed to
  the ingress drove the real dog (`ACTION=… adapter=puppypi … completed`, camera-confirmed).
- ⏳ **Live end-to-end gesture**: pending the robot-camera stream (step 4) or a browser-webcam session.

## Cleanup

```bash
# on the DGX: Ctrl+C the run_openpave.sh (sends a shutdown STOP), or kill it.
ssh pi@<puppypi-ip> 'docker stop puppypi_ros2'   # rest the dog
```
