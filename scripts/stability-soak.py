#!/usr/bin/env python3
"""Collect seven-day systemd stability evidence for a VPS Sentinel Agent."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time


GATE_DURATION_SECONDS = 7 * 24 * 60 * 60
MAX_GATE_INTERVAL_SECONDS = 300
FIELDS = (
    "sampled_at",
    "elapsed_seconds",
    "boot_fingerprint",
    "active_state",
    "sub_state",
    "main_pid",
    "n_restarts",
)


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_machine_identity():
    try:
        value = Path("/etc/machine-id").read_text(
            encoding="utf-8",
        ).strip()
    except OSError:
        value = ""
    return value or platform.node()


def host_fingerprint():
    return hashlib.sha256(
        ("vps-sentinel-beta:" + read_machine_identity()).encode("utf-8")
    ).hexdigest()[:16]


def boot_fingerprint():
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="utf-8",
        ).strip()
    except OSError:
        value = ""
    if not value:
        raise ValueError("cannot read boot ID")
    return hashlib.sha256(
        ("vps-sentinel-soak:" + value).encode("utf-8")
    ).hexdigest()[:16]


def systemd_properties(service):
    command = [
        "systemctl",
        "show",
        service,
        "--property=ActiveState",
        "--property=SubState",
        "--property=MainPID",
        "--property=NRestarts",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"systemctl failed: {type(error).__name__}") from error
    if result.returncode != 0:
        raise ValueError("systemctl show failed")
    values = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    try:
        pid = int(values.get("MainPID", "0"))
        restarts = int(values.get("NRestarts", "-1"))
    except ValueError as error:
        raise ValueError("systemd returned invalid numeric data") from error
    return {
        "boot_fingerprint": boot_fingerprint(),
        "active_state": values.get("ActiveState", ""),
        "sub_state": values.get("SubState", ""),
        "main_pid": pid,
        "n_restarts": restarts,
    }


def snapshot_failure(snapshot, baseline):
    if snapshot["boot_fingerprint"] != baseline["boot_fingerprint"]:
        return "host rebooted during soak"
    if snapshot["active_state"] != "active":
        return f"service is {snapshot['active_state'] or 'unknown'}"
    if snapshot["sub_state"] != "running":
        return f"service sub-state is {snapshot['sub_state'] or 'unknown'}"
    if snapshot["main_pid"] <= 0:
        return "service has no main PID"
    if snapshot["main_pid"] != baseline["main_pid"]:
        return "service main PID changed"
    if snapshot["n_restarts"] != baseline["n_restarts"]:
        return "service restart counter changed"
    return None


def write_json_private(payload, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(target)
    checksum = target.with_suffix(target.suffix + ".sha256")
    checksum.write_text(
        f"{sha256(target)}  {target.name}\n",
        encoding="utf-8",
    )
    checksum.chmod(0o600)
    return target, checksum


def run_soak(args, sampler=systemd_properties):
    output = Path(args.output)
    summary_path = Path(
        args.summary or f"{output}.summary.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    started_at = utc_timestamp()
    started_monotonic = time.monotonic()
    status = "running"
    failure = None
    samples = 0
    baseline = sampler(args.service)

    first_failure = snapshot_failure(baseline, baseline)
    if first_failure:
        raise ValueError(first_failure)

    with output.open("w", encoding="utf-8", newline="") as stream:
        os.chmod(output, 0o600)
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        try:
            while True:
                now = time.monotonic()
                elapsed = now - started_monotonic
                snapshot = sampler(args.service)
                row = {
                    "sampled_at": utc_timestamp(),
                    "elapsed_seconds": round(elapsed, 3),
                    **snapshot,
                }
                writer.writerow(row)
                stream.flush()
                samples += 1
                failure = snapshot_failure(snapshot, baseline)
                if failure:
                    status = "failed"
                    break
                if elapsed >= args.duration:
                    status = "completed"
                    break
                time.sleep(min(args.interval, max(0.01, args.duration - elapsed)))
        except KeyboardInterrupt:
            status = "interrupted"
            failure = "interrupted by operator"
        except (OSError, ValueError) as error:
            status = "failed"
            failure = str(error)

    actual = round(time.monotonic() - started_monotonic, 3)
    qualifies = (
        status == "completed"
        and actual >= args.duration * 0.99
        and args.duration >= GATE_DURATION_SECONDS
        and args.interval <= MAX_GATE_INTERVAL_SECONDS
    )
    summary = {
        "schema_version": 1,
        "name": "python-agent-seven-day-soak",
        "version": args.version,
        "build_ref": args.build_ref,
        "status": status,
        "failure": failure,
        "measurement_complete": status == "completed",
        "qualifies_for_seven_day_gate": qualifies,
        "started_at": started_at,
        "ended_at": utc_timestamp(),
        "requested_duration_seconds": args.duration,
        "actual_measurement_seconds": actual,
        "interval_seconds": args.interval,
        "samples": samples,
        "baseline": baseline,
        "final": snapshot if samples else baseline,
        "raw_csv": os.path.relpath(output, summary_path.parent),
        "raw_csv_sha256": sha256(output),
        "host": {
            "fingerprint": host_fingerprint(),
            "os": platform.system(),
            "kernel": platform.release(),
            "architecture": platform.machine(),
        },
    }
    write_json_private(summary, summary_path)
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="收集 VPS Sentinel Python Agent 七天無重啟穩定性證據"
    )
    parser.add_argument("--service", default="vps-monitor")
    parser.add_argument("--version", required=True)
    parser.add_argument("--build-ref", required=True)
    parser.add_argument("--duration", type=int, default=GATE_DURATION_SECONDS)
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary")
    args = parser.parse_args(argv)
    if args.duration < 60:
        parser.error("--duration must be at least 60 seconds")
    if args.interval < 1 or args.interval > MAX_GATE_INTERVAL_SECONDS:
        parser.error("--interval must be between 1 and 300 seconds")
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        summary = run_soak(args)
    except ValueError as error:
        raise SystemExit(f"FAIL: {error}") from error
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["qualifies_for_seven_day_gate"]:
        print("PASS: seven-day stability gate")
        return 0
    print("INCOMPLETE: summary does not qualify for the seven-day gate")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
