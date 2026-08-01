import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
MONITOR_DIR = ROOT / "vps-monitor"
CONTROLLER_DIR = ROOT / "controller"
sys.path.insert(0, str(MONITOR_DIR))
sys.path.insert(0, str(CONTROLLER_DIR))

SPEC = importlib.util.spec_from_file_location(
    "apply_agent_config",
    CONTROLLER_DIR / "apply_agent_config.py",
)
apply_agent_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(apply_agent_config)

from enrollment import Enrollment
from enrollment_bundle import create_bundle, write_bundle


NOW = datetime(2026, 8, 1, 10, 30, tzinfo=timezone.utc)


class ApplyAgentConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        installer = self.repo / "vps-monitor" / "install.sh"
        installer.parent.mkdir(parents=True)
        installer.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        self.bundle_path = self.root / "agent.json"
        bundle = create_bundle(
            Enrollment(
                node_id="tokyo-web-01",
                username="vps-node-tokyo-web-01",
                password='secret-with-"quotes"',
            ),
            display_name="東京網站",
            broker_host="controller.example.ts.net",
            now=NOW,
            lifetime_seconds=900,
        )
        write_bundle(self.bundle_path, bundle)
        self.env_path = self.root / "etc" / "vps-monitor.env"
        self.ca_path = self.root / "etc" / "agent-ca.crt"

    def tearDown(self):
        self.temporary.cleanup()

    def run_main(self, returncode=0):
        with (
            patch.object(apply_agent_config, "ENV_PATH", self.env_path),
            patch.object(apply_agent_config, "CA_PATH", self.ca_path),
            patch.object(apply_agent_config.os, "geteuid", return_value=0),
            patch.object(
                apply_agent_config.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=returncode),
            ) as process,
            patch.object(
                sys,
                "argv",
                [
                    "apply_agent_config.py",
                    str(self.bundle_path),
                    "--repo-root",
                    str(self.repo),
                ],
            ),
            patch.object(
                apply_agent_config,
                "load_bundle",
                side_effect=lambda path: __import__(
                    "enrollment_bundle"
                ).load_bundle(path, now=NOW),
            ),
        ):
            apply_agent_config.main()
        return process

    def test_success_writes_secure_env_enables_v1_and_consumes_bundle(self):
        process = self.run_main()
        environment = self.env_path.read_text(encoding="utf-8")
        self.assertEqual(stat.S_IMODE(self.env_path.stat().st_mode), 0o600)
        self.assertIn('VPS_ID="tokyo-web-01"', environment)
        self.assertIn('MQTT_USERNAME="vps-node-tokyo-web-01"', environment)
        self.assertIn('PUBLISH_V1_CONTRACT="true"', environment)
        self.assertIn('MQTT_PASSWORD="secret-with-\\"quotes\\""', environment)
        self.assertFalse(self.bundle_path.exists())
        call_environment = process.call_args.kwargs["env"]
        self.assertEqual(
            call_environment["VPS_SENTINEL_NONINTERACTIVE"],
            "true",
        )

    def test_failed_install_restores_previous_env_and_keeps_bundle(self):
        self.env_path.parent.mkdir(parents=True)
        self.env_path.write_text("OLD=1\n", encoding="utf-8")
        self.env_path.chmod(0o600)
        with self.assertRaises(SystemExit):
            self.run_main(returncode=1)
        self.assertEqual(
            self.env_path.read_text(encoding="utf-8"),
            "OLD=1\n",
        )
        self.assertTrue(self.bundle_path.exists())

    def test_rejects_bundle_readable_by_group_or_others(self):
        self.bundle_path.chmod(0o644)
        with (
            patch.object(apply_agent_config.os, "geteuid", return_value=0),
            patch.object(
                sys,
                "argv",
                ["apply_agent_config.py", str(self.bundle_path)],
            ),
        ):
            with self.assertRaisesRegex(SystemExit, "0600"):
                apply_agent_config.main()


if __name__ == "__main__":
    unittest.main()
