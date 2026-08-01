import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).parents[1]
MONITOR_DIR = ROOT / "vps-monitor"
sys.path.insert(0, str(MONITOR_DIR))
MODULE_PATH = MONITOR_DIR / "legacy_adapter.py"
SPEC = importlib.util.spec_from_file_location("legacy_adapter", MODULE_PATH)
legacy_adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(legacy_adapter)


class LegacyAdapterTests(unittest.TestCase):
    def setUp(self):
        self.capabilities = legacy_adapter.legacy_capabilities(
            monitor_network=True,
            docker_present=True,
            remote_actions=False,
        )
        self.resource_payload = {
            "cpu_percent": 12.3,
            "memory_percent": 48.1,
            "memory_used_gb": 0.48,
            "memory_available_gb": 0.52,
            "memory_total_gb": 1.0,
            "download_mbps": 1.25,
            "upload_mbps": 0.25,
            "reporting": True,
            "last_report": "2026-08-01T10:30:00+00:00",
        }
        self.status_payload = {
            "disk_percent": 50.0,
            "disk_used_gb": 10.0,
            "disk_free_gb": 10.0,
            "disk_total_gb": 20.0,
            "load_1": 0.1,
            "load_5": 0.2,
            "load_15": 0.3,
            "uptime_hours": 12.0,
            "boot_time": "2026-08-01T00:00:00+00:00",
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
            "last_report": "2026-08-01T10:30:00+00:00",
        }

    def common(self):
        return {
            "vps_id": "tokyo-web-01",
            "display_name": "東京網站",
            "agent_version": "0.9.8",
            "sequence": 1,
            "capabilities": self.capabilities,
        }

    def test_resource_mapping_uses_allowlist(self):
        payload = {
            **self.resource_payload,
            "password": "must-not-leak",
            "provider": "not-a-resource-field",
            "future_unknown": 123,
        }
        envelope = legacy_adapter.resource_envelope(
            **self.common(),
            payload=payload,
        )
        self.assertEqual(envelope["message_type"], "resources")
        self.assertEqual(
            set(envelope["data"]),
            set(self.resource_payload) - {"last_report"},
        )
        self.assertNotIn("password", str(envelope))
        self.assertNotIn("future_unknown", envelope["data"])

    def test_health_mapping_separates_node_metadata(self):
        envelope = legacy_adapter.health_envelope(
            **self.common(),
            payload=self.status_payload,
        )
        self.assertEqual(envelope["message_type"], "health")
        self.assertEqual(envelope["node"]["provider"], "Example Cloud")
        self.assertEqual(envelope["node"]["labels"]["country_code"], "jp")
        self.assertNotIn("provider", envelope["data"])
        self.assertNotIn("country_code", envelope["data"])
        self.assertNotIn("os_name", envelope["data"])

    def test_metadata_mapping_is_small_and_explicit(self):
        envelope = legacy_adapter.metadata_envelope(
            **self.common(),
            status_payload={
                **self.status_payload,
                "mqtt_password": "must-not-leak",
                "future_unknown": "must-not-leak",
            },
            architecture="x86_64",
        )
        self.assertEqual(envelope["message_type"], "metadata")
        self.assertEqual(
            envelope["data"],
            {
                "os_name": "Ubuntu 24.04 LTS",
                "architecture": "x86_64",
            },
        )
        self.assertNotIn("mqtt_password", str(envelope))
        self.assertNotIn("future_unknown", str(envelope))

    def test_missing_last_report_requires_explicit_observed_time(self):
        payload = dict(self.resource_payload)
        payload.pop("last_report")
        with self.assertRaises(legacy_adapter.LegacyCompatibilityError):
            legacy_adapter.resource_envelope(
                **self.common(),
                payload=payload,
            )
        envelope = legacy_adapter.resource_envelope(
            **self.common(),
            payload=payload,
            observed_at="2026-08-01T10:30:00Z",
        )
        self.assertEqual(envelope["observed_at"], "2026-08-01T10:30:00Z")

    def test_incompatible_legacy_id_is_not_silently_rewritten(self):
        with self.assertRaisesRegex(
            legacy_adapter.LegacyCompatibilityError,
            "不會自動改寫識別碼",
        ):
            legacy_adapter.migration_node_id("-legacy-id")

    def test_capabilities_match_enabled_legacy_features(self):
        self.assertEqual(
            legacy_adapter.legacy_capabilities(
                monitor_network=True,
                docker_present=True,
                remote_actions=True,
            ),
            [
                "health.basic",
                "resources.basic",
                "network.throughput",
                "runtime.docker",
                "maintenance.actions",
            ],
        )
        self.assertEqual(
            legacy_adapter.legacy_capabilities(
                monitor_network=False,
                docker_present=False,
                remote_actions=False,
            ),
            ["health.basic", "resources.basic"],
        )


if __name__ == "__main__":
    unittest.main()
