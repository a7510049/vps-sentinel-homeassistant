import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "v1_attestation",
    ROOT / "scripts" / "v1-attestation.py",
)
attestation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(attestation)

VERSION = "1.0.0-rc.1"
BUILD_REF = "0123456789abcdef0123456789abcdef01234567"


class V1AttestationTests(unittest.TestCase):
    def make_manifest(self, root):
        base = Path(root)
        payload = attestation.template(VERSION, BUILD_REF, "qa-operator")
        for gate in payload["gates"]:
            artifact = base / f"{gate['id']}.log"
            artifact.write_text(
                f"sanitized evidence for {gate['id']}\n",
                encoding="utf-8",
            )
            gate.update({
                "result": "PASS",
                "started_at": "2026-08-01T00:00:00Z",
                "ended_at": "2026-08-01T00:05:00Z",
                "command": f"verify-{gate['id']}",
                "evidence": [{
                    "label": "sanitized evidence",
                    "kind": "log",
                    "path": artifact.name,
                    "sha256": attestation.sha256(artifact),
                }],
                "notes": "verified on the real Beta environment",
            })
        path = attestation.write_private(
            payload,
            base / "v1-attestation.json",
        )
        attestation.seal(path)
        return path

    def rewrite_and_seal(self, path, update):
        payload = json.loads(path.read_text(encoding="utf-8"))
        update(payload)
        attestation.write_private(payload, path)
        attestation.seal(path)

    def test_complete_manifest_verifies_all_fixed_gates(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.make_manifest(temporary)
            report = attestation.verify_manifest(
                path,
                VERSION,
                BUILD_REF,
            )
            self.assertEqual(report["result"], "MANUAL_ACCEPTANCE_PASS")
            self.assertEqual(report["gate_count"], len(attestation.GATES))
            self.assertEqual(report["artifact_count"], len(attestation.GATES))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                attestation.checksum_path(path).stat().st_mode & 0o777,
                0o600,
            )

    def test_pending_missing_coverage_and_bad_time_are_rejected(self):
        cases = (
            (
                lambda payload: payload["gates"][0].update(
                    {"result": "PENDING"}
                ),
                "result must be PASS",
            ),
            (
                lambda payload: payload["gates"][0].update(
                    {"coverage": []}
                ),
                "missing coverage",
            ),
            (
                lambda payload: payload["gates"][0].update({
                    "started_at": "2026-08-01T01:00:00Z",
                    "ended_at": "2026-08-01T00:00:00Z",
                }),
                "precedes",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            for update, message in cases:
                path = self.make_manifest(temporary)
                self.rewrite_and_seal(path, update)
                with self.assertRaisesRegex(ValueError, message):
                    attestation.verify_manifest(path, VERSION, BUILD_REF)

    def test_gate_set_path_escape_and_changed_artifact_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            path = self.make_manifest(base)
            self.rewrite_and_seal(
                path,
                lambda payload: payload["gates"].pop(),
            )
            with self.assertRaisesRegex(ValueError, "gate set mismatch"):
                attestation.verify_manifest(path, VERSION, BUILD_REF)

            path = self.make_manifest(base)
            outside = base.parent / "outside-v1-evidence.log"
            outside.write_text("outside\n", encoding="utf-8")
            self.addCleanup(outside.unlink)
            def escape(payload):
                artifact = payload["gates"][0]["evidence"][0]
                artifact["path"] = f"../{outside.name}"
                artifact["sha256"] = attestation.sha256(outside)
            self.rewrite_and_seal(path, escape)
            with self.assertRaisesRegex(ValueError, "escapes the bundle"):
                attestation.verify_manifest(path, VERSION, BUILD_REF)

            path = self.make_manifest(base)
            first = json.loads(path.read_text(encoding="utf-8"))["gates"][0]
            (base / first["evidence"][0]["path"]).write_text(
                "changed\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                attestation.verify_manifest(path, VERSION, BUILD_REF)

    def test_manifest_checksum_and_version_are_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.make_manifest(temporary)
            with self.assertRaisesRegex(ValueError, "version does not match"):
                attestation.verify_manifest(path, "1.0.0", BUILD_REF)
            path.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest checksum"):
                attestation.verify_manifest(path, VERSION, BUILD_REF)


if __name__ == "__main__":
    unittest.main()
