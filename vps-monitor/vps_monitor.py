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
INTERVAL = max(10, int(env("PUBLISH_INTERVAL", "30")))
HEALTH_INTERVAL = max(INTERVAL, int(env("HEALTH_CHECK_INTERVAL", "300")))
UPDATE_INTERVAL = max(3600, int(env("UPDATE_CHECK_INTERVAL", "86400")))
MONITOR_NETWORK = env("MONITOR_NETWORK", "false").lower() in ("1", "true", "yes")
PREFIX = env("DISCOVERY_PREFIX", "homeassistant").strip("/")
BASE = f"vps/{VPS_ID}"
STATE = f"{BASE}/state"
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
DEVICE = {
    "identifiers": [f"ubuntu_vps_{VPS_ID}"],
    "name": NAME,
    # Keep the existing identifier so upgrades do not create a duplicate device.
    "manufacturer": OS_RELEASE.get("NAME", "Linux"),
    "model": "VPS Sentinel",
    "sw_version": platform.release(),
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


def config_sensor(key, name, unit=None, device_class=None, state_class=None,
                  icon=None, entity_category="diagnostic"):
    cfg = {
        "name": name,
        "unique_id": f"{VPS_ID}_{key}",
        "default_entity_id": f"sensor.{VPS_ID}_{key}",
        "state_topic": STATE,
        "value_template": f"{{{{ value_json.{key} }}}}",
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
    return cfg


def config_binary(key, name, device_class="occupancy", available=True):
    cfg = {
        "name": name,
        "unique_id": f"{VPS_ID}_{key}",
        "default_entity_id": f"binary_sensor.{VPS_ID}_{key}",
        "state_topic": ONLINE if key == "offline" else STATE,
        "value_template": (
            "{{ 'OFF' if value == 'ON' else 'ON' }}"
            if key == "offline"
            else f"{{{{ 'ON' if value_json.{key} else 'OFF' }}}}"
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
    return cfg


def publish_discovery(client):
    sensors = {
        "cpu_percent": config_sensor(
            "cpu_percent", "CPU 使用率", "%", None, "measurement", "mdi:cpu-64-bit"
        ),
        "memory_percent": config_sensor(
            "memory_percent", "記憶體使用率", "%", None, "measurement", "mdi:memory"
        ),
        "disk_percent": config_sensor(
            "disk_percent", "磁碟使用率", "%", None, "measurement", "mdi:harddisk"
        ),
        "load_1": config_sensor("load_1", "負載 1 分鐘", icon="mdi:gauge"),
        "load_5": config_sensor("load_5", "負載 5 分鐘", icon="mdi:gauge"),
        "load_15": config_sensor("load_15", "負載 15 分鐘", icon="mdi:gauge"),
        "uptime_hours": config_sensor(
            "uptime_hours", "已運行", "h", "duration", "measurement"
        ),
        "boot_time": config_sensor(
            "boot_time", "最近開機時間", device_class="timestamp"
        ),
        "security_updates": config_sensor(
            "security_updates", "待安裝安全更新", icon="mdi:shield-alert"
        ),
        "failed_services": config_sensor(
            "failed_services", "異常服務", icon="mdi:server-off"
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
            "download_mbps", "下載速率", "Mbit/s", "data_rate", "measurement"
        ),
        "upload_mbps": config_sensor(
            "upload_mbps", "上傳速率", "Mbit/s", "data_rate", "measurement"
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

    try:
        while True:
            loop_started = time.monotonic()
            cpu = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory().percent
            disk = psutil.disk_usage("/").percent
            load = os.getloadavg()
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

            overloaded = cpu >= CPU_WARN or memory >= MEM_WARN
            overload_count = overload_count + 1 if overloaded else 0
            if now >= next_update_check:
                updates = security_updates()
                next_update_check = now + UPDATE_INTERVAL
            if now >= next_health_check:
                failed = service_health()
                docker = docker_health()
                next_health_check = now + HEALTH_INTERVAL

            boot = datetime.fromtimestamp(
                psutil.boot_time(), tz=timezone.utc
            ).isoformat()
            payload = {
                "cpu_percent": round(cpu, 1),
                "memory_percent": round(memory, 1),
                "disk_percent": round(disk, 1),
                "load_1": round(load[0], 2),
                "load_5": round(load[1], 2),
                "load_15": round(load[2], 2),
                "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 1),
                "boot_time": boot,
                "security_updates": updates,
                "docker_running": docker["running"],
                "docker_unhealthy": docker["unhealthy"],
                "failed_services": ", ".join(failed) if failed else "無",
                "resource_overload": overload_count >= OVERLOAD_SAMPLES,
                "disk_low": disk >= DISK_WARN,
                "service_problem": bool(
                    failed
                    or (DOCKER_PRESENT and not docker["available"])
                    or (
                        docker["available"]
                        and isinstance(docker["unhealthy"], int)
                        and docker["unhealthy"] > 0
                    )
                ),
                "reboot_required": os.path.exists("/var/run/reboot-required"),
            }
            if MONITOR_NETWORK:
                payload.update({
                    "download_mbps": round(max(0, download), 3),
                    "upload_mbps": round(max(0, upload), 3),
                })
            client.publish(
                STATE, json.dumps(payload, ensure_ascii=False), qos=1, retain=True
            )
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
