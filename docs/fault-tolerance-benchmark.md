# Automated fault-tolerance benchmark

This benchmark starts a dedicated test brain, sends TROT, confirms a lease renewal,
and kills that brain with SIGKILL. The Raspberry Pi's existing motion lease must
then expire and complete a software STOP. It repeats automatically and writes CSV.
No inference model is needed. The body service stays running.

## Prepare both hosts

Use the same current OpenPAVE checkout on both the DGX Spark and Raspberry Pi 5,
with Python 3.10 or later. The updated raw Zenoh client requires an updated
OpenPAVE body that echoes request correlation IDs in its replies; replies from
older bodies without this support are ignored.

From the repository root on **each host**:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-seam.txt
```

Use a dedicated test body with no other brains or command publishers. Allow TCP
port 7447 from the Spark to the Pi. This benchmark currently supports **raw Zenoh**
only; Device Connect is not implemented or hardware-validated for this benchmark.

## Raspberry Pi 5: start the body

In the Pi's activated environment, from the repository root:

```bash
SERVO_DRYRUN=1 ROBOT_ADAPTER=gpio_servo SEAM_TRANSPORT=raw_zenoh \
BODY_MOTION_TTL_S=5 ZENOH_LISTEN=tcp/0.0.0.0:7447 \
python scripts/seam_cli.py serve
```

Leave this terminal running. `gpio_servo` supports TROT and STOP; `mock_arm` does
not support TROT. Dry-run mode does not drive GPIO and needs no connected servo.
The adapter's existing safety and STOP behavior are unchanged.

## DGX Spark: run the benchmark

In the Spark's activated environment, replace `<RPI5_IP>` with the Pi's address:

```bash
ZENOH_CONNECT='tcp/<RPI5_IP>:7447' \
python scripts/benchmark_fault_tolerance.py --runs 5 \
  --brain-platform 'DGX Spark' --body-platform 'Raspberry Pi 5' \
  --output benchmark-results/fault-tolerance.csv
```

Before any TROT, the tool verifies once that the remote body reports `gpio_servo`,
`SERVO_DRYRUN=1`, actual dry-run mode, TROT/STOP support, a valid TTL, and no active
lease. It then pins all requests to that body instance. Both hosts need the updated
code: older bodies lack diagnostics and correlated replies and will fail preflight.

Expect one verification message, one status line per trial, the CSV path, and a
summary of total, successful, failed, and timed-out trials, success rate, and mean,
P50, and P95 timings. Statistics include only valid successful measurements.
Platform labels are user-supplied metadata; their default is `unknown`.

The default CSV is `benchmark-results/fault-tolerance.csv` (overwritten each run).
This directory is already ignored by Git. Custom paths outside it may need their
own ignore rule. Each attempted trial is flushed immediately, including failures.
`--timeout` controls request/brain startup waits (default 10 seconds);
`--expiry-timeout` overrides the post-kill observation window (default TTL + request
timeout + 2 seconds). The normal exit code is 0; an unsuccessful trial returns 1.
Native Zenoh connection setup or teardown can outlast an asynchronous request timeout.

## Interpret the measurements

All event timestamps come from the **body's monotonic clock**, taken inside the
existing lease implementation. The retained expiry event identifies the exact
lease and includes the final accepted renewal, even if a renewal was in transit
when the brain died. Status polling and network return time are excluded.

| CSV field | Meaning |
| --- | --- |
| `renewal_to_expiry_ms` | Last accepted renewal to body detecting expiry; includes TTL and watcher polling/dispatch-lock delay. |
| `expiry_to_stop_issued_ms` | Detection to calling the software STOP dispatcher. |
| `expiry_to_stop_completed_ms` | Detection to software STOP returning; inspect `stop_completed` for success. |
| `response_ms` | Last accepted renewal to software STOP returning; the summary's response time. |
| `brain_termination_to_stop_ms` | Always blank: separate host clocks and network delays prevent an accurate measurement here. |

The watchdog polls approximately every 100 ms. STOP completion means the adapter
returned successfully, **not physical motor stopping time**. Dry-run measurements
exercise the software path and cannot establish real actuator stopping performance.
SIGKILL tests a brain process failure; it does not test body crashes, power loss,
or network partitions. Scheduling and transport delays can affect lease delivery.

The CSV also records run number, transport, platform labels, body/lease IDs, TTL,
raw body timestamps, TROT/renewal acceptance, deliberate brain termination, expiry,
STOP outcome, trial status, and error details. Unknown measurements stay blank.

Any unsuccessful trial stops the batch to prevent delayed motion or uncertain
state from contaminating later trials. The tool reaps its own child and attempts a
cleanup STOP, which is never counted as the measured expiry STOP. Resolve the
reported error and restart. The benchmark never kills the body or other processes.
