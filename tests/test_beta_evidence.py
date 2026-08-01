import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "beta_evidence",
    ROOT / "scripts" / "beta-evidence.py",
)
beta_evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(beta_evidence)
SETUP = (ROOT / "setup.sh").read_text(encoding="utf-8")
AGENT_INSTALL = (ROOT / "vps-monitor" / "install.sh").read_text(encoding="utf-8")
UPGRADE = (ROOT / "scripts" / "upgrade.sh").read_text(encoding="utf-8")
UNINSTALL = (ROOT / "scripts" / "uninstall.sh").read_text(encoding="utf-8")
MANAGE = (ROOT / "scripts" / "manage.sh").read_text(encoding="utf-8")


class BetaEvidenceTests(unittest.TestCase):
    def make_root(self, role):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "etc").mkdir()
        (root / "etc" / "machine-id").write_text(
            "0123456789abcdef\n",
            encoding="utf-8",
        )
        (root / "etc" / "os-release").write_text(
            'PRETTY_NAME="Ubuntu 24.04 LTS"\n',
            encoding="utf-8",
        )
        (root / "proc").mkdir()
        (root / "proc" / "meminfo").write_text(
            "MemTotal:       1048576 kB\n",
            encoding="utf-8",
        )
        if role in {"agent", "combined"}:
            path = root / "etc" / "vps-monitor.env"
            path.write_text(
                'VPS_ID="secret-node-name"\n'
                'MQTT_HOST="10.0.0.9"\n'
                'MQTT_USERNAME="vps-node-secret"\n'
                'MQTT_PASSWORD="super-secret"\n',
                encoding="utf-8",
            )
            os.chmod(path, 0o600)
            version = root / "opt" / "vps-monitor" / ".version"
            version.parent.mkdir(parents=True)
            version.write_text("1.0.0-beta.1\n", encoding="utf-8")
        if role in {"controller", "combined"}:
            path = root / "etc" / "vps-sentinel-controller.env"
            path.write_text(
                'MQTT_HOST="127.0.0.1"\n'
                'MQTT_PASSWORD="controller-secret"\n',
                encoding="utf-8",
            )
            os.chmod(path, 0o600)
            compose = root / "opt" / "homeassistant" / "compose.yaml"
            compose.parent.mkdir(parents=True, exist_ok=True)
            compose.write_text("services: {}\n", encoding="utf-8")
            broker = (
                root
                / "etc"
                / "mosquitto"
                / "conf.d"
                / "home-assistant.conf"
            )
            broker.parent.mkdir(parents=True)
            broker.write_text("allow_anonymous false\n", encoding="utf-8")
        return temporary, root

    def test_detects_all_three_roles_without_live_side_effects(self):
        for expected in ("agent", "controller", "combined"):
            temporary, root = self.make_root(expected)
            self.addCleanup(temporary.cleanup)
            report = beta_evidence.collect(
                root=root,
                expected_role=expected,
                live=False,
                provider="Example Cloud",
                region="test-region",
            )
            self.assertEqual(report["detected_role"], expected)
            self.assertEqual(report["summary"]["result"], "INCOMPLETE")
            self.assertEqual(report["summary"]["failed"], 0)
            self.assertEqual(report["host"]["memory_mib"], 1024)

    def test_report_never_contains_secrets_or_raw_identity(self):
        temporary, root = self.make_root("combined")
        self.addCleanup(temporary.cleanup)
        report = beta_evidence.collect(root=root, live=False)
        serialized = json.dumps(report, ensure_ascii=False)
        for forbidden in (
            "super-secret",
            "controller-secret",
            "secret-node-name",
            "vps-node-secret",
            "10.0.0.9",
            "0123456789abcdef",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertRegex(report["host"]["fingerprint"], r"^[0-9a-f]{16}$")

    def test_node_fingerprint_is_stable_but_keyed_to_the_host(self):
        temporary, root = self.make_root("controller")
        self.addCleanup(temporary.cleanup)
        first = beta_evidence.identity_fingerprint(root, "tokyo-web-01")
        self.assertEqual(
            first,
            beta_evidence.identity_fingerprint(root, "tokyo-web-01"),
        )
        (root / "etc" / "machine-id").write_text(
            "different-machine-id\n",
            encoding="utf-8",
        )
        self.assertNotEqual(
            first,
            beta_evidence.identity_fingerprint(root, "tokyo-web-01"),
        )

    def test_role_mismatch_fails_even_without_live_checks(self):
        temporary, root = self.make_root("agent")
        self.addCleanup(temporary.cleanup)
        report = beta_evidence.collect(
            root=root,
            expected_role="controller",
            live=False,
        )
        self.assertEqual(report["summary"]["result"], "FAIL")
        self.assertEqual(report["summary"]["failed"], 1)

    def test_collector_follows_install_upgrade_and_uninstall_lifecycle(self):
        command = "vps-sentinel-beta-evidence"
        self.assertIn("scripts/beta-evidence.py", SETUP)
        self.assertIn(command, SETUP)
        self.assertIn("../scripts/beta-evidence.py", AGENT_INSTALL)
        self.assertIn(command, AGENT_INSTALL)
        self.assertIn("scripts/beta-evidence.py", UPGRADE)
        self.assertIn(command, UPGRADE)
        self.assertIn(command, UNINSTALL)
        self.assertIn("evidence)", MANAGE)
        self.assertIn('"${EVIDENCE_COMMAND}" "$@"', MANAGE)

    def test_writes_atomic_private_report_and_matching_checksum(self):
        temporary, root = self.make_root("agent")
        self.addCleanup(temporary.cleanup)
        report = beta_evidence.collect(root=root, live=False)
        output = root / "evidence" / "report.json"
        report_path, checksum_path = beta_evidence.write_report(report, output)
        self.assertEqual(report_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(checksum_path.stat().st_mode & 0o777, 0o600)
        digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
        self.assertTrue(
            checksum_path.read_text(encoding="utf-8").startswith(digest)
        )


if __name__ == "__main__":
    unittest.main()
