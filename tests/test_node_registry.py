import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).parents[1]
MONITOR_DIR = ROOT / "vps-monitor"
CONTROLLER_DIR = ROOT / "controller"
sys.path.insert(0, str(MONITOR_DIR))

CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "node_contract",
    MONITOR_DIR / "node_contract.py",
)
node_contract = importlib.util.module_from_spec(CONTRACT_SPEC)
CONTRACT_SPEC.loader.exec_module(node_contract)
sys.modules["node_contract"] = node_contract

REGISTRY_SPEC = importlib.util.spec_from_file_location(
    "node_registry",
    CONTROLLER_DIR / "node_registry.py",
)
node_registry = importlib.util.module_from_spec(REGISTRY_SPEC)
REGISTRY_SPEC.loader.exec_module(node_registry)


UTC = timezone.utc
START = datetime(2026, 8, 1, 10, 30, tzinfo=UTC)


class NodeRegistryTests(unittest.TestCase):
    def setUp(self):
        self.now = START
        self.registry = node_registry.NodeRegistry(
            clock=lambda: self.now,
            stream_ttls={"resources": 60, "health": 600, "metadata": 86400},
            offline_after=90,
        )

    def envelope(
        self,
        *,
        node_id="tokyo-web-01",
        message_type="resources",
        sequence=1,
        observed_at=START,
        data=None,
        display_name="東京網站",
    ):
        default_data = (
            {"status": "online"}
            if message_type == "availability"
            else {"cpu_percent": 12.3}
        )
        return node_contract.build_envelope(
            node_id=node_id,
            display_name=display_name,
            agent_version="1.0.0-alpha.1",
            message_type=message_type,
            observed_at=observed_at,
            sequence=sequence,
            capabilities=["health.basic", "resources.basic"],
            data=default_data if data is None else data,
            provider="Example Cloud",
            labels={"environment": "test"},
        )

    def ingest(self, envelope, credential_id="credential-a", topic_node=None):
        node_id = topic_node or envelope["node"]["id"]
        topic = node_contract.topic_for(node_id, envelope["message_type"])
        return self.registry.ingest(
            topic,
            json.dumps(envelope, ensure_ascii=False),
            credential_id=credential_id,
            received_at=self.now,
        )

    def test_keeps_multiple_sources_isolated_and_sorted(self):
        tokyo = self.envelope(node_id="tokyo-web-01")
        frankfurt = self.envelope(
            node_id="frankfurt-db-01",
            display_name="法蘭克福資料庫",
        )
        self.ingest(tokyo, credential_id="credential-tokyo")
        self.ingest(frankfurt, credential_id="credential-frankfurt")
        snapshot = self.registry.snapshot()
        self.assertEqual(
            [item["node"]["id"] for item in snapshot],
            ["frankfurt-db-01", "tokyo-web-01"],
        )
        self.assertEqual(
            snapshot[0]["streams"]["resources"]["data"]["cpu_percent"],
            12.3,
        )

    def test_rejects_topic_identity_or_stream_mismatch(self):
        envelope = self.envelope(node_id="tokyo-web-01")
        with self.assertRaises(node_registry.IdentityMismatchError):
            self.ingest(envelope, topic_node="frankfurt-db-01")
        wrong_stream = node_contract.topic_for("tokyo-web-01", "health")
        with self.assertRaises(node_registry.IdentityMismatchError):
            self.registry.ingest(
                wrong_stream,
                json.dumps(envelope),
                credential_id="credential-a",
            )

    def test_rejects_same_node_from_another_credential(self):
        envelope = self.envelope()
        self.ingest(envelope, credential_id="credential-a")
        with self.assertRaises(node_registry.DuplicateNodeError):
            self.ingest(
                self.envelope(sequence=2, observed_at=START + timedelta(seconds=15)),
                credential_id="credential-b",
            )
        self.assertNotIn("credential", str(self.registry.snapshot()))

    def test_replay_does_not_replace_newer_stream_state(self):
        self.ingest(self.envelope(sequence=2, data={"cpu_percent": 20.0}))
        with self.assertRaises(node_registry.StaleMessageError):
            self.ingest(self.envelope(sequence=1, data={"cpu_percent": 99.0}))
        stored = self.registry.node("tokyo-web-01")
        self.assertEqual(
            stored["streams"]["resources"]["data"]["cpu_percent"],
            20.0,
        )

    def test_agent_restart_may_reset_sequence_when_observation_is_newer(self):
        self.ingest(self.envelope(sequence=50))
        self.now += timedelta(minutes=1)
        result = self.ingest(
            self.envelope(
                sequence=1,
                observed_at=self.now,
                data={"cpu_percent": 15.0},
            )
        )
        self.assertEqual(result["streams"]["resources"]["sequence"], 1)

    def test_offline_and_stale_are_distinct_states(self):
        self.ingest(self.envelope(message_type="resources"))
        self.ingest(
            self.envelope(
                message_type="health",
                sequence=2,
                data={"health_status": "normal"},
            )
        )
        self.ingest(self.envelope(message_type="metadata", sequence=3))
        healthy = self.registry.node("tokyo-web-01")
        self.assertTrue(healthy["online"])
        self.assertEqual(healthy["status"], "normal")

        self.now += timedelta(seconds=61)
        stale = self.registry.node("tokyo-web-01")
        self.assertTrue(stale["online"])
        self.assertEqual(stale["status"], "stale")
        self.assertIn("resources", stale["stale_streams"])

        self.now += timedelta(seconds=30)
        offline = self.registry.node("tokyo-web-01")
        self.assertFalse(offline["online"])
        self.assertEqual(offline["status"], "offline")

    def test_explicit_availability_offline_wins_immediately(self):
        self.ingest(self.envelope())
        self.ingest(
            self.envelope(
                message_type="availability",
                sequence=2,
                data={"status": "offline"},
            )
        )
        result = self.registry.node("tokyo-web-01")
        self.assertFalse(result["online"])
        self.assertEqual(result["status"], "offline")

    def test_rejects_unknown_schema_fields_and_large_payload(self):
        envelope = self.envelope()
        envelope["credential"] = "must-not-be-accepted"
        with self.assertRaises(node_registry.RegistryError):
            self.ingest(envelope)
        with self.assertRaisesRegex(node_registry.RegistryError, "64 KiB"):
            self.registry.ingest(
                node_contract.topic_for("tokyo-web-01", "resources"),
                "x" * 65537,
                credential_id="credential-a",
            )


if __name__ == "__main__":
    unittest.main()
