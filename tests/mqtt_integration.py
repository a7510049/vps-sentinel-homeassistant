#!/usr/bin/env python3
"""Real Mosquitto integration test for three isolated v1 nodes."""

from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

import paho.mqtt.client as mqtt


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "controller"))
sys.path.insert(0, str(ROOT / "vps-monitor"))

from broker_policy import BrokerPolicy
from controller import ControllerRuntime, NODE_SUBSCRIPTION
from enrollment import EnrollmentStore
from node_contract import build_envelope, topic_for
from node_registry import NodeRegistry


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_until(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition timed out")


def client_for(port, client_id, username, password):
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        clean_session=True,
    )
    client.username_pw_set(username, password)
    connected = threading.Event()

    def on_connect(_client, _userdata, _flags, reason_code, _properties):
        if reason_code == 0:
            connected.set()

    client.on_connect = on_connect
    client.connect("127.0.0.1", port, 30)
    client.loop_start()
    wait_until(connected.is_set)
    return client


def envelope(node_id, message_type, sequence):
    data = {
        "resources": {"cpu_percent": sequence, "memory_percent": 20},
        "health": {"health_status": "normal"},
        "metadata": {"os_name": "Ubuntu 24.04 LTS"},
        "availability": {"status": "offline"},
    }[message_type]
    return build_envelope(
        node_id=node_id,
        display_name=node_id,
        agent_version="1.0.0-e2e",
        message_type=message_type,
        observed_at=datetime.now(timezone.utc),
        sequence=sequence,
        capabilities=["health.basic", "resources.basic"],
        data=data,
        labels={"test": "mqtt-e2e"},
    )


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        port = free_port()
        store = EnrollmentStore(root / "enrollments.json")
        enrollments = [
            store.register(node_id, node_id)
            for node_id in ("tokyo-web-01", "frankfurt-db-01", "singapore-api-01")
        ]
        passwd = root / "passwd"
        credentials = [
            ("home-assistant", "ha-secret"),
            ("vps-controller", "controller-secret"),
            *[(item.username, item.password) for item in enrollments],
        ]
        for index, (username, password) in enumerate(credentials):
            command = ["mosquitto_passwd", "-b"]
            if index == 0:
                command.append("-c")
            command.extend([str(passwd), username, password])
            subprocess.run(command, check=True, capture_output=True)

        acl = root / "acl"
        acl.write_text(BrokerPolicy(store).render_acl(), encoding="utf-8")
        config = root / "mosquitto.conf"
        config.write_text(
            "allow_anonymous false\n"
            f"password_file {passwd}\n"
            f"acl_file {acl}\n"
            f"listener {port} 127.0.0.1\n"
            "persistence false\n",
            encoding="utf-8",
        )
        broker = subprocess.Popen(
            ["mosquitto", "-c", str(config)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        clients = []
        try:
            wait_until(lambda: broker.poll() is None)
            observer = client_for(
                port,
                "e2e-observer",
                "home-assistant",
                "ha-secret",
            )
            clients.append(observer)
            fleets = []
            observer.on_message = lambda _c, _u, message: fleets.append(
                json.loads(message.payload)
            )
            observer.subscribe("vps-sentinel/v1/controller/fleet", qos=1)

            controller_client = client_for(
                port,
                "e2e-controller",
                "vps-controller",
                "controller-secret",
            )
            clients.append(controller_client)
            runtime = ControllerRuntime(
                controller_client,
                NodeRegistry(
                    stream_ttls={
                        "resources": 60,
                        "health": 600,
                        "metadata": 86400,
                    },
                    offline_after=90,
                ),
                store,
            )

            def controller_message(_client, _userdata, message):
                runtime.handle_message(message.topic, message.payload)

            controller_client.on_message = controller_message
            controller_client.subscribe(NODE_SUBSCRIPTION, qos=1)
            runtime.publish_discovery()
            runtime.publish_snapshot(force=True)

            for enrollment in enrollments:
                agent = client_for(
                    port,
                    "e2e-" + enrollment.node_id,
                    enrollment.username,
                    enrollment.password,
                )
                clients.append(agent)
                for sequence, message_type in enumerate(
                    ("resources", "health", "metadata"),
                    start=1,
                ):
                    body = json.dumps(
                        envelope(enrollment.node_id, message_type, sequence)
                    )
                    token = agent.publish(
                        topic_for(enrollment.node_id, message_type),
                        body,
                        qos=1,
                        retain=True,
                    )
                    token.wait_for_publish(5)

            fleet = wait_until(
                lambda: next(
                    (
                        item
                        for item in reversed(fleets)
                        if item.get("node_count") == 3
                    ),
                    None,
                )
            )
            assert fleet["online_count"] == 3
            assert fleet["problem_count"] == 0
            assert {
                node["node"]["id"] for node in fleet["nodes"]
            } == {
                "tokyo-web-01",
                "frankfurt-db-01",
                "singapore-api-01",
            }

            first = clients[2]
            accepted = runtime.accepted_messages
            forbidden = json.dumps(
                envelope("frankfurt-db-01", "resources", 99)
            )
            first.publish(
                topic_for("frankfurt-db-01", "resources"),
                forbidden,
                qos=1,
            )
            time.sleep(1)
            assert runtime.accepted_messages == accepted

            print("three-node MQTT isolation and fleet discovery passed")
        finally:
            for client in clients:
                client.disconnect()
                client.loop_stop()
            broker.terminate()
            try:
                broker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                broker.kill()


if __name__ == "__main__":
    main()
