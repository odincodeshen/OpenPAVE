#!/usr/bin/env python3
"""Evaluate saved STOP/TROT images through an existing vLLM API; no robot dispatch.

See docs/gesture-model-benchmark.md for dataset preparation and model server setup.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
import math
import os
import platform
import statistics
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pave_runtime.application import create_application_runtime
from pave_runtime.inference import InferenceRequest, Observation, create_inference_runtime
from pave_runtime.inference_backends.vllm_openai import SUPPORTED_IMAGE_TYPES
from pave_runtime.observation import create_observation_source
from scripts.run_inference import DEFAULT_PROMPT_PRESET, load_prompt
from scripts.seam_bench import _pct

FIELDS = ["run_id", "image_number", "image", "image_sha256", "label", "raw_response",
          "prediction", "correct", "invalid_output", "fallback_stop", "status", "error",
          "api_response_ms", "selected_model", "reported_model", "endpoint", "finish_reason",
          "usage", "dataset", "manifest_sha256", "dataset_sha256", "prompt_id", "prompt_sha256",
          "temperature", "max_tokens", "timeout_seconds", "warmup_count", "warmup_failures",
          "started_at", "python_version", "client_platform", "server_notes"]


@dataclass
class Sample:
    image: str
    label: str
    path: Path
    observation: Observation | None = None
    image_sha256: str = ""
    error: str = ""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load_manifest(path):
    raw = path.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    if reader.fieldnames is None or len(reader.fieldnames) != 2 or set(reader.fieldnames) != {"image", "label"}:
        raise ValueError("manifest must have exactly the columns image,label")
    samples = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"manifest line {reader.line_num}: expected two fields")
        image, label = row["image"].strip(), row["label"].strip().upper()
        if not image or label not in {"STOP", "TROT"}:
            raise ValueError(f"manifest line {reader.line_num}: image is required and label must be STOP or TROT")
        samples.append(Sample(image, label, (path.parent / image).resolve()))
    if not samples:
        raise ValueError("manifest contains no labelled images")
    return samples, sha256(raw)


async def prepare_samples(samples):
    # Freeze the small dataset before warm-up: measured requests reuse these exact bytes.
    for sample in samples:
        try:
            observation = await create_observation_source("file", path=sample.path).capture()
            if observation.media_type not in SUPPORTED_IMAGE_TYPES:
                raise ValueError(f"unsupported image type {observation.media_type}; use JPEG or PNG")
            sample.observation = observation
            sample.image_sha256 = sha256(observation.data)
        except (OSError, RuntimeError, ValueError) as exc:
            sample.error = f"{type(exc).__name__}: {exc}"
    identity = [(s.label, s.image_sha256) for s in samples]
    return sha256(json.dumps(identity, separators=(",", ":")).encode("utf-8"))


def finite_latency(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def error_status(exc):
    # The shared client wraps socket timeouts in InferenceRuntimeError/URLError.
    while isinstance(exc, BaseException):
        if isinstance(exc, TimeoutError):
            return "timeout"
        exc = exc.__cause__ or getattr(exc, "reason", None)
    return "failed"


def score_result(row, result, application):
    if not isinstance(result.text, str) or not finite_latency(result.latency_ms):
        raise ValueError("invalid inference result: text and finite nonnegative API latency required")
    proposal = application.decide(result)
    invalid = proposal.safety_fallback
    prediction = "" if invalid else proposal.action.upper()
    row.update(raw_response=result.text, prediction=prediction,
               correct=not invalid and prediction == row["label"], invalid_output=invalid,
               fallback_stop=invalid, status="completed", api_response_ms=result.latency_ms,
               reported_model=result.model or "", finish_reason=result.metadata.get("finish_reason") or "",
               usage=json.dumps(result.metadata.get("usage"), sort_keys=True))


def summarize(rows):
    completed = [r for r in rows if r["status"] == "completed"]
    correct = sum(r["correct"] is True for r in rows)
    result = {"total": len(rows), "completed": len(completed), "correct": correct,
              "failed": sum(r["status"] == "failed" for r in rows),
              "timeouts": sum(r["status"] == "timeout" for r in rows),
              "invalid": sum(r["invalid_output"] is True for r in rows),
              "accuracy": correct / len(rows) * 100 if rows else 0,
              "mean_ms": None, "p50_ms": None, "p95_ms": None}
    print("Images={total} completed_API_requests={completed} failed={failed} timeouts={timeouts} "
          "invalid_outputs={invalid} correct={correct} accuracy={accuracy:.2f}%".format(**result))
    values = [r["api_response_ms"] for r in completed if finite_latency(r["api_response_ms"])]
    if values:
        result.update(mean_ms=statistics.mean(values), p50_ms=_pct(values, 50), p95_ms=_pct(values, 95))
        print("API response ms: mean={mean_ms:.3f} p50={p50_ms:.3f} p95={p95_ms:.3f} "
              f"(n={len(values)})".format(**result))
    else:
        print("API response latency: unavailable (no valid completed requests)")
    print("Accuracy denominator includes every labelled image. API response time is not GPU-only inference time.")
    return result


async def run(args, factory=None):
    samples, manifest_hash = load_manifest(args.dataset)
    prompt_id, prompt = load_prompt(args.prompt_preset)
    protected = {args.dataset.resolve(), args.prompt_preset.resolve(), *(s.path for s in samples)}
    if args.output.resolve() in protected:
        raise ValueError("output must not overwrite the manifest, prompt, or an input image")
    dataset_hash = await prepare_samples(samples)
    runtime = (factory or create_inference_runtime)("vllm_openai", model=args.model,
               api_base=args.api_base, timeout_sec=args.timeout, max_tokens=args.max_tokens)
    application = create_application_runtime("gesture_commander")

    def request(sample):
        return InferenceRequest(observation=sample.observation, prompt=prompt, model=args.model,
                                options={"temperature": args.temperature, "max_tokens": args.max_tokens})

    ready = [s for s in samples if s.observation is not None]
    warmup_failures = 0
    if not args.server_notes:
        print("Serving configuration unrecorded: use --server-notes to describe the actual server setup.")
    for index in range(args.warmup):
        try:
            if not ready:
                raise ValueError("no readable supported images for warm-up")
            result = await runtime.infer(request(ready[index % len(ready)]))
            if not isinstance(result.text, str) or not finite_latency(result.latency_ms):
                raise ValueError("invalid warm-up response")
        except Exception as exc:
            warmup_failures += 1
            print(f"Warm-up {index + 1} failed (excluded): {exc}", file=sys.stderr)
    print(f"Warm-ups: requested={args.warmup} failed={warmup_failures}; excluded from CSV and statistics.")
    common = dict(run_id=uuid.uuid4().hex, selected_model=args.model, endpoint=runtime.endpoint,
                  dataset=str(args.dataset.resolve()), manifest_sha256=manifest_hash,
                  dataset_sha256=dataset_hash, prompt_id=prompt_id, prompt_sha256=sha256(prompt.encode("utf-8")),
                  temperature=args.temperature, max_tokens=args.max_tokens, timeout_seconds=args.timeout,
                  warmup_count=args.warmup, warmup_failures=warmup_failures,
                  started_at=datetime.now(timezone.utc).isoformat(), python_version=platform.python_version(),
                  client_platform=platform.platform(), server_notes=args.server_notes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with args.output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        for number, sample in enumerate(samples, 1):
            row = dict.fromkeys(FIELDS, "")
            row.update(common, image_number=number, image=sample.image, image_sha256=sample.image_sha256,
                       label=sample.label, correct=False, status="failed", error=sample.error)
            if not sample.error:
                try:
                    score_result(row, await runtime.infer(request(sample)), application)
                except Exception as exc:
                    row.update(status=error_status(exc), error=f"{type(exc).__name__}: {exc}")
            rows.append(row)
            writer.writerow(row)
            file.flush()
            print(f"Image {number}: {row['status']} label={sample.label} prediction={row['prediction']} {row['error']}")
    print(f"CSV: {args.output}")
    summary = summarize(rows)
    return 1 if summary["failed"] or summary["timeouts"] or warmup_failures else 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Model ID/served name on the existing API server")
    parser.add_argument("--dataset", required=True, type=Path, help="CSV with image,label; image paths relative to CSV")
    parser.add_argument("--output", required=True, type=Path, help="Results CSV (overwritten); benchmark-results/ is Git-ignored")
    parser.add_argument("--api-base", default=os.getenv("INFERENCE_API_BASE") or os.getenv("UI_API_BASE") or "http://127.0.0.1:8000/v1",
                        help="HTTP(S) API base or chat-completions endpoint (default INFERENCE_API_BASE/UI_API_BASE or localhost:8000/v1)")
    parser.add_argument("--prompt-preset", type=Path, default=DEFAULT_PROMPT_PRESET, help="Shared OpenPAVE prompt JSON")
    parser.add_argument("--timeout", type=float, default=30, help="HTTP timeout seconds (default 30; not a hard total deadline)")
    parser.add_argument("--temperature", type=float, default=0, help="Sampling temperature (default 0)")
    parser.add_argument("--max-tokens", type=int, default=16, help="Maximum output tokens (default 16)")
    parser.add_argument("--warmup", type=int, default=1, help="Excluded warm-up requests, cycling readable images in order (default 1)")
    parser.add_argument("--server-notes", default="", help="Record image/version, model revision, dtype and actual server launch settings")
    args = parser.parse_args(argv)
    if not args.model.strip():
        parser.error("model must be nonempty")
    args.model = args.model.strip()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    if not math.isfinite(args.temperature) or args.temperature < 0:
        parser.error("temperature must be finite and nonnegative")
    if args.max_tokens <= 0 or args.warmup < 0:
        parser.error("max-tokens must be positive and warmup nonnegative")
    url = urlparse(args.api_base)
    if url.scheme not in {"http", "https"} or not url.netloc:
        parser.error("api-base must be an HTTP(S) URL")
    return args


def cli(argv=None):
    args = parse_args(argv)
    try:
        return asyncio.run(run(args))
    except (OSError, ValueError, csv.Error, UnicodeError) as exc:
        print(f"Benchmark setup failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(cli())
