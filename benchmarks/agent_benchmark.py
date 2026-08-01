#!/usr/bin/env python3
"""Reproducible long-running CPU and RSS measurement for one Agent."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shlex
import statistics
import subprocess
import time


FIELDS = (
    "observed_at",
    "elapsed_seconds",
    "rss_kib",
    "cpu_percent",
)


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_env(path):
    values = {}
    if not path:
        return values
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"environment file does not exist: {source}")
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def process_sample(pid):
    status = {}
    for line in Path(f"/proc/{pid}/status").read_text(
        encoding="utf-8"
    ).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            status[key] = value.strip()
    stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
    return {
        "rss_kib": int(status["VmRSS"].split()[0]),
        "cpu_ticks": int(stat[13]) + int(stat[14]),
    }


def percentile(values, percentage):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentage / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def metric_summary(values, digits=3):
    if not values:
        return {"mean": None, "p95": None, "max": None}
    return {
        "mean": round(statistics.fmean(values), digits),
        "p95": round(percentile(values, 95), digits),
        "max": round(max(values), digits),
    }


def host_fingerprint():
    machine_id = ""
    try:
        machine_id = Path("/etc/machine-id").read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        pass
    value = machine_id or platform.node()
    return hashlib.sha256(
        ("vps-sentinel-benchmark:" + value).encode("utf-8")
    ).hexdigest()[:16]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def service_is_active(name):
    if not name:
        return False
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", name],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def wait_warmup(process, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        time.sleep(min(1.0, max(0.05, deadline - time.monotonic())))
    return process.poll() is None


def terminate(process):
    if process.poll() is not None:
        return False
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    return True


def run_benchmark(args):
    command = shlex.split(args.command)
    if not command:
        raise ValueError("command must not be empty")
    if args.duration < 60:
        raise ValueError("duration must be >= 60")
    if args.warmup < 0:
        raise ValueError("warmup must be >= 0")
    if args.interval < 0.1:
        raise ValueError("interval must be >= 0.1")
    if not args.skip_service_check and service_is_active(args.service):
        raise ValueError(
            f"{args.service} is active; stop it before measuring another Agent"
        )

    environment = dict(os.environ)
    environment.update(load_env(args.env_file))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_path = Path(args.summary) if args.summary else output.with_suffix(
        output.suffix + ".summary.json"
    )

    started_at = utc_timestamp()
    process = subprocess.Popen(
        command,
        env=environment,
        start_new_session=True,
    )
    status = "warming_up"
    terminated_by_harness = False
    rows = 0
    rss_values = []
    cpu_values = []
    measurement_started_at = None
    measurement_ended_at = None
    measurement_started = None
    measurement_elapsed = 0.0
    previous = None
    ticks_per_second = os.sysconf("SC_CLK_TCK")

    try:
        with output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            stream.flush()

            if not wait_warmup(process, args.warmup):
                status = "unexpected_exit_during_warmup"
            else:
                status = "measuring"
                measurement_started = time.monotonic()
                measurement_started_at = utc_timestamp()
                deadline = measurement_started + args.duration
                next_sample = measurement_started
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        status = "unexpected_exit"
                        break
                    now = time.monotonic()
                    if now < next_sample:
                        time.sleep(next_sample - now)
                        continue
                    try:
                        sample = process_sample(process.pid)
                    except (OSError, KeyError, IndexError, ValueError):
                        if process.poll() is not None:
                            status = "unexpected_exit"
                        else:
                            status = "sample_error"
                        break
                    observed = time.monotonic()
                    cpu_percent = 0.0
                    if previous is not None:
                        elapsed = observed - previous["time"]
                        ticks = sample["cpu_ticks"] - previous["cpu_ticks"]
                        cpu_percent = (
                            100 * ticks / ticks_per_second / max(elapsed, 0.001)
                        )
                    row = {
                        "observed_at": utc_timestamp(),
                        "elapsed_seconds": round(
                            observed - measurement_started,
                            3,
                        ),
                        "rss_kib": sample["rss_kib"],
                        "cpu_percent": round(cpu_percent, 3),
                    }
                    writer.writerow(row)
                    stream.flush()
                    rows += 1
                    rss_values.append(row["rss_kib"])
                    if previous is not None:
                        cpu_values.append(row["cpu_percent"])
                    previous = {"time": observed, **sample}
                    next_sample += args.interval
                else:
                    status = "completed"

                if status == "measuring":
                    status = "completed"
                measurement_elapsed = round(
                    time.monotonic() - measurement_started,
                    3,
                )
                measurement_ended_at = utc_timestamp()
            os.chmod(output, 0o600)
    finally:
        terminated_by_harness = terminate(process)

    summary = {
        "schema_version": 1,
        "name": args.name,
        "status": status,
        "measurement_complete": status == "completed",
        "started_at": started_at,
        "measurement_started_at": measurement_started_at,
        "measurement_ended_at": measurement_ended_at,
        "requested_warmup_seconds": args.warmup,
        "requested_duration_seconds": args.duration,
        "actual_measurement_seconds": measurement_elapsed,
        "interval_seconds": args.interval,
        "samples": rows,
        "rss_kib": metric_summary(rss_values),
        "cpu_percent": metric_summary(cpu_values),
        "process_exit_code": process.returncode,
        "terminated_by_harness": terminated_by_harness,
        "raw_csv": str(output),
        "raw_csv_sha256": sha256(output),
        "environment_file_used": bool(args.env_file),
        "host": {
            "fingerprint": host_fingerprint(),
            "os": platform.system(),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "cpu_count": os.cpu_count(),
        },
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = summary_path.with_name(
        f".{summary_path.name}.{os.getpid()}.tmp"
    )
    temporary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, summary_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--duration", type=int, default=86400)
    parser.add_argument("--warmup", type=int, default=1800)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--env-file", default="/etc/vps-monitor.env")
    parser.add_argument("--service", default="vps-monitor")
    parser.add_argument("--skip-service-check", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary")
    return parser.parse_args(argv)


def main(argv=None):
    try:
        summary = run_benchmark(parse_args(argv))
    except ValueError as error:
        raise SystemExit(str(error)) from error
    return 0 if summary["measurement_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
