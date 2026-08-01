#!/usr/bin/env python3
"""Sample CPU and RSS for one Agent command without running agents together."""

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
import time


def process_sample(pid):
    status = {}
    for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            status[key] = value.strip()
    stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
    return {
        "rss_kib": int(status["VmRSS"].split()[0]),
        "cpu_ticks": int(stat[13]) + int(stat[14]),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--duration", type=int, default=86400)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.duration < 60 or args.interval < 0.1:
        raise SystemExit("duration must be >= 60 and interval >= 0.1")
    command = shlex.split(args.command)
    started = time.monotonic()
    process = subprocess.Popen(command)
    rows = []
    previous = None
    try:
        while process.poll() is None and time.monotonic() - started < args.duration:
            sample = process_sample(process.pid)
            now = time.monotonic()
            cpu_percent = 0.0
            if previous:
                elapsed = now - previous["time"]
                ticks = sample["cpu_ticks"] - previous["cpu_ticks"]
                cpu_percent = 100 * ticks / max(1, int(Path("/proc/sys/kernel/hz").read_text()) if Path("/proc/sys/kernel/hz").exists() else 100) / elapsed
            rows.append({
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(now - started, 3),
                "rss_kib": sample["rss_kib"],
                "cpu_percent": round(cpu_percent, 3),
            })
            previous = {"time": now, **sample}
            time.sleep(args.interval)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "name": args.name,
        "command": command,
        "duration_seconds": round(time.monotonic() - started, 3),
        "samples": len(rows),
        "exit_code": process.returncode,
        "raw_csv": str(output),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
