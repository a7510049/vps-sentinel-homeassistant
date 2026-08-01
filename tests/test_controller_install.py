from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
INSTALLER = (ROOT / "controller" / "install-component.sh").read_text(
    encoding="utf-8"
)
SERVICE = (ROOT / "controller" / "vps-sentinel-controller.service").read_text(
    encoding="utf-8"
)
REQUIREMENTS = (ROOT / "controller" / "requirements.txt").read_text(
    encoding="utf-8"
)


class ControllerInstallTests(unittest.TestCase):
    def test_service_uses_dedicated_unprivileged_account(self):
        self.assertIn("User=vps-sentinel-controller", SERVICE)
        self.assertIn("Group=vps-sentinel-controller", SERVICE)
        self.assertIn("NoNewPrivileges=true", SERVICE)
        self.assertIn("CapabilityBoundingSet=", SERVICE)
        self.assertIn("ProtectSystem=strict", SERVICE)
        self.assertIn(
            "ReadWritePaths=/var/lib/vps-sentinel-controller",
            SERVICE,
        )

    def test_service_paths_follow_one_fixed_layout(self):
        self.assertIn(
            "EnvironmentFile=/etc/vps-sentinel-controller.env",
            SERVICE,
        )
        self.assertIn(
            "WorkingDirectory=/opt/vps-sentinel-controller",
            SERVICE,
        )
        self.assertIn(
            "/opt/vps-sentinel-controller/venv/bin/python "
            "/opt/vps-sentinel-controller/controller.py",
            SERVICE,
        )

    def test_installer_deploys_every_runtime_module(self):
        for module in [
            "controller.py",
            "enrollment.py",
            "node_registry.py",
            "node_contract.py",
        ]:
            with self.subTest(module=module):
                self.assertIn(module, INSTALLER)
        self.assertIn("python3 -m venv --clear", INSTALLER)
        self.assertIn(".requirements.sha256", INSTALLER)
        self.assertIn("-m py_compile", INSTALLER)

    def test_installer_preserves_existing_credentials_and_permissions(self):
        self.assertIn('if [[ ! -f "${ENV_FILE}" ]]', INSTALLER)
        self.assertIn("不覆寫 MQTT 憑證", INSTALLER)
        self.assertIn('chmod 0600 "${ENV_FILE}"', INSTALLER)
        self.assertIn(
            'install -d -m 0700 -o "${SERVICE_USER}"',
            INSTALLER,
        )
        self.assertNotIn("CONTROLLER_MQTT_PASSWORD", SERVICE)

    def test_controller_dependency_is_pinned(self):
        self.assertEqual(REQUIREMENTS.strip(), "paho-mqtt==2.1.0")


if __name__ == "__main__":
    unittest.main()
