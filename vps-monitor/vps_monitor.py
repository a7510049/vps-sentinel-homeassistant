#!/usr/bin/env python3
import json
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import threading
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psutil
import paho.mqtt.client as mqtt


def env(name, default=""):
    return os.getenv(name, default)


VPS_ID = env("VPS_ID", socket.gethostname().lower())
if not re.fullmatch(r"[a-z0-9_-]+", VPS_ID):
    raise SystemExit("VPS_ID may contain only lowercase letters, digits, _ and -")

NAME = env("VPS_NAME", socket.gethostname())
HOST = env("MQTT_HOST")
PORT = int(env("MQTT_PORT", "1883"))
USER = env("MQTT_USERNAME")
PASSWORD = env("MQTT_PASSWORD")
INTERVAL = max(10, int(env("PUBLISH_INTERVAL", "15")))
HEALTH_INTERVAL = max(INTERVAL, int(env("HEALTH_CHECK_INTERVAL", "300")))
UPDATE_INTERVAL = max(3600, int(env("UPDATE_CHECK_INTERVAL", "86400")))
MONITOR_NETWORK = env("MONITOR_NETWORK", "false").lower() in ("1", "true", "yes")
PREFIX = env("DISCOVERY_PREFIX", "homeassistant").strip("/")
BASE = f"vps/{VPS_ID}"
STATE = f"{BASE}/state"
RESOURCE_STATE = f"{BASE}/resources"
STATUS_STATE = f"{BASE}/status"
ONLINE = f"{BASE}/online"
CPU_WARN = float(env("CPU_WARN_PERCENT", "90"))
MEM_WARN = float(env("MEMORY_WARN_PERCENT", "90"))
DISK_WARN = float(env("DISK_WARN_PERCENT", "85"))
OVERLOAD_SAMPLES = max(1, int(env("OVERLOAD_SAMPLES", "10")))
SERVICES = env("WATCH_SERVICES").split()
DOCKER_PRESENT = shutil.which("docker") is not None

if not HOST:
    raise SystemExit("MQTT_HOST is required")

def os_release():
    values = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as release_file:
            for line in release_file:
                key, separator, value = line.rstrip().partition("=")
                if separator:
                    values[key] = value.strip().strip('"')
    except OSError:
        pass
    return values


OS_RELEASE = os_release()
OS_NAME = OS_RELEASE.get("PRETTY_NAME", OS_RELEASE.get("NAME", "Linux"))


def installed_version():
    try:
        with open("/opt/vps-monitor/.version", encoding="utf-8") as version_file:
            return version_file.read().strip() or "unknown"
    except OSError:
        return "development"


DEVICE = {
    "identifiers": [f"ubuntu_vps_{VPS_ID}"],
    "name": NAME,
    # Keep the existing identifier so upgrades do not create a duplicate device.
    "manufacturer": OS_RELEASE.get("NAME", "Linux"),
    "model": f"VPS Sentinel／{platform.machine()}",
    "sw_version": installed_version(),
}


def run(command):
    try:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None


def parse_security_updates(output):
    return sum(
        1
        for line in output.splitlines()
        if line.startswith("Inst ") and "-security" in line
    )


def parse_ip_metadata(payload):
    if not payload.get("success"):
        return {"country_code": "unknown", "provider": "unknown"}
    connection = payload.get("connection") or {}
    country_code = str(payload.get("country_code") or "").upper()
    if not re.fullmatch(r"[A-Z]{2}", country_code):
        country_code = "unknown"
    provider = (
        connection.get("org")
        or connection.get("isp")
        or connection.get("domain")
        or "unknown"
    )
    return {
        "country_code": country_code,
        "provider": str(provider).strip() or "unknown",
    }


