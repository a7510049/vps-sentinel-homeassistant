import importlib.util
from pathlib import Path
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
    "bootstrap_migration",
    CONTROLLER_DIR / "bootstrap.py",
)
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)

from broker_policy import BrokerPolicyError
from enrollment import EnrollmentStore


class FakeTransaction:
    calls = []
    fail_on = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def apply(self, **kwargs):
        self.__class__.calls.append(kwargs)
        if self.__class__.fail_on == len(self.__class__.calls):
            raise BrokerPolicyError("injected broker failure")
        return True


class CombinedAgentMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        component = self.repo / "controller" / "install-component.sh"
        component.parent.mkdir(parents=True)
        component.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        self.monitor_env = self.root / "etc" / "vps-monitor.env"
        self.monitor_env.parent.mkdir(parents=True)
        self.monitor_env.write_text(
            'MQTT_HOST="127.0.0.1"\n'
            'MQTT_PORT="1883"\n'
            'MQTT_USERNAME="vps-monitor"\n'
            'MQTT_PASSWORD="legacy-secret"\n'
            'VPS_ID="local-vps-01"\n'
            'VPS_NAME="本機 VPS"\n'
            'PUBLISH_V1_CONTRACT="false"\n',
            encoding="utf-8",
        )
        self.monitor_env.chmod(0o600)
        self.controller_env = self.root / "etc" / "controller.env"
        self.store_path = self.root / "data" / "enrollments.json"
        FakeTransaction.calls = []
        FakeTransaction.fail_on = None

    def tearDown(self):
        self.temporary.cleanup()

    def run_main(self, run_side_effect=None):
        def successful_run(command, **_kwargs):
            if run_side_effect:
                result = run_side_effect(command)
                if result is not None:
                    return result
            return SimpleNamespace(returncode=0)

        with (
            patch.object(bootstrap, "CONTROLLER_ENV", self.controller_env),
            patch.object(bootstrap, "MONITOR_ENV", self.monitor_env),
            patch.object(bootstrap, "STORE_PATH", self.store_path),
            patch.object(bootstrap.os, "geteuid", return_value=0),
            patch.object(
                bootstrap.secrets,
                "token_urlsafe",
                side_effect=["controller-secret", "node-secret"],
            ),
            patch.object(bootstrap, "run", side_effect=successful_run),
            patch.object(
                bootstrap,
                "BrokerFilesTransaction",
                FakeTransaction,
            ),
            patch.object(bootstrap.shutil, "chown"),
            patch.object(
                sys,
                "argv",
                [
                    "bootstrap.py",
                    "--repo-root",
                    str(self.repo),
                ],
            ),
        ):
            bootstrap.main()

    def test_first_run_switches_agent_then_revokes_shared_username(self):
        self.run_main()
        values = bootstrap.read_environment(self.monitor_env)
        self.assertEqual(
            values["MQTT_USERNAME"],
            "vps-node-local-vps-01",
        )
        self.assertEqual(values["MQTT_PASSWORD"], "node-secret")
        self.assertEqual(values["PUBLISH_V1_CONTRACT"], "true")
        store = EnrollmentStore(self.store_path)
        self.assertEqual(
            store.credential_for("local-vps-01"),
            "vps-node-local-vps-01",
        )
        self.assertEqual(len(FakeTransaction.calls), 2)
        transition = FakeTransaction.calls[0]["acl_text"]
        self.assertIn("user vps-monitor", transition)
        self.assertIn("user vps-node-local-vps-01", transition)
        final = FakeTransaction.calls[1]
        self.assertEqual(final["remove_usernames"], ["vps-monitor"])
        self.assertNotIn("user vps-monitor\n", final["acl_text"])

    def test_initial_broker_failure_restores_unmigrated_state(self):
        FakeTransaction.fail_on = 1
        with self.assertRaisesRegex(SystemExit, "injected broker failure"):
            self.run_main()
        values = bootstrap.read_environment(self.monitor_env)
        self.assertEqual(values["MQTT_USERNAME"], "vps-monitor")
        self.assertEqual(values["PUBLISH_V1_CONTRACT"], "false")
        self.assertFalse(self.store_path.exists())

    def test_agent_restart_failure_compensates_store_acl_and_env(self):
        def fail_agent_restart(command):
            if command[:3] == ["systemctl", "restart", "vps-monitor"]:
                return SimpleNamespace(returncode=1)
            return None

        with self.assertRaisesRegex(
            SystemExit,
            "node credential",
        ):
            self.run_main(run_side_effect=fail_agent_restart)
        values = bootstrap.read_environment(self.monitor_env)
        self.assertEqual(values["MQTT_USERNAME"], "vps-monitor")
        self.assertEqual(values["MQTT_PASSWORD"], "legacy-secret")
        self.assertFalse(self.store_path.exists())
        self.assertEqual(len(FakeTransaction.calls), 2)
        compensation = FakeTransaction.calls[-1]
        self.assertEqual(
            compensation["remove_usernames"],
            ["vps-node-local-vps-01"],
        )
        self.assertIn("user vps-monitor", compensation["acl_text"])

    def test_binding_helper_deduplicates_one_username(self):
        self.assertEqual(
            bootstrap._bindings(
                ("vps-node-a", "node-a"),
                ("vps-node-a", "node-a"),
            ),
            {"vps-node-a": ["node-a"]},
        )

    def test_rerun_preserves_node_credential_and_is_safe(self):
        self.run_main()
        first_values = bootstrap.read_environment(self.monitor_env)
        first_store = self.store_path.read_bytes()
        FakeTransaction.calls = []

        self.run_main()

        self.assertEqual(
            bootstrap.read_environment(self.monitor_env),
            first_values,
        )
        self.assertEqual(self.store_path.read_bytes(), first_store)
        self.assertEqual(len(FakeTransaction.calls), 2)
        self.assertEqual(
            FakeTransaction.calls[-1]["remove_usernames"],
            ["vps-monitor"],
        )


if __name__ == "__main__":
    unittest.main()
