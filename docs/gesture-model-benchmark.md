# Qwen vs LLaVA gesture benchmark

Evaluate **Qwen2.5-VL-3B-Instruct** and **LLaVA v1.6 Mistral 7B** on the same saved
STOP/TROT images. Each invocation evaluates one already-served model, saves CSV,
and prints accuracy and API response latency statistics. No camera service,
robot body, Zenoh transport, or servo is required; no actions are dispatched.

## Prepare a labelled dataset

Use your own JPEG/PNG images, with both clear thumbs-up (**TROT**) and open-palm
(**STOP**) examples. Include varied lighting and viewpoints and a balanced number
of examples per class. Images without a clear gesture can be labelled STOP under
the shared prompt's uncertainty rule. Review labels before running either model;
do not tune the evaluation set separately for each model.

Obtain permission before sharing identifiable images. Keep local images under
`benchmark-results/`, which is already Git-ignored, rather than committing them.
From the current OpenPAVE checkout:

```bash
mkdir -p benchmark-results/gesture-dataset/images
```

Save your real images there. For example, after saving your own images as
`thumbs_up_01.jpg` and `open_palm_01.jpg`, create the manifest:

```bash
cat > benchmark-results/gesture-dataset/manifest.csv <<'CSV'
image,label
images/thumbs_up_01.jpg,TROT
images/open_palm_01.jpg,STOP
CSV
```

Add one row per image. Paths resolve relative to the manifest directory, and row
order is preserved. Labels are stripped and normalized to uppercase STOP/TROT.
Repeated rows are evaluated repeatedly and contribute repeatedly to accuracy.

Malformed manifests, invalid labels and empty datasets stop setup before any
inference. Missing, empty or unsupported image files produce failed CSV rows
and stay in the accuracy denominator. File types are checked by MIME inferred
from the filename; image decoding is left to the model server. Do not compare
batches with unreadable files. No images are downloaded or supplied by this tool.

## Prepare the servers

Use the same current OpenPAVE checkout and Python 3.10 or later for both runs.
The benchmark client uses the Python standard library and existing OpenPAVE
modules; it adds no dependencies. A client environment can be prepared with:

```bash
python3 -m venv .venv
source .venv/bin/activate
python scripts/benchmark_gesture_models.py --help
```

Start each model using its existing launch documentation:

