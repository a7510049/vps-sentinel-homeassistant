#!/usr/bin/env python3
"""Compose Controller component installation with the recoverable Broker transaction."""

import argparse
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import sys

CONTROLLER_DIR = Path(__file__).resolve().parent
REPO_ROOT = CONTROLLER_DIR.parent
sys.path.insert(0, str(CONTROLLER_DIR))
sys.path.insert(0, str(REPO_ROOT / "vps-monitor"))

from broker_policy import BrokerFilesTransaction, BrokerPolicy, BrokerPolicyError
from enrollment import EnrollmentStore


def read_environment(path):
    values = {}
    path = Path(path)
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        try:
            parsed = shlex.split(value, posix=True)
        except ValueError as error:
            raise SystemExit(f"無法解析 {path} 中的 {key}") from error
        values[key] = parsed[0] if parsed else ""
    return values


def run(command, *, environment=None, timeout=1800):
    return subprocess.run(
        command,
        env=environment,
        timeout=timeout,
        check=False,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()
    if os.geteuid() != 0:
        raise SystemExit("Controller bootstrap 需要 root 權限")

    component = repo_root / "controller" / "install-component.sh"
    if not component.is_file():
        raise SystemExit("找不到 Controller 元件安裝器")

    controller_env_path = Path("/etc/vps-sentinel-controller.env")
    existing = read_environment(controller_env_path)
    controller_password = existing.get("MQTT_PASSWORD") or secrets.token_urlsafe(32)
    controller_username = existing.get("MQTT_USERNAME") or "vps-controller"

    component_environment = os.environ.copy()
    component_environment.update({
        "CONTROLLER_MQTT_HOST": existing.get("MQTT_HOST", "127.0.0.1"),
        "CONTROLLER_MQTT_PORT": existing.get("MQTT_PORT", "1883"),
        "CONTROLLER_MQTT_USERNAME": controller_username,
        "CONTROLLER_MQTT_PASSWORD": controller_password,
        "CONTROLLER_MQTT_TLS": existing.get("MQTT_TLS", "false"),
        "CONTROLLER_MQTT_CA_FILE": existing.get("MQTT_CA_FILE", ""),
        "CONTROLLER_DISCOVERY_PREFIX": existing.get(
            "DISCOVERY_PREFIX",
            "homeassistant",
        ),
        "CONTROLLER_START": "false",
    })
    installed = run(
        ["bash", str(component)],
        environment=component_environment,
    )
    if installed.returncode != 0:
        raise SystemExit("Controller 元件部署失敗，尚未修改 Broker 權限")

    enrollments = EnrollmentStore(
        "/var/lib/vps-sentinel-controller/enrollments.json"
    )
    monitor = read_environment("/etc/vps-monitor.env")
    legacy_bindings = {}
    if monitor.get("VPS_ID") and monitor.get("MQTT_USERNAME"):
        legacy_bindings[monitor["MQTT_USERNAME"]] = [monitor["VPS_ID"]]
    policy = BrokerPolicy(
        enrollments,
        controller_username=controller_username,
        legacy_bindings=legacy_bindings,
    )

    def restart_services():
        mosquitto = run(
            ["systemctl", "restart", "mosquitto"],
            timeout=60,
        )
        if mosquitto.returncode != 0:
            return False
        controller = run(
            ["systemctl", "restart", "vps-sentinel-controller"],
            timeout=60,
        )
        if controller.returncode != 0:
            return False
        active = run(
            ["systemctl", "is-active", "--quiet", "vps-sentinel-controller"],
            timeout=30,
        )
        return active.returncode == 0

    transaction = BrokerFilesTransaction(restarter=restart_services)
    try:
        transaction.apply(
            credentials={controller_username: controller_password},
            acl_text=policy.render_acl(),
        )
    except BrokerPolicyError as error:
        raise SystemExit(str(error)) from error

    card_source = (
        repo_root
        / "home-assistant"
        / "www"
        / "vps-sentinel-fleet-card.js"
    )
    card_target = Path(
        "/opt/homeassistant/config/www/vps-sentinel-fleet-card.js"
    )
    if card_source.is_file() and card_target.parent.exists():
        card_target.parent.mkdir(parents=True, exist_ok=True)
        temporary = card_target.with_name(f".{card_target.name}.new")
        temporary.write_bytes(card_source.read_bytes())
        os.chmod(temporary, 0o644)
        os.replace(temporary, card_target)

    print("Controller、Mosquitto ACL 與 Fleet Card 已完成部署。")
    print("下一步只需在 Home Assistant 註冊 Fleet Card 資源並加入 Agent。")


if __name__ == "__main__":
    main()
