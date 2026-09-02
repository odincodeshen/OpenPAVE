# Seam Latency Model (basic)

A first, honest breakdown of where time goes on one brain→body action over the seam. It splits the
round trip into three segments and fills in what has been measured. This is the basic performance
model: enough to reason about the bottleneck and to reproduce, not a full benchmark suite.

## The three segments

```text
brain                                   body
  |                                       |
  |  (1) inference: decide the action     |
  |------ (2) seam: carry {action,params} →|
  |                                    (3) execution: adapter runs it
  |←----- (2) seam: carry state back ------|
```

1. **Inference** — the brain deciding what to do (VLM/VLA or a planner). Upstream of the seam.
2. **Seam** — the transport moving the capability JSON there and the state back. Itself two parts:
   - **session setup** — establishing the transport (discovery / connection). Paid **once per brain
     session** in a persistent design; the current `seam_cli.py send` opens a fresh session per call,
     so it pays this every call.
   - **steady-state wire** — the actual message round trip once the session is up.
3. **Execution** — the body-side adapter doing the work (`detail.latency_ms` in the state), e.g. the
   PuppyPi bridge driving `puppy_control`.

## Measured (2026-09-02, aarch64 hosts)

| Segment | Value | How measured |
| --- | --- | --- |
| Inference (VLM) | not yet measured in-seam | Roadmap. The benchmark harness (`scripts/run_benchmark.py`) measures the control path today; folding a VLM-inference segment in is future work. |
| Seam — session setup | ~0.5 s per call for `raw_zenoh` (a fixed `asyncio.sleep(0.5)` discovery settle in the backend); `device_connect` pays D2D discovery of similar order. Under rapid per-call churn it can rise toward ~1 s. | `scripts/seam_bench.py` against a `mock_arm` body (execution ≈ 0), first send / per-call. |
| Seam — steady-state wire | **~0.58 ms p50, 0.65 ms p95** (max 1.14 ms), `raw_zenoh` | Persistent single zenoh session, 30 round trips to a `mock_arm` body on one host. |
| Execution | **home/stop ~514 ms, trot ~1013 ms** (`path=bridge`) | Real PuppyPi over the persistent bridge; see `docs/validation-matrix.md`. |

## What this says

- **The steady-state seam is negligible** (sub-millisecond) — the transport itself is not a
  bottleneck. This holds across brains and transports (see the validation matrix).
- **The per-call session setup is not negligible.** For a single `seam_cli.py send`, the ~0.5 s
  `raw_zenoh` settle is comparable to the execution of a fast action (home/stop ~514 ms), which is why
  a one-shot `home` measures ~1.1–1.2 s end to end. This cost is **per session, not per action** — a
  brain that keeps one session open and streams actions pays it once and then rides the ~0.6 ms wire.
- **Execution dominates real actuation.** The bridge / `puppy_control` sets the floor (~514 ms /
  ~1013 ms); optimizing the seam further would not move it.

### Recommendation

For high-rate or latency-sensitive control, use a **persistent brain session** instead of the
per-call `seam_cli.py send`. The steady-state wire (~0.6 ms) then disappears into the noise and
execution is the only meaningful segment. The current per-call CLI is fine for scripted, occasional
commands and for validation runs.

## Reproduce

Per-call seam segment (isolated with a mock body, execution ≈ 0):

```bash
# body (one host)
SEAM_TRANSPORT=raw_zenoh ROBOT_ADAPTER=mock_arm ZENOH_LISTEN=tcp/0.0.0.0:7447 \
  python scripts/seam_cli.py serve
# bench (same or another host; set ZENOH_CONNECT to the body for cross-host)
SEAM_TRANSPORT=raw_zenoh ZENOH_CONNECT=tcp/127.0.0.1:7447 BENCH_N=20 \
  python scripts/seam_bench.py
```

`seam_bench.py` prints, per send, `total`, `exec` (`detail.latency_ms`) and `seam = total - exec`,
then min/p50/p95. Steady-state wire is measured with a persistent zenoh session (one settle, then N
round trips) — the snippet used for the number above is a ~15-line `zenoh.open` loop; keeping a
persistent-session helper is a natural follow-up.

Execution numbers come from the real-robot runs recorded in `docs/validation-matrix.md`.
