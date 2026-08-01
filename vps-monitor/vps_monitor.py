#!/usr/bin/env python3
import json
import math
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

from legacy_adapter import (
    LegacyCompatibilityError,
    health_envelope,
    legacy_capabilities,
    metadata_envelope,
    migration_node_id,
    resource_envelope,
)
from node_contract import topic_for


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
MAINTENANCE_STATE = f"{BASE}/maintenance"
MAINTENANCE_EVENT = f"{BASE}/maintenance/event"
COMMAND_TOPIC = f"{BASE}/command"
ONLINE = f"{BASE}/online"
CPU_WARN = float(env("CPU_WARN_PERCENT", "90"))
MEM_WARN = float(env("MEMORY_WARN_PERCENT", "90"))
DISK_WARN = float(env("DISK_WARN_PERCENT", "85"))
OVERLOAD_SAMPLES = max(1, int(env("OVERLOAD_SAMPLES", "10")))
SERVICES = env("WATCH_SERVICES").split()
DOCKER_PRESENT = shutil.which("docker") is not None
REMOTE_ACTIONS = env("ALLOW_REMOTE_ACTIONS", "false").lower() in (
    "1", "true", "yes"
)
COMMAND_COOLDOWN = max(60, int(env("COMMAND_COOLDOWN", "300")))
PUBLISH_V1_CONTRACT = env("PUBLISH_V1_CONTRACT", "false").lower() in (
    "1", "true", "yes"
)

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


class V1Publisher:
    """Opt-in dual publisher used while the Controller is under development."""

    def __init__(
        self,
        client,
        *,
        enabled,
        node_id,
        display_name,
        agent_version,
        capabilities,
    ):
        self.client = client
        self.enabled = enabled
        self.node_id = node_id
        self.display_name = display_name
        self.agent_version = agent_version
        self.capabilities = capabilities
        self.sequence = 0
        self.lock = threading.Lock()
        if enabled:
            migration_node_id(node_id)

    def _next_sequence(self):
        with self.lock:
            self.sequence += 1
            return self.sequence

    def _publish(self, message_type, builder, qos):
        if not self.enabled:
            return None
        envelope = builder(self._next_sequence())
        self.client.publish(
            topic_for(self.node_id, message_type),
            json.dumps(envelope, ensure_ascii=False),
            qos=qos,
            retain=True,
        )
        return envelope

    def publish_resources(self, payload):
        return self._publish(
            "resources",
            lambda sequence: resource_envelope(
                vps_id=self.node_id,
                display_name=self.display_name,
                agent_version=self.agent_version,
                payload=payload,
                sequence=sequence,
                capabilities=self.capabilities,
            ),
            qos=0,
        )

    def publish_health(self, payload):
        return self._publish(
            "health",
            lambda sequence: health_envelope(
                vps_id=self.node_id,
                display_name=self.display_name,
                agent_version=self.agent_version,
                payload=payload,
                sequence=sequence,
                capabilities=self.capabilities,
            ),
            qos=1,
        )

    def publish_metadata(self, status_payload):
        return self._publish(
            "metadata",
            lambda sequence: metadata_envelope(
                vps_id=self.node_id,
                display_name=self.display_name,
                agent_version=self.agent_version,
                status_payload=status_payload,
                sequence=sequence,
                capabilities=self.capabilities,
                architecture=platform.machine(),
            ),
            qos=1,
        )


DEVICE = {
    "identifiers": [f"ubuntu_vps_{VPS_ID}"],
    "name": NAME,
    # Keep the existing identifier so upgrades do not create a duplicate device.
    "manufacturer": OS_RELEASE.get("NAME", "Linux"),
    "model": f"VPS Sentinel／{platform.machine()}",
    "sw_version": installed_version(),
}


def run(command, timeout=15):
    try:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
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


def transient_command(unit, command):
    return [
        "/usr/bin/systemd-run",
        "--quiet",
        "--wait",
        "--pipe",
        "--collect",
        f"--unit={unit}",
        "--property=PrivateTmp=yes",
        "--property=ProtectHome=yes",
        "--property=NoNewPrivileges=yes",
        *command,
    ]


