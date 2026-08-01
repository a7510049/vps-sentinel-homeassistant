import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


benchmark = load_module(
    "agent_benchmark",
    ROOT / "benchmarks" / "agent_benchmark.py",
)
comparison = load_module(
    "compare_agent_benchmarks",
    ROOT / "benchmarks" / "compare_agent_benchmarks.py",
)


class AgentBenchmarkTests(unittest.TestCase):
    def test_percentile_and_summary_are_deterministic(self):
        self.assertEqual(benchmark.percentile([1, 2, 3, 4], 50), 2.5)
        self.assertEqual(
            benchmark.metric_summary([10, 20, 30]),
            {"mean": 20.0, "p95": 29.0, "max": 30},
        )
        self.assertEqual(
            benchmark.metric_summary([]),
            {"mean": None, "p95": None, "max": None},
        )

    def test_env_file_is_loaded_without_being_added_to_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "agent.env"
            path.write_text(
                '# comment\nMQTT_HOST="broker.internal"\n'
                'MQTT_PASSWORD="secret-value"\n',
                encoding="utf-8",
            )
            values = benchmark.load_env(path)
            self.assertEqual(values["MQTT_HOST"], "broker.internal")
            self.assertEqual(values["MQTT_PASSWORD"], "secret-value")

    def make_summary(self, root, name, index, rss_p95, cpu_p95=1.0):
        csv_path = Path(root) / f"{name}-{index}.csv"
        log_path = Path(root) / f"{name}-{index}.log"
        csv_path.write_text("sample\n", encoding="utf-8")
        log_path.write_text("agent log\n", encoding="utf-8")
        payload = {
            "schema_version": 1,
            "name": name,
            "version": "1.0.0-rc.1",
            "build_ref": "0123456789abcdef",
            "status": "completed",
            "measurement_complete": True,
            "requested_duration_seconds": 86400,
            "actual_measurement_seconds": 86400,
            "samples": 17280,
            "rss_kib": {
                "mean": rss_p95 * 0.9,
                "p95": rss_p95,
                "max": rss_p95 * 1.1,
            },
            "cpu_percent": {
                "mean": cpu_p95 * 0.8,
                "p95": cpu_p95,
                "max": cpu_p95 * 1.2,
            },
            "raw_csv": str(csv_path),
            "raw_csv_sha256": benchmark.sha256(csv_path),
            "raw_log": str(log_path),
            "raw_log_sha256": benchmark.sha256(log_path),
            "host": {
                "fingerprint": "0123456789abcdef",
                "architecture": "x86_64",
            },
        }
        path = Path(root) / f"{name}-{index}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_comparison_requires_three_complete_same_host_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            python = [
                self.make_summary(temporary, "python", index, rss)
                for index, rss in enumerate((100, 102, 98), 1)
            ]
            go = [
                self.make_summary(temporary, "go", index, rss)
                for index, rss in enumerate((60, 62, 58), 1)
            ]
            report = comparison.compare(python, go)
            self.assertEqual(
                report["comparison"]["rss_30_percent_gate"],
                "PASS",
            )
            self.assertEqual(
                report["resource_recommendation"],
                "GO_RESOURCE_GATE_PASS",
            )
            self.assertEqual(report["final_decision"], "PENDING_OTHER_ADR_GATES")

            with self.assertRaisesRegex(ValueError, "at least three"):
                comparison.compare(python[:2], go)

    def test_comparison_rejects_short_or_cross_host_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            python = [
                self.make_summary(temporary, "python", index, 100)
                for index in range(1, 4)
            ]
            go = [
                self.make_summary(temporary, "go", index, 60)
                for index in range(1, 4)
            ]
            payload = json.loads(go[0].read_text(encoding="utf-8"))
            payload["host"]["fingerprint"] = "fedcba9876543210"
            go[0].write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "same host"):
                comparison.compare(python, go)

            payload["host"]["fingerprint"] = "0123456789abcdef"
            payload["actual_measurement_seconds"] = 100
            go[0].write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "24-hour"):
                comparison.compare(python, go)

    def test_comparison_rejects_changed_raw_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            python = [
                self.make_summary(temporary, "python", index, 100)
                for index in range(1, 4)
            ]
            go = [
                self.make_summary(temporary, "go", index, 60)
                for index in range(1, 4)
            ]
            payload = json.loads(go[0].read_text(encoding="utf-8"))
            Path(payload["raw_csv"]).write_text(
                "changed\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "changed raw_csv"):
                comparison.compare(python, go)

    def test_comparison_report_is_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "comparison.json"
            comparison.write_report({"result": "test"}, output)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
