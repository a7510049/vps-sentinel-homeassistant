#!/usr/bin/env python3
"""Create, seal, and verify the manual VPS Sentinel 1.0 acceptance manifest."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re


SCHEMA_VERSION = 1
DIGEST = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_KINDS = {"csv", "json", "log", "screenshot", "text", "video"}
GATES = {
    "install_combined": ("combined",),
    "install_controller": ("controller",),
    "enroll_three_agents": ("agent_a", "agent_b", "agent_c"),
    "reinstall_idempotency": ("node_id", "credential", "service"),
    "fleet_auto_load": ("mobile", "desktop"),
    "fleet_isolation": ("three_nodes", "no_cross_talk"),
    "metric_accuracy": ("cpu", "memory", "disk", "load"),
    "fleet_filters_sort": ("search", "attention", "offline", "priority"),
    "ui_responsive_accessibility": (
        "mobile", "desktop", "dark", "light", "keyboard", "reduced_motion",
    ),
    "agent_network_recovery": ("offline", "recovered"),
    "broker_restart_recovery": ("controller_recovered", "agents_recovered"),
    "controller_restart_recovery": ("fleet_rebuilt",),
    "credential_rotation": ("old_rejected", "new_accepted"),
    "credential_revocation": ("revoked_rejected",),
    "topic_acl_isolation": ("cross_topic_rejected",),
    "combined_upgrade_098": ("node_id", "ha_entities", "settings"),
    "agent_upgrade_rollback": (
        "failure_injected", "automatic_rollback", "service_healthy",
    ),
    "controller_upgrade_rollback": (
        "failure_injected", "automatic_rollback", "service_healthy",
    ),
    "combined_upgrade_rollback": (
        "failure_injected", "automatic_rollback", "service_healthy",
    ),
    "agent_backup_restore": ("no_fake_ha_directory", "service_healthy"),
    "controller_combined_backup": (
        "enrollment", "acl", "controller_env", "fleet_card",
    ),
    "restore_validation_rollback": (
        "validation_failed", "safety_backup_restored", "service_healthy",
    ),
    "go_functional_comparison": (
        "contract", "packet", "disconnect_recovery", "feature_gaps",
    ),
    "agent_decision_adr": ("adr_updated", "decision_recorded"),
}


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_path(path):
    target = Path(path)
    return target.with_suffix(target.suffix + ".sha256")


def seal(path):
    target = Path(path)
    try:
        json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{target}: invalid manifest JSON") from error
    target.chmod(0o600)
    checksum = checksum_path(target)
    checksum.write_text(
        f"{sha256(target)}  {target.name}\n",
        encoding="utf-8",
    )
    checksum.chmod(0o600)
    return checksum


def verify_checksum(path):
    target = Path(path)
    checksum = checksum_path(target)
    try:
        parts = checksum.read_text(encoding="utf-8").strip().split("  ", 1)
    except OSError as error:
        raise ValueError(f"{target}: missing manifest checksum") from error
    if (
        len(parts) != 2
        or not DIGEST.fullmatch(parts[0])
        or parts[1] != target.name
        or sha256(target) != parts[0]
    ):
        raise ValueError(f"{target}: manifest checksum mismatch")


def parse_timestamp(value, field):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} is not ISO-8601") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def template(version, build_ref, operator):
    return {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "build_ref": build_ref,
        "operator": operator,
        "created_at": utc_timestamp(),
        "gates": [
            {
                "id": gate_id,
                "result": "PENDING",
                "started_at": None,
                "ended_at": None,
                "command": "",
                "coverage": list(required),
                "evidence": [],
                "notes": "",
            }
            for gate_id, required in GATES.items()
        ],
    }


def write_private(payload, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(target)
    return target


def resolve_artifact(bundle_root, relative, gate_id):
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"{gate_id}: evidence path is required")
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ValueError(f"{gate_id}: absolute evidence paths are forbidden")
    root = bundle_root.resolve()
    target = (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{gate_id}: evidence path escapes the bundle") from error
    if not target.is_file() or target.stat().st_size == 0:
        raise ValueError(f"{gate_id}: evidence file is missing or empty")
    return target


def verify_artifacts(gate, bundle_root):
    gate_id = gate["id"]
    artifacts = gate.get("evidence")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError(f"{gate_id}: at least one evidence artifact is required")
    seen = set()
    verified = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError(f"{gate_id}: evidence entry must be an object")
        label = artifact.get("label")
        kind = artifact.get("kind")
        relative = artifact.get("path")
        expected = artifact.get("sha256")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"{gate_id}: evidence label is required")
        if kind not in ALLOWED_KINDS:
            raise ValueError(f"{gate_id}: unsupported evidence kind")
        if relative in seen:
            raise ValueError(f"{gate_id}: duplicate evidence path")
        seen.add(relative)
        if not isinstance(expected, str) or not DIGEST.fullmatch(expected):
            raise ValueError(f"{gate_id}: invalid evidence SHA-256")
        target = resolve_artifact(bundle_root, relative, gate_id)
        if sha256(target) != expected:
            raise ValueError(f"{gate_id}: evidence checksum mismatch")
        verified.append({
            "label": label.strip(),
            "kind": kind,
            "path": relative,
            "sha256": expected,
        })
    return verified


def verify_manifest(path, expected_version, expected_ref):
    source = Path(path)
    verify_checksum(source)
    try:
        manifest = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{source}: invalid manifest JSON") from error
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported attestation schema")
    if manifest.get("version") != expected_version:
        raise ValueError("attestation version does not match")
    if manifest.get("build_ref") != expected_ref:
        raise ValueError("attestation build ref does not match")
    operator = manifest.get("operator")
    if not isinstance(operator, str) or not operator.strip():
        raise ValueError("attestation operator is required")
    parse_timestamp(manifest.get("created_at"), "created_at")

    gates = manifest.get("gates")
    if not isinstance(gates, list):
        raise ValueError("attestation gates must be a list")
    identifiers = [item.get("id") for item in gates if isinstance(item, dict)]
    if len(identifiers) != len(gates) or len(set(identifiers)) != len(gates):
        raise ValueError("attestation contains invalid or duplicate gate IDs")
    missing = sorted(set(GATES) - set(identifiers))
    extra = sorted(set(identifiers) - set(GATES))
    if missing or extra:
        raise ValueError(
            f"attestation gate set mismatch; missing={missing}, extra={extra}"
        )

    verified_gates = []
    artifact_count = 0
    for gate in gates:
        gate_id = gate["id"]
        if gate.get("result") != "PASS":
            raise ValueError(f"{gate_id}: result must be PASS")
        started = parse_timestamp(gate.get("started_at"), f"{gate_id}.started_at")
        ended = parse_timestamp(gate.get("ended_at"), f"{gate_id}.ended_at")
        if ended < started:
            raise ValueError(f"{gate_id}: ended_at precedes started_at")
        command = gate.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError(f"{gate_id}: command is required")
        coverage = gate.get("coverage")
        if not isinstance(coverage, list) or len(set(coverage)) != len(coverage):
            raise ValueError(f"{gate_id}: coverage must be a unique list")
        missing_coverage = sorted(set(GATES[gate_id]) - set(coverage))
        if missing_coverage:
            raise ValueError(
                f"{gate_id}: missing coverage {missing_coverage}"
            )
        artifacts = verify_artifacts(gate, source.parent)
        artifact_count += len(artifacts)
        verified_gates.append({
            "id": gate_id,
            "started_at": gate["started_at"],
            "ended_at": gate["ended_at"],
            "coverage": coverage,
            "artifact_count": len(artifacts),
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "verified_at": utc_timestamp(),
        "version": expected_version,
        "build_ref": expected_ref,
        "operator": operator.strip(),
        "result": "MANUAL_ACCEPTANCE_PASS",
        "gate_count": len(verified_gates),
        "artifact_count": artifact_count,
        "gates": verified_gates,
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="建立、封存或驗證 VPS Sentinel 1.0 實機驗收 manifest"
    )
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    initialize = subparsers.add_parser("init")
    initialize.add_argument("--version", required=True)
    initialize.add_argument("--build-ref", required=True)
    initialize.add_argument("--operator", required=True)
    initialize.add_argument("--output", required=True)

    seal_parser = subparsers.add_parser("seal")
    seal_parser.add_argument("manifest")

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("manifest")
    verify_parser.add_argument("--expected-version", required=True)
    verify_parser.add_argument("--expected-ref", required=True)
    verify_parser.add_argument("--output")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.command_name == "init":
            path = write_private(
                template(args.version, args.build_ref, args.operator),
                args.output,
            )
            checksum = seal(path)
            print(f"範本：{path}")
            print(f"編輯完成後執行：python3 {__file__} seal {path}")
            return 0
        if args.command_name == "seal":
            checksum = seal(args.manifest)
            print(f"SHA-256：{checksum}")
            return 0
        report = verify_manifest(
            args.manifest,
            args.expected_version,
            args.expected_ref,
        )
    except ValueError as error:
        raise SystemExit(f"FAIL: {error}") from error

    if args.output:
        path = write_private(report, args.output)
        checksum = seal(path)
        print(f"PASS：{path}")
        print(f"SHA-256：{checksum}")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
