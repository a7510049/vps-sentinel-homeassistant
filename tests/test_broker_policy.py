import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).parents[1]
MONITOR_DIR = ROOT / "vps-monitor"
CONTROLLER_DIR = ROOT / "controller"
sys.path.insert(0, str(MONITOR_DIR))
sys.path.insert(0, str(CONTROLLER_DIR))

POLICY_SPEC = importlib.util.spec_from_file_location(
    "broker_policy",
    CONTROLLER_DIR / "broker_policy.py",
)
broker_policy = importlib.util.module_from_spec(POLICY_SPEC)
POLICY_SPEC.loader.exec_module(broker_policy)

from enrollment import EnrollmentStore


NOW = datetime(2026, 8, 1, 10, 30, tzinfo=timezone.utc)


class FakePasswordRunner:
    def __init__(self, fail_username=None):
        self.commands = []
        self.fail_username = fail_username

    def __call__(self, command):
        self.commands.append(command)
        if "-D" in command:
            target = Path(command[-2])
            username = command[-1]
            if username == self.fail_username or not target.exists():
                return SimpleNamespace(returncode=1)
            remaining = [
                line
                for line in target.read_text(encoding="utf-8").splitlines()
                if not line.startswith(f"{username}:")
            ]
            target.write_text(
                "\n".join(remaining) + ("\n" if remaining else ""),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0)
        target = Path(command[-3])
        username = command[-2]
        if username == self.fail_username:
            return SimpleNamespace(returncode=1)
        if "-c" in command:
            target.write_text("", encoding="utf-8")
        with target.open("a", encoding="utf-8") as output:
            output.write(f"{username}:HASHED\n")
        return SimpleNamespace(returncode=0)


class BrokerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.enrollments = EnrollmentStore(self.root / "enrollments.json")
        self.enrollments.register("tokyo-web-01", "東京網站", now=NOW)

    def tearDown(self):
        self.temporary.cleanup()

    def test_acl_separates_home_assistant_controller_legacy_and_v1(self):
        policy = broker_policy.BrokerPolicy(
            self.enrollments,
            legacy_bindings={"vps-monitor": ["local-vps-01"]},
        )
        acl = policy.render_acl()
        self.assertIn("user home-assistant\ntopic readwrite #", acl)
        self.assertIn(
            "user vps-controller\n"
            "topic read vps-sentinel/v1/nodes/+/+",
            acl,
        )
        self.assertIn(
            "user vps-monitor\n"
            "topic write vps/local-vps-01/#\n"
            "topic read vps/local-vps-01/command",
            acl,
        )
        self.assertIn(
            "user vps-node-tokyo-web-01\n"
            "topic write vps-sentinel/v1/nodes/tokyo-web-01/metadata",
            acl,
        )
        v1_section = acl.split("user vps-node-tokyo-web-01", 1)[1]
        self.assertNotIn("topic write vps-sentinel/v1/nodes/#", v1_section)
        self.assertNotIn("topic readwrite #", v1_section)

    def test_acl_rejects_invalid_legacy_binding(self):
        policy = broker_policy.BrokerPolicy(
            self.enrollments,
            legacy_bindings={"vps-monitor": ["-invalid"]},
        )
        with self.assertRaises(broker_policy.BrokerPolicyError):
            policy.render_acl()

    def transaction(self, runner, restarter):
        return broker_policy.BrokerFilesTransaction(
            password_file=self.root / "mosquitto" / "passwd",
            acl_file=self.root / "mosquitto" / "vps-sentinel.acl",
            config_file=self.root / "mosquitto" / "conf.d" / "home-assistant.conf",
            runner=runner,
            restarter=restarter,
            chown=lambda *_args, **_kwargs: None,
        )

    def test_transaction_stages_all_files_and_restarts_once(self):
        runner = FakePasswordRunner()
        restarts = []
        transaction = self.transaction(
            runner,
            lambda: restarts.append(True) or True,
        )
        acl = broker_policy.BrokerPolicy(self.enrollments).render_acl()
        self.assertTrue(transaction.apply(
            credentials={
                "home-assistant": "ha-secret",
                "vps-controller": "controller-secret",
            },
            acl_text=acl,
        ))
        passwd = transaction.password_file.read_text(encoding="utf-8")
        self.assertIn("home-assistant:HASHED", passwd)
        self.assertIn("vps-controller:HASHED", passwd)
        self.assertNotIn("ha-secret", passwd)
        self.assertNotIn("controller-secret", passwd)
        self.assertEqual(transaction.acl_file.read_text(encoding="utf-8"), acl)
        config = transaction.config_file.read_text(encoding="utf-8")
        self.assertIn(f"password_file {transaction.password_file}", config)
        self.assertIn(f"acl_file {transaction.acl_file}", config)
        self.assertEqual(restarts, [True])

    def test_restart_failure_restores_every_original_file(self):
        runner = FakePasswordRunner()
        transaction = self.transaction(runner, lambda: True)
        for path, value in [
            (transaction.password_file, b"old-passwd\n"),
            (transaction.acl_file, b"old-acl\n"),
            (transaction.config_file, b"old-config\n"),
        ]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)

        restart_results = iter([False, True])
        transaction.restarter = lambda: next(restart_results)
        with self.assertRaisesRegex(
            broker_policy.BrokerPolicyError,
            "original files restored",
        ):
            transaction.apply(
                credentials={"vps-controller": "new-secret"},
                acl_text="user vps-controller\ntopic read x/#\n",
            )
        self.assertEqual(transaction.password_file.read_bytes(), b"old-passwd\n")
        self.assertEqual(transaction.acl_file.read_bytes(), b"old-acl\n")
        self.assertEqual(transaction.config_file.read_bytes(), b"old-config\n")

    def test_password_tool_failure_does_not_expose_secret_or_touch_live_files(self):
        runner = FakePasswordRunner(fail_username="vps-controller")
        transaction = self.transaction(runner, lambda: True)
        transaction.password_file.parent.mkdir(parents=True)
        transaction.password_file.write_text("old\n", encoding="utf-8")
        with self.assertRaises(broker_policy.BrokerPolicyError) as raised:
            transaction.apply(
                credentials={"vps-controller": "never-log-this-secret"},
                acl_text="user vps-controller\ntopic read x/#\n",
            )
        self.assertNotIn("never-log-this-secret", str(raised.exception))
        self.assertEqual(
            transaction.password_file.read_text(encoding="utf-8"),
            "old\n",
        )

    def test_transaction_removes_revoked_username_from_staging_copy(self):
        runner = FakePasswordRunner()
        transaction = self.transaction(runner, lambda: True)
        transaction.password_file.parent.mkdir(parents=True)
        transaction.password_file.write_text(
            "home-assistant:HASHED\n"
            "vps-node-old:HASHED\n",
            encoding="utf-8",
        )
        transaction.apply(
            credentials={},
            remove_usernames=["vps-node-old"],
            acl_text="user home-assistant\ntopic readwrite #\n",
        )
        passwd = transaction.password_file.read_text(encoding="utf-8")
        self.assertIn("home-assistant:HASHED", passwd)
        self.assertNotIn("vps-node-old", passwd)
        self.assertTrue(any("-D" in command for command in runner.commands))

    def test_transaction_rejects_update_and_removal_of_same_user(self):
        transaction = self.transaction(FakePasswordRunner(), lambda: True)
        with self.assertRaisesRegex(
            broker_policy.BrokerPolicyError,
            "updated and removed",
        ):
            transaction.apply(
                credentials={"vps-node-a": "secret"},
                remove_usernames=["vps-node-a"],
                acl_text="user home-assistant\ntopic readwrite #\n",
            )


if __name__ == "__main__":
    unittest.main()