- Qwen: [NVIDIA Docker/vLLM launch, step 3c](runbooks/v1.8-quick-demo.md).
- LLaVA: [separate vLLM environment and launch](validated-baseline.md#start-a-vllm-backend).

The documented Qwen recipe uses `nvcr.io/nvidia/vllm:26.03.post1-py3` and
`--dtype auto`; the LLaVA recipe pins `vllm==0.21.0` and uses `--dtype float16`.
These are different serving environments. The benchmark does not change them
or establish that one shared environment works for both models. Record the
actual image digest/package versions, model weight revision, dtype, launch flags,
GPU and host details with your results. Use `--server-notes` to retain these notes
in every CSV row, or reference a saved experiment log there. Do not include secrets.

Run one server at a time on the same DGX Spark, using its documented shutdown
procedure before switching models. Wait for it to be ready and check the served
model before each benchmark:

```bash
curl --fail http://127.0.0.1:8000/v1/models
```

Use the same endpoint location for both runs. If authentication is required, set
`INFERENCE_API_KEY` in the client environment. The benchmark records selected and
reported model names, but cannot verify the weights behind a server's model alias.

## Run one command per model

After starting Qwen, run from the client environment at the repository root:

```bash
python scripts/benchmark_gesture_models.py \
  --model Qwen/Qwen2.5-VL-3B-Instruct \
  --api-base http://127.0.0.1:8000/v1 \
  --dataset benchmark-results/gesture-dataset/manifest.csv \
  --output benchmark-results/qwen-gestures.csv \
  --timeout 30 --temperature 0 --max-tokens 16 --warmup 1 \
  --server-notes 'Qwen serving configuration: see my saved launch/version log'
```

After switching the server to LLaVA:

```bash
python scripts/benchmark_gesture_models.py \
  --model llava-hf/llava-v1.6-mistral-7b-hf \
  --api-base http://127.0.0.1:8000/v1 \
  --dataset benchmark-results/gesture-dataset/manifest.csv \
  --output benchmark-results/llava-gestures.csv \
  --timeout 30 --temperature 0 --max-tokens 16 --warmup 1 \
  --server-notes 'LLaVA serving configuration: see my saved launch/version log'
```

Replace the notes with details or a reference to your actual experiment log.
`--api-base` also accepts a full chat-completions URL; its default comes from
`INFERENCE_API_BASE`, then `UI_API_BASE`, then localhost. Other defaults are the
shared gesture prompt, temperature 0, 16 output tokens, a 30-second HTTP timeout,
and one excluded warm-up. Select another shared prompt JSON with `--prompt-preset`.
The timeout is the existing client's HTTP timeout, not a hard total deadline.

Images are loaded into memory before warm-up and reused without resizing. Warm-up
requests cycle through readable images in manifest order and never become measured
CSV rows. Warm-up failures are reported, recorded as metadata, and do not prevent
the measured pass; resolve them before using a batch for comparison. Measured
requests run sequentially, without automatic retries. CSV rows are flushed after
each image. Output files are overwritten, so use new filenames for repeat batches.

## Read the results

| Metric/field | Meaning |
| --- | --- |
| Accuracy | Correct valid predictions / total labelled dataset rows, including file/request failures and invalid model outputs in the denominator. |
| Completed API requests | Valid inference responses, including wrong classifications and invalid STOP/TROT text. Separate from correct predictions. |
| `prediction` | STOP or TROT after the existing application's whitespace/case normalization; blank for invalid output or request failure. |
| `invalid_output`, `fallback_stop` | Invalid text would trigger OpenPAVE's STOP fallback. It never earns a correct STOP classification. Blank when no valid API response exists. |
| `api_response_ms` | Existing client timing from HTTP request to full response-body read/decode; includes network, queueing and server processing. |
| Mean / P50 / P95 | Mean, median and interpolated 95th percentile of completed API latencies, including incorrect/invalid classifications; excludes failures, timeouts and warm-ups. |

Raw model text, labels, correctness, status/error, model names, endpoint, token
usage and finish reason are recorded. The CSV also includes a manifest hash, image
hashes, prompt ID/text hash, generation settings, warm-up counts, timestamp, client
Python/platform and server notes. `dataset_sha256` fingerprints ordered labels and
image hashes; it excludes absolute paths. Compare that fingerprint, per-image
hashes, prompt hash and settings across both CSVs before comparing their summaries.
A blank image hash indicates an unreadable/unsupported input, not a verified match.

`completed`, `failed` and `timeout` are request statuses; invalid gesture text is a
completed request with `invalid_output=True`. Recognizable HTTP/socket timeouts
are marked timeout; other API errors, including malformed completions, are failed.
Failures retain their rows with blank unavailable measurements. An all-failed
batch has 0% accuracy and unavailable latency statistics. Exit code 0 means the
batch completed without request/warm-up failures, **not** perfect accuracy;
1 indicates such failures and 2 indicates a setup error. Ctrl+C interrupts the
batch; already flushed measured rows remain, but the batch is incomplete.

## Compare fairly and understand the limits

Keep the image bytes, labels, order, prompt text, generation settings, warm-up
count, client/server location, network and host load fixed. Do not change images
between runs. Inspect invalid counts, errors, finish reasons and per-class results
alongside overall accuracy; a STOP-heavy dataset can hide poor TROT recognition.
Latency statistics use all completed responses, not just correct predictions.

`api_response_ms` excludes file loading, base64/request construction and application
postprocessing. It is **not GPU-only inference time**, model-load time, throughput,
or physical stopping time. The CSV does not claim a GPU-only measurement.
Server generation defaults, chat templates, vision preprocessing and numerical
behavior can differ between models even with the same requested settings.
Temperature 0 does not guarantee identical results across serving stacks.

With the existing distinct launch environments, results describe the two complete
model-serving configurations; differences cannot be attributed solely to model
choice. Repeated batches help assess variability; a small personal dataset does
not establish general model quality or statistical significance. Neither real
model has been benchmarked by this implementation's mock-based automated tests.
