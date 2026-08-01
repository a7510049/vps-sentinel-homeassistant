#!/usr/bin/env python3
"""Compose Controller, Broker ACL and local Agent migration transactions."""

import argparse
import os
from pathlib import Path
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile

CONTROLLER_DIR = Path(__file__).resolve().parent
REPO_ROOT = CONTROLLER_DIR.parent
sys.path.insert(0, str(CONTROLLER_DIR))
sys.path.insert(0, str(REPO_ROOT / "vps-monitor"))

from broker_policy import BrokerFilesTransaction, BrokerPolicy, BrokerPolicyError
from enrollment import EnrollmentError, EnrollmentStore


CONTROLLER_ENV = Path("/etc/vps-sentinel-controller.env")
MONITOR_ENV = Path("/etc/vps-monitor.env")
STORE_PATH = Path("/var/lib/vps-sentinel-controller/enrollments.json")


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


def _quote(value):
    value = str(value)
    if "\n" in value or "\r" in value:
        raise ValueError("environment value contains a newline")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _snapshot(path):
    path = Path(path)
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
    path = Path(path)
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
    path = Path(path)
    if snapshot is None:
        path.unlink(missing_ok=True)
        return
    content, mode, uid, gid = snapshot
    _atomic_write(path, content, mode)
    os.chown(path, uid, gid)


def write_environment(path, values):
    lines = ["# Updated by VPS Sentinel Controller bootstrap."]
    lines.extend(
        f"{key}={_quote(value)}"
        for key, value in sorted(values.items())
    )
    _atomic_write(
        path,
        ("\n".join(lines) + "\n").encode("utf-8"),
        0o600,
    )


def run(command, *, environment=None, timeout=1800):
    return subprocess.run(
        command,
        env=environment,
        timeout=timeout,
        check=False,
    )


def _secure_store_owner():
    if STORE_PATH.exists():
        os.chmod(STORE_PATH, 0o600)
        shutil.chown(
            STORE_PATH,
            user="vps-sentinel-controller",
            group="vps-sentinel-controller",
        )


def _bindings(*pairs):
    result = {}
    for username, node_id in pairs:
        if username and node_id:
            nodes = result.setdefault(username, [])
            if node_id not in nodes:
                nodes.append(node_id)
    return result


def _policy(store, controller_username, bindings):
    return BrokerPolicy(
        store,
        controller_username=controller_username,
        legacy_bindings=bindings,
    ).render_acl()


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

    existing = read_environment(CONTROLLER_ENV)
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

    store_snapshot = _snapshot(STORE_PATH)
    monitor_snapshot = _snapshot(MONITOR_ENV)
    store = EnrollmentStore(STORE_PATH)
    monitor = read_environment(MONITOR_ENV)
    node_id = monitor.get("VPS_ID")
    old_username = monitor.get("MQTT_USERNAME")
    local_enrollment = None
    expected_username = None

    try:
        if node_id:
            expected_username = store.credential_for(node_id)
            if expected_username is None:
                local_enrollment = store.register(
                    node_id,
                    monitor.get("VPS_NAME") or node_id,
                )
                expected_username = local_enrollment.username
            elif old_username != expected_username:
                local_enrollment = store.rotate(node_id)
        _secure_store_owner()
    except (EnrollmentError, OSError) as error:
        _restore(STORE_PATH, store_snapshot)
        raise SystemExit(str(error)) from error

    def restart_services():
        if run(
            ["systemctl", "restart", "mosquitto"],
            timeout=60,
        ).returncode != 0:
            return False
        if run(
            ["systemctl", "restart", "vps-sentinel-controller"],
            timeout=60,
        ).returncode != 0:
            return False
        if run(
            ["systemctl", "is-active", "--quiet", "vps-sentinel-controller"],
            timeout=30,
        ).returncode != 0:
            return False
        if MONITOR_ENV.exists():
            if run(
                ["systemctl", "restart", "vps-monitor"],
                timeout=60,
            ).returncode != 0:
                return False
            if run(
                ["systemctl", "is-active", "--quiet", "vps-monitor"],
                timeout=30,
            ).returncode != 0:
                return False
        return True

    transaction = BrokerFilesTransaction(restarter=restart_services)
    transition_bindings = _bindings(
        (old_username, node_id),
        (expected_username, node_id),
    )
    credentials = {controller_username: controller_password}
    if local_enrollment is not None:
        credentials[local_enrollment.username] = local_enrollment.password

    try:
        transaction.apply(
            credentials=credentials,
            acl_text=_policy(
                store,
                controller_username,
                transition_bindings,
            ),
        )
    except BrokerPolicyError as error:
        _restore(STORE_PATH, store_snapshot)
        _secure_store_owner()
        run(["systemctl", "restart", "vps-sentinel-controller"], timeout=60)
        raise SystemExit(str(error)) from error

    if local_enrollment is not None:
        migrated = dict(monitor)
        migrated.update({
            "MQTT_USERNAME": local_enrollment.username,
            "MQTT_PASSWORD": local_enrollment.password,
            "PUBLISH_V1_CONTRACT": "true",
        })
        try:
            write_environment(MONITOR_ENV, migrated)
            if not restart_services():
                raise RuntimeError("本機 Agent 無法使用 node credential 啟動")
        except Exception as error:
            _restore(MONITOR_ENV, monitor_snapshot)
            _restore(STORE_PATH, store_snapshot)
            _secure_store_owner()
            rollback_store = EnrollmentStore(STORE_PATH)
            rollback_bindings = _bindings((old_username, node_id))
            try:
                transaction.apply(
                    credentials={controller_username: controller_password},
                    remove_usernames=[local_enrollment.username],
                    acl_text=_policy(
                        rollback_store,
                        controller_username,
                        rollback_bindings,
                    ),
                )
            finally:
                restart_services()
            raise SystemExit(str(error)) from error
        old_username = local_enrollment.username

    if node_id and expected_username:
        final_bindings = _bindings((expected_username, node_id))
        obsolete = (
            ["vps-monitor"]
            if expected_username != "vps-monitor"
            else []
        )
        try:
            transaction.apply(
                credentials={controller_username: controller_password},
                remove_usernames=obsolete,
                acl_text=_policy(
                    store,
                    controller_username,
                    final_bindings,
                ),
            )
        except BrokerPolicyError as error:
            raise SystemExit(
                "Agent 已切換成功，但舊 vps-monitor credential "
                f"撤銷失敗，可安全重跑安裝器：{error}"
            ) from error

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
    if node_id:
        print(f"本機 Agent {node_id} 已使用專用 credential 發布 v1 fleet 資料。")
    print("下一步只需在 Home Assistant 註冊 Fleet Card 資源並加入其他 Agent。")


if __name__ == "__main__":
    main()
