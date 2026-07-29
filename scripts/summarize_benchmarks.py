#!/usr/bin/env python3
"""Summarize and compare OpenPAVE benchmark JSONL results."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_GROUP_BY = ["scenario.id", "adapter.name"]


def read_jsonl(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                payload = json.loads(stripped)
                if not isinstance(payload, dict):
                    raise ValueError(f"expected JSON object at {path}:{line_number}")
                payload.setdefault("_source_file", str(path))
                records.append(payload)
    return records


def get_dotted(record: dict[str, Any], dotted_key: str) -> Any:
    value: Any = record
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def normalize_group_value(value: Any) -> str:
    if value is None or value == "":
        return "unknown"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def group_records(
    records: list[dict[str, Any]],
    group_by: list[str],
) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = tuple(normalize_group_value(get_dotted(record, field)) for field in group_by)
        groups[key].append(record)
    return dict(groups)


def summarize_group(records: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [
        record["benchmark"]["latency_ms"]
        for record in records
        if isinstance(record.get("benchmark"), dict)
        and record["benchmark"].get("latency_ms") is not None
    ]
    passed = sum(
        1
        for record in records
        if isinstance(record.get("benchmark"), dict) and record["benchmark"].get("pass")
    )
    summary: dict[str, Any] = {
        "total": len(records),
        "passed": passed,
        "failed": len(records) - passed,
        "pass_rate": round(passed / len(records), 4) if records else 0.0,
    }
    if latencies:
        summary.update(
            {
                "avg_latency_ms": round(statistics.mean(latencies), 3),
                "min_latency_ms": round(min(latencies), 3),
                "max_latency_ms": round(max(latencies), 3),
            }
        )
    return summary


def summarize_records(records: list[dict[str, Any]], group_by: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, group in sorted(group_records(records, group_by).items()):
        # keep zip(strict=True)'s guarantee without the 3.10+ kwarg (deploy targets run
        # 3.12, but the tests run on 3.9): the key must line up with the requested fields.
        if len(key) != len(group_by):
            raise ValueError(f"group key {key!r} does not match group_by {group_by!r}")
        row = {
            "group": dict(zip(group_by, key)),
            "summary": summarize_group(group),
        }
        rows.append(row)
    return rows


def format_text(rows: list[dict[str, Any]], group_by: list[str]) -> str:
    headers = [
        *group_by,
        "total",
        "passed",
        "failed",
        "pass_rate",
        "avg_latency_ms",
        "min_latency_ms",
        "max_latency_ms",
    ]
    lines = ["\t".join(headers)]
    for row in rows:
        group = row["group"]
        summary = row["summary"]
        values = [
            *(group[field] for field in group_by),
            str(summary["total"]),
            str(summary["passed"]),
            str(summary["failed"]),
            f"{summary['pass_rate']:.2%}",
            str(summary.get("avg_latency_ms", "n/a")),
            str(summary.get("min_latency_ms", "n/a")),
            str(summary.get("max_latency_ms", "n/a")),
        ]
        lines.append("\t".join(values))
    return "\n".join(lines)


def evaluate_thresholds(
    rows: list[dict[str, Any]],
    *,
    min_pass_rate: float | None,
    max_avg_latency_ms: float | None,
) -> list[str]:
    violations: list[str] = []
    for row in rows:
        group = ", ".join(f"{key}={value}" for key, value in row["group"].items())
        summary = row["summary"]
        if min_pass_rate is not None and summary["pass_rate"] < min_pass_rate:
            violations.append(
                f"{group}: pass_rate {summary['pass_rate']:.2%} < {min_pass_rate:.2%}"
            )
        if max_avg_latency_ms is not None:
            avg_latency_ms = summary.get("avg_latency_ms")
            if avg_latency_ms is None:
                violations.append(f"{group}: avg_latency_ms is unavailable")
            elif avg_latency_ms > max_avg_latency_ms:
                violations.append(
                    f"{group}: avg_latency_ms {avg_latency_ms} > {max_avg_latency_ms}"
                )
    return violations


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize and compare OpenPAVE benchmark JSONL results"
    )
    parser.add_argument("jsonl", nargs="+", help="Benchmark JSONL files")
    parser.add_argument(
        "--group-by",
        action="append",
        dest="group_by",
        help=(
            "Dotted record field used for grouping. Can be specified multiple times. "
            f"Default: {', '.join(DEFAULT_GROUP_BY)}"
        ),
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        help="Fail if any group pass rate is below this value, e.g. 1.0",
    )
    parser.add_argument(
        "--max-avg-latency-ms",
        type=float,
        help="Fail if any group average latency exceeds this value",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    paths = [Path(path) for path in args.jsonl]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        print(f"Missing benchmark result file(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    records = read_jsonl(paths)
    if not records:
        print("No benchmark records found", file=sys.stderr)
        return 2

    group_by = args.group_by or DEFAULT_GROUP_BY
    rows = summarize_records(records, group_by)
    violations = evaluate_thresholds(
        rows,
        min_pass_rate=args.min_pass_rate,
        max_avg_latency_ms=args.max_avg_latency_ms,
    )
    if args.format == "json":
        print(
            json.dumps(
                {"group_by": group_by, "results": rows, "violations": violations},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(format_text(rows, group_by))
        for violation in violations:
            print(f"threshold_violation={violation}", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
