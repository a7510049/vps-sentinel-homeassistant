import importlib.util
import json
from datetime import datetime, timezone
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

SPEC = importlib.util.spec_from_file_location(
    "enrollment",
    CONTROLLER_DIR / "enrollment.py",
)
enrollment = importlib.util.module_from_spec(SPEC)
sys.modules["enrollment"] = enrollment
SPEC.loader.exec_module(enrollment)


NOW = datetime(2026, 8, 1, 10, 30, tzinfo=timezone.utc)


class EnrollmentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "controller" / "enrollments.json"
        self.store = enrollment.EnrollmentStore(self.path)

    def tearDown(self):
        self.temporary.cleanup()

    @patch.object(enrollment.secrets, "token_urlsafe", return_value="secret-once")
    def test_register_returns_secret_once_but_never_persists_it(self, _token):
        result = self.store.register("tokyo-web-01", "東京網站", now=NOW)
        self.assertEqual(result.username, "vps-node-tokyo-web-01")
        self.assertEqual(result.password, "secret-once")
        self.assertIn("password=<redacted>", repr(result))
        self.assertNotIn("secret-once", repr(result))

        persisted = self.path.read_text(encoding="utf-8")
        self.assertNotIn("secret-once", persisted)
        self.assertNotIn('"password"', persisted)
        self.assertEqual(
            stat.S_IMODE(self.path.stat().st_mode),
            0o600,
        )
        reloaded = enrollment.EnrollmentStore(self.path)
        self.assertEqual(
            reloaded.credential_for("tokyo-web-01"),
            "vps-node-tokyo-web-01",
        )

    def test_duplicate_and_invalid_node_ids_are_rejected(self):
        self.store.register("tokyo-web-01", "東京網站", now=NOW)
        with self.assertRaisesRegex(enrollment.EnrollmentError, "already enrolled"):
            self.store.register("tokyo-web-01", "另一台", now=NOW)
        with self.assertRaises(enrollment.EnrollmentError):
            self.store.register("-invalid", "錯誤節點", now=NOW)

    @patch.object(
        enrollment.secrets,
        "token_urlsafe",
        side_effect=["first-secret", "rotated-secret"],
    )
    def test_rotation_keeps_username_and_updates_public_metadata(self, _token):
        original = self.store.register("tokyo-web-01", "東京網站", now=NOW)
        rotated = self.store.rotate(
            "tokyo-web-01",
            now=datetime(2026, 8, 2, 10, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(original.username, rotated.username)
        self.assertNotEqual(original.password, rotated.password)
        record = self.store.nodes()[0]
        self.assertEqual(record["created_at"], "2026-08-01T10:30:00Z")
        self.assertEqual(record["rotated_at"], "2026-08-02T10:30:00Z")
        persisted = self.path.read_text(encoding="utf-8")
        self.assertNotIn("first-secret", persisted)
        self.assertNotIn("rotated-secret", persisted)

    def test_revoke_removes_binding(self):
        self.store.register("tokyo-web-01", "東京網站", now=NOW)
        username = self.store.revoke("tokyo-web-01")
        self.assertEqual(username, "vps-node-tokyo-web-01")
        self.assertIsNone(self.store.credential_for("tokyo-web-01"))
        self.assertEqual(self.store.nodes(), [])
        with self.assertRaises(enrollment.EnrollmentError):
            self.store.rotate("tokyo-web-01", now=NOW)

    def test_acl_limits_each_node_to_its_own_topics(self):
        self.store.register("tokyo-web-01", "東京網站", now=NOW)
        self.store.register("frankfurt-db-01", "資料庫", now=NOW)
        acl = self.store.acl_text()

        self.assertIn("user vps-controller", acl)
        self.assertIn("topic read vps-sentinel/v1/nodes/+/+", acl)
        self.assertIn("topic write homeassistant/#", acl)
        self.assertIn("user vps-node-tokyo-web-01", acl)
        self.assertIn(
            "topic write vps-sentinel/v1/nodes/tokyo-web-01/resources",
            acl,
        )
        self.assertIn(
            "topic read vps-sentinel/v1/nodes/tokyo-web-01/commands",
            acl,
        )
        self.assertNotIn(
            "user vps-node-tokyo-web-01\ntopic write "
            "vps-sentinel/v1/nodes/#",
            acl,
        )

    def test_load_rejects_secret_fields_and_corrupt_records(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            json.dumps({
                "version": 1,
                "nodes": {
                    "tokyo-web-01": {
                        "username": "vps-node-tokyo-web-01",
                        "display_name": "東京網站",
                        "created_at": "2026-08-01T10:30:00Z",
                        "password": "must-not-be-stored",
                    },
                },
            }),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(enrollment.EnrollmentError, "secrets"):
            enrollment.EnrollmentStore(self.path)


if __name__ == "__main__":
    unittest.main()
