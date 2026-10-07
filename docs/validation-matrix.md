# OpenPAVE Validation Matrix

This matrix records what has been run in OpenPAVE, on what kind of evidence, and how far each combination has been taken.

It should be read as an evidence map, not a marketing compatibility table. Each row is graded by the status definitions below, and a grade is only as strong as what was actually run: a mocked or forced part of the chain, a single short run, or a dry-run device does not count as hardware evidence for that part.

## Status Labels

| Status | Meaning |
| --- | --- |
| Candidate | Planned or intended; not integrated yet, or no evidence in this repository |
| Experimental | Implemented and partly tested, but the evidence is incomplete — for example a mocked part of the chain, a single short run, or untested behaviour |
| Supported | The specified combination has been run through its **complete flow once** on its real hardware (for a software-only combination: its complete flow in software), from a documented procedure |
| Validated | Supported, **and** a reproducible runbook, structured benchmark results, recorded artifacts, and documented limitations. Every declared action has been exercised at least 10 times; a gesture combination also needs a fixed replay set plus hardware runs, and a manipulation combination at least 10 physical rollouts with the full success rate reported (not only the best run) |

**Evidence class** says what kind of evidence the status rests on:

| Class | Meaning |
| --- | --- |
| `hardware` | The body device named in the row (actuator or sensor) was real in the evidence run |
| `software` | No real device was in the evidence run (mock adapters, dry-run hardware, or no body at all) |
| — | Nothing to classify (Candidate rows) |

`Validated` with class `software` is a statement about software behaviour only; it is never evidence that a physical body works. An upstream project's own hardware claims do not raise a row's status — OpenPAVE must run the combination itself.

**Legacy labels.** Before 2026-10 the matrix used `Baseline`, `Partial` and a looser `Validated`. They were re-graded to the definitions above; the mapping and what each row still needs are in *Re-grade (2026-10)* below. The dated narrative sections further down record what was run on those dates; the Status column of the table is the current grade.

## Integration Levels

| Level | Meaning |
| --- | --- |
| Level 0 | Catalogue entry only |
| Level 1 | Launch, status, or result wrapper |
| Level 2 | State or result bridge |
| Level 3 | Normalized intent / capability control contract |
| Level 4 | Benchmark integration |

## Current Matrix

