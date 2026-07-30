import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


os.environ.setdefault("MQTT_HOST", "127.0.0.1")
MODULE_PATH = Path(__file__).parents[1] / "vps-monitor" / "vps_monitor.py"
SPEC = importlib.util.spec_from_file_location("vps_monitor", MODULE_PATH)
vps_monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vps_monitor)


class MonitorParsingTests(unittest.TestCase):
    def test_security_updates_counts_only_security_origin(self):
        output = "\n".join([
            "Inst openssl [1.0] (1.1 Ubuntu:24.04/noble-security [amd64])",
            "Inst curl [1.0] (1.1 Ubuntu:24.04/noble-updates [amd64])",
            "Conf openssl (1.1 Ubuntu:24.04/noble-security [amd64])",
        ])
        self.assertEqual(vps_monitor.parse_security_updates(output), 1)

    def test_docker_health_counts_running_and_unhealthy(self):
        output = "\n".join([
            "running|Up 2 hours",
            "running|Up 1 minute (unhealthy)",
            "restarting|Restarting (1) 2 seconds ago",
            "exited|Exited (0) 1 hour ago",
        ])
        result = vps_monitor.parse_docker_health(output)
        self.assertTrue(result["available"])
        self.assertEqual(result["running"], 2)
        self.assertEqual(result["unhealthy"], 2)

    def test_os_release_parser_returns_mapping(self):
        self.assertIsInstance(vps_monitor.OS_RELEASE, dict)

    def test_development_version_has_safe_fallback(self):
        self.assertTrue(vps_monitor.installed_version())

    def test_discovery_sensor_tolerates_old_retained_payload(self):
        config = vps_monitor.config_sensor("last_report", "最近回報時間")
        self.assertIn(
            "value_json.get('last_report', 'unknown')",
            config["value_template"],
        )

    def test_discovery_binary_tolerates_missing_field(self):
        config = vps_monitor.config_binary("service_problem", "服務運作狀態")
        self.assertIn(
            "value_json.get('service_problem', false)",
            config["value_template"],
        )

    def test_fast_resource_sensor_uses_expiring_resource_topic(self):
        config = vps_monitor.config_sensor(
            "cpu_percent",
            "CPU 使用率",
            topic=vps_monitor.RESOURCE_STATE,
            expire_after=60,
        )
        self.assertEqual(config["state_topic"], vps_monitor.RESOURCE_STATE)
        self.assertEqual(config["expire_after"], 60)

    def test_health_status_prioritizes_critical_conditions(self):
        self.assertEqual(
            vps_monitor.health_status(False, True, False, False, 0),
            "critical",
        )
        self.assertEqual(
            vps_monitor.health_status(True, False, False, False, 0),
            "warning",
        )
        self.assertEqual(
            vps_monitor.health_status(False, False, False, False, 0),
            "normal",
        )

    @patch.object(vps_monitor, "run", return_value=None)
    def test_security_updates_returns_unknown_on_command_failure(self, _run):
        self.assertEqual(vps_monitor.security_updates(), "unknown")

    @patch.object(vps_monitor, "DOCKER_PRESENT", True)
    @patch.object(
        vps_monitor,
        "run",
        return_value=SimpleNamespace(returncode=1, stdout=""),
    )
    def test_docker_health_returns_unknown_on_command_failure(self, _run):
        result = vps_monitor.docker_health()
        self.assertFalse(result["available"])
        self.assertEqual(result["running"], "unknown")
        self.assertEqual(result["unhealthy"], "unknown")


if __name__ == "__main__":
    unittest.main()
