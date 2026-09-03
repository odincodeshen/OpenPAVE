# OpenPAVE 快速上手

> 第一次接觸 OpenPAVE?從這裡開始。· English: [quickstart.md](quickstart.md)

OpenPAVE 是一個開源的**「大腦–小腦」Physical AI 驗證平台**,專為 Arm edge 生態設計。這份給第一次接觸的
開發者:它是什麼、怎麼先跑、接下來讀哪份文件。

## 1. OpenPAVE 是什麼?

一句話:一個 **reference base(參考底座)**,讓你在上面接自己的硬體 / 模型 / 傳輸 / 場景。它專注在
**一件事**——把「大腦想做什麼」可靠地送到「小腦(機器人)去做」,並把結果回報、量測。

**它不是**:LLM 服務框架(像 vLLM / Ollama),也不是完整商用機器人系統。它是一條*可驗證、可量測*的
brain↔body workflow。

## 2. 心智模型:兩層 + 一條 seam

整個系統只有兩層,中間一條 **seam** —— OpenPAVE 只管這條線。

![Brain–Body Architecture](architecture-brain-body.svg)

再加上「**四個維度**」的組合觀念;一組完整配置就是挑這四樣,一份 `config` 檔把它們綁成開箱即用的配方:

| 維度 | 是什麼 | 怎麼換 |
| --- | --- | --- |
| 大腦 | 哪台運算平台 | 選一台 host |
| 小腦 | 哪個機器人 / 感測器 | `ROBOT_ADAPTER=` puppypi / camera_usb … |
| 傳輸 | seam 底層走的線 | `SEAM_TRANSPORT=` raw_zenoh / device_connect |
| 應用 | 上層跑什麼 | vLLM / 手勢 prompt … |

## 3. 先跑起來(5 分鐘,免任何硬體)

用 `mock` profile 驗證整條 runtime,不需要機器人:

```bash
git clone --recurse-submodules https://github.com/odincodeshen/OpenPAVE.git
cd OpenPAVE
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip -r intent_ingress/requirements.txt -e ui
OPENPAVE_CONFIG=configs/mock.env ./scripts/run_openpave.sh
```

開瀏覽器 → `http://127.0.0.1:8090/pave`。看得到 console,就代表整條 runtime(intent → 控制 → 回饋)通了。

## 4. 照目標選路徑

OpenPAVE 有**兩條「跑」的路,別搞混。** 先想清楚你的目標:

| 你想做什麼 | 走哪條 | 從這裡開始 |
| --- | --- | --- |
| 只想先玩玩、沒有硬體 | baseline | 第 3 節(mock) |
| 看懂設計理念 | 閱讀 | [openpave-platform-spec.md](openpave-platform-spec.md) |
| 大腦透過 seam 驅動真機器人(送 home / trot / stop) | **seam** | `docs/runbooks/<大腦>-<小腦>.md` |
| 完整手勢控制 demo(相機 → VLM → 狗動) | baseline | [runbooks/puppypi-gesture-control.md](runbooks/puppypi-gesture-control.md) |
| 看驗證了哪些組合 + 效能 | 閱讀 | [validation-matrix.md](validation-matrix.md) · [latency-model.md](latency-model.md) |

**兩條路的差別(關鍵)**:**seam** 路(`seam_run.sh`)是可換傳輸,送離散 capability 指令。**baseline**
路(`run_openpave.sh`)是完整應用 runtime(含 VLM / UI / 手勢)。手勢 demo 走 baseline,**不走 seam**。

## 5. 接真硬體:挑組合、照 runbook 走

每個「大腦 × 小腦」組合都有一份自足的 runbook(依賴 → 部署 → 起 body → 送指令 → 預期 → 清理):

| 組合 | 路 | runbook |
| --- | --- | --- |
| DGX → PuppyPi(狗) | seam | [dgx-puppypi.md](runbooks/dgx-puppypi.md) |
| Radxa O6 → PuppyPi(狗) | seam | [radxa-puppypi.md](runbooks/radxa-puppypi.md) |
| DGX → RPi5 相機 | seam | [dgx-rpicam.md](runbooks/dgx-rpicam.md) |
| Radxa O6 → RPi5 相機 | seam | [radxa-rpicam.md](runbooks/radxa-rpicam.md) |
| 手勢控制(DGX brain) | baseline | [puppypi-gesture-control.md](runbooks/puppypi-gesture-control.md) |

seam 路就三步(細節在 runbook 裡,換傳輸只改 config 裡 `SEAM_TRANSPORT` 一行):

```bash
# 1. 部署 seam bundle 到大腦
scripts/deploy_seam.sh <user>@<brain-ip> '$HOME/openpave-seam' '<venv>/bin/python'
# 2. 在小腦端起 body
scripts/seam_run.sh configs/dgx-puppypi.env body
# 3. 在大腦端送指令
scripts/seam_run.sh configs/dgx-puppypi.env brain send home
```

## 6. 名詞小抄

| 名詞 | 意義 |
| --- | --- |
| seam | 大腦↔小腦之間唯一的協議邊界 —— OpenPAVE 的核心 |
| capability | `{action, params}` 進、狀態出的統一 body 契約(由 dispatch 執行) |
| adapter | 接某個小腦的零件:`puppypi_bridge`、`camera_usb` … |
| transport | seam 底層走的線:`raw_zenoh`、`device_connect` |
| config | 把四維綁成一組驗證組合的 `.env` 配方 |
| /pave | 觀測 UI(prompt / 結果 / 回饋),由 `live-vlm-webui` fork 提供 |

## 7. 接下來讀什麼

1. [README.md](../README.md) / [README_cn.md](../README_cn.md) —— 完整總覽(英 / 中)
2. [openpave-platform-spec.md](openpave-platform-spec.md) —— 定位、四維模型、架構
3. [validation-matrix.md](validation-matrix.md) —— 驗證了什麼、到什麼程度
4. [runbooks/](runbooks/) —— 挑你的組合,照著做
5. [latency-model.md](latency-model.md) —— 效能三段延遲

**卡住了?** 先看對應 runbook 的 **Troubleshooting** 段。常見坑都記在裡面:raw_zenoh 偶發重送、
device_connect 要同網段、PuppyPi bridge 要用 `-u ubuntu`、相機需 headless OpenCV。
