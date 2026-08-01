import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "controller"))

from install_config import InstallConfigError, load_install_config, preflight


class InstallConfigTests(unittest.TestCase):
    def write(self, value):
        temporary = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
        )
        json.dump(value, temporary, ensure_ascii=False)
        temporary.close()
        self.addCleanup(Path(temporary.name).unlink, missing_ok=True)
        return temporary.name

    def test_controller_config_is_minimal_and_strict(self):
        path = self.write({"install_version": 1, "role": "controller"})
        self.assertEqual(
            load_install_config(path),
            {"kind": "deployment", "role": "controller"},
        )

    def test_combined_config_carries_node_defaults(self):
        path = self.write({
            "install_version": 1,
            "role": "combined",
            "node": {
                "id": "taipei-web-01",
                "display_name": "台北網站",
                "profile": "balanced",
            },
        })
        config = load_install_config(path)
        self.assertEqual(config["node_id"], "taipei-web-01")
        self.assertEqual(config["node_name"], "台北網站")
        self.assertEqual(config["profile"], "balanced")

    def test_unknown_fields_are_rejected(self):
        path = self.write({
            "install_version": 1,
            "role": "controller",
            "password": "must-not-be-accepted",
        })
        with self.assertRaisesRegex(InstallConfigError, "fields"):
            load_install_config(path)

    def test_agent_bundle_is_classified_without_consuming_it(self):
        path = self.write({"bundle_version": 1, "role": "agent"})
        self.assertEqual(
            load_install_config(path),
            {"kind": "agent", "role": "agent"},
        )

    @patch("install_config.shutil.disk_usage")
    @patch("install_config._memory_mb", return_value=2048)
    @patch("install_config.Path.read_text")
    @patch("install_config.shutil.which", return_value="/usr/bin/tailscale")
    @patch("install_config.subprocess.run")
    def test_preflight_reports_role_and_external_requirements(
        self,
        run,
        _which,
        read_text,
        _memory,
        disk_usage,
    ):
        run.return_value.returncode = 0
        run.return_value.stdout = "100.64.0.1\n"
        read_text.return_value = 'ID="ubuntu"\nVERSION_ID="24.04"\n'
        disk_usage.return_value.free = 8 * 1024 * 1024 * 1024
        report = preflight("controller")
        self.assertTrue(report["ok"])
        self.assertEqual(report["role"], "controller")
        self.assertEqual(
            {check["name"] for check in report["checks"]},
            {"operating_system", "memory", "disk", "tailscale_session"},
        )


if __name__ == "__main__":
    unittest.main()
