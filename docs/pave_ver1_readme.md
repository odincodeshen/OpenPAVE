# PAVE Ver1 (MVP) — Lightweight Physical-AI Edge VLA Experimentation

PAVE Ver1 is a **lightweight, reproducible Physical-AI MVP** that demonstrates an end-to-end workflow:

- Use an **Observability UI** to iterate on VLA/VLM models and prompts
- Convert model outputs into **robot intents**
- Execute intents as **ROS 2 commands** to control a physical robot (PuppyPi)

---

## 0) MVP Pipeline (Ver1)

**live-vlm-webui (Observability UI)** → **Intent Ingress (HTTP)** → **Intent File Bus** → **Control Daemon** → **ROS 2 commands** → **PuppyPi**

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                         PAVE Ver1 — MVP Data Path                            │
└──────────────────────────────────────────────────────────────────────────────┘

   (RTSP / Camera Stream)
           │
           ▼
┌───────────────────────────────┐
│ live-vlm-webui                │
│ Observability UI / Debug UI   │
│ - select model / prompt       │
│ - shows inference output      │
│ - server-side hook emits      │
│   STOP/TROT                   │
└───────────────┬───────────────┘
                │  HTTP POST /intent  (e.g. { "text": "STOP" })
                ▼
┌───────────────────────────────┐
│ Intent Ingress (HTTP :7071)   │
│ - validate / map text→intent  │
│ - atomic write                │
└───────────────┬───────────────┘
                │  Intent File Bus
                │  /tmp/vla_intent.json
                ▼
┌───────────────────────────────┐
│ Control Daemon (DGX)          │
│ - watch file mtime            │
│ - intent → ROS 2 commands     │
│ - calls ros2 via docker       │
└───────────────┬───────────────┘
                │  ROS 2 (DDS multicast, same LAN)
                ▼
┌───────────────────────────────┐
│ PuppyPi (Robot)               │
│ - puppy_control.launch.py     │
│ - executes motion             │
└───────────────────────────────┘
```

In Ver1, we validate that a VLM can output a small, stable “intent” (e.g., `STOP` / `TROT`) and reliably drive a physical robot via ROS 2.
---

## 1) Repository Layout

This repo contains all Ver1 components:

- `ui/live-vlm-webui/`  
  Updated WebUI used as **VLA Observability UI / Debug UI**.

- `intent-ingress/`  
  A tiny HTTP service (default port **7071**) that maps `STOP/TROT/...` into an intent JSON and writes atomically to:
  - `/tmp/vla_intent.json`

- `control-daemon/`  
  Watches `/tmp/vla_intent.json` (mtime de-dup) and emits ROS 2 commands (via dockerized ROS 2 CLI) to control PuppyPi.

- `third_party/puppy_control_msgs/`  
  Vendored (unmodified) PuppyPi custom message package used to build a ROS 2 CLI image for publishing:
  - `/puppy_control/velocity_move` (`puppy_control_msgs/msg/Velocity`)

- `scripts/`  
  Helper scripts, including a build script for `puppy-ros2-cli:humble`.

---

## 2) Clone

```bash
git clone --recurse-submodules https://github.com/odincodeshen/PAVE.git
cd PAVE
```

---

## 3) Prerequisites

### Hardware / Network
- PuppyPi and DGX on the **same LAN**
- ROS 2 DDS multicast must work (VLAN / enterprise Wi-Fi can break multicast)

### Software (DGX)
- Docker installed
- Python 3.10+
- vLLM (OpenAI-compatible server) running on DGX
- `ui/live-vlm-webui` runnable (per its own instructions)

### Software (PuppyPi)
- ROS 2 Humble (inside a Docker container image)
- `puppy_control.launch.py` available inside the container

---

## 4) Required ROS 2 Environment (Must Match)

On **both PuppyPi and DGX**:

```bash
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
```

> If these don’t match, you may see `/puppy` sometimes but service/topic calls will fail or hang.

---

## 4) Step-by-Step Demo (Copy/Paste)

### Step 1 — Start PuppyPi controller (robot-side)


On PuppyPi (inside your ROS 2 container / shell).  
> This assumes your container name is `puppypi_ros2`. If yours differs, replace it.

```bash
docker start puppypi_ros2
docker exec -it -u ubuntu -w /home/ubuntu puppypi_ros2 /bin/zsh
```

Inside the container:

```bash
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
source /opt/ros/humble/setup.bash
ros2 launch puppy_control puppy_control.launch.py
```

Verify robot node is alive:

```bash
ros2 node list | grep -E "^/puppy$" || echo "NO /puppy"
ros2 service list | grep puppy_control
```

### Step 2 — Build a ROS 2 CLI Docker Image with ROS2 Custom Messages

Robotics may have dirreent customer message can use, if you want DGX to publish following command in PuppyPI, 

- `/puppy_control/velocity_move`
- message type: `puppy_control_msgs/msg/Velocity`

you must use a ROS 2 CLI environment that includes the **custom message package** `puppy_control_msgs`.
The base image `ros:humble` does not include it.

This repo vendors the message package here:

- `third_party/puppy_control_msgs`

```bash
chmod +x scripts/build_puppy_ros2_cli.sh
./scripts/build_puppy_ros2_cli.sh
```

This produces:
* Docker image: puppy-ros2-cli:humble

Verify the image can resolve the custom message:

```bash
docker run -it --rm puppy-ros2-cli:humble bash -lc \
"source /opt/ros/humble/setup.bash && source /ws/install/setup.bash && ros2 interface show puppy_control_msgs/msg/Velocity"
```

Expected output will be:
```bash
* float32 x
* float32 y
* float32 yaw_rate
```

You can also publish a safe TURN command to verifiy as well:

```bash
docker run -it --rm --net=host \
  -e ROS_DOMAIN_ID=0 \
  -e RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  puppy-ros2-cli:humble bash -lc \
