#!/usr/bin/env python3
"""Collect a secret-free VPS Sentinel 1.0 Beta evidence report."""

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time


SCHEMA_VERSION = 1
COLLECTOR_VERSION = "1.0.0-alpha.2"
AGENT_ENV = "/etc/vps-monitor.env"
CONTROLLER_ENV = "/etc/vps-sentinel-controller.env"
COMPONENT_PATHS = {
    "agent": AGENT_ENV,
    "controller": CONTROLLER_ENV,
    "home_assistant": "/opt/homeassistant/compose.yaml",
    "home_assistant_legacy": "/opt/homeassistant/docker-compose.yml",
    "broker_config": "/etc/mosquitto/conf.d/home-assistant.conf",
    "broker_acl": "/etc/mosquitto/vps-sentinel.acl",
}
def utc_timestamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def rooted(root, path):
    return Path(root) / path.lstrip("/")


def read_text(path, default=""):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return default


def read_env(path):
    values = {}
    for raw_line in read_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def detected_components(root):
    present = {
        name: rooted(root, path).exists()
        for name, path in COMPONENT_PATHS.items()
    }
    return {
        "agent": present["agent"],
        "controller": present["controller"],
        "home_assistant": (
            present["home_assistant"] or present["home_assistant_legacy"]
        ),
        "broker": present["broker_config"] or present["broker_acl"],
    }


def detected_role(components):
    if components["agent"] and components["controller"]:
        return "combined"
    if components["controller"]:
        return "controller"
    if components["agent"]:
        return "agent"
    return "unknown"


def host_secret(root):
    value = read_text(rooted(root, "/etc/machine-id")).strip()
    return value or platform.node()


def host_fingerprint(root):
    return hashlib.sha256(
        ("vps-sentinel-beta:" + host_secret(root)).encode("utf-8")
    ).hexdigest()[:16]


def identity_fingerprint(root, value):
    return hmac.new(
        host_secret(root).encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:12]


def os_name(root):
    values = read_env(rooted(root, "/etc/os-release"))
    return values.get("PRETTY_NAME") or values.get("NAME") or "Linux"


def memory_mib(root):
    for line in read_text(rooted(root, "/proc/meminfo")).splitlines():
        if line.startswith("MemTotal:"):
            try:
                return round(int(line.split()[1]) / 1024)
            except (IndexError, ValueError):
                break
    return None


def installed_version(root):
    for path in (
        "/opt/vps-monitor/.version",
        "/opt/vps-sentinel-controller/.version",
    ):
        value = read_text(rooted(root, path)).strip()
        if value:
            return value
    return "unknown"


def command_result(command, timeout=20):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, type(error).__name__
    return result.returncode == 0, (result.stdout or result.stderr).strip()[:200]


def service_active(name):
    ok, _detail = command_result(["systemctl", "is-active", "--quiet", name])
    return ok


def file_check(root, path, expected_modes):
    target = rooted(root, path)
    if not target.is_file():
        return False, "missing"
    mode = target.stat().st_mode & 0o777
    if mode not in expected_modes:
        return False, f"mode {mode:o}"
    return True, f"mode {mode:o}"


def ensure_mqtt_dependency():
    try:
        available = importlib.util.find_spec("paho.mqtt.client") is not None
    except ModuleNotFoundError:
        available = False
    if available:
        return
    if os.environ.get("VPS_SENTINEL_EVIDENCE_REEXEC") == "1":
        return
    for candidate in (
        "/opt/vps-monitor/venv/bin/python",
        "/opt/vps-sentinel-controller/venv/bin/python",
    ):
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            environment = dict(os.environ)
            environment["VPS_SENTINEL_EVIDENCE_REEXEC"] = "1"
            os.execve(candidate, [candidate, __file__, *sys.argv[1:]], environment)