def maintenance_result(action, runner=run):
    if action == "refresh":
        result = runner(
            transient_command(
                "vps-sentinel-refresh",
                ["/usr/bin/apt-get", "update"],
            ),
            timeout=600,
        )
        if not result or result.returncode != 0:
            return False, "更新清單失敗"
        updates = security_updates()
        if isinstance(updates, int):
            return True, f"可安裝 {updates} 項安全更新"
        return True, "套件清單已更新"
    if action == "security_update":
        executable = shutil.which("unattended-upgrade")
        if not executable:
            return False, "主機未安裝 unattended-upgrade"
        result = runner(
            transient_command(
                "vps-sentinel-security-update",
                [executable, "-d"],
            ),
            timeout=1800,
        )
        if not result or result.returncode != 0:
            return False, "安全更新執行失敗"
        return True, "安全更新已完成"
    if action == "reboot":
        result = runner([
            "/usr/bin/systemd-run",
            "--quiet",
            "--collect",
            "--unit=vps-sentinel-reboot",
            "--on-active=30s",
            "/usr/bin/systemctl",
            "reboot",
        ], timeout=30)
        if not result or result.returncode != 0:
            return False, "重新啟動排程失敗"
        return True, "主機將在 30 秒後重新啟動"
    return False, "不支援的維護操作"


