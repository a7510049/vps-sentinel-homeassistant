#!/usr/bin/env python3
"""Validate deployment configs and produce role-aware preflight reports."""

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


INSTALL_VERSION = 1
ROLES = {"combined", "controller"}
PROFILES = {"efficient", "balanced", "realtime"}


class InstallConfigError(ValueError):
    """Raised when a deployment config is invalid."""


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InstallConfigError(f"{field} is invalid")
    if any(ord(character) < 32 for character in value):
        raise InstallConfigError(f"{field} contains control characters")
    return value


def load_install_config(path):
    target = Path(path)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InstallConfigError("install config cannot be read") from error
    if not isinstance(value, dict):
        raise InstallConfigError("install config must be an object")

    if value.get("role") == "agent" and value.get("bundle_version") == 1:
        return {"kind": "agent", "role": "agent"}

    role = value.get("role")
    expected = {"install_version", "role"}
    if role == "combined":
        expected.add("node")
    if set(value) != expected:
        raise InstallConfigError("install config fields do not match version 1")
    if value.get("install_version") != INSTALL_VERSION or role not in ROLES:
        raise InstallConfigError("unsupported install config")
    result = {"kind": "deployment", "role": role}
    if role == "combined":
        node = value["node"]
        if not isinstance(node, dict) or set(node) != {
            "id",
            "display_name",
            "profile",
        }:
            raise InstallConfigError("node fields are invalid")
        node_id = _text(node["id"], "node.id", 64)
        if not all(
            character.islower()
            or character.isdigit()
            or character in "_-"
            for character in node_id
        ) or not node_id[0].isalnum():
            raise InstallConfigError("node.id is invalid")
        profile = node["profile"]
        if profile not in PROFILES:
            raise InstallConfigError("node.profile is invalid")
        result.update({
            "node_id": node_id,
            "node_name": _text(node["display_name"], "node.display_name", 80),
            "profile": profile,
        })
    return result


def _memory_mb():
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def preflight(role):
    checks = []
    os_id = "unknown"
    version = ""
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"')
            if key == "ID":
                os_id = value
            elif key == "VERSION_ID":
                version = value
    except OSError:
        pass
    supported = (os_id, version) in {
        ("ubuntu", "22.04"),
        ("ubuntu", "24.04"),
        ("debian", "12"),
        ("debian", "13"),
    }
    checks.append({
        "name": "operating_system",
        "ok": supported,
        "detail": f"{os_id} {version}".strip(),
    })
    memory = _memory_mb()
    checks.append({
        "name": "memory",
        "ok": memory >= 900,
        "detail": f"{memory} MiB",
    })
    free_mb = shutil.disk_usage("/").free // 1024 // 1024
    checks.append({
        "name": "disk",
        "ok": free_mb >= 4096,
        "detail": f"{free_mb} MiB free",
    })
    tailscale_ok = False
    if shutil.which("tailscale"):
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        tailscale_ok = result.returncode == 0 and bool(result.stdout.strip())
    checks.append({
        "name": "tailscale_session",
        "ok": tailscale_ok,
        "detail": "connected" if tailscale_ok else "login required",
    })
    return {
        "preflight_version": 1,
        "role": role,
        "architecture": platform.machine(),
        "ok": all(check["ok"] for check in checks),
        "checks": checks,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument(
        "--field",
        choices=["kind", "role", "node_id", "node_name", "profile"],
    )
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    try:
        config = load_install_config(args.config)
    except InstallConfigError as error:
        raise SystemExit(str(error)) from error
    if args.preflight:
        report = preflight(config["role"])
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report["ok"] else 1)
    if args.field:
        print(config.get(args.field, ""))
    else:
        print(json.dumps(config, ensure_ascii=False))


if __name__ == "__main__":
    main()
