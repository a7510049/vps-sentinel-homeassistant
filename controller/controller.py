#!/usr/bin/env python3
"""MQTT runtime for the VPS Sentinel 1.0 multi-node Controller."""

from datetime import datetime, timezone
import json
import os
import ssl
import time

import paho.mqtt.client as mqtt

from enrollment import EnrollmentStore
from node_contract import ContractError, parse_topic
from node_registry import NodeRegistry, RegistryError


NODE_SUBSCRIPTION = "vps-sentinel/v1/nodes/+/+"


def env(name, default=""):
    return os.getenv(name, default)


def _utc_now():
    return datetime.now(timezone.utc)


def _timestamp(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class ControllerRuntime:
    """Accept enrolled node messages and publish a sanitized fleet snapshot."""

    def __init__(
        self,
        client,
        registry,
        enrollments,
        *,
        fleet_topic="vps-sentinel/v1/controller/fleet",
        availability_topic="vps-sentinel/v1/controller/online",
        discovery_prefix="homeassistant",
        clock=None,
    ):
        self.client = client
        self.registry = registry
        self.enrollments = enrollments
        self.fleet_topic = fleet_topic
        self.availability_topic = availability_topic
        self.discovery_prefix = discovery_prefix.strip("/")
        self.clock = clock or _utc_now
        self.accepted_messages = 0
        self.rejected_messages = 0
        self.last_snapshot_signature = None

    def publish_discovery(self):
        device = {
            "identifiers": ["vps_sentinel_controller"],
            "name": "VPS Sentinel Controller",
            "manufacturer": "VPS Sentinel",
            "model": "Multi-node Controller",
        }
        common = {
            "state_topic": self.fleet_topic,
            "availability_topic": self.availability_topic,
            "payload_available": "ON",
            "payload_not_available": "OFF",
            "device": device,
        }
        sensor = {
            **common,
            "name": "受監控 VPS 數量",
            "unique_id": "vps_sentinel_fleet_node_count",
            "default_entity_id": "sensor.vps_sentinel_fleet_nodes",
            "value_template": "{{ value_json.node_count }}",
            "json_attributes_topic": self.fleet_topic,
            "icon": "mdi:server-network",
            "entity_category": "diagnostic",
        }
        problem = {
            **common,
            "name": "VPS Fleet 問題",
            "unique_id": "vps_sentinel_fleet_problem",
            "default_entity_id": "binary_sensor.vps_sentinel_fleet_problem",
            "value_template": (
                "{{ 'ON' if value_json.problem_count | int > 0 else 'OFF' }}"
            ),
            "device_class": "problem",
        }
        configs = {
            (
                f"{self.discovery_prefix}/sensor/"
                "vps_sentinel_controller/fleet_nodes/config"
            ): sensor,
            (
                f"{self.discovery_prefix}/binary_sensor/"
                "vps_sentinel_controller/fleet_problem/config"
            ): problem,
        }
        for topic, payload in configs.items():
            self.client.publish(
                topic,
                json.dumps(payload, ensure_ascii=False),
                qos=1,
                retain=True,
            )
        return configs

    def handle_message(self, topic, raw_payload):
        try:
            node_id, _message_type = parse_topic(topic)
            credential_id = self.enrollments.credential_for(node_id)
            if credential_id is None:
                raise RegistryError(f"node_id {node_id!r} is not enrolled")
            self.registry.ingest(
                topic,
                raw_payload,
                credential_id=credential_id,
                received_at=self.clock(),
            )
        except (ContractError, RegistryError, ValueError) as error:
            self.rejected_messages += 1
            print(f"已拒絕節點訊息：{error}", flush=True)
            return False
        self.accepted_messages += 1
        self.publish_snapshot()
        return True

    def snapshot(self):
        now = self.clock()
        nodes = self.registry.snapshot(now=now)
        return {
            "schema_version": "1.0",
            "generated_at": _timestamp(now),
            "node_count": len(nodes),
            "online_count": sum(node["online"] for node in nodes),
            "problem_count": sum(
                node["status"] in {"critical", "offline", "stale", "warning"}
                for node in nodes
            ),
            "nodes": nodes,
        }

    def publish_snapshot(self, *, force=False):
        snapshot = self.snapshot()
        signature = json.dumps(
            {key: value for key, value in snapshot.items() if key != "generated_at"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if not force and signature == self.last_snapshot_signature:
            return False
        self.client.publish(
            self.fleet_topic,
            json.dumps(snapshot, ensure_ascii=False),
            qos=1,
            retain=True,
        )
        self.last_snapshot_signature = signature
        return True


def main():
    host = env("MQTT_HOST")
    if not host:
        raise SystemExit("MQTT_HOST is required")
    port = int(env("MQTT_PORT", "1883"))
    username = env("MQTT_USERNAME")
    password = env("MQTT_PASSWORD")
    fleet_topic = env(
        "CONTROLLER_FLEET_TOPIC",
        "vps-sentinel/v1/controller/fleet",
    )
    availability_topic = env(
        "CONTROLLER_AVAILABILITY_TOPIC",
        "vps-sentinel/v1/controller/online",
    )
    enrollment_path = env(
        "CONTROLLER_ENROLLMENT_STORE",
        "/var/lib/vps-sentinel-controller/enrollments.json",
    )
    refresh_interval = max(5, int(env("CONTROLLER_REFRESH_INTERVAL", "15")))
    discovery_prefix = env("DISCOVERY_PREFIX", "homeassistant")

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=env("CONTROLLER_CLIENT_ID", "vps-sentinel-controller"),
        clean_session=False,
    )
    registry = NodeRegistry()
    enrollments = EnrollmentStore(enrollment_path)
    runtime = ControllerRuntime(
        client,
        registry,
        enrollments,
        fleet_topic=fleet_topic,
        availability_topic=availability_topic,
        discovery_prefix=discovery_prefix,
    )

    def on_connect(mqtt_client, _userdata, _flags, reason_code, _properties):
        if reason_code != 0:
            print(f"Controller MQTT 連線遭拒：{reason_code}", flush=True)
            return
        mqtt_client.subscribe(NODE_SUBSCRIPTION, qos=1)
        mqtt_client.publish(availability_topic, "ON", qos=1, retain=True)
        runtime.publish_discovery()
        runtime.publish_snapshot(force=True)
        print(
            f"Controller 已連線並監聽 {NODE_SUBSCRIPTION}",
            flush=True,
        )

    def on_message(_client, _userdata, message):
        runtime.handle_message(message.topic, message.payload)

    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=5, max_delay=300)
    if username:
        client.username_pw_set(username, password)
    if env("MQTT_TLS", "false").lower() in ("1", "true", "yes"):
        client.tls_set(
            ca_certs=env("MQTT_CA_FILE") or None,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
    client.will_set(availability_topic, "OFF", qos=1, retain=True)
    client.connect_async(host, port, keepalive=max(60, refresh_interval * 3))
    client.loop_start()
    try:
        while True:
            runtime.publish_snapshot()
            time.sleep(refresh_interval)
    finally:
        client.publish(availability_topic, "OFF", qos=1, retain=True)
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