class MaintenanceController:
    ACTIONS = {"refresh", "security_update", "reboot"}
    PERSISTENT_STATES = {"idle", "running"}

    def __init__(self, client, enabled=REMOTE_ACTIONS,
                 cooldown=COMMAND_COOLDOWN, clock=time.monotonic,
                 wall_clock=time.time):
        self.client = client
        self.enabled = enabled
        self.cooldown = cooldown
        self.clock = clock
        self.wall_clock = wall_clock
        self.lock = threading.Lock()
        self.busy = False
        self.last_started = {}
        self.current_action = "none"
        self.current_request_id = None

    def _payload(self, state, action="none", message="", request_id=None,
                 remaining_seconds=None):
        payload = {
            "state": state,
            "action": action,
            "message": message,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if request_id:
            payload["request_id"] = request_id
        if remaining_seconds is not None:
            payload["remaining_seconds"] = remaining_seconds
        return payload

    def publish_state(self, state, action="none", message="",
                      request_id=None):
        payload = self._payload(
            state, action, message, request_id=request_id
        )
        self.client.publish(
            MAINTENANCE_STATE,
            json.dumps(payload, ensure_ascii=False),
            qos=1,
            retain=True,
        )

    def publish_event(self, state, action="none", message="",
                      request_id=None, remaining_seconds=None):
        payload = self._payload(
            state,
            action,
            message,
            request_id=request_id,
            remaining_seconds=remaining_seconds,
        )
        payload["event_type"] = state
        self.client.publish(
            MAINTENANCE_EVENT,
            json.dumps(payload, ensure_ascii=False),
            qos=1,
            retain=False,
        )

    def publish(self, state, action="none", message="",
                remaining_seconds=None, request_id=None):
        if state in self.PERSISTENT_STATES:
            self.publish_state(
                state, action, message, request_id=request_id
            )
            return
        self.publish_event(
            state,
            action,
            message,
            request_id=request_id,
            remaining_seconds=remaining_seconds,
        )

    def snapshot(self):
        with self.lock:
            if self.busy:
                return (
                    "running",
                    self.current_action,
                    self.current_request_id,
                )
        return "idle", "none", None

    def submit(self, raw_payload):
        if not self.enabled:
            self.publish("disabled", message="遠端維護未啟用")
            return False
        if not isinstance(raw_payload, str) or len(raw_payload) > 512:
            self.publish("rejected", message="命令內容過長或格式無效")
            return False
        try:
            payload = json.loads(raw_payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            self.publish("rejected", message="命令格式無效")
            return False
        if not isinstance(payload, dict):
            self.publish("rejected", message="命令格式無效")
            return False
        action = payload.get("action")
        request_id = payload.get("request_id")
        issued_at = payload.get("issued_at")
        allowed_keys = {"action", "request_id", "issued_at"}
        fresh = (
            isinstance(issued_at, (int, float))
            and abs(self.wall_clock() * 1000 - issued_at) <= 60000
        )
        valid_request = (
            isinstance(request_id, str)
            and 1 <= len(request_id) <= 64
            and re.fullmatch(r"[A-Za-z0-9_-]+", request_id)
        )
        if (
            action not in self.ACTIONS
            or set(payload) - allowed_keys
            or not fresh
            or not valid_request
        ):
            self.publish(
                "rejected",
                message="命令不在允許清單",
                request_id=request_id if valid_request else None,
            )
            return False
        with self.lock:
            now = self.clock()
            if self.busy:
                self.publish(
                    "busy",
                    action,
                    "已有維護操作正在執行",
                    request_id=request_id,
                )
                return False
            if now - self.last_started.get(action, float("-inf")) < self.cooldown:
                remaining = max(
                    1,
                    math.ceil(
                        self.cooldown - (now - self.last_started[action])
                    ),
                )
                self.publish(
                    "cooldown",
                    action,
                    f"{action} 操作冷卻中，約 {remaining} 秒後可再次執行",
                    remaining,
                    request_id=request_id,
                )
                return False
            self.busy = True
            self.last_started[action] = now
            self.current_action = action
            self.current_request_id = request_id
        worker = threading.Thread(
            target=self._execute,
            args=(action, request_id),
            daemon=True,
            name=f"maintenance-{action}",
        )
        worker.start()
        return True

    def _execute(self, action, request_id):
        self.publish_state(
            "running",
            action,
            "操作執行中",
            request_id=request_id,
        )
        try:
            success, message = maintenance_result(action)
            state = "scheduled" if success and action == "reboot" else (
                "success" if success else "failed"
            )
            self.publish_event(
                state,
                action,
                message,
                request_id=request_id,
            )
        except Exception:
            self.publish_event(
                "failed",
                action,
                "操作發生未預期錯誤",
                request_id=request_id,
            )
        finally:
            with self.lock:
                self.busy = False
                self.current_action = "none"
                self.current_request_id = None
            self.publish_state("idle", message="等待操作")

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
    if REMOTE_ACTIONS:
        sensors["maintenance_status"] = config_sensor(
            "maintenance_status",
            "主機維護狀態",
            icon="mdi:tools",
            topic=MAINTENANCE_STATE,
            value_template="{{ value_json.get('state', 'unknown') }}",
            attributes="{{ value_json | tojson }}",
        )
        event_config = {
            "name": "主機維護事件",
            "unique_id": f"{VPS_ID}_maintenance_event",
            "default_entity_id": f"event.{VPS_ID}_maintenance_event",
            "state_topic": MAINTENANCE_EVENT,
            "event_types": [
                "success",
                "scheduled",
                "failed",
                "cooldown",
                "busy",
                "rejected",
                "disabled",
            ],
            "availability_topic": ONLINE,
            "payload_available": "ON",
            "payload_not_available": "OFF",
            "device": DEVICE,
            "entity_category": "diagnostic",
            "icon": "mdi:message-alert-outline",
        }
        client.publish(
            f"{PREFIX}/event/{VPS_ID}/maintenance_event/config",
            json.dumps(event_config, ensure_ascii=False),
            qos=1,
            retain=True,
        )
    else:
        client.publish(
            f"{PREFIX}/sensor/{VPS_ID}/maintenance_status/config",
            payload=None, qos=1, retain=True,
        )
        client.publish(
            f"{PREFIX}/event/{VPS_ID}/maintenance_event/config",
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
    maintenance = MaintenanceController(client)
    v1_publisher = V1Publisher(
        client,
        enabled=PUBLISH_V1_CONTRACT,
        node_id=VPS_ID,
        display_name=NAME,
        agent_version=installed_version(),
        capabilities=legacy_capabilities(
            monitor_network=MONITOR_NETWORK,
            docker_present=DOCKER_PRESENT,
            remote_actions=REMOTE_ACTIONS,
        ),
    )

    def on_command(_client, _userdata, message):
        # Empty retained cleanup messages are housekeeping.
        if not message.payload:
            return
        if message.retain:
            maintenance.publish_event(
                "rejected", message="已拒絕保留的舊命令"
            )
            return
        try:
            payload = message.payload.decode("utf-8")
        except UnicodeDecodeError:
            maintenance.publish_event(
                "rejected", message="命令編碼無效"
            )
            return
        maintenance.submit(payload)

    def on_connect(mqtt_client, _userdata, _flags, reason_code, _properties):
        if reason_code != 0:
            print(f"MQTT 連線遭拒：{reason_code}", flush=True)
            return
        print(f"MQTT 已連線：{HOST}:{PORT}", flush=True)
        publish_discovery(mqtt_client)
        mqtt_client.publish(ONLINE, "ON", qos=1, retain=True)
        if REMOTE_ACTIONS:
            mqtt_client.publish(
                COMMAND_TOPIC, payload=None, qos=1, retain=True
            )
            mqtt_client.publish(
                MAINTENANCE_EVENT, payload=None, qos=1, retain=True
            )
            mqtt_client.subscribe(COMMAND_TOPIC, qos=1)
            state, action, request_id = maintenance.snapshot()
            message = (
                "操作執行中" if state == "running" else "等待操作"
            )
            maintenance.publish_state(
                state, action, message, request_id=request_id
            )
        wake_on_connect.set()

    client.on_connect = on_connect
    client.message_callback_add(COMMAND_TOPIC, on_command)
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
            v1_publisher.publish_resources(resource_payload)

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
                v1_publisher.publish_health(status_payload)
                v1_publisher.publish_metadata(status_payload)
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
