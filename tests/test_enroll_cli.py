import importlib.util
import io
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
MONITOR_DIR = ROOT / "vps-monitor"
CONTROLLER_DIR = ROOT / "controller"
sys.path.insert(0, str(MONITOR_DIR))
sys.path.insert(0, str(CONTROLLER_DIR))

SPEC = importlib.util.spec_from_file_location(
    "enroll_cli",
    CONTROLLER_DIR / "enroll_cli.py",
)
enroll_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(enroll_cli)

from broker_policy import BrokerPolicyError


class FakeTransaction:
    calls = []
    failure = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def apply(self, **kwargs):
        self.__class__.calls.append(kwargs)
        if self.__class__.failure:
            raise self.__class__.failure
        return True


class EnrollCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store_path = self.root / "data" / "enrollments.json"
        self.bundle_dir = self.root / "bundles"
        FakeTransaction.calls = []
        FakeTransaction.failure = None

    def tearDown(self):
        self.temporary.cleanup()

    def run_cli(self, arguments):
        output = io.StringIO()
        with (
            patch.object(enroll_cli, "STORE_PATH", self.store_path),
            patch.object(enroll_cli, "BUNDLE_DIR", self.bundle_dir),
            patch.object(enroll_cli.os, "geteuid", return_value=0),
            patch.object(
                enroll_cli,
                "read_environment",
                side_effect=lambda path: (
                    {"MQTT_USERNAME": "vps-controller"}
                    if "controller" in str(path)
                    else {}
                ),
            ),
            patch.object(
                enroll_cli,
                "BrokerFilesTransaction",
                FakeTransaction,
            ),
            patch.object(enroll_cli, "_run", return_value=True),
            patch.object(sys, "argv", ["vps-sentinel-enroll", *arguments]),
            patch("sys.stdout", output),
        ):
            enroll_cli.main()
        return output.getvalue()

    def test_create_updates_acl_and_outputs_path_without_secret(self):
        output = self.run_cli([
            "create",
            "tokyo-web-01",
            "--name",
            "東京網站",
            "--broker-host",
            "controller.example.ts.net",
        ])
        bundle = self.bundle_dir / "tokyo-web-01.json"
        self.assertTrue(bundle.exists())
        self.assertEqual(stat.S_IMODE(bundle.stat().st_mode), 0o600)
        self.assertIn(str(bundle), output)
        self.assertIn("sudo bash install.sh --config", output)
        call = FakeTransaction.calls[-1]
        password = call["credentials"]["vps-node-tokyo-web-01"]
        self.assertNotIn(password, output)
        self.assertNotIn(password, self.store_path.read_text(encoding="utf-8"))
        self.assertIn(
            "user vps-node-tokyo-web-01",
            call["acl_text"],
        )

    def test_revoke_removes_broker_username_and_acl_entry(self):
        self.run_cli([
            "create",
            "tokyo-web-01",
            "--name",
            "東京網站",
            "--broker-host",
            "controller.example.ts.net",
        ])
        (self.bundle_dir / "tokyo-web-01.json").unlink()
        output = self.run_cli(["revoke", "tokyo-web-01"])
        call = FakeTransaction.calls[-1]
        self.assertEqual(
            call["remove_usernames"],
            ["vps-node-tokyo-web-01"],
        )
        self.assertNotIn(
            "user vps-node-tokyo-web-01",
            call["acl_text"],
        )
        self.assertIn("已撤銷", output)

    def test_broker_failure_restores_store_and_deletes_bundle(self):
        FakeTransaction.failure = BrokerPolicyError("injected failure")
        with self.assertRaisesRegex(SystemExit, "injected failure"):
            self.run_cli([
                "create",
                "tokyo-web-01",
                "--name",
                "東京網站",
                "--broker-host",
                "controller.example.ts.net",
            ])
        self.assertFalse(self.store_path.exists())
        self.assertFalse(
            (self.bundle_dir / "tokyo-web-01.json").exists()
        )


if __name__ == "__main__":
    unittest.main()