"source /opt/ros/humble/setup.bash && source /ws/install/setup.bash && \
(ros2 topic pub -r 10 /puppy_control/velocity_move puppy_control_msgs/msg/Velocity '{x: 0.0, y: 0.0, yaw_rate: 0.3}' & PID=\$!; sleep 2; kill \$PID >/dev/null 2>&1 || true) && \
ros2 topic pub -1 /puppy_control/velocity_move puppy_control_msgs/msg/Velocity '{x: 0.0, y: 0.0, yaw_rate: 0.0}'"
```

---

### Step 3 — Start Intent Ingress on DGX (HTTP → File Bus)

On DGX:

```bash

cd intent-ingress
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 intent_ingress.py

```

Health check:

```bash
curl -s http://127.0.0.1:7071/healthz
```

This service writes intents atomically to:

- `/tmp/vla_intent.json`

---

### Step 4 — Start Control Daemon on DGX (File Bus → ROS 2)

In a new DGX terminal:

```bash
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

cd control-daemon
python3 daemon.py
```

---

### Step 5 — Start vLLM (DGX inference backend)

Start your vLLM server (example — adjust to your environment):

- Model: `llava-hf/llava-v1.6-mistral-7b-hf`
- Must expose an OpenAI-compatible endpoint (e.g., `http://localhost:8000/v1`)

> Your exact vLLM command depends on GPU and deployment policy.
> Confirm vLLM is reachable from live-vlm-webui before proceeding.

For example:

```bash
vllm serve llava-hf/llava-v1.6-mistral-7b-hf --port 8000 --dtype auto
```


---

### Step 6 — Start live-vlm-webui (Observability UI) and forward STOP/TROT to Ingress

This repo vendors an updated WebUI under:
- `ui`

It includes a **server-side intent hook** that POSTs `STOP/TROT` to Intent Ingress.
#### A) Create a Python venv and install dependencies

```bash
cd ui
python3 -m venv .venv
source .venv/bin/activate

pip install -U pip requests
# If requirements.txt exists:
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
fi
# Editable install (pyproject.toml / setup.py)
pip install -e .
```

If you see missing packages at runtime, install them into the same venv.


#### B) Set Intent Ingress endpoint (required)

```bash
export INTENT_INGRESS_URL="http://127.0.0.1:7071/intent"
```

#### C) Start the WebUI server

```bash
live-vlm-webui
```

Try one of the following (depending on how this WebUI is packaged):

**Expected behavior:**

- WebUI shows inference output (`STOP` / `TROT`)
- `intent_ingress.py` logs: `POST /intent 200`
- `/tmp/vla_intent.json` updates
- Control daemon triggers robot motion

#### D) Open the WebUI

By default, open:
* https://<DGX_IP>:8090/ (or the host/port printed by the server)

Expected behavior:

* WebUI displays inference output (STOP / TROT)
* intent_ingress.py prints POST /intent 200
* /tmp/vla_intent.json updates
* Control daemon triggers robot motion

---

## 6) Manual End-to-End Test (Without WebUI)

You can validate the control path even without VLM:
### TROT

```bash
curl -s -X POST http://127.0.0.1:7071/intent \
  -H 'Content-Type: application/json' \
  -d '{"text":"TROT"}'
```

### STOP (includes posture reset to standing)

