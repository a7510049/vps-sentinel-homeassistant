#!/usr/bin/env python3
"""Consume one Agent enrollment bundle and install without interactive secrets."""

import argparse
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

CONTROLLER_DIR = Path(__file__).resolve().parent
REPO_ROOT = CONTROLLER_DIR.parent
sys.path.insert(0, str(CONTROLLER_DIR))
sys.path.insert(0, str(REPO_ROOT / "vps-monitor"))

from enrollment_bundle import BundleError, load_bundle


ENV_PATH = Path("/etc/vps-monitor.env")
CA_PATH = Path("/etc/vps-sentinel-agent-ca.crt")


def _snapshot(path):
    if not path.exists():
        return None
    metadata = path.stat()
    return (
        path.read_bytes(),
        stat.S_IMODE(metadata.st_mode),
        metadata.st_uid,
        metadata.st_gid,
    )


def _atomic_write(path, content, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        os.chmod(path, mode)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _restore(path, snapshot):
    if snapshot is None:
        path.unlink(missing_ok=True)
        return
    content, mode, uid, gid = snapshot
    _atomic_write(path, content, mode)
    os.chown(path, uid, gid)


def _quote(value):
    value = str(value)
    if "\n" in value or "\r" in value:
        raise BundleError("environment value contains a newline")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _environment(bundle):
    mqtt = bundle["mqtt"]
    node = bundle["node"]
    monitor = bundle["monitor"]
    values = {
        "MQTT_HOST": mqtt["host"],
        "MQTT_PORT": mqtt["port"],
        "MQTT_USERNAME": mqtt["username"],
        "MQTT_PASSWORD": mqtt["password"],
        "MQTT_TLS": str(mqtt["tls"]).lower(),
        "MQTT_CA_FILE": str(CA_PATH) if mqtt["tls"] else "",
        "VPS_ID": node["id"],
        "VPS_NAME": node["display_name"],
        "PUBLISH_INTERVAL": monitor["publish_interval"],
        "HEALTH_CHECK_INTERVAL": monitor["health_check_interval"],
        "UPDATE_CHECK_INTERVAL": monitor["update_check_interval"],
        "MONITOR_NETWORK": str(monitor["monitor_network"]).lower(),
        "DISCOVERY_PREFIX": "homeassistant",
        "CPU_WARN_PERCENT": 90,
        "MEMORY_WARN_PERCENT": 90,
        "DISK_WARN_PERCENT": 85,
        "OVERLOAD_SAMPLES": 20,
        "WATCH_SERVICES": "ssh",
        "ALLOW_REMOTE_ACTIONS": str(
            monitor["allow_remote_actions"]
        ).lower(),
        "COMMAND_COOLDOWN": 300,
        "PUBLISH_V1_CONTRACT": "true",
    }
    lines = ["# Generated from a one-time VPS Sentinel enrollment bundle."]
    lines.extend(f"{key}={_quote(value)}" for key, value in values.items())
    return ("\n".join(lines) + "\n").encode("utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Agent enrollment 需要 root 權限")

    bundle_path = Path(args.bundle).resolve()
    metadata = bundle_path.stat()
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise SystemExit("Enrollment bundle 權限過寬，必須為 0600")
    try:
        bundle = load_bundle(bundle_path)
    except BundleError as error:
        raise SystemExit(str(error)) from error

    repo_root = Path(args.repo_root).resolve()
    installer = repo_root / "vps-monitor" / "install.sh"
    if not installer.is_file():
        raise SystemExit("找不到 Agent 元件安裝器")

    snapshots = {
        ENV_PATH: _snapshot(ENV_PATH),
        CA_PATH: _snapshot(CA_PATH),
    }
    service_existed = Path(
        "/etc/systemd/system/vps-monitor.service"
    ).exists()
    try:
        _atomic_write(ENV_PATH, _environment(bundle), 0o600)
        if bundle["mqtt"]["tls"]:
            _atomic_write(
                CA_PATH,
                bundle["mqtt"]["ca_certificate"].encode("utf-8"),
                0o644,
            )
        environment = os.environ.copy()
        environment["VPS_SENTINEL_NONINTERACTIVE"] = "true"
        installed = subprocess.run(
            ["bash", str(installer)],
            env=environment,
            timeout=1800,
            check=False,
        )
        if installed.returncode != 0:
            raise BundleError("Agent 安裝或端到端驗證失敗")
    except Exception as error:
        for path, snapshot in snapshots.items():
            _restore(path, snapshot)
        if service_existed:
            subprocess.run(
                ["systemctl", "restart", "vps-monitor"],
                timeout=60,
                check=False,
            )
        raise SystemExit(str(error)) from error

    bundle_path.unlink()
    print("Agent 已加入 Controller；一次性 enrollment bundle 已安全刪除。")


if __name__ == "__main__":
    main()
