import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "vps-monitor" / "node_contract.py"
SCHEMA_PATH = ROOT / "docs" / "schema" / "node-message-v1.schema.json"
SPEC = importlib.util.spec_from_file_location("node_contract", MODULE_PATH)
node_contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(node_contract)


class NodeContractTests(unittest.TestCase):
    def build(self, **overrides):
        values = {
            "node_id": "tokyo-web-01",
            "display_name": "東京網站",
            "agent_version": "1.0.0-alpha.1",
            "message_type": "resources",
            "observed_at": "2026-08-01T10:30:00+08:00",
            "sequence": 42,
            "capabilities": ["resources.basic", "network.throughput"],
            "data": {"cpu_percent": 12.3, "memory_percent": 48.1},
            "provider": "Example Cloud",
            "region": "jp-east",
            "labels": {"role": "web", "environment": "production"},
        }
        values.update(overrides)
        return node_contract.build_envelope(**values)

    def test_builds_deterministic_serializable_envelope(self):
        envelope = self.build(
            capabilities=["resources.basic", "network.throughput", "resources.basic"],
            labels={"role": "web", "environment": "production"},
        )
        self.assertEqual(envelope["schema_version"], "1.0")
        self.assertEqual(envelope["observed_at"], "2026-08-01T02:30:00Z")
        self.assertEqual(
            envelope["node"]["capabilities"],
            ["network.throughput", "resources.basic"],
        )
        self.assertEqual(
            list(envelope["node"]["labels"]),
            ["environment", "role"],
        )
        json.dumps(envelope, ensure_ascii=False)

    def test_node_id_is_stable_when_display_name_changes(self):
        original = self.build(display_name="東京網站")
        renamed = self.build(display_name="主要網站")
        self.assertEqual(original["node"]["id"], renamed["node"]["id"])
        self.assertEqual(
            node_contract.topic_for(original["node"]["id"], "resources"),
            node_contract.topic_for(renamed["node"]["id"], "resources"),
        )

    def test_topic_uses_versioned_namespace_and_event_plural(self):
        self.assertEqual(
            node_contract.topic_for("tokyo-web-01", "health"),
            "vps-sentinel/v1/nodes/tokyo-web-01/health",
        )
        self.assertEqual(
            node_contract.topic_for("tokyo-web-01", "event"),
            "vps-sentinel/v1/nodes/tokyo-web-01/events",
        )

    def test_rejects_invalid_node_ids_without_rewriting(self):
        invalid_ids = [
            "",
            "Tokyo",
            "-tokyo",
            "tokyo-",
            "tokyo/web",
            "tokyo web",
            "a" * 65,
        ]
        for node_id in invalid_ids:
            with self.subTest(node_id=node_id):
                with self.assertRaises(node_contract.ContractError):
                    node_contract.validate_node_id(node_id)

    def test_requires_timezone_and_normalizes_datetime_to_utc(self):
        with self.assertRaises(node_contract.ContractError):
            self.build(observed_at="2026-08-01T10:30:00")
        value = datetime(
            2026,
            8,
            1,
            10,
            30,
            tzinfo=timezone(timedelta(hours=8)),
        )
        self.assertEqual(
            self.build(observed_at=value)["observed_at"],
            "2026-08-01T02:30:00Z",
        )

    def test_rejects_sensitive_fields_at_any_depth(self):
        for data in [
            {"password": "example"},
            {"connection": {"mqtt-password": "example"}},
            {"items": [{"private_key": "example"}]},
            {"authorization": "Bearer example"},
        ]:
            with self.subTest(data=data):
                with self.assertRaises(node_contract.ContractError):
                    self.build(data=data)

    def test_rejects_invalid_sequence_message_type_and_data(self):
        for sequence in [-1, True, 1.5]:
            with self.subTest(sequence=sequence):
                with self.assertRaises(node_contract.ContractError):
                    self.build(sequence=sequence)
        with self.assertRaises(node_contract.ContractError):
            self.build(message_type="command")
        with self.assertRaises(node_contract.ContractError):
            self.build(data=[])

    def test_contract_schema_matches_implementation_constants(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            node_contract.SCHEMA_VERSION,
        )
        self.assertEqual(
            set(schema["properties"]["message_type"]["enum"]),
            node_contract.MESSAGE_TYPES,
        )
        envelope = self.build()
        self.assertEqual(set(envelope), set(schema["required"]))
        self.assertTrue(set(envelope["node"]).issubset(
            set(schema["properties"]["node"]["properties"])
        ))


if __name__ == "__main__":
    unittest.main()
