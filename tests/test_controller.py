import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
MONITOR_DIR = ROOT / "vps-monitor"
CONTROLLER_DIR = ROOT / "controller"
sys.path.insert(0, str(MONITOR_DIR))
sys.path.insert(0, str(CONTROLLER_DIR))

SPEC = importlib.util.spec_from_file_location(
    "controller_runtime",
    CONTROLLER_DIR / "controller.py",
)
controller = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(controller)

from enrollment import EnrollmentStore
from node_contract import build_envelope, topic_for
from node_registry import NodeRegistry


UTC = timezone.utc
START = datetime(2026, 8, 1, 10, 30, tzinfo=UTC)


class FakeClient:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, **kwargs):
        self.messages.append((topic, json.loads(payload), kwargs))


class ControllerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = EnrollmentStore(
            Path(self.temporary.name) / "enrollments.json"
        )
        self.now = START
        self.client = FakeClient()
        self.registry = NodeRegistry(
            clock=lambda: self.now,
            stream_ttls={"resources": 60, "health": 600, "metadata": 86400},
            offline_after=90,
        )
        self.runtime = controller.ControllerRuntime(
            self.client,
            self.registry,
            self.store,
            clock=lambda: self.now,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def envelope(
        self,
        message_type="resources",
        *,
        node_id="tokyo-web-01",
        sequence=1,
        data=None,
    ):
        defaults = {
            "resources": {"cpu_percent": 12.3},
            "health": {"health_status": "normal"},
            "metadata": {"os_name": "Ubuntu 24.04 LTS"},
            "availability": {"status": "online"},
        }
        return build_envelope(
            node_id=node_id,
            display_name=node_id,
            agent_version="1.0.0-alpha.1",
            message_type=message_type,
            observed_at=self.now,
            sequence=sequence,
            capabilities=["health.basic", "resources.basic"],
            data=defaults[message_type] if data is None else data,
            labels={"environment": "test"},
        )

    def send(self, envelope):
        return self.runtime.handle_message(
            topic_for(
                envelope["node"]["id"],
                envelope["message_type"],
            ),
            json.dumps(envelope, ensure_ascii=False),
        )

    def enroll(self, node_id="tokyo-web-01"):
        self.store.register(node_id, node_id, now=self.now)

    def send_healthy_node(self, node_id="tokyo-web-01"):
        self.enroll(node_id)
        self.send(self.envelope("resources", node_id=node_id, sequence=1))
        self.send(self.envelope("health", node_id=node_id, sequence=2))
        self.send(self.envelope("metadata", node_id=node_id, sequence=3))

    def test_rejects_unenrolled_node_before_registry_update(self):
        self.assertFalse(self.send(self.envelope()))
        self.assertEqual(self.runtime.rejected_messages, 1)
        self.assertEqual(self.registry.snapshot(), [])
        self.assertEqual(self.client.messages, [])

    def test_accepts_enrolled_node_and_publishes_sanitized_fleet(self):
        self.send_healthy_node()
        self.assertEqual(self.runtime.accepted_messages, 3)
        topic, fleet, options = self.client.messages[-1]
        self.assertEqual(topic, "vps-sentinel/v1/controller/fleet")
        self.assertEqual(fleet["schema_version"], "1.0")
        self.assertEqual(fleet["node_count"], 1)
        self.assertEqual(fleet["online_count"], 1)
        self.assertEqual(fleet["problem_count"], 0)
        self.assertEqual(options, {"qos": 1, "retain": True})
        serialized = json.dumps(fleet)
        self.assertNotIn("credential", serialized)
        self.assertNotIn("password", serialized)
        self.assertNotIn("vps-node-", serialized)

    def test_snapshot_only_republishes_when_public_state_changes(self):
        self.send_healthy_node()
        publish_count = len(self.client.messages)
        self.now += timedelta(seconds=30)
        self.assertFalse(self.runtime.publish_snapshot())
        self.assertEqual(len(self.client.messages), publish_count)

        self.now += timedelta(seconds=31)
        self.assertTrue(self.runtime.publish_snapshot())
        fleet = self.client.messages[-1][1]
        self.assertEqual(fleet["nodes"][0]["status"], "stale")
        self.assertEqual(fleet["problem_count"], 1)

    def test_combines_multiple_enrolled_sources(self):
        self.send_healthy_node("tokyo-web-01")
        self.send_healthy_node("frankfurt-db-01")
        fleet = self.runtime.snapshot()
        self.assertEqual(fleet["node_count"], 2)
        self.assertEqual(fleet["online_count"], 2)
        self.assertEqual(
            [node["node"]["id"] for node in fleet["nodes"]],
            ["frankfurt-db-01", "tokyo-web-01"],
        )

    def test_bad_json_is_counted_and_does_not_replace_snapshot(self):
        self.enroll()
        topic = topic_for("tokyo-web-01", "resources")
        self.assertFalse(self.runtime.handle_message(topic, b"{invalid"))
        self.assertEqual(self.runtime.rejected_messages, 1)
        self.assertEqual(self.registry.snapshot(), [])


if __name__ == "__main__":
    unittest.main()