```bash
curl -s -X POST http://127.0.0.1:7071/intent \
  -H 'Content-Type: application/json' \
  -d '{"text":"STOP"}'
```

---

## 7) Optional: Enable TURN publishing from DGX (custom ROS 2 message support)

To publish to:

- `/puppy_control/velocity_move`
- type: `puppy_control_msgs/msg/Velocity`

DGX needs a ROS 2 CLI environment that contains the custom message package.  
This repo vendors the package here:

- `third_party/puppy_control_msgs`

### Step 1 — Build the custom ROS 2 CLI Docker image

From the PAVE repo root:

```bash
chmod +x scripts/build_puppy_ros2_cli.sh
./scripts/build_puppy_ros2_cli.sh
```

This produces:

- Docker image: `puppy-ros2-cli:humble`

### Step 2 — Verify message type exists

```bash
docker run -it --rm puppy-ros2-cli:humble bash -lc \
"source /opt/ros/humble/setup.bash && source /ws/install/setup.bash && ros2 interface show puppy_control_msgs/msg/Velocity"
```

Expected output:

- `float32 x`
- `float32 y`
- `float32 yaw_rate`

### Step 3 — Publish a safe TURN command (2 seconds + auto stop)

```bash
docker run -it --rm --net=host \
  -e ROS_DOMAIN_ID=0 \
  -e RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  puppy-ros2-cli:humble bash -lc \
"source /opt/ros/humble/setup.bash && source /ws/install/setup.bash && \
(ros2 topic pub -r 10 /puppy_control/velocity_move puppy_control_msgs/msg/Velocity '{x: 0.0, y: 0.0, yaw_rate: 0.3}' & PID=\$!; sleep 2; kill \$PID >/dev/null 2>&1 || true) && \
ros2 topic pub -1 /puppy_control/velocity_move puppy_control_msgs/msg/Velocity '{x: 0.0, y: 0.0, yaw_rate: 0.0}'"
```

Notes:
- Start with small yaw (`0.2 ~ 0.3`) to reduce imbalance risk.
- This pattern avoids cases where Ctrl+C does not stop a repeating publisher cleanly.

---

## 8) Recommended MVP Prompt (Stable Output)

To maximize downstream reliability, force a single-token intent output:

**Example prompt:**
> Output exactly ONE word: `TROT` or `STOP`. No other text.

---

## 9) Current MVP Status (Ver1)

✅ Working:

- STOP / TROT end-to-end control
- Remote control via DGX using ROS 2 over LAN
- WebUI server-side hook → ingress integration


Mini step:
1. Launch puppypi
   ```bash
   docker start puppypi_ros2
   docker exec -it -u ubuntu -w /home/ubuntu puppypi_ros2 /bin/zsh
   ```
   Inside container
   
   ```bash
   export ROS_DOMAIN_ID=0
   export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
   source /opt/ros/humble/setup.bash
   ros2 launch puppy_control puppy_control.launch.py
   ```
   
2. VLA side #1
   ```bash
   vllm serve llava-hf/llava-v1.6-mistral-7b-hf --port 8000 --dtype auto
   ```
   
3. VLA side #2
   ```bash
   cd control-daemon/
   source .venv/bin/activate
   python3 pave_control_daemon_mvp.py
   ```
   
4. VLA side #3
   ```bash
   cd ui/
   live-vlm-webui --model llava-hf/llava-v1.6-mistral-7b-hf --api-base http://localhost:8000/v1
   ```
   
   if can't find live-vlm-webui
   ```bash
   python3 -m pip install -e . // if can't find live-vlm-webui
   ```

5. Open brower:
   a. Select PuppyPi IP.
   b. Confirm the APi port and model selection.
   c. Select correct video source. For example: http://192.168.0.8:8080/stream?topic=/usb_cam/image_raw

⚠️ Known limitations:
- Straight walking (`vx`) remains debug / platform-dependent
- Turning via `velocity_move yaw` can be unstable at high yaw values
- FastDDS can occasionally enter a bad state (see runbook)




---

## 10) Runbook (Most Common Failure)

### Symptom

Robot suddenly stops responding even though messages appear delivered.

### Common log

`RTPS_READER_HISTORY Error ... cannot be resized`

### Fix (fastest)

- Restart PuppyPi `puppy_control.launch.py`

- Optionally:

  ```bash
  ros2 daemon stop || true
  ros2 daemon start
  ```

---

## 11) Licensing

- This repo is MIT-licensed (see `LICENSE`).
- `third_party/puppy_control_msgs` is vendored from Hiwonder PuppyPi and is licensed under Apache-2.0.
  See:
  - `third_party_notices.md`
  - `third_party/puppy_control_msgs/package.xml`
