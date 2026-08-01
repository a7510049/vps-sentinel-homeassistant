#!/usr/bin/env python3
"""Compare three completed Python and Go Agent benchmark runs."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics


MINIMUM_RUNS = 3
MINIMUM_DURATION = 86400


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_summary(path, expected_name):
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read summary: {source}") from error
    if payload.get("name") != expected_name:
        raise ValueError(f"{source} is not a {expected_name} run")
    if not payload.get("measurement_complete"):
        raise ValueError(f"{source} did not complete its measurement")
    requested = payload.get("requested_duration_seconds")
    actual = payload.get("actual_measurement_seconds")
    if (
        not isinstance(requested, (int, float))
        or requested < MINIMUM_DURATION
        or not isinstance(actual, (int, float))
        or actual < requested * 0.99
    ):
        raise ValueError(f"{source} is shorter than the 24-hour gate")
    for metric in ("rss_kib", "cpu_percent"):
        values = payload.get(metric)
        if (
            not isinstance(values, dict)
            or not isinstance(values.get("p95"), (int, float))
            or not isinstance(values.get("mean"), (int, float))
        ):
            raise ValueError(f"{source} has incomplete {metric} statistics")
    fingerprint = payload.get("host", {}).get("fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 16:
        raise ValueError(f"{source} has no host fingerprint")
    return payload


def aggregate(runs):
    return {
        "runs": len(runs),
        "rss_kib": {
            "mean_of_means": round(
                statistics.fmean(item["rss_kib"]["mean"] for item in runs),
                3,
            ),
            "median_p95": round(
                statistics.median(item["rss_kib"]["p95"] for item in runs),
                3,
            ),
            "worst_p95": round(
                max(item["rss_kib"]["p95"] for item in runs),
                3,
            ),
        },
        "cpu_percent": {
            "mean_of_means": round(
                statistics.fmean(
                    item["cpu_percent"]["mean"] for item in runs
                ),
                3,
            ),
            "median_p95": round(
                statistics.median(
                    item["cpu_percent"]["p95"] for item in runs
                ),
                3,
            ),
            "worst_p95": round(
                max(item["cpu_percent"]["p95"] for item in runs),
                3,
            ),
        },
        "samples": sum(item["samples"] for item in runs),
    }


def percent_reduction(baseline, candidate):
    if baseline <= 0:
        return None
    return round(100 * (baseline - candidate) / baseline, 3)


def compare(python_paths, go_paths):
    if len(python_paths) < MINIMUM_RUNS or len(go_paths) < MINIMUM_RUNS:
        raise ValueError("at least three Python and three Go runs are required")
    python_runs = [load_summary(path, "python") for path in python_paths]
    go_runs = [load_summary(path, "go") for path in go_paths]
    fingerprints = {
        item["host"]["fingerprint"] for item in [*python_runs, *go_runs]
    }
    architectures = {
        item["host"].get("architecture") for item in [*python_runs, *go_runs]
    }
    if len(fingerprints) != 1:
        raise ValueError("all runs must come from the same host")
    if len(architectures) != 1:
        raise ValueError("all runs must use the same architecture")

    python = aggregate(python_runs)
    go = aggregate(go_runs)
    rss_reduction = percent_reduction(
        python["rss_kib"]["median_p95"],
        go["rss_kib"]["median_p95"],
    )
    cpu_change = None
    python_cpu = python["cpu_percent"]["median_p95"]
    if python_cpu > 0:
        cpu_change = round(
            100
            * (go["cpu_percent"]["median_p95"] - python_cpu)
            / python_cpu,
            3,
        )
    rss_gate = rss_reduction is not None and rss_reduction >= 30
    return {
        "schema_version": 1,
        "generated_at": utc_timestamp(),
        "gate": {
            "minimum_runs_each": MINIMUM_RUNS,
            "minimum_duration_seconds": MINIMUM_DURATION,
            "same_host": True,
            "same_architecture": True,
        },
        "host_fingerprint": next(iter(fingerprints)),
        "architecture": next(iter(architectures)),
        "python": python,
        "go": go,
        "comparison": {
            "p95_rss_reduction_percent": rss_reduction,
            "p95_cpu_change_percent": cpu_change,
            "rss_30_percent_gate": "PASS" if rss_gate else "FAIL",
        },
        "resource_recommendation": (
            "GO_RESOURCE_GATE_PASS"
            if rss_gate
            else "KEEP_PYTHON_RESOURCE_GATE_NOT_MET"
        ),
        "final_decision": "PENDING_OTHER_ADR_GATES",
    }


def write_report(report, output):
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)
    return path


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", nargs="+", required=True)
    parser.add_argument("--go", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        report = compare(args.python, args.go)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    write_report(report, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
