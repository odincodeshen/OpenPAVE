# Communication seam benchmark

Run from the repository root in a Python environment with `requirements-seam.txt`
installed on each host. Use the same current OpenPAVE source on brain and body:
the updated raw Zenoh client requires the body to echo request correlation IDs.
Replies from older bodies without that support are ignored. No hardware validation
is implied by the automated tests.

On the Raspberry Pi 5 (body), explicitly select the software-only adapter:

```sh
python3 -m pip install -r requirements-seam.txt
SEAM_TRANSPORT=raw_zenoh ROBOT_ADAPTER=mock_arm \
  ZENOH_LISTEN=tcp/0.0.0.0:7447 python3 scripts/seam_cli.py serve
```

Confirm the startup log says `adapter=mock_arm`. Stop other OpenPAVE seam bodies
on the reachable Zenoh network: raw Zenoh uses shared action/state keys and does
not select or verify a particular adapter. Allow TCP port 7447 between the hosts.

On the DGX Spark (brain), replace `<RPI5_IP>` with the Pi's reachable IP:

```sh
python3 -m pip install -r requirements-seam.txt
export PI5_IP='<RPI5_IP>'
SEAM_TRANSPORT=raw_zenoh ZENOH_CONNECT="tcp/${PI5_IP}:7447" \
  BENCH_ACTION=stop BENCH_PARAMS='{}' BENCH_N=20 BENCH_TIMEOUT_SECONDS=15 \
  BENCH_BRAIN_PLATFORM='DGX Spark' BENCH_BODY_PLATFORM='Raspberry Pi 5' \
  BENCH_OUTPUT=benchmark-results/dgx-spark-rpi5-raw-zenoh.csv \
  python3 scripts/seam_bench.py
```

`stop` is the default action. To exercise the previous `move_joint` workload,
first verify that the only reachable body is `mock_arm`, then set
`BENCH_ACTION=move_joint BENCH_PARAMS='{"joint":1,"position":0.2}'
BENCH_ALLOW_MOTION=1` on the brain command. `move_joint` can move real hardware;
setting `ROBOT_ADAPTER=mock_arm` on the brain does not configure the remote body.
The opt-in is required for every action except `stop` and `estop`.
Real servo adapter behavior is unchanged.

The benchmark retains `BENCH_N`, `BENCH_ACTION`, `BENCH_PARAMS`, `SEAM_TRANSPORT`
(`raw_zenoh` or `device_connect`), and `BENCH_OUTPUT` (default
`benchmark-results/seam-benchmark.csv`). Optional `BENCH_BRAIN_PLATFORM` and
`BENCH_BODY_PLATFORM` are user-supplied labels, defaulting to `unknown`; they are
not detected remotely.

`BENCH_TIMEOUT_SECONDS` defaults to 15 seconds to allow connection and discovery,
including raw Zenoh's fixed 0.5 second settle. It must be finite and positive.
The deadline includes worker startup, SDK imports, connection, discovery and the
request. Total latency times `send()` inside the worker, excluding worker startup
and backend import. Each send creates fresh transport state, so these are
per-call measurements with setup overhead, not pure network latency or
steady-state performance. The seam segment subtracts only body-reported
execution latency; it still includes connection/discovery and other overhead.
`mock_arm` logs actions without hardware and does **not** supply `latency_ms`,
so its execution and seam segment columns remain blank rather than claiming zero.

Each request runs in an isolated spawned process. This is necessary because
`device_connect.send()` synchronously calls connect/discover/invoke and ignores
its timeout argument: asyncio cancellation or a thread cannot enforce a deadline.
Raw Zenoh closes its session on cooperative cancellation, but its open/close and
publish calls can also block. On deadline the worker is terminated and reaped
(with a bounded terminate wait then kill); OS process resources are released.
This cannot retract a command already received by the body. It also cannot
promise SDK-specific graceful deregistration after forced termination.

Device-connect attempts continue after failures/timeouts using new workers and
RPC invocations. Raw Zenoh continues after explicit failed body responses,
but conservatively stops when no valid response is received (including exceptions
and timeouts). Check body availability, matching current code and connectivity
before restarting. This is a diagnostic policy: correlation IDs already prevent
delayed replies from being accepted for another request. Normal raw Zenoh runs
still require exclusive use of the shared action/state keys because T4 does not
select a body instance and other publishers can send commands to the same body.
The reported attempted count can therefore be smaller than `BENCH_N`.

CSV rows are flushed after every attempt. `completed`, `failed`, and `timeout`
are mutually exclusive statuses; backend `no_reply` responses count as timeouts.
Exceptions, missing responses, and timeouts leave latency fields blank. Valid
unsuccessful body responses retain observed round-trip timing, and body timing
only when supplied as a finite nonnegative number. Invalid responses are failures.
Timeouts and failures include error details. Success rate uses all attempts;
mean, P50, P95 and minimum latency use successful attempts only. Missing body
timing is excluded from execution and seam statistics. With no successes,
statistics are explicitly unavailable. Failed and timed-out summary counts are
separate categories.