| Brain-side node | Body endpoint | Inference / application layer | Seam transport | Status | Evidence class | Level | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DGX Spark | PuppyPi | vLLM / OpenAI-compatible VLM | Baseline ROS 2 / adapter path | Supported | hardware | Level 3 / partial Level 4 | `docs/validated-baseline.md`, `docs/targets/puppypi-dgx.md`, `configs/puppypi.env` |
| DGX Spark | Mock robot | none or vLLM smoke test | Local file/runtime path | Validated | software | Level 3 / Level 4 control path | `configs/mock.env`, `scripts/run_benchmark.py`, `scripts/summarize_benchmarks.py` |
| DGX Spark | RPi5 camera obs → mock robot | headless inference/application plugin: `vllm_openai` runtime + `gesture_commander` app | n/a (local dispatch to mock adapter) | Experimental | hardware | Level 3 headless path | Real-DGX run 2026-09-03: RPi5 `/dev/video0` frame (640×480 JPEG) → DGX `llava-hf/llava-v1.6-mistral-7b-hf` (`INFERENCE_RUNTIME=vllm_openai`, HTTP 200, ~1187 ms) → `gesture_commander` proposal `stop` → capability normalize → dispatch `completed` to mock. Dispatch is mock-only in v1.7; real robot is v1.8. `scripts/run_inference.py`, `docs/v1.7_spec.md`, `configs/mock.env` |
| Radxa O6 (Armv9) | RPi5 camera obs → mock robot | headless inference/application plugin on Armv9: `gesture_commander` app + dispatch; `vllm_openai` client → **remote** DGX vLLM | n/a (local dispatch to mock adapter) | Experimental | hardware | Level 3 headless path | Real-brain run 2026-09-03: Radxa O6 (`orion-o6`, aarch64) ran the runtime plugin's brain duties (inference-runtime **client** + application + dispatch). `vllm_openai` is an OpenAI-compatible client, so it called DGX `.24`'s vLLM cross-host (`INFERENCE_API_BASE=http://192.168.0.24:8000/v1`, HTTP 200, ~1000 ms) — **Radxa has no local model server yet**. Same RPi5 frame → `gesture_commander` `stop` → dispatch `completed` to mock. Validates plugin portability + inference-runtime-as-client; **local inference on Radxa is v1.8 (2nd backend)**. `scripts/run_inference.py` |
| DGX Spark | PuppyPi (real, over seam) | v1.8 single-shot: inference/application → seam dispatch (`run_inference.py --seam`) | raw_zenoh seam plugin (`puppypi_bridge` body) | Experimental | hardware | Level 3 real-body path | Real-dog run 2026-09-03: RPi5 frame → DGX `vllm_openai` (~1 s) → `gesture_commander` → `--seam raw_zenoh` → real PuppyPi, `path=bridge` (STOP ~515 ms, TROT ~1013 ms). Motion gated (`--allow-motion` + bounded lease + auto-STOP), outcome→exit code, `--action-target` selects the body. `scripts/run_inference.py`, `docs/v1.8-live-body.md` |
| DGX Spark | PuppyPi (real, over seam) | v1.8 live loop: observe→infer→confirm→dispatch (`run_live.py`) | raw_zenoh seam plugin (`puppypi_bridge` body) | Experimental | hardware | Level 3 live control | Real-dog run 2026-09-03: RPi5 JPEG snapshot source → DGX live loop → raw_zenoh → real PuppyPi. Real vLLM: room → `stop` → dog stop (edge-triggered). Forced `TROT` (mock): confirmed on the 2nd frame → dog trots (`path=bridge` ~1019 ms) → bounded run → **automatic STOP**. Multi-observation confirmation + stall watchdog + fail-safe STOP. `scripts/run_live.py`, `docs/v1.8-live-body.md` |
| Any brain | RPi 5 + hobby servo (real) | general **ROS-free** actuator: `gpio_servo` adapter → GPIO (gpiozero), same seam + `{action, params}` | raw_zenoh seam plugin (`gpio_servo` body) | Experimental | hardware | Level 3 live control | Real-hardware run 2026-09-03: DGX brain `run_live` (mock TROT) → raw_zenoh → RPi 5 real `gpio_servo` body (`AngularServo` GPIO18). Confirmed on the 2nd frame → `trot` dispatched; body returned `completed` with servo detail `{sweep_deg: 40, hz: 2}` (the servo swept), edge-triggered hold, bounded run → **automatic STOP** (centered). Servo motion independently confirmed via a `gpiozero` preflight; `GpioServoAdapter` also has 10 dry-run unit tests. Demonstrates a general, ROS-free body — same seam/contract, only `ROBOT_ADAPTER` changes. `control_daemon/adapters.py` (`GpioServoAdapter`, also `LedAdapter` — software-only), `tests/test_gpio_servo_adapter.py`, `docs/runbooks/v1.8-quick-demo.md` |
| DGX Spark | PuppyPi | VLM prompt/result path | `/pave` console + OpenAI-compatible API | Experimental | software | Level 2 / Level 3 UI validation | `docs/pave-console.md`, `ui` submodule |
| DGX Spark | PuppyPi | capability actions | persistent bridge | Experimental | hardware | Level 3 / Level 4 latency | `experiments/persistent-bridge/`, `ROBOT_ADAPTER=puppypi_bridge` |
| DGX Spark | PuppyPi | capability actions | raw zenoh seam plugin | Supported | hardware | Level 3 | Real-brain run 2026-09-02: DGX brain drove real PuppyPi, home 516 / trot 1015 / stop 515 ms (`path=bridge`). `pave_runtime/seam.py`, `pave_runtime/seam_backends/zenoh_seam.py`; origin `experiments/neutral-seam/` |
| DGX Spark | PuppyPi | capability actions | device-connect seam plugin | Supported | hardware | Level 3 | Real-brain run 2026-09-02: DGX brain drove real PuppyPi via cross-host D2D discovery, home 511 / trot 1013 / stop 514 ms (`path=bridge`). `pave_runtime/seam_backends/dc_seam.py`; origin `experiments/device-connect/` |
| DGX Spark | mock arm | manipulation capability | raw zenoh seam | Supported | software | Level 3 | `experiments/capability-mve/`, `ROBOT_ADAPTER=mock_arm` |
| DGX Spark | USB camera on RPi5 | sensing capability (`get_image`) | raw_zenoh / device_connect seam plugin | Supported | hardware | Level 2 / Level 3 | Real-brain run 2026-09-02: DGX brain got `get_image` control-plane metadata (jpeg ~98 KB, 640x480, `/dev/video0`) over BOTH transports. `configs/dgx-rpicam.env`, `scripts/seam_run.sh`; frame data plane is separate, see `experiments/camera-mve/` |
| Radxa O6 | USB camera on RPi5 | sensing capability (`get_image`) | raw_zenoh / device_connect seam plugin | Supported | hardware | Level 2 / Level 3 | Real-brain run 2026-09-02: Radxa O6 brain got `get_image` control-plane metadata (jpeg ~99 KB, 640x480) over BOTH transports. `configs/radxa-rpicam.env`, `scripts/seam_run.sh` |
| Jetson Thor | robot/sensor endpoints | VLM/VLA workflows | target-dependent | Candidate | — | To be documented | Previously described as experimentally validated, but nothing is documented in this repository, so it is graded Candidate until a run is recorded here |
| Radxa O6 | PuppyPi | capability actions | raw zenoh seam plugin | Supported | hardware | Level 3 | First real-brain validation 2026-09-02: Radxa O6 (Armv9) brain drove real PuppyPi, home 512 / trot 1013 / stop 514 ms (`path=bridge`). `pave_runtime/seam.py`, `pave_runtime/seam_backends/zenoh_seam.py` |
| Radxa O6 | PuppyPi | capability actions | device-connect seam plugin | Supported | hardware | Level 3 | First real-brain validation 2026-09-02: Radxa O6 brain drove real PuppyPi via cross-host D2D discovery, home 511 / trot 1014 / stop 514 ms (`path=bridge`). `pave_runtime/seam_backends/dc_seam.py` |
| Radxa O6 | robot/sensor endpoints | VLM/VLA workflows | target-dependent | Candidate | — | To be documented | Seam control path validated (rows above); VLM/VLA inference workflow still needs a baseline-style runbook on this target |
| Other Arm-based edge nodes | robot/sensor endpoints | VLM/VLA workflows | target-dependent | Candidate | — | To be documented | Previously described as experimentally validated at different levels; nothing is documented in this repository, so these are graded Candidate until a run per target is recorded here |
| SO-101 robot arm + camera | SO-101 | VLA manipulation / policy | To be selected | Candidate | — | Level 0 / Level 1 first | Planned demo catalogue and integration notes |
| Raspberry Pi ROS 2 car/camera | RPi car/camera | VLM/VLA or perception-to-action workflow | To be selected | Candidate | — | Level 0 / Level 1 first | Planned demo catalogue and integration notes |
| DGX Spark | RPi 5 (`osrpi5-2`) + USB camera, **dry-run** servo | body-side dead-man motion lease on `run_live` (mock TROT, real camera frames) | raw_zenoh seam plugin (`gpio_servo` body, `SERVO_DRYRUN=1`) | Experimental | software | Level 3 live control | 2026-10-05: DGX brain → LAN → RPi 5 body. 13 s of motion on a 5 s lease = 1 TROT, 0 expiries (renewals only); brain `kill -9` mid-motion → the body stopped itself in **3.0 s** and was not restarted; body `SIGTERM` → adapter stopped. Same lease on one host (DGX, mock body): 4.2 s. **No physical actuator moved** (the Pi has no servo attached), so this is logic over a real network, not actuation evidence. `pave_runtime/lease.py`, `tests/test_lease.py`, `docs/v1.8-live-body.md` |

