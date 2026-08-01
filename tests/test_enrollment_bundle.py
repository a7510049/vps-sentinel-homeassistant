import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import stat
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
MONITOR_DIR = ROOT / "vps-monitor"
CONTROLLER_DIR = ROOT / "controller"
sys.path.insert(0, str(MONITOR_DIR))
sys.path.insert(0, str(CONTROLLER_DIR))

SPEC = importlib.util.spec_from_file_location(
    "enrollment_bundle",
    CONTROLLER_DIR / "enrollment_bundle.py",
)
enrollment_bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(enrollment_bundle)

from enrollment import Enrollment


NOW = datetime(2026, 8, 1, 10, 30, tzinfo=timezone.utc)


class EnrollmentBundleTests(unittest.TestCase):
    def enrollment(self):
        return Enrollment(
            node_id="tokyo-web-01",
            username="vps-node-tokyo-web-01",
            password="one-time-secret",
        )

    def bundle(self, **overrides):
        values = {
            "display_name": "東京網站",
            "broker_host": "controller.example.ts.net",
            "now": NOW,
            "lifetime_seconds": 900,
        }
        values.update(overrides)
        return enrollment_bundle.create_bundle(
            self.enrollment(),
            **values,
        )

    def test_bundle_contains_agent_role_and_short_expiry(self):
        bundle = self.bundle()
        self.assertEqual(bundle["bundle_version"], 1)
        self.assertEqual(bundle["role"], "agent")
        self.assertEqual(bundle["issued_at"], "2026-08-01T10:30:00Z")
        self.assertEqual(bundle["expires_at"], "2026-08-01T10:45:00Z")
        self.assertEqual(bundle["node"]["id"], "tokyo-web-01")
        self.assertEqual(bundle["mqtt"]["password"], "one-time-secret")
        self.assertTrue(bundle["monitor"]["publish_interval"] >= 10)

    def test_expired_future_and_overlong_bundles_are_rejected(self):
        bundle = self.bundle()
        with self.assertRaisesRegex(
            enrollment_bundle.BundleError,
            "expired",
        ):
            enrollment_bundle.validate_bundle(
                bundle,
                now=NOW + timedelta(minutes=16),
            )
        with self.assertRaisesRegex(
            enrollment_bundle.BundleError,
            "future",
        ):
            enrollment_bundle.validate_bundle(
                bundle,
                now=NOW - timedelta(minutes=6),
            )
        with self.assertRaises(enrollment_bundle.BundleError):
            self.bundle(lifetime_seconds=86401)

    def test_tls_bundle_requires_embedded_ca_certificate(self):
        with self.assertRaisesRegex(
            enrollment_bundle.BundleError,
            "CA certificate",
        ):
            enrollment_bundle.validate_bundle(
                self.bundle(tls=True),
                now=NOW,
            )
        bundle = self.bundle(
            tls=True,
            ca_certificate="-----BEGIN CERTIFICATE-----\nexample\n"
            "-----END CERTIFICATE-----\n",
        )
        self.assertTrue(
            enrollment_bundle.validate_bundle(bundle, now=NOW)["mqtt"]["tls"]
        )

    def test_unknown_fields_and_invalid_monitor_values_are_rejected(self):
        bundle = self.bundle()
        bundle["command"] = "shell"
        with self.assertRaises(enrollment_bundle.BundleError):
            enrollment_bundle.validate_bundle(bundle, now=NOW)
        bundle = self.bundle()
        bundle["monitor"]["publish_interval"] = 5
        with self.assertRaisesRegex(
            enrollment_bundle.BundleError,
            "at least 10",
        ):
            enrollment_bundle.validate_bundle(bundle, now=NOW)

    def test_bundle_is_written_atomically_with_0600_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "tokyo-web-01.json"
            enrollment_bundle.write_bundle(path, self.bundle())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            loaded = enrollment_bundle.load_bundle(path, now=NOW)
            self.assertEqual(loaded["mqtt"]["password"], "one-time-secret")
            self.assertEqual(
                list(path.parent.glob(f".{path.name}.*")),
                [],
            )


if __name__ == "__main__":
    unittest.main()
