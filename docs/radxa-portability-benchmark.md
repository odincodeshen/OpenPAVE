# Radxa Orion O6 portability benchmark

Run the existing T4 STOP benchmark from two brain-side communication hosts:
**DGX Spark → Raspberry Pi 5**, then **Radxa Orion O6 → the same Raspberry Pi 5**.
The Radxa runs OpenPAVE's communication and control-plane software; no local Qwen
inference, GPU setup, Docker, or camera is needed. This tests software portability,
not model inference speed or physical actuator performance.

## Prepare the same current checkout

All three hosts need a 64-bit Linux Arm64 environment, Python 3.10 or later with
`venv` and pip, and network access to the Pi's TCP port 7447. Use the same Python
minor version where practical. The Radxa needs the same `requirements-seam.txt`
dependencies as the Spark; there are no additional Radxa-specific dependencies.
Installation and this exact benchmark still need validation on your hardware.

Use a full copy of the **same current OpenPAVE checkout** on all three hosts,
including `scripts/seam_bench.py` and the current raw Zenoh backend. The updated
client requires an updated body that echoes request correlation IDs; older bodies'
uncorrelated replies are ignored. Do not use an older release tag.

One way to preserve the current source, including uncommitted benchmarking changes,
is to copy the full checkout into a dedicated directory on each host. From the
current repository root on your source machine, replace all SSH placeholders:

```bash
for host in '<DGX_USER>@<DGX_IP>' '<RADXA_USER>@<RADXA_IP>' '<RPI_USER>@<RPI5_IP>'; do
  rsync -az --exclude='.venv/' --exclude='venv/' \
    --exclude='__pycache__/' --exclude='benchmark-results/' \
    ./ "$host:~/OpenPAVE-portability/"
done
```

This requires SSH access and `rsync` on both ends. Use a fresh destination directory
for this experiment. The copy includes Git metadata and current working files;
matching Git commit IDs alone does not verify uncommitted changes. If you already
have identical current full checkouts, use those instead and adjust the paths below.
The minimal `deploy_seam.sh` bundle omits the benchmark, so it is not used here.

On **each host**, in a fresh terminal:

```bash
cd ~/OpenPAVE-portability
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-seam.txt
mkdir -p benchmark-results
```

Record `git rev-parse HEAD`, `git status --short`, `python --version`, and
`python -m pip show eclipse-zenoh` with your experiment notes. Keep code and package
versions fixed throughout both runs. Do not source `configs/radxa-rpicam.env`:
that recipe and its runbook use a different USB-camera `get_image` workload.

## Start the Raspberry Pi 5 body

On the Pi, in the activated environment:

```bash
SEAM_TRANSPORT=raw_zenoh ROBOT_ADAPTER=mock_arm \
ZENOH_LISTEN=tcp/0.0.0.0:7447 python scripts/seam_cli.py serve
```

Confirm the startup log says `adapter=mock_arm`. Leave this **same body service**
running for both experiments. Use only this body on the reachable Zenoh network
and no other command publishers. Correlation IDs match requests to replies, but
T4 does not select or verify a particular body or adapter. The software-only
`mock_arm` adapter does not drive hardware.

## Run from the DGX Spark

From the prepared checkout with its environment activated, replace `<RPI5_IP>`:

```bash
SEAM_TRANSPORT=raw_zenoh ZENOH_CONNECT='tcp/<RPI5_IP>:7447' \
BENCH_ACTION=stop BENCH_PARAMS='{}' BENCH_N=20 BENCH_TIMEOUT_SECONDS=15 \
BENCH_BRAIN_PLATFORM='DGX Spark' BENCH_BODY_PLATFORM='Raspberry Pi 5' \
BENCH_OUTPUT=benchmark-results/dgx-spark-rpi5-raw-zenoh.csv \
python scripts/seam_bench.py | tee benchmark-results/dgx-spark-rpi5-summary.txt
```

Wait for completion before starting the Radxa run.

## Run from the Radxa Orion O6

From the prepared checkout with its environment activated, use the **same Pi IP**:

```bash
SEAM_TRANSPORT=raw_zenoh ZENOH_CONNECT='tcp/<RPI5_IP>:7447' \
BENCH_ACTION=stop BENCH_PARAMS='{}' BENCH_N=20 BENCH_TIMEOUT_SECONDS=15 \
BENCH_BRAIN_PLATFORM='Radxa Orion O6' BENCH_BODY_PLATFORM='Raspberry Pi 5' \
BENCH_OUTPUT=benchmark-results/radxa-orion-o6-rpi5-raw-zenoh.csv \
python scripts/seam_bench.py | tee benchmark-results/radxa-orion-o6-rpi5-summary.txt
```

Each host saves its own CSV and console summary under `benchmark-results/`, which
is Git-ignored. Repeating a command overwrites those files; rename or copy them
before another batch. Platform labels are supplied by the commands, not detected.

## Compare and interpret

Use the two saved summaries side by side. Each already reports attempted requests,
successful requests, success rate, and mean/P50/P95 `total e2e` latency in ms.
Keep the corresponding CSVs as the request-level evidence; no extra comparison
utility is required. For example, copy the Radxa files to the Spark, running this
from the Spark's checkout (replace the SSH placeholders):

```bash
scp '<RADXA_USER>@<RADXA_IP>:~/OpenPAVE-portability/benchmark-results/radxa-orion-o6-rpi5-*' benchmark-results/
cat benchmark-results/dgx-spark-rpi5-summary.txt
cat benchmark-results/radxa-orion-o6-rpi5-summary.txt
```

| Metric | Interpretation |
| --- | --- |
| Attempted / successful | Actual requests recorded / requests that completed successfully. |
| Success rate | Successful requests divided by all attempted requests, including failures and timeouts. |
| Mean | Arithmetic average latency of successful requests. |
| P50 | Median successful latency. |
| P95 | Interpolated 95th percentile of successful latencies; a small-sample view of slower responses. |

T4's `total_ms` measures `send()` inside each worker, including fresh Zenoh
connection/discovery, the fixed 0.5-second settling wait, request/reply, and session
closure. Worker startup and backend imports are excluded from latency but included
in the 15-second attempt deadline. These are **per-call round trips with setup
overhead**, not pure network latency or persistent-session throughput.
`mock_arm` supplies no execution timing, so `execution_ms` and `seam_ms` stay blank.

Failed and timed-out requests count against success rate and are excluded from
latency statistics. Inspect CSV `status` and `error` fields. With no successes,
latency statistics are unavailable. T4 conservatively stops early after a missing
valid reply or transport error, so the attempted count can be below 20. Treat that
as an incomplete batch: resolve the error and repeat both sides with the same
settings rather than silently comparing different request counts.

Keep the Pi, body process, adapter, action, parameters, count, timeout, software,
and network conditions fixed. Use comparable links (for example, both wired),
avoid concurrent loads, and record OS, power/thermal settings and background load.
Repeat batches and alternate host order if investigating differences. Twenty
requests do not establish statistical significance, and differences cannot be
attributed solely to CPU architecture. There are no measured results in this
guide; the current STOP workload and dependencies require real hardware validation
on the Spark, Radxa, and Pi. Earlier camera validation does not validate this test.

## Stop the experiment

The benchmark exits after its batch and reaps its request workers. To interrupt
it, press **Ctrl+C in that benchmark's terminal** and let cleanup finish. After
both runs, press **Ctrl+C in the Pi body terminal**; `seam_cli.py` performs its
existing shutdown STOP. No unrelated OpenPAVE processes need to be terminated.