## Re-grade (2026-10)

The Status column was re-graded against the stricter definitions above. Most rows moved: runs that
used a mocked part of the chain, or a single short run, are now Experimental; combinations that were
reproduced from a runbook on a clean checkout are now Supported.

| Combination | Was | Now | Why / what it still needs |
| --- | --- | --- | --- |
| DGX Spark → PuppyPi, baseline ROS 2 path (vLLM) | Baseline | Supported | Complete v1.0 flow on hardware. Needs per-action ≥10 runs, structured results and a live real-gesture run to be Validated; the live gesture is still pending a robot-camera stream |
| DGX Spark + mock robot (control-path benchmark) | Baseline | Validated (`software`) | Repeatable software benchmark with gate checks; says nothing about a physical body |
| v1.7 headless pipeline: RPi 5 camera → vLLM → mock (DGX, and Radxa as a remote-vLLM client) | Validated | Experimental | One run each; the actuator was a mock |
| v1.8 single-shot `--seam` to the real dog | Validated | Experimental | The TROT was forced by a mock runtime, not a real gesture; the motion gate and lease were written after the real-dog run and have not been run on it |
| v1.8 live loop to the real dog | Validated | Experimental | One short run; TROT again forced; no real gesture. Needs a real-gesture → trot → stop run and repeats |
| `gpio_servo` on an RPi 5 | Validated | Experimental | One run exercising only `trot` and the closing STOP; `home` / `move` / `estop` not run on hardware; not reproduced by anyone else |
| `/pave` console VLM prompt/result path | Baseline | Experimental | Text-only inference was exercised; a live gesture → action run is not |
| Persistent PuppyPi bridge | Experimental | Experimental | Real-robot before/after numbers exist; repeat counts need confirming |
| DGX / Radxa → PuppyPi over `raw_zenoh` and `device_connect` (4 rows) | Experimental | Supported | Complete home/trot/stop flow on the real dog, reproduced from the runbooks on clean checkouts. Needs ≥10 runs per action and structured results |
| DGX / Radxa → RPi 5 camera `get_image` over both transports (2 rows) | Experimental | Supported | Same; also needs frame-data-plane evidence (today only the metadata is checked) |
| DGX Spark + `mock_arm` | Experimental | Supported (`software`) | Unit tests and the capability experiment; no benchmark or recorded artifacts |
| Jetson Thor; Radxa O6 VLM/VLA workflow; other Arm nodes | Partial | Candidate | No evidence in this repository (Radxa's seam control path is covered by its own rows above) |
| SO-101 + camera; Raspberry Pi ROS 2 car/camera | Candidate | Candidate | Unchanged |

**Common gaps to Validated, for every row:** each declared action run at least 10 times with the full
success rate reported; structured result records (command result + state + versions + checksums);
a benchmark; documented limitations; and a reproduction by someone other than the original author.

## Current Performance Evidence

| Path | Evidence | Notes |
| --- | --- | --- |
| PuppyPi Dockerized ROS 2 CLI | Validated baseline | Simple and reproducible; not optimized for high-rate control |
| PuppyPi persistent bridge | `experiments/persistent-bridge/b2_result.md` | Experimental path with measured real-robot latency improvements and fallback |
| Mock control-path benchmark | `scripts/run_benchmark.py`, `scripts/summarize_benchmarks.py` | Repeatable software-only validation and gate checks |
| `/pave` text-only inference | `POST /api/pave/infer` | Validates vLLM/OpenAI-compatible API and UI prompt/result path without camera input |
| Camera sensing MVE | `experiments/camera-mve/` | Validates control-plane / data-plane split for a USB camera |
| Seam plugin real-brain latency | Real-brain runs 2026-09-02 (see subsection below) | Across DGX and Radxa O6 brains and both transports, `latency_ms` is ~514 ms (home/stop) and ~1013 ms (trot), all `path=bridge`. Latency is dominated by the body-side bridge / `puppy_control`. |
| Seam latency breakdown | `docs/latency-model.md`, `scripts/seam_bench.py` | Three-segment model: steady-state seam wire ~0.6 ms/action; a ~0.5 s one-time session setup (per-call in the current CLI); execution bridge-dominated. |

## Real-Brain Seam Plugin Validation (2026-09-02)

To reproduce this section end to end, follow `docs/seam-validation-runbook.md` (install deps, deploy with `scripts/deploy_seam.sh`, run with `scripts/seam_run.sh`).

This run promoted the seam from experiment code to a transport plugin (`pave_runtime.seam.create_seam_transport`) and validated it with **real brains driving a real robot**. Two brains (DGX Spark, Radxa O6) each drove the physical PuppyPi over both transports, using the **same** `scripts/seam_cli.py` and the **same** `puppypi_bridge` adapter — only `SEAM_TRANSPORT` (and the brain host) changed. No body or brain code was modified between cells.

Body-side `latency_ms` per cell (`home` / `trot` / `stop`), all `path=bridge`:

| Brain (real) | `raw_zenoh` | `device_connect` (D2D) |
| --- | --- | --- |
| DGX Spark | 516 / 1015 / 515 ms | 511 / 1013 / 514 ms |
| Radxa O6 (Armv9, first validation) | 512 / 1013 / 514 ms | 511 / 1014 / 514 ms |

Every cell returned `status=completed`, `path=bridge`, and was camera-confirmed (trot gait → stop stance) via the RPi5 USB camera.

Findings:

- **The seam is insensitive to both brain and transport.** All four cells land within a few ms of each other; latency is set by the body-side bridge / `puppy_control`, not the seam or the brain. The three-segment split (`inference + seam + execution`, see `docs/latency-model.md`) is: inference out of scope here; **seam steady-state ~0.6 ms** per action, but a **~0.5 s one-time session setup** that the per-call `seam_cli.py send` pays every call (removable with a persistent brain session); execution ~514 ms home/stop, ~1013 ms trot (bridge-dominated).
- **Cross-host `device_connect` D2D works with zero infrastructure.** DGX and Radxa brains discovered the PuppyPi `openpave-body` over zenoh multicast presence on the LAN — no fabric server, no registry.
- **Radxa O6 (Armv9) is validated as a real brain** over both transports for the seam control path.
- **Brain-side deployment is light:** the brain needs only `pave_runtime/` (~9 KB) plus `zenoh` / `device-connect-agent-tools`; `scripts/seam_cli.py` imports the adapter lazily, so the brain does not need `control_daemon`.
- **Known behavior:** `raw_zenoh` opens a fresh zenoh session per `send`, so discovery can occasionally miss within the settle window (observed once on `stop`); an immediate resend succeeds. A long-lived brain session would remove this.

### Sensing endpoint over the seam (RPi5 USB camera)

The same plugin also carries a **sensing** capability. Using four-dimension recipes (`configs/dgx-rpicam.env`, `configs/radxa-rpicam.env`) with the one-command launcher `scripts/seam_run.sh`, both brains drove the RPi5 USB camera (`ROBOT_ADAPTER=camera_usb`) over both transports. `get_image` returned real **control-plane metadata** for a freshly grabbed 640×480 JPEG:

| Brain (real) | `raw_zenoh` | `device_connect` (D2D) |
| --- | --- | --- |
| DGX Spark | jpeg 98,223 B | jpeg 97,070 B |
| Radxa O6 | jpeg 99,935 B | jpeg 98,694 B |

Every cell returned `status=completed` with `{encoding: jpeg, width: 640, height: 480, source: /dev/video0, seq}`. The **frame bytes travel on a separate data plane** (see `experiments/camera-mve/`); the seam plugin and `seam_run.sh` carry only the control plane — the intended control/data-plane split for sensing. This confirms the seam spans **actuator and sensor** body endpoints, across both brains and both transports, driven entirely by config recipes.

### Per-config runbook re-validation (2026-09-02)

Every seam config was re-validated end to end through the **documented** path (`deploy_seam.sh` +
`seam_run.sh`, per-config runbooks under `docs/runbooks/`) on **clean release checkouts** — the
PuppyPi (`.6`) and RPi5 (`.21`) were re-cloned to `v1.5.0-seam` first, confirming a fresh clone
reproduces. Each combo passed on both transports:

| Config | Runbook | raw_zenoh | device_connect |
| --- | --- | --- | --- |
| `dgx-puppypi` (actuator) | `docs/runbooks/dgx-puppypi.md` | ✅ home/trot/stop, `path=bridge` | ✅ |
| `radxa-puppypi` (actuator) | `docs/runbooks/radxa-puppypi.md` | ✅ home/trot/stop, `path=bridge` | ✅ |
| `dgx-rpicam` (sensor) | `docs/runbooks/dgx-rpicam.md` | ✅ `get_image` jpeg ~130 KB | ✅ |
| `radxa-rpicam` (sensor) | `docs/runbooks/radxa-rpicam.md` | ✅ `get_image` jpeg ~130 KB | ✅ |

**Gesture control (baseline, `docs/runbooks/puppypi-gesture-control.md`)**: the DGX runtime (`run_openpave.sh` →
`intent_ingress` + `control_daemon` + `/pave`) came up; vLLM inference works; DGX drove the real dog
by ROS 2 cross-host (`TROT`/`STOP` intent → `adapter=puppypi` → completed). The **live end-to-end
gesture is pending a robot-camera stream** — the scenario references `http://<robot>:8080/stream` but
the repo ships no `web_video_server` / camera-stream launch (open gap); a browser webcam works as an
interim source.

## Matrix Maintenance Rules

- Add a row when a new hardware, transport, adapter, inference runtime, or demo path is first exercised.
- Prefer explicit status labels over vague claims, and always give the Evidence class.
- Link each row to a runbook, config, experiment note, benchmark output, or reproducible script.
- Do not mark a combination Supported or Validated until it has a clear reproduction guide in this repository.
- A run with a mocked, dry-run or forced part of the chain cannot support a hardware claim for that part; say what was mocked.
- Keep external or collaborator validation as Experimental until the validation depth and environment are documented, and re-run it here before raising the grade.
- When a row's evidence changes, update its Status and add the date and what was run; do not leave an old grade standing on a stronger claim than the evidence.

