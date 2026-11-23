#!/usr/bin/env python3
"""Analyse a seam_bench.py communication CSV using only the standard library.

Exit status is 0 for a valid dataset (including failed requests), or 2 for
invalid/unreadable input. Blank timings are unavailable, never zero.
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from pathlib import Path


FIELDS = (
    "request", "transport", "brain_platform", "body_platform", "action",
    "total_ms", "execution_ms", "seam_ms", "success", "status", "error",
)
METADATA = ("brain_platform", "body_platform", "transport", "action")


def percentile(values: list[float], p: float) -> float:
    """Use seam_bench's linear interpolation at (n - 1) * p / 100."""
    if not values or not 0 <= p <= 100:
        raise ValueError("Percentiles need at least one value and p between 0 and 100")
    values = sorted(values)
    k = (len(values) - 1) * p / 100.0
    lower = int(k)
    if lower + 1 >= len(values):
        return values[lower]
    return values[lower] + (values[lower + 1] - values[lower]) * (k - lower)


def read_results(path: Path) -> list[dict]:
    """Validate the producer's schema, values and metadata before summarising."""
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source, strict=True)
        headers = reader.fieldnames
        if not headers:
            raise ValueError("CSV is empty. Supply a CSV written by scripts/seam_bench.py")
        missing = set(FIELDS) - set(headers)
        if missing:
            raise ValueError("Missing required columns: " + ", ".join(sorted(missing))
                             + ". Supply the original seam_bench.py CSV")
        if len(headers) != len(set(headers)):
            raise ValueError("Duplicate CSV headers. Supply the original seam_bench.py CSV")
        for row in reader:
            where = f"CSV line {reader.line_num}"
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{where}: wrong number of columns; check the CSV export")
            row = {key: value.strip() for key, value in row.items()}
            try:
                number = int(row["request"])
                if number < 1:
                    raise ValueError
            except ValueError:
                raise ValueError(f"{where}: request must be a positive integer") from None
            if row["success"].lower() not in {"true", "false"}:
                raise ValueError(f"{where}: success must be True or False")
            row["success"] = row["success"].lower() == "true"
            if row["status"] not in {"completed", "failed", "timeout"}:
                raise ValueError(f"{where}: status must be completed, failed or timeout")
            if row["success"] and row["status"] != "completed":
                raise ValueError(f"{where}: success=True conflicts with status={row['status']}; "
                                 "check the original benchmark CSV")
            for field in ("total_ms", "execution_ms", "seam_ms"):
                if row[field] == "":
                    row[field] = None
                    continue
                try:
                    value = float(row[field])
                except ValueError:
                    raise ValueError(f"{where}: {field} must be a finite number or blank") from None
                # seam_ms is a subtraction in the producer and may be negative.
                if not math.isfinite(value) or (field != "seam_ms" and value < 0):
                    raise ValueError(f"{where}: invalid {field}; use a finite "
                                     + ("number" if field == "seam_ms" else "nonnegative number")
                                     + " or leave unavailable timing blank")
                row[field] = value
            for field in METADATA:
                if not row[field]:
                    raise ValueError(f"{where}: {field} is blank; restore the benchmark label")
            rows.append(row)
    if not rows:
        raise ValueError("CSV has no request rows. Run the communication benchmark first")
    for field in METADATA:
        values = sorted({row[field] for row in rows})
        if len(values) > 1:
            raise ValueError(f"Conflicting benchmark metadata for {field}: "
                             + ", ".join(repr(value) for value in values)
                             + ". Analyse each platform/workload separately using its original CSV")
    return rows


def format_summary(rows: list[dict]) -> str:
    successful = [row for row in rows if row["success"] and row["status"] == "completed"]
    timed_out = sum(row["status"] == "timeout" for row in rows)
    failed = len(rows) - len(successful) - timed_out
    latencies = [row["total_ms"] for row in successful if row["total_ms"] is not None]
    lines = ["OpenPAVE Communication Benchmark Analysis", "-" * 42]
    for field, label in zip(METADATA, ("Brain platform:", "Body platform:", "Transport:", "Action:")):
        lines.append(f"{label:<16}{rows[0][field]}")
    lines.extend([
        "",
        f"{'Requests attempted:':<20}{len(rows)}",
        f"{'Successful:':<20}{len(successful)}",
        f"{'Failed:':<20}{failed}",
        f"{'Timed out:':<20}{timed_out}",
        f"{'Success rate:':<20}{len(successful) / len(rows) * 100:.1f}%",
        "",
        "Successful-request latency (total_ms)",
        f"Timing measurements: {len(latencies)}/{len(successful)} successful requests",
    ])
    metrics = (
        ("Mean:", statistics.mean(latencies) if latencies else None),
        ("P50:", percentile(latencies, 50) if latencies else None),
        ("P95:", percentile(latencies, 95) if latencies else None),
        ("Minimum:", min(latencies) if latencies else None),
    )
    for label, value in metrics:
        lines.append(f"{label:<20}" + (f"{value:.1f} ms" if value is not None else "unavailable"))
    if len(latencies) < len(successful):
        lines.append("Note: blank total_ms values are unavailable; statistics use only measured successes.")
    if not successful:
        lines.append("No successful requests; latency statistics unavailable. Check the CSV status/error columns.")
    if any(rows[0][field].lower() == "unknown" for field in METADATA):
        lines.append("Note: unknown metadata was recorded by the benchmark; verify the run's platform/workload labels.")
    lines.extend([
        "",
        "Note: total_ms includes communication setup and discovery overhead, including",
        "the fixed 0.5-second settling period for raw_zenoh. It is not pure network latency.",
        "Failed and timed-out requests are excluded from latency statistics; timeouts are counted separately from failures.",
        "Only metadata recorded in this CSV can be checked; unrecorded settings cannot be verified.",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="Communication CSV written by scripts/seam_bench.py")
    args = parser.parse_args(argv)
    try:
        rows = read_results(args.csv_path)
    except FileNotFoundError:
        print(f"Error: CSV file not found: {args.csv_path}. Check the path and filename.", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        print(f"Error reading {args.csv_path}: {exc}", file=sys.stderr)
        return 2
    print(format_summary(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
