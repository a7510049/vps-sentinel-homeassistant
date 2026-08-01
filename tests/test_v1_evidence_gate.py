import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_v1_evidence",
    ROOT / "scripts" / "verify-v1-evidence.py",
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

VERSION = "1.0.0-rc.1"
BUILD_REF = "0123456789abcdef0123456789abcdef01234567"


class V1EvidenceGateTests(unittest.TestCase):
    def write_checksum(self, path):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksum = path.with_suffix(path.suffix + ".sha256")
        checksum.write_text(
            f"{digest}  {path.name}\n",
            encoding="utf-8",
        )

    def make_evidence(
        self,
        root,
        name,
        fingerprint,
        provider,
        region,
        architecture,
        role,
    ):
        path = Path(root) / f"{name}.json"
        report = {
            "schema_version": 1,
            "collector_version": "1.0.0-alpha.2",
            "build_ref": BUILD_REF,
            "collected_at": "2026-08-01T00:00:00Z",
            "host": {
                "fingerprint": fingerprint,
                "provider": provider,
                "region": region,
                "architecture": architecture,
            },
            "version": VERSION,
            "detected_role": role,
            "checks": [
                {"name": "role", "status": "PASS", "detail": {}},
                {"name": "agent_mqtt", "status": "PASS", "detail": {}},
            ],
            "summary": {
                "passed": 2,
                "failed": 0,
                "skipped": 0,
                "result": "PASS",
            },
        }
        path.write_text(json.dumps(report), encoding="utf-8")
        self.write_checksum(path)
        return path

    def make_benchmark(self, root, name, index, rss):
        base = Path(root)
        csv_path = base / f"{name}-{index}.csv"
        log_path = base / f"{name}-{index}.log"
        csv_path.write_text("sample\n", encoding="utf-8")
        log_path.write_text("agent log\n", encoding="utf-8")
        payload = {
            "schema_version": 1,
            "name": name,
            "version": VERSION,
            "build_ref": BUILD_REF,
            "status": "completed",
            "measurement_complete": True,
            "requested_duration_seconds": 86400,
            "actual_measurement_seconds": 86400,
            "samples": 17280,
            "rss_kib": {"mean": rss, "p95": rss, "max": rss},
            "cpu_percent": {"mean": 1.0, "p95": 1.0, "max": 1.0},
            "raw_csv": csv_path.name,
            "raw_csv_sha256": gate.sha256(csv_path),
            "raw_log": log_path.name,
            "raw_log_sha256": gate.sha256(log_path),
            "host": {
                "fingerprint": "fedcba9876543210",
                "architecture": "x86_64",
            },
        }
        path = base / f"{name}-{index}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def make_soak(self, root, name, fingerprint):
        base = Path(root)
        csv_path = base / f"{name}.soak.csv"
        csv_path.write_text("sample\n", encoding="utf-8")
        stable = {
            "boot_fingerprint": "1111111111111111",
            "active_state": "active",
            "sub_state": "running",
            "main_pid": 1234,
            "n_restarts": 0,
        }
        summary = {
            "schema_version": 1,
            "name": "python-agent-seven-day-soak",
            "version": VERSION,
            "build_ref": BUILD_REF,
            "status": "completed",
            "failure": None,
            "measurement_complete": True,
            "qualifies_for_seven_day_gate": True,
            "requested_duration_seconds": 604800,
            "actual_measurement_seconds": 604800,
            "interval_seconds": 60,
            "samples": 10081,
            "baseline": stable,
            "final": stable,
            "raw_csv": csv_path.name,
            "raw_csv_sha256": gate.sha256(csv_path),
            "host": {
                "fingerprint": fingerprint,
                "architecture": "x86_64",
            },
        }
        path = base / f"{name}.soak.summary.json"
        path.write_text(json.dumps(summary), encoding="utf-8")
        self.write_checksum(path)
        return path

    def make_attestation(self, root):
        base = Path(root)
        payload = gate.attestation.template(
            VERSION,
            BUILD_REF,
            "qa-operator",
        )
        for item in payload["gates"]:
            artifact = base / f"manual-{item['id']}.log"
            artifact.write_text("sanitized PASS evidence\n", encoding="utf-8")
            item.update({
                "result": "PASS",
                "started_at": "2026-08-01T00:00:00Z",
                "ended_at": "2026-08-01T00:05:00Z",
                "command": f"verify-{item['id']}",
                "evidence": [{
                    "label": "real acceptance evidence",
                    "kind": "log",
                    "path": artifact.name,
                    "sha256": gate.sha256(artifact),
                }],
            })
        path = gate.attestation.write_private(
            payload,
            base / "attestation.json",
        )
        gate.attestation.seal(path)
        return path

    def make_bundle(self, root):
        evidence = [
            self.make_evidence(
                root, "agent-a", "0000000000000001",
                "Cloud A", "taipei", "x86_64", "agent",
            ),
            self.make_evidence(
                root, "agent-b", "0000000000000002",
                "Cloud B", "tokyo", "aarch64", "agent",
            ),
            self.make_evidence(
                root, "agent-c", "0000000000000003",
                "Cloud C", "singapore", "x86_64", "agent",
            ),
            self.make_evidence(
                root, "controller", "0000000000000004",
                "Home", "taiwan", "x86_64", "controller",
            ),
        ]
        soak = [
            self.make_soak(
                root,
                f"agent-{index}",
                f"{index:016x}",
            )
            for index in range(1, 4)
        ]
        python = [
            self.make_benchmark(root, "python", index, 100)
            for index in range(1, 4)
        ]
        go = [
            self.make_benchmark(root, "go", index, 60)
            for index in range(1, 4)
        ]
        return evidence, soak, python, go

    def test_complete_bundle_passes_without_claiming_manual_gates(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence, soak, python, go = self.make_bundle(temporary)
            report = gate.verify(
                evidence, soak, python, go, VERSION, BUILD_REF,
            )
            self.assertEqual(report["result"], "AUTOMATED_EVIDENCE_PASS")
            self.assertEqual(report["inventory"]["agent_capable_hosts"], 3)
            self.assertEqual(
                report["inventory"]["architectures"],
                ["amd64", "arm64"],
            )
            self.assertEqual(report["stability"]["hosts"], 3)
            self.assertEqual(report["benchmark"]["python_runs"], 3)
            self.assertEqual(report["benchmark"]["go_runs"], 3)
            self.assertNotIn(
                "seven_day_stability",
                report["remaining_manual_gates"],
            )

    def test_complete_attestation_upgrades_result_to_release_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence, soak, python, go = self.make_bundle(temporary)
            attestation = self.make_attestation(temporary)
            report = gate.verify(
                evidence,
                soak,
                python,
                go,
                VERSION,
                BUILD_REF,
                attestation,
            )
            self.assertEqual(report["result"], "RELEASE_EVIDENCE_PASS")
            self.assertEqual(report["remaining_manual_gates"], [])
            self.assertEqual(
                report["manual_acceptance"]["gate_count"],
                len(gate.attestation.GATES),
            )

    def test_rejects_changed_report_and_duplicate_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence, soak, python, go = self.make_bundle(temporary)
            evidence[0].write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                gate.verify(evidence, soak, python, go, VERSION, BUILD_REF)

            evidence, soak, python, go = self.make_bundle(temporary)
            payload = json.loads(evidence[1].read_text(encoding="utf-8"))
            payload["host"]["fingerprint"] = "0000000000000001"
            evidence[1].write_text(json.dumps(payload), encoding="utf-8")
            self.write_checksum(evidence[1])
            with self.assertRaisesRegex(ValueError, "duplicate fingerprints"):
                gate.verify(evidence, soak, python, go, VERSION, BUILD_REF)

    def test_rejects_source_architecture_and_build_mismatch(self):
        cases = (
            ("provider", "Cloud A", "distinct agent providers"),
            ("architecture", "x86_64", "amd64 and arm64"),
            ("build_ref", "wrong-ref", "build ref does not match"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            for field, value, message in cases:
                evidence, soak, python, go = self.make_bundle(temporary)
                payload = json.loads(evidence[1].read_text(encoding="utf-8"))
                if field in {"provider", "architecture"}:
                    payload["host"][field] = value
                else:
                    payload[field] = value
                evidence[1].write_text(json.dumps(payload), encoding="utf-8")
                self.write_checksum(evidence[1])
                with self.assertRaisesRegex(ValueError, message):
                    gate.verify(evidence, soak, python, go, VERSION, BUILD_REF)

    def test_rejects_missing_or_changed_soak_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence, soak, python, go = self.make_bundle(temporary)
            with self.assertRaisesRegex(ValueError, "every agent evidence"):
                gate.verify(
                    evidence, soak[:2], python, go, VERSION, BUILD_REF,
                )

            evidence, soak, python, go = self.make_bundle(temporary)
            payload = json.loads(soak[0].read_text(encoding="utf-8"))
            csv_path = soak[0].parent / payload["raw_csv"]
            csv_path.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing or changed"):
                gate.verify(
                    evidence, soak, python, go, VERSION, BUILD_REF,
                )

    def test_private_summary_has_matching_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "gate.json"
            path, checksum = gate.write_report({"result": "PASS"}, output)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(checksum.stat().st_mode & 0o777, 0o600)
            gate.verify_checksum(path)


if __name__ == "__main__":
    unittest.main()