def ip_metadata():
    if env("IP_METADATA", "true").lower() not in ("1", "true", "yes"):
        return {"country_code": "unknown", "provider": "unknown"}
    request = Request(
        "https://ipwho.is/",
        headers={"User-Agent": f"VPS-Sentinel/{installed_version()}"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read(65536).decode("utf-8"))
        return parse_ip_metadata(payload)
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
        return {"country_code": "unknown", "provider": "unknown"}


def security_updates():
    result = run(["apt-get", "-s", "upgrade"])
    if not result or result.returncode != 0:
        return "unknown"
    return parse_security_updates(result.stdout)


def service_health():
    failed = []
    for service in SERVICES:
        result = run(["systemctl", "is-active", "--quiet", service])
        if not result or result.returncode != 0:
            failed.append(service)
    return failed


def parse_docker_health(output):
    rows = [row.lower() for row in output.splitlines() if row]
    return {
        "available": True,
        "running": sum(row.startswith("running|") for row in rows),
        "unhealthy": sum(
            "unhealthy" in row or row.startswith("restarting|") for row in rows
        ),
    }


def docker_health():
    if not DOCKER_PRESENT:
        return {"available": False, "running": "unknown", "unhealthy": "unknown"}
    result = run([
        "docker", "ps", "-a", "--format",
        "{{.State}}|{{if .Status}}{{.Status}}{{end}}",
    ])
    if not result or result.returncode != 0:
        return {"available": False, "running": "unknown", "unhealthy": "unknown"}
    return parse_docker_health(result.stdout)


def health_status(resource_overload, disk_low, service_problem,
                  reboot_required, security_update_count):
    if service_problem or disk_low:
        return "critical"
    if resource_overload or reboot_required:
        return "warning"
    if isinstance(security_update_count, int) and security_update_count > 0:
        return "warning"
    return "normal"


def config_sensor(key, name, unit=None, device_class=None, state_class=None,
                  icon=None, entity_category="diagnostic", topic=STATUS_STATE,
                  expire_after=None, attributes=None, value_template=None):
    cfg = {
        "name": name,
        "unique_id": f"{VPS_ID}_{key}",
        "default_entity_id": f"sensor.{VPS_ID}_{key}",
        "state_topic": topic,
        # MQTT may still retain a payload from an older version that does not
        # contain a newly added field. Return unknown until the next report
        # instead of making the Home Assistant template fail.
        "value_template": value_template or (
            f"{{{{ value_json.get('{key}', 'unknown') }}}}"
        ),
        "availability_topic": ONLINE,
        "payload_available": "ON",
        "payload_not_available": "OFF",
        "device": DEVICE,
        "entity_category": entity_category,
    }
    if unit:
        cfg["unit_of_measurement"] = unit
    if device_class:
        cfg["device_class"] = device_class
    if state_class:
        cfg["state_class"] = state_class
    if icon:
        cfg["icon"] = icon
    if expire_after:
        cfg["expire_after"] = expire_after
    if attributes:
        cfg["json_attributes_topic"] = topic
        cfg["json_attributes_template"] = attributes
    return cfg


def config_binary(key, name, device_class="occupancy", available=True,
                  topic=STATUS_STATE, expire_after=None):
    cfg = {
        "name": name,
        "unique_id": f"{VPS_ID}_{key}",
        "default_entity_id": f"binary_sensor.{VPS_ID}_{key}",
        "state_topic": ONLINE if key == "offline" else topic,
        "value_template": (
            "{{ 'OFF' if value == 'ON' else 'ON' }}"
            if key == "offline"
            else (
                f"{{{{ 'ON' if value_json.get('{key}', false) else 'OFF' }}}}"
            )
        ),
        "payload_on": "ON",
        "payload_off": "OFF",
        "device_class": device_class,
        "device": DEVICE,
    }
    if available:
        cfg.update({
            "availability_topic": ONLINE,
            "payload_available": "ON",
            "payload_not_available": "OFF",
        })
    if expire_after:
        cfg["expire_after"] = expire_after
    return cfg


def publish_discovery(client):
    sensors = {
        "cpu_percent": config_sensor(
            "cpu_percent", "CPU 使用率", "%", None, "measurement",
            "mdi:cpu-64-bit", topic=RESOURCE_STATE,
            expire_after=max(60, INTERVAL * 3),
        ),
        "memory_percent": config_sensor(
            "memory_percent", "記憶體使用率", "%", None, "measurement",
            "mdi:memory", topic=RESOURCE_STATE,
            expire_after=max(60, INTERVAL * 3),
            attributes=(
                "{{ {'used_gb': value_json.get('memory_used_gb'), "
                "'available_gb': value_json.get('memory_available_gb'), "
                "'total_gb': value_json.get('memory_total_gb')} | tojson }}"
            ),
        ),
        "disk_percent": config_sensor(
            "disk_percent", "磁碟使用率", "%", None, "measurement",
            "mdi:harddisk",
            attributes=(
                "{{ {'used_gb': value_json.get('disk_used_gb'), "
                "'free_gb': value_json.get('disk_free_gb'), "
                "'total_gb': value_json.get('disk_total_gb')} | tojson }}"
            ),
        ),
        "load_1": config_sensor("load_1", "負載 1 分鐘", icon="mdi:gauge"),
        "load_5": config_sensor("load_5", "負載 5 分鐘", icon="mdi:gauge"),
        "load_15": config_sensor("load_15", "負載 15 分鐘", icon="mdi:gauge"),
        "uptime_hours": config_sensor(
            "uptime_hours", "已運作", "h", "duration", "measurement"
        ),
        "boot_time": config_sensor(
            "boot_time", "最近開機時間", device_class="timestamp"
        ),
        "health_status": config_sensor(
            "health_status", "整體狀態", icon="mdi:heart-pulse",
            value_template=(
                "{% set status = value_json.get('health_status', 'unknown') %}"
                "{{ {'normal':'運作正常', 'warning':'需要留意', "
                "'critical':'需要處理'}.get(status, '資料不可用') }}"
            ),
        ),
        "security_updates": config_sensor(
            "security_updates", "待安裝安全更新", icon="mdi:shield-alert"
        ),
        "failed_services": config_sensor(
            "failed_services", "異常服務", icon="mdi:server-off"
        ),
        "country_code": config_sensor(
            "country_code", "節點國家", icon="mdi:flag"
        ),
        "provider": config_sensor(
            "provider", "VPS 供應商", icon="mdi:cloud"
        ),
        "os_name": config_sensor(
            "os_name", "作業系統", icon="mdi:linux"
        ),
    }
    docker_sensors = {
        "docker_running": config_sensor(
            "docker_running", "執行中的容器", icon="mdi:docker"
        ),
        "docker_unhealthy": config_sensor(
            "docker_unhealthy", "Docker 異常", icon="mdi:docker"
        ),
    }
    if DOCKER_PRESENT:
        sensors.update(docker_sensors)
    else:
        for key in docker_sensors:
            client.publish(
                f"{PREFIX}/sensor/{VPS_ID}/{key}/config",
                payload=None, qos=1, retain=True,
            )
    network_sensors = {
        "download_mbps": config_sensor(
            "download_mbps", "下載速率", "Mbit/s", "data_rate", "measurement",
            topic=RESOURCE_STATE, expire_after=max(60, INTERVAL * 3),
        ),
        "upload_mbps": config_sensor(
            "upload_mbps", "上傳速率", "Mbit/s", "data_rate", "measurement",
            topic=RESOURCE_STATE, expire_after=max(60, INTERVAL * 3),
        ),
    }
    if MONITOR_NETWORK:
        sensors.update(network_sensors)
    else:
        # Remove retained discovery entries left by an earlier configuration.
        for key in network_sensors:
            client.publish(
                f"{PREFIX}/sensor/{VPS_ID}/{key}/config",
                payload=None, qos=1, retain=True,
            )
    binaries = {
        "reporting": config_binary(
            "reporting", "資料持續更新", device_class="connectivity",
            topic=RESOURCE_STATE, expire_after=max(60, INTERVAL * 3),
        ),
        "offline": config_binary(
            "offline", "連線狀態", device_class="problem", available=False
        ),
        "resource_overload": config_binary(
            "resource_overload", "系統負載狀態", device_class="problem"
        ),
        "disk_low": config_binary(
            "disk_low", "磁碟空間狀態", device_class="problem"
        ),
        "service_problem": config_binary(
            "service_problem", "服務運作狀態", device_class="problem"
        ),
        "reboot_required": config_binary(
            "reboot_required", "重新啟動提醒", device_class="problem"
        ),
    }
    # v0.6 replaces the timestamp entity with a clear live/stale indicator.
    client.publish(
        f"{PREFIX}/sensor/{VPS_ID}/last_report/config",
        payload=None, qos=1, retain=True,
    )
    for key, cfg in sensors.items():
        client.publish(
            f"{PREFIX}/sensor/{VPS_ID}/{key}/config",
            json.dumps(cfg, ensure_ascii=False), qos=1, retain=True,
        )
    for key, cfg in binaries.items():
        client.publish(
            f"{PREFIX}/binary_sensor/{VPS_ID}/{key}/config",
            json.dumps(cfg, ensure_ascii=False), qos=1, retain=True,
        )


def main():
    wake_on_connect = threading.Event()
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"vps-monitor-{VPS_ID}",
        clean_session=True,
    )

    def on_connect(mqtt_client, _userdata, _flags, reason_code, _properties):
        if reason_code != 0:
            print(f"MQTT 連線遭拒：{reason_code}", flush=True)
            return
        print(f"MQTT 已連線：{HOST}:{PORT}", flush=True)
        publish_discovery(mqtt_client)
        mqtt_client.publish(ONLINE, "ON", qos=1, retain=True)
        wake_on_connect.set()

    client.on_connect = on_connect
    client.reconnect_delay_set(min_delay=5, max_delay=300)
    if USER:
        client.username_pw_set(USER, PASSWORD)
    if env("MQTT_TLS", "false").lower() in ("1", "true", "yes"):
        ca_file = env("MQTT_CA_FILE") or None
        client.tls_set(ca_certs=ca_file, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    client.will_set(ONLINE, "OFF", qos=1, retain=True)
    client.connect_async(HOST, PORT, keepalive=max(60, INTERVAL * 3))
    client.loop_start()

    psutil.cpu_percent(interval=None)
    previous_net = psutil.net_io_counters() if MONITOR_NETWORK else None
    previous_time = time.monotonic()
    overload_count = 0
    updates = "unknown"
    next_update_check = 0.0
    failed = []
    docker = {"available": False, "running": "unknown", "unhealthy": "unknown"}
    next_health_check = 0.0
    disk = psutil.disk_usage("/")
    load = os.getloadavg()
    last_status_payload = None
    location = ip_metadata()

    try:
        while True:
            loop_started = time.monotonic()
            cpu = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            now = time.monotonic()
            download = upload = 0.0
            if MONITOR_NETWORK:
                net = psutil.net_io_counters()
                elapsed = max(0.1, now - previous_time)
                download = (
                    (net.bytes_recv - previous_net.bytes_recv) * 8 / elapsed / 1e6
                )
                upload = (
                    (net.bytes_sent - previous_net.bytes_sent) * 8 / elapsed / 1e6
                )
                previous_net, previous_time = net, now

            overloaded = cpu >= CPU_WARN or memory.percent >= MEM_WARN
            overload_count = overload_count + 1 if overloaded else 0

            resource_payload = {
                "cpu_percent": round(cpu, 1),
                "memory_percent": round(memory.percent, 1),
                "memory_used_gb": round(memory.used / 1e9, 2),
                "memory_available_gb": round(memory.available / 1e9, 2),
                "memory_total_gb": round(memory.total / 1e9, 2),
                "reporting": True,
                "last_report": datetime.now(timezone.utc).isoformat(),
            }
            if MONITOR_NETWORK:
                resource_payload.update({
                    "download_mbps": round(max(0, download), 3),
                    "upload_mbps": round(max(0, upload), 3),
                })
            client.publish(
                RESOURCE_STATE,
                json.dumps(resource_payload, ensure_ascii=False),
                qos=0,
                retain=True,
            )

            if now >= next_update_check:
                updates = security_updates()
                next_update_check = now + UPDATE_INTERVAL
            health_check_due = now >= next_health_check
            if health_check_due:
                failed = service_health()
                docker = docker_health()
                disk = psutil.disk_usage("/")
                load = os.getloadavg()
                next_health_check = now + HEALTH_INTERVAL

            resource_overload = overload_count >= OVERLOAD_SAMPLES
            disk_low = disk.percent >= DISK_WARN
            service_problem = bool(
                failed
                or (DOCKER_PRESENT and not docker["available"])
                or (
                    docker["available"]
                    and isinstance(docker["unhealthy"], int)
                    and docker["unhealthy"] > 0
                )
            )
            reboot_required = os.path.exists("/var/run/reboot-required")
            status_payload = {
                "disk_percent": round(disk.percent, 1),
                "disk_used_gb": round(disk.used / 1e9, 2),
                "disk_free_gb": round(disk.free / 1e9, 2),
                "disk_total_gb": round(disk.total / 1e9, 2),
                "load_1": round(load[0], 2),
                "load_5": round(load[1], 2),
                "load_15": round(load[2], 2),
                "uptime_hours": round(
                    (time.time() - psutil.boot_time()) / 3600, 1
                ),
                "boot_time": datetime.fromtimestamp(
                    psutil.boot_time(), tz=timezone.utc
                ).isoformat(),
                "last_report": resource_payload["last_report"],
                "security_updates": updates,
                "docker_running": docker["running"],
                "docker_unhealthy": docker["unhealthy"],
                "failed_services": ", ".join(failed) if failed else "無",
                "country_code": location["country_code"],
                "provider": location["provider"],
                "os_name": OS_NAME,
                "resource_overload": resource_overload,
                "disk_low": disk_low,
                "service_problem": service_problem,
                "reboot_required": reboot_required,
                "health_status": health_status(
                    resource_overload,
                    disk_low,
                    service_problem,
                    reboot_required,
                    updates,
                ),
            }
            comparable_status = {
                key: value
                for key, value in status_payload.items()
                if key not in ("last_report", "uptime_hours")
            }
            if health_check_due or comparable_status != last_status_payload:
                client.publish(
                    STATUS_STATE,
                    json.dumps(status_payload, ensure_ascii=False),
                    qos=1,
                    retain=True,
                )
                # Keep the v0.5 topic current during rolling upgrades.
                client.publish(
                    STATE,
                    json.dumps(
                        {**status_payload, **resource_payload},
                        ensure_ascii=False,
                    ),
                    qos=1,
                    retain=True,
                )
                last_status_payload = comparable_status
            wake_on_connect.wait(
                timeout=max(1, INTERVAL - (time.monotonic() - loop_started))
            )
            wake_on_connect.clear()
    finally:
        client.publish(ONLINE, "OFF", qos=1, retain=True)
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
