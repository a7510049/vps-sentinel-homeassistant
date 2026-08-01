#!/usr/bin/env python3
"""Verify the machine-checkable portion of the VPS Sentinel 1.0 evidence gate."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re


ROOT = Path(__file__).parents[1]
COMPARISON_SPEC = importlib.util.spec_from_file_location(
    "compare_agent_benchmarks",
    ROOT / "benchmarks" / "compare_agent_benchmarks.py",
)
comparison = importlib.util.module_from_spec(COMPARISON_SPEC)
COMPARISON_SPEC.loader.exec_module(comparison)

MINIMUM_AGENT_HOSTS = 3
FINGERPRINT = re.compile(r"^[0-9a-f]{16}$")
DIGEST = re.compile(r"^([0-9a-f]{64})  (.+)$")
ARCHITECTURE_ALIASES = {
    "amd64": "amd64",
    "x86_64": "amd64",
    "arm64": "arm64",
    "aarch64": "arm64",
}


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(path):
    source = Path(path)
    checksum = source.with_suffix(source.suffix + ".sha256")
    try:
        line = checksum.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ValueError(f"{source}: missing checksum file") from error
    match = DIGEST.fullmatch(line)
    if not match or match.group(2) != source.name:
        raise ValueError(f"{checksum}: invalid checksum format")
    if sha256(source) != match.group(1):
        raise ValueError(f"{source}: checksum mismatch")


def load_evidence(path, expected_version, expected_ref):
    source = Path(path)
    verify_checksum(source)
    try:
        report = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{source}: invalid evidence JSON") from error

    if report.get("schema_version") != 1:
        raise ValueError(f"{source}: unsupported evidence schema")
    if report.get("summary", {}).get("result") != "PASS":
        raise ValueError(f"{source}: live evidence did not pass")
    if report.get("summary", {}).get("failed") != 0:
        raise ValueError(f"{source}: evidence contains failed checks")
    if report.get("version") != expected_version:
        raise ValueError(f"{source}: version does not match {expected_version}")
    if report.get("build_ref") != expected_ref:
        raise ValueError(f"{source}: build ref does not match {expected_ref}")

    host = report.get("host", {})
    fingerprint = host.get("fingerprint")
    provider = host.get("provider")
    region = host.get("region")
    raw_architecture = str(host.get("architecture", "")).lower()
    architecture = ARCHITECTURE_ALIASES.get(raw_architecture)
    role = report.get("detected_role")
    if not isinstance(fingerprint, str) or not FINGERPRINT.fullmatch(fingerprint):
        raise ValueError(f"{source}: invalid host fingerprint")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError(f"{source}: provider is required")
    if not isinstance(region, str) or not region.strip():
        raise ValueError(f"{source}: region is required")
    if architecture is None:
        raise ValueError(f"{source}: unsupported architecture {raw_architecture!r}")
    if role not in {"agent", "controller", "combined"}:
        raise ValueError(f"{source}: unsupported role {role!r}")

    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError(f"{source}: checks are missing")
    if any(item.get("status") != "PASS" for item in checks):
        raise ValueError(f"{source}: every live check must pass")

    return {
        "source": str(source),
        "fingerprint": fingerprint,
        "provider": provider.strip(),
        "region": region.strip(),
        "architecture": architecture,
        "role": role,
        "collected_at": report.get("collected_at"),
    }


def verify_inventory(paths, expected_version, expected_ref):
    if len(paths) < MINIMUM_AGENT_HOSTS:
        raise ValueError("at least three host evidence reports are required")
    hosts = [
        load_evidence(path, expected_version, expected_ref)
        for path in paths
    ]
    fingerprints = {item["fingerprint"] for item in hosts}
    if len(fingerprints) != len(hosts):
        raise ValueError("host evidence contains duplicate fingerprints")

    agents = [
        item for item in hosts
        if item["role"] in {"agent", "combined"}
    ]
    controllers = [
        item for item in hosts
        if item["role"] in {"controller", "combined"}
    ]
    if len(agents) < MINIMUM_AGENT_HOSTS:
        raise ValueError("at least three agent-capable hosts are required")
    if not controllers:
        raise ValueError("at least one controller-capable host is required")

    sources = {
        (item["provider"].casefold(), item["region"].casefold())
        for item in agents
    }
    providers = {item["provider"].casefold() for item in agents}
    if len(sources) < MINIMUM_AGENT_HOSTS or len(providers) < MINIMUM_AGENT_HOSTS:
        raise ValueError("three distinct agent providers and regions are required")

    architectures = {item["architecture"] for item in agents}
    if not {"amd64", "arm64"} <= architectures:
        raise ValueError("agent evidence must cover amd64 and arm64")

    return {
        "hosts": len(hosts),
        "agent_capable_hosts": len(agents),
        "controller_capable_hosts": len(controllers),
        "providers": sorted({item["provider"] for item in agents}),
        "regions": sorted({item["region"] for item in agents}),
        "architectures": sorted(architectures),
        "reports": hosts,
    }


def load_soak(path, expected_version, expected_ref):
    source = Path(path)
    verify_checksum(source)
    try:
        summary = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{source}: invalid soak JSON") from error
    if summary.get("name") != "python-agent-seven-day-soak":
        raise ValueError(f"{source}: unsupported soak type")
    if summary.get("version") != expected_version:
        raise ValueError(f"{source}: soak version does not match")
    if summary.get("build_ref") != expected_ref:
        raise ValueError(f"{source}: soak build ref does not match")
    if summary.get("status") != "completed":
        raise ValueError(f"{source}: soak did not complete")
    if not summary.get("qualifies_for_seven_day_gate"):
        raise ValueError(f"{source}: soak does not qualify for seven-day gate")
    requested = summary.get("requested_duration_seconds")
    actual = summary.get("actual_measurement_seconds")
    interval = summary.get("interval_seconds")
    if (
        not isinstance(requested, (int, float))
        or requested < 604800
        or not isinstance(actual, (int, float))
        or actual < requested * 0.99
        or not isinstance(interval, (int, float))
        or interval > 300
    ):
        raise ValueError(f"{source}: invalid seven-day timing")

    baseline = summary.get("baseline", {})
    final = summary.get("final", {})
    for key in ("boot_fingerprint", "main_pid", "n_restarts"):
        if baseline.get(key) != final.get(key):
            raise ValueError(f"{source}: unstable {key}")
    if final.get("active_state") != "active" or final.get("sub_state") != "running":
        raise ValueError(f"{source}: service was not running at completion")

    fingerprint = summary.get("host", {}).get("fingerprint")
    if not isinstance(fingerprint, str) or not FINGERPRINT.fullmatch(fingerprint):
        raise ValueError(f"{source}: invalid soak host fingerprint")
    artifact = summary.get("raw_csv")
    digest = summary.get("raw_csv_sha256")
    if not isinstance(artifact, str) or not isinstance(digest, str):
        raise ValueError(f"{source}: soak CSV integrity data is missing")
    target = Path(artifact)
    if not target.is_absolute():
        target = source.parent / target
    if not target.is_file() or sha256(target) != digest:
        raise ValueError(f"{source}: soak CSV is missing or changed")
    return {
        "source": str(source),
        "fingerprint": fingerprint,
        "samples": summary.get("samples"),
        "actual_measurement_seconds": actual,
    }


def verify_soaks(paths, inventory, expected_version, expected_ref):
    soaks = [
        load_soak(path, expected_version, expected_ref)
        for path in paths
    ]
    fingerprints = {item["fingerprint"] for item in soaks}
    if len(fingerprints) != len(soaks):
        raise ValueError("soak evidence contains duplicate hosts")
    agent_fingerprints = {
        item["fingerprint"]
        for item in inventory["reports"]
        if item["role"] in {"agent", "combined"}
    }
    if fingerprints != agent_fingerprints:
        raise ValueError("every agent evidence host needs one seven-day soak")
    return {
        "hosts": len(soaks),
        "minimum_duration_seconds": min(
            item["actual_measurement_seconds"] for item in soaks
        ),
        "summaries": soaks,
    }


def verify_benchmarks(python_paths, go_paths, expected_version, expected_ref):
    report = comparison.compare(python_paths, go_paths)
    if report.get("version") != expected_version:
        raise ValueError("benchmark version does not match evidence")
    if report.get("build_ref") != expected_ref:
        raise ValueError("benchmark build ref does not match evidence")
    return report


def verify(
    evidence_paths, soak_paths, python_paths, go_paths,
    expected_version, expected_ref,
):
    inventory = verify_inventory(
        evidence_paths,
        expected_version,
        expected_ref,
    )
    stability = verify_soaks(
        soak_paths,
        inventory,
        expected_version,
        expected_ref,
    )
    benchmark = verify_benchmarks(
        python_paths,
        go_paths,
        expected_version,
        expected_ref,
    )
    return {
        "schema_version": 1,
        "generated_at": utc_timestamp(),
        "expected_version": expected_version,
        "expected_build_ref": expected_ref,
        "result": "AUTOMATED_EVIDENCE_PASS",
        "inventory": inventory,
        "stability": stability,
        "benchmark": {
            "host_fingerprint": benchmark["host_fingerprint"],
            "architecture": benchmark["architecture"],
            "python_runs": benchmark["python"]["runs"],
            "go_runs": benchmark["go"]["runs"],
            "rss_30_percent_gate": benchmark["comparison"][
                "rss_30_percent_gate"
            ],
            "resource_recommendation": benchmark[
                "resource_recommendation"
            ],
            "final_decision": benchmark["final_decision"],
        },
        "remaining_manual_gates": [
            "fleet_ui",
            "network_and_broker_recovery",
            "credential_rotation_and_revocation",
            "role_aware_upgrade_restore",
        ],
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
    checksum = path.with_suffix(path.suffix + ".sha256")
    checksum.write_text(
        f"{sha256(path)}  {path.name}\n",
        encoding="utf-8",
    )
    checksum.chmod(0o600)
    return path, checksum


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="驗證 VPS Sentinel 1.0 可機器判讀的實機證據套件"
    )
    parser.add_argument("--evidence", nargs="+", required=True)
    parser.add_argument("--soak", nargs="+", required=True)
    parser.add_argument("--python", nargs="+", required=True)
    parser.add_argument("--go", nargs="+", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-ref", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        report = verify(
            args.evidence,
            args.soak,
            args.python,
            args.go,
            args.expected_version,
            args.expected_ref,
        )
    except ValueError as error:
        raise SystemExit(f"FAIL: {error}") from error
    path, checksum = write_report(report, args.output)
    print(f"PASS: {path}")
    print(f"SHA-256: {checksum}")
    print("仍需完成 #65 的人工實機 Gate，這份報告不代表可直接發布。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