def mqtt_probe(environment, topics, accept, timeout=12):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        return False, {"reason": "paho-mqtt unavailable"}

    host = environment.get("MQTT_HOST")
    username = environment.get("MQTT_USERNAME")
    password = environment.get("MQTT_PASSWORD")
    try:
        port = int(environment.get("MQTT_PORT", "1883"))
    except ValueError:
        return False, {"reason": "invalid MQTT_PORT"}
    if not host or not username or password is None:
        return False, {"reason": "incomplete MQTT settings"}

    connected = threading.Event()
    received = threading.Event()
    result = {"reason": "timeout"}

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"vps-sentinel-evidence-{os.getpid()}",
        clean_session=True,
    )
    client.username_pw_set(username, password)

    def on_connect(mqtt_client, _userdata, _flags, reason_code, _properties):
        if reason_code != 0:
            result["reason"] = f"CONNACK {reason_code.value}"
            connected.set()
            received.set()
            return
        for topic in topics:
            mqtt_client.subscribe(topic, qos=1)
        result["reason"] = "connected"
        connected.set()

    def on_message(_client, _userdata, message):
        try:
            accepted = accept(message.topic, message.payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return
        if accepted is not None:
            result.clear()
            result.update(accepted)
            received.set()

    client.on_connect = on_connect
    client.on_message = on_message
    if environment.get("MQTT_TLS", "false").lower() in {"1", "true", "yes"}:
        client.tls_set(ca_certs=environment.get("MQTT_CA_FILE") or None)
    try:
        client.connect(host, port, 30)
        client.loop_start()
        if not connected.wait(timeout):
            return False, {"reason": "connection timeout"}
        if not received.wait(timeout):
            return False, result
        return "reason" not in result, result
    except OSError as error:
        return False, {"reason": type(error).__name__}
    finally:
        try:
            client.disconnect()
            client.loop_stop()
        except RuntimeError:
            pass


def agent_probe(root):
    environment = read_env(rooted(root, AGENT_ENV))
    node_id = environment.get("VPS_ID")
    if not node_id:
        return False, {"reason": "VPS_ID missing"}

    topics = [
        f"vps/{node_id}/online",
        f"vps-sentinel/v1/nodes/{node_id}/availability",
    ]

    def accept(topic, payload):
        if topic.endswith("/online") and payload.decode("utf-8") == "ON":
            return {"stream": "legacy", "status": "online"}
        candidate = json.loads(payload)
        if candidate.get("data", {}).get("status") == "online":
            return {"stream": "v1", "status": "online"}
        return None

    return mqtt_probe(environment, topics, accept)


def controller_probe(root):
    environment = read_env(rooted(root, CONTROLLER_ENV))
    topic = environment.get(
        "CONTROLLER_FLEET_TOPIC",
        "vps-sentinel/v1/controller/fleet",
    )

    def accept(_topic, payload):
        candidate = json.loads(payload)
        if candidate.get("schema_version") != "1.0":
            return None
        node_hashes = sorted(
            identity_fingerprint(
                root,
                item.get("node", {}).get("id", ""),
            )
            for item in candidate.get("nodes", [])
            if item.get("node", {}).get("id")
        )
        return {
            "schema_version": "1.0",
            "node_count": candidate.get("node_count"),
            "online_count": candidate.get("online_count"),
            "problem_count": candidate.get("problem_count"),
            "node_fingerprints": node_hashes,
        }

    return mqtt_probe(environment, [topic], accept)


def collect(\n    root="/", expected_role="auto", live=True, provider="", region="",\n    build_ref="",\n):
    components = detected_components(root)
    role = detected_role(components)
    checks = []

    def add(name, ok, detail):
        checks.append({
            "name": name,
            "status": "PASS" if ok else "FAIL",
            "detail": detail,
        })

    if expected_role != "auto":
        add("role", role == expected_role, {
            "expected": expected_role,
            "detected": role,
        })
    else:
        add("role", role != "unknown", {"detected": role})

    required_services = []
    if components["agent"]:
        required_services.append("vps-monitor")
        ok, detail = file_check(root, AGENT_ENV, {0o600})
        add("agent_env_permissions", ok, detail)
    if components["controller"]:
        required_services.append("vps-sentinel-controller")
        ok, detail = file_check(root, CONTROLLER_ENV, {0o600})
        add("controller_env_permissions", ok, detail)
    if components["broker"]:
        required_services.append("mosquitto")
    if components["home_assistant"]:
        required_services.append("docker")

    if live:
        for service in required_services:
            active = service_active(service)
            add(
                f"service_{service}",
                active,
                "active" if active else "inactive",
            )
        if components["agent"]:
            ok, detail = agent_probe(root)
            add("agent_mqtt", ok, detail)
        if components["controller"]:
            ok, detail = controller_probe(root)
            add("controller_fleet", ok, detail)
        if components["home_assistant"]:
            ok, _ = command_result([
                "docker", "exec", "homeassistant", "python", "-m",
                "homeassistant", "--script", "check_config",
                "--config", "/config",
            ], timeout=90)
            add("home_assistant_config", ok, "valid" if ok else "invalid")
    else:
        checks.append({
            "name": "live_checks",
            "status": "SKIP",
            "detail": "disabled",
        })

    passed = sum(item["status"] == "PASS" for item in checks)
    failed = sum(item["status"] == "FAIL" for item in checks)
    skipped = sum(item["status"] == "SKIP" for item in checks)
    return {
        "schema_version": SCHEMA_VERSION,
        "collector_version": COLLECTOR_VERSION,\n        "build_ref": build_ref or None,\n        "collected_at": utc_timestamp(),
        "host": {
            "fingerprint": host_fingerprint(root),
            "provider": provider or None,
            "region": region or None,
            "os": os_name(root),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "cpu_count": os.cpu_count(),
            "memory_mib": memory_mib(root),
        },
        "version": installed_version(root),
        "expected_role": expected_role,
        "detected_role": role,
        "components": components,
        "checks": checks,
        "summary": {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "result": "PASS" if failed == 0 and live else (
                "FAIL" if failed else "INCOMPLETE"
            ),
        },
    }


def write_report(report, output):
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    temporary.write_text(serialized, encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    checksum = path.with_suffix(path.suffix + ".sha256")
    checksum.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    os.chmod(checksum, 0o600)
    return path, checksum


def main():
    parser = argparse.ArgumentParser(
        description="建立不含密碼、Token、IP 與原始 node_id 的 1.0 Beta 證據報告"
    )
    parser.add_argument(
        "--expect-role",
        choices=("auto", "agent", "controller", "combined"),
        default="auto",
    )
    parser.add_argument("--provider", default="")
    parser.add_argument("--region", default="")\n    parser.add_argument(\n        "--build-ref",\n        default="",\n        help="受測 commit SHA 或 Beta tag；建立正式驗收證據時必填",\n    )\n    parser.add_argument("--root", default="/", help=argparse.SUPPRESS)
    parser.add_argument("--no-live", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output")
    args = parser.parse_args()

    live = not args.no_live and args.root == "/"
    if live and os.geteuid() != 0:
        raise SystemExit("請使用 sudo 執行，才能讀取 root 專用設定並完成 MQTT 驗證。")
    if live:
        ensure_mqtt_dependency()

    output = args.output
    if not output:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output = f"/root/vps-sentinel-evidence/evidence-{timestamp}.json"

    report = collect(
        root=args.root,
        expected_role=args.expect_role,
        live=live,
        provider=args.provider,
        region=args.region,\n        build_ref=args.build_ref,\n    )
    report_path, checksum_path = write_report(report, output)
    print(f"證據報告：{report_path}")
    print(f"SHA-256：{checksum_path}")
    print(
        "結果："
        f"{report['summary']['result']} "
        f"({report['summary']['passed']} PASS / "
        f"{report['summary']['failed']} FAIL / "
        f"{report['summary']['skipped']} SKIP)"
    )
    print("報告不包含 MQTT 密碼、Token、Broker 位址、IP 或原始 node_id。")
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
