# OpenPAVE: Open Physical AI Validation and Experimentation

## 面向 Arm-based edge platforms 的 Physical AI demo 開放參考驗證 workflow

OpenPAVE 幫助開發者在本地端組裝、執行、觀察與比較 Physical AI demos。

它把原本常常分開評估的元件，接成一條可以驗證的 workflow：

- local VLM/VLA inference
- robot 或 sensor endpoints
- robot middleware
- brain-body transport
- normalized intent 與 capability contracts
- command and state feedback
- observability UI
- demo runbooks
- benchmark and validation paths

OpenPAVE 不是像 vLLM 或 Ollama 這類 LLM serving framework，也不是完整商用 robotics stack。它是一個 fork-friendly reference base，用來驗證 Arm-based edge platforms 上的 Physical AI workflow。

## Demo References

以下早期 demo 展示了 OpenPAVE 延伸出來的原始方向，可作為參考：

- [Physical AI edge VLA demo short](https://youtube.com/shorts/QwUnFLIUNe4?si=P6FuZvVzHTzYnd57)
- [Physical AI robot workflow demo](https://youtu.be/kRiXri0te0g?si=ijmNqtQX8cuCoHHs)

## OpenPAVE 提供什麼

OpenPAVE 提供三個實用 building blocks：

1. **本地 Arm edge Physical AI testbed**
   - 從已驗證的 PuppyPi + DGX baseline 開始。
   - 後續可以替換 robot/sensor endpoints、edge nodes、transports 或 inference backends。

2. **可重複的 validation workflow**
   - 用 integration levels、scenarios、configs 和 runbooks 描述 demo。
   - 透過 `/pave` console 觀察 runtime state。
   - 記錄 command results、robot state 和 benchmark outputs。

3. **plugin-oriented extension model**
   - 新增 robot/sensor adapter。
   - 新增 seam transport。
   - 新增 validated hardware combination 的 config recipe。
   - 新增 demo scenarios 和 benchmark paths。

## 架構：Brain、Body、Seam

OpenPAVE 將一個 Physical AI demo 建模成兩層，並由一條主要 seam 連接：

```text
Brain side: local inference / control / observability node
    |
    | seam: brain-body communication boundary
    |
Body side: robot or sensor endpoint
    |-- local controller, adapter, policy, or middleware
    |-- motors, servos, cameras, IMU, and sensors
```

OpenPAVE 聚焦在 brain-body seam、跨 seam 傳遞的 control contract，以及 body side 回傳的 observable state。它不試圖定義 body controller 和每個 motor / sensor 之間的內部連線。

目前 validated baseline：

```text
PuppyPi + DGX Spark
```

這是第一個 validated deep-integration target，不是專案邊界。

## 四維模型

一組完整的 OpenPAVE validation configuration 由四個維度組成：

| Dimension | Role | Current state |
| --- | --- | --- |
| Brain-side edge node | Local inference、orchestration、UI、benchmark runner | DGX Spark baseline；Jetson Thor、Radxa O6 與其他 Arm-based edge nodes 已完成不同程度驗證 |
| Body-side robot/sensor endpoint | Robot、arm、camera、sensor endpoint 或 future body-side policy unit | PuppyPi baseline；已有 mock、mock arm、camera adapters |
| Seam transport | Brain-body communication boundary | baseline adapter path；raw zenoh 與 device-connect 屬 experimental |
| Inference / upper-layer application | VLM/VLA backend、planner 或 policy layer | 目前是 vLLM/OpenAI-compatible API；pluginization 是 roadmap |

Configs 會把這些維度綁成可重複執行的 recipes。例如：

```text
configs/mock.env
configs/puppypi.env
```

## Demo Integration Levels

不是每個 demo 都需要採用完整 OpenPAVE runtime。Demo 可以用不同深度加入：

```text
Level 0: Catalogue only
Level 1: Launch / status / result wrapper
Level 2: State or result bridge
Level 3: Normalized intent / capability control contract
Level 4: Benchmark integration
```

這讓 demo 可以維持獨立執行，同時透過 OpenPAVE 取得共用 documentation、observability、control contracts 或 benchmark tooling。

## Quick Start

主要 runbook 請使用 validated baseline guide：

```text
docs/validated-baseline.md
```

最小 software-only validation：

```bash
cd /path/to/OpenPAVE

git submodule update --init --recursive

python3 -m venv .venv
source .venv/bin/activate

python3 -m pip install -U pip
python3 -m pip install -r intent_ingress/requirements.txt
python3 -m pip install -e ui

OPENPAVE_CONFIG=configs/mock.env ./scripts/run_openpave.sh
```

開啟：

```text
http://127.0.0.1:8090/pave
```

`mock` profile 可以在沒有 robot hardware 的情況下驗證 runtime path。

## Validated Baseline

目前 baseline 展示：

```text
local VLM/VLA inference
-> normalized intent
-> Control Daemon
-> Robot Adapter
-> ROS 2 execution
-> command/state feedback
-> benchmark validation
```

Baseline components：

- Intent Ingress: `intent_ingress/server.py`
- Intent schema: `pave_runtime/intent_schema.py`
- Capability schema: `pave_runtime/capability_schema.py`
- Control daemon and adapters: `control_daemon/`
- Runtime launcher: `scripts/run_openpave.sh`
- Prompt presets: `prompts/`
- Scenarios: `scenarios/`
- Benchmark runner: `scripts/run_benchmark.py`
- Benchmark summarizer: `scripts/summarize_benchmarks.py`
- OpenPAVE console: `ui/` submodule，目前基於 OpenPAVE-maintained `live-vlm-webui` fork

## Validation Matrix

OpenPAVE 用 validation matrix 追蹤支援狀態，而不是直接宣稱所有組合都完整相容。

建議從這裡開始：

- [Validation Matrix](docs/validation-matrix.md)
- [Validated Baseline](docs/validated-baseline.md)
- [PuppyPi + DGX Target](docs/targets/puppypi-dgx.md)

目前狀態摘要：

- **Baseline**: DGX Spark + PuppyPi，透過 validated runtime path。
- **Experimental**: persistent PuppyPi bridge、raw zenoh neutral seam、device-connect seam、capability 與 camera MVEs。
- **Partial**: Jetson Thor、Radxa O6 與其他 Arm-based edge nodes 已完成不同程度驗證，但仍需要 baseline-style matrix rows 和 runbooks。
- **Candidate**: SO-101 robot arm + camera、Raspberry Pi ROS 2 car/camera。

## 重現 Seam 驗證

real-brain seam matrix（brain 節點透過 seam plugin 驅動實體 body、涵蓋兩種 transport）可從四維
config recipe 加兩支腳本完整重現。完整指南：[Seam Validation Runbook](docs/seam-validation-runbook.md)。

```bash
# 1. 把 seam 依賴裝進每台 host 的 venv（版本已 pin）
<venv>/bin/pip install -r requirements-seam.txt          # brain + body
<venv>/bin/pip install -r requirements-seam-camera.txt   # 只有 camera sensor body 需要

# 2. 把 seam bundle 部署到 brain（含 pave_runtime + seam_cli + seam_run + configs）
scripts/deploy_seam.sh odin@192.168.0.24 '$HOME/openpave-seam' '$HOME/.venv-zenoh/bin/python'

# 3. 先起 body，再從 brain 送指令 — 同一支 launcher、任一 recipe
scripts/seam_run.sh configs/dgx-puppypi.env body             # 在 body（PuppyPi）
scripts/seam_run.sh configs/dgx-puppypi.env brain send home  # 在 brain（DGX）
```

一個 recipe（`configs/<brain>-<body>.env`）綁定四個維度；換 transport 只需改 `SEAM_TRANSPORT` 一行
（`raw_zenoh` | `device_connect`）。目前可用的 recipe：`dgx-puppypi`、`radxa-puppypi`（actuator）、
`dgx-camera`、`radxa-camera`（sensor）。

## Benchmarking

先啟動 runtime，再執行：

```bash
python3 scripts/run_benchmark.py scenarios/mock-intent-stop-trot.json
python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl
```

目前 benchmark harness 驗證的是 control path，並可根據 scenario metadata 彙整結果。未來工作會加入 sensor replay、VLM/VLA output quality checks、transport latency breakdown 和 multi-target comparison。

## Documentation

建議從這裡開始：

- [Documentation Index](docs/index.md)
- [OpenPAVE Platform Specification](docs/openpave-platform-spec.md)
- [Validation Matrix](docs/validation-matrix.md)
- [Validated Baseline Guide](docs/validated-baseline.md)
- [Further Work](docs/further-work.md)

核心參考：

- [Architecture](docs/architecture.md)
- [Brain-Body Architecture](docs/architecture-brain-body.md)
- [Demo Integration Levels](docs/demo-integration-levels.md)
- [Demo Catalogue](docs/demo-catalog.md)
- [Contributing Demos](docs/contributing-demos.md)
- [Intent Schema](docs/intent-schema.md)
- [Robot Adapters](docs/robot-adapters.md)
- [Robot Feedback](docs/robot-feedback.md)
- [Benchmark Harness](docs/benchmark-harness.md)
- [Ecosystem Validation Map](docs/ecosystem-validation-map.md)
- [Third-Party Notices](docs/third-party-notices.md)

歷史資料保留於：

```text
docs/archive/
```

## Current Limitations

- Default PuppyPi command path 使用 Dockerized one-shot ROS 2 CLI calls。Experimental persistent bridge 已存在，但尚未成為 default。
- Default brain-body path 仍是 validated baseline adapter path。Raw zenoh 和 device-connect seam transports 屬 experimental。
- `/pave` 目前仍位於 OpenPAVE-maintained `live-vlm-webui` fork。未來規劃 OpenPAVE native console。
- 目前 benchmark coverage 聚焦 control-path validation。完整 sensor replay 和 VLM/VLA quality benchmark 是 future work。
- 其他 Arm-based edge nodes 已完成不同程度驗證，但大多仍需要 baseline-quality runbooks 和 matrix entries。

## Third-Party Notice

OpenPAVE 目前使用 OpenPAVE-maintained fork of `NVIDIA-AI-IOT/live-vlm-webui` 作為 UI/backend path 的 submodule。這不代表 NVIDIA endorsement 或官方 product alignment。請參考 [Third-Party Notices](docs/third-party-notices.md)。
