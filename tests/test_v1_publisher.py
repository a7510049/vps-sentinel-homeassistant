import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest


os.environ.setdefault("MQTT_HOST", "127.0.0.1")
ROOT = Path(__file__).parents[1]
MONITOR_DIR = ROOT / "vps-monitor"
sys.path.insert(0, str(MONITOR_DIR))
MODULE_PATH = MONITOR_DIR / "vps_monitor.py"
SPEC = importlib.util.spec_from_file_location("vps_monitor_v1", MODULE_PATH)
vps_monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vps_monitor)


class FakeClient:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, **kwargs):
        self.messages.append((topic, json.loads(payload), kwargs))


class V1PublisherTests(unittest.TestCase):
    def publisher(self, client, **overrides):
        values = {
            "enabled": True,
            "node_id": "tokyo-web-01",
            "display_name": "東京網站",
            "agent_version": "0.9.8",
            "capabilities": ["resources.basic", "health.basic"],
        }
        values.update(overrides)
        return vps_monitor.V1Publisher(client, **values)

    def resource_payload(self):
        return {
            "cpu_percent": 12.3,
            "memory_percent": 48.1,
            "memory_used_gb": 0.48,
            "memory_available_gb": 0.52,
            "memory_total_gb": 1.0,
            "reporting": True,
            "last_report": "2026-08-01T10:30:00Z",
        }

    def health_payload(self):
        return {
            "disk_percent": 50.0,
            "disk_used_gb": 10.0,
            "disk_free_gb": 10.0,
            "disk_total_gb": 20.0,
            "load_1": 0.1,
            "load_5": 0.2,
            "load_15": 0.3,
            "uptime_hours": 12.0,
            "boot_time": "2026-08-01T00:00:00Z",
            "security_updates": 0,
            "docker_running": 2,
            "docker_unhealthy": 0,
            "failed_services": "無",
            "country_code": "JP",
            "provider": "Example Cloud",
            "os_name": "Ubuntu 24.04 LTS",
            "resource_overload": False,
            "disk_low": False,
            "service_problem": False,
            "reboot_required": False,
            "health_status": "normal",
            "last_report": "2026-08-01T10:30:00Z",
        }

    def test_disabled_publisher_has_no_side_effect(self):
        client = FakeClient()
        publisher = self.publisher(
            client,
            enabled=False,
            node_id="-legacy-id",
        )
        self.assertIsNone(publisher.publish_resources(self.resource_payload()))
        self.assertEqual(client.messages, [])
        self.assertEqual(publisher.sequence, 0)

    def test_enabled_publisher_rejects_incompatible_legacy_id(self):
        with self.assertRaises(vps_monitor.LegacyCompatibilityError):
            self.publisher(FakeClient(), node_id="-legacy-id")

    def test_publishes_versioned_topics_with_monotonic_sequence(self):
        client = FakeClient()
        publisher = self.publisher(client)
        publisher.publish_resources(self.resource_payload())
        publisher.publish_health(self.health_payload())
        publisher.publish_metadata(self.health_payload())

        self.assertEqual(
            [message[0] for message in client.messages],
            [
                "vps-sentinel/v1/nodes/tokyo-web-01/resources",
                "vps-sentinel/v1/nodes/tokyo-web-01/health",
                "vps-sentinel/v1/nodes/tokyo-web-01/metadata",
            ],
        )
        self.assertEqual(
            [message[1]["sequence"] for message in client.messages],
            [1, 2, 3],
        )
        self.assertEqual(
            [message[2]["qos"] for message in client.messages],
            [0, 1, 1],
        )
        self.assertTrue(all(
            message[2]["retain"] for message in client.messages
        ))
        self.assertTrue(all(
            message[1]["node"]["id"] == "tokyo-web-01"
            for message in client.messages
        ))

    def test_unknown_legacy_fields_are_not_dual_published(self):
        client = FakeClient()
        publisher = self.publisher(client)
        payload = {
            **self.resource_payload(),
            "password": "must-not-leak",
            "future_unknown": 123,
        }
        envelope = publisher.publish_resources(payload)
        self.assertNotIn("password", str(envelope))
        self.assertNotIn("future_unknown", envelope["data"])


if __name__ == "__main__":
    unittest.main()
