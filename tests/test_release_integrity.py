from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
CARD = (ROOT / "home-assistant/www/vps-sentinel-apple-card.js").read_text(encoding="utf-8")
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
SETUP = (ROOT / "setup.sh").read_text(encoding="utf-8")
APPLE = (ROOT / "scripts/apple-dashboard.sh").read_text(encoding="utf-8")
BACKUP = (ROOT / "scripts/backup.sh").read_text(encoding="utf-8")
DOCTOR = (ROOT / "scripts/doctor.sh").read_text(encoding="utf-8")
UPGRADE = (ROOT / "scripts/upgrade.sh").read_text(encoding="utf-8")
RELEASE = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")


class StabilityPreparationTests(unittest.TestCase):
    def test_release_version_surfaces_are_consistent(self):
        self.assertEqual(VERSION, "0.9.8")
        self.assertIn(f'const CARD_VERSION = "{VERSION}";', CARD)
        self.assertIn(f"## {VERSION}", CHANGELOG)

    def test_setup_verifies_mqtt_and_preserves_credentials(self):
        self.assertIn("wait_for_monitor_mqtt", SETUP)
        self.assertIn("MQTT 認證與在線資料正常", SETUP)
        self.assertIn("write_credentials", SETUP)
        self.assertIn("已同步 VPS Monitor MQTT 密碼", SETUP)
        self.assertIn("use_x_forwarded_for: true", SETUP)
        self.assertIn('    - "::1"', SETUP)

    def test_apple_resource_url_uses_installed_version(self):
        self.assertIn('VERSION_FILE="/opt/vps-monitor/.version"', APPLE)
        self.assertIn("resource_url()", APPLE)
        self.assertNotIn('RESOURCE_URL="/local/', APPLE)
        self.assertIn("不需要重新啟動 Home Assistant", APPLE)

    def test_apple_dashboard_includes_maintenance_event(self):
        self.assertIn("maintenanceEvent:", APPLE)
        self.assertIn("commandTopic:", APPLE)

    def test_backup_includes_compose_and_mqtt_identity(self):
        self.assertIn('${HA_DIR}/compose.yaml', BACKUP)
        self.assertIn('readonly MQTT_PASSWD="/etc/mosquitto/passwd"', BACKUP)
        self.assertIn('echo "format=2"', BACKUP)
        self.assertIn("mqtt_probe", BACKUP)
        self.assertIn("format=(1|2)", BACKUP)

    def test_doctor_uses_live_mqtt_probe_and_safe_repairs(self):
        self.assertIn("mosquitto_sub", DOCTOR)
        self.assertIn("同步 VPS Monitor MQTT 密碼", DOCTOR)
        self.assertIn("清除 Home Assistant IP 封鎖", DOCTOR)
        self.assertIn("Tailscale Serve", DOCTOR)
        self.assertIn("Apple 卡片已同步", DOCTOR)

    def test_upgrade_validates_runtime_and_frontend(self):
        self.assertIn("mqtt_probe", UPGRADE)
        self.assertIn("CARD_TARGET", UPGRADE)
        self.assertIn("Apple 卡片版本", UPGRADE)
        self.assertIn("MQTT 認證與在線資料均已驗證", UPGRADE)

    def test_release_runs_validation_before_publish(self):
        self.assertIn("Run Python tests", RELEASE)
        self.assertIn("Check release consistency", RELEASE)
        self.assertLess(
            RELEASE.index("Run Python tests"),
            RELEASE.index("Publish GitHub Release"),
        )


if __name__ == "__main__":
    unittest.main()
