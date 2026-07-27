# OpenPAVE Benchmark Harness

The current benchmark harness validates the OpenPAVE control path for Validated Baseline v1.0.

The first benchmark runner does not benchmark VLM inference. It validates the runtime control path:

```text
scenario expected intent
-> Intent Ingress
-> intent file bus
-> Control Daemon
-> Robot Adapter
-> command result feedback
```

This keeps the first benchmark repeatable and safe before adding camera frame datasets or VLM replay inputs.

## Start Runtime

Start the OpenPAVE runtime first.

For software-only validation:

```bash
OPENPAVE_CONFIG=configs/mock.env ./scripts/run_stage3_demo.sh
```

For physical PuppyPi validation, start the PuppyPi controller and then:

```bash
OPENPAVE_CONFIG=configs/puppypi.env ./scripts/run_stage3_demo.sh
```

## Run Mock Benchmark

From another terminal:

```bash
source .venv/bin/activate

python3 scripts/run_benchmark.py scenarios/mock-intent-stop-trot.json
```

The runner writes JSONL output under:

```text
benchmark-results/
```

## Summarize Benchmark Results

Summarize one or more benchmark result files:

```bash
python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl
```

The default grouping compares results by scenario and adapter:

```text
scenario.id    adapter.name    total    passed    failed    pass_rate    avg_latency_ms
```

Use `--group-by` to compare different experiment dimensions.

Compare result files whose scenarios declare different models under the same scenario:

```bash
python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl \
  --group-by scenario.id \
  --group-by inference_node.default_model
```

Compare by the model value captured from the actual runtime environment:

```bash
python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl \
  --group-by scenario.id \
  --group-by runtime_env.UI_MODEL
```

Compare result files whose scenarios declare different robot or sensor endpoints:

```bash
python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl \
  --group-by scenario.id \
  --group-by robot_sensor_endpoint.validated_target
```

Compare result files whose scenarios declare different Arm-based inference nodes:

```bash
python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl \
  --group-by scenario.id \
  --group-by inference_node.validated_target
```

Emit machine-readable summary output:

```bash
python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl --format json
```

## Add Benchmark Gates

Use threshold options when you want the summary command to fail on regressions:

```bash
python3 scripts/summarize_benchmarks.py benchmark-results/*.jsonl \
  --min-pass-rate 1.0 \
  --max-avg-latency-ms 1500
```

The command exits with status `1` if any grouped result falls below the pass-rate threshold or exceeds the average-latency threshold. This is useful as a lightweight release check for the control path.

## Run Physical PuppyPi Benchmark

Physical scenarios are blocked unless explicitly allowed:

```bash
python3 scripts/run_benchmark.py scenarios/puppypi-gesture-stop-trot.json --allow-physical
```

Use this only when the PuppyPi side controller is running and the robot is in a safe test area.

## Result Format

Each JSONL row includes:

- scenario id, title, version, and runtime profile
- prompt id, title, version, and file reference
- expected intent
- observed intent
- observed command status
- pass/fail
- control-path latency in milliseconds
- Intent Ingress HTTP response
- command result feedback
- robot state feedback
- selected runtime environment values such as `ROBOT_ADAPTER`, `UI_MODEL`, `UI_API_BASE`, `ROS_DOMAIN_ID`, and ROS Docker image settings
- robot/sensor endpoint assumptions
- inference node assumptions
- adapter assumptions
- safety constraints

## Useful Options

Override expected intents:

```bash
python3 scripts/run_benchmark.py scenarios/mock-intent-stop-trot.json --intent STOP --intent TROT
```

Override runtime files:

```bash
python3 scripts/run_benchmark.py scenarios/mock-intent-stop-trot.json \
  --command-result-path /tmp/vla_command_result.json \
  --robot-state-path /tmp/vla_robot_state.json
```

Use a different Intent Ingress URL:

```bash
python3 scripts/run_benchmark.py scenarios/mock-intent-stop-trot.json \
  --intent-url http://127.0.0.1:7071/intent
```

## Current Scope

Validated Baseline v1.0 measures control-path behavior and can summarize results by scenario metadata such as model, robot/sensor endpoint, adapter, and inference node. VLM inference latency, camera frame replay, FPS, GPU usage, transport latency, and model output quality should be added in future work once benchmark input datasets are defined.

For a quick vLLM/UI smoke test outside the benchmark runner, use the `/pave` console's text-only inference path. That validates the OpenAI-compatible backend and prompt/result UI without requiring a camera stream.
