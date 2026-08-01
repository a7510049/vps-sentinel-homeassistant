import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "stability_soak",
    ROOT / "scripts" / "stability-soak.py",
)
soak = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(soak)


def stable_snapshot(pid=1234, restarts=0, boot="aaaaaaaaaaaaaaaa"):
    return {
        "boot_fingerprint": boot,
        "active_state": "active",
        "sub_state": "running",
        "main_pid": pid,
        "n_restarts": restarts,
    }


class StabilitySoakTests(unittest.TestCase):
    def args(self, root, duration=0):
        return SimpleNamespace(
            output=str(Path(root) / "soak.csv"),
            summary=str(Path(root) / "soak.summary.json"),
            service="vps-monitor",
            version="1.0.0-rc.1",
            build_ref="0123456789abcdef",
            duration=duration,
            interval=1,
        )

    def test_snapshot_failure_detects_every_restart_signal(self):
        baseline = stable_snapshot()
        cases = (
            (stable_snapshot(boot="bbbbbbbbbbbbbbbb"), "host rebooted"),
            (dict(baseline, active_state="failed"), "service is failed"),
            (dict(baseline, sub_state="auto-restart"), "sub-state"),
            (dict(baseline, main_pid=4321), "main PID changed"),
            (dict(baseline, n_restarts=1), "restart counter changed"),
        )
        for snapshot, message in cases:
            self.assertIn(
                message,
                soak.snapshot_failure(snapshot, baseline),
            )
        self.assertIsNone(soak.snapshot_failure(baseline, baseline))

    def test_short_completed_run_is_private_but_not_gate_qualified(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary = soak.run_soak(
                self.args(temporary),
                sampler=lambda _service: stable_snapshot(),
            )
            self.assertEqual(summary["status"], "completed")
            self.assertFalse(summary["qualifies_for_seven_day_gate"])
            output = Path(temporary) / "soak.csv"
            summary_path = Path(temporary) / "soak.summary.json"
            checksum = Path(temporary) / "soak.summary.json.sha256"
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(summary_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(checksum.stat().st_mode & 0o777, 0o600)

    def test_pid_change_fails_immediately(self):
        with tempfile.TemporaryDirectory() as temporary:
            values = iter((stable_snapshot(), stable_snapshot(pid=4321)))
            summary = soak.run_soak(
                self.args(temporary, duration=100),
                sampler=lambda _service: next(values),
            )
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["failure"], "service main PID changed")
            self.assertFalse(summary["measurement_complete"])

    def test_summary_contains_no_raw_machine_or_boot_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary = soak.run_soak(
                self.args(temporary),
                sampler=lambda _service: stable_snapshot(),
            )
            serialized = json.dumps(summary)
            self.assertNotIn("machine-id", serialized)
            self.assertRegex(
                summary["host"]["fingerprint"],
                r"^[0-9a-f]{16}$",
            )


if __name__ == "__main__":
    unittest.main()
