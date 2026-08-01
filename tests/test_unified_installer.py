from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
ENTRYPOINT = (ROOT / "install.sh").read_text(encoding="utf-8")
SETUP = (ROOT / "setup.sh").read_text(encoding="utf-8")
BOOTSTRAP = (ROOT / "controller" / "bootstrap.py").read_text(
    encoding="utf-8"
)


class UnifiedInstallerTests(unittest.TestCase):
    def test_one_entrypoint_has_three_explicit_roles(self):
        for role in ["combined", "controller", "agent"]:
            with self.subTest(role=role):
                self.assertIn(role, ENTRYPOINT)
        self.assertIn("--role combined|controller|agent", ENTRYPOINT)
        self.assertIn('exec bash "${REPO_DIR}/vps-monitor/install.sh"', ENTRYPOINT)

    def test_dry_run_finishes_before_root_requirement(self):
        dry_run = ENTRYPOINT.index('if [[ "${dry_run}" == "true" ]]')
        root_check = ENTRYPOINT.index("if [[ $EUID -ne 0 ]]")
        self.assertLess(dry_run, root_check)
        self.assertIn("未修改系統", ENTRYPOINT)

    def test_controller_role_skips_agent_and_combined_keeps_it(self):
        self.assertIn(
            "VPS_SENTINEL_SKIP_AGENT=true VPS_SENTINEL_DEFER_SUMMARY=true",
            ENTRYPOINT,
        )
        self.assertIn(
            'if [[ "${SKIP_AGENT}" != "true" ]]; then',
            SETUP,
        )
        self.assertIn("已依角色略過本機 VPS Agent", SETUP)
        self.assertIn('services_to_check+=(vps-monitor)', SETUP)

    def test_unified_entrypoint_owns_the_final_summary(self):
        self.assertIn("VPS_SENTINEL_DEFER_SUMMARY=true", ENTRYPOINT)
        self.assertIn(
            'if [[ "${DEFER_SUMMARY}" != "true" ]]; then',
            SETUP,
        )
        self.assertEqual(
            ENTRYPOINT.count("安裝完成"),
            1,
        )

    def test_controller_component_is_deployed_before_broker_transaction(self):
        component = BOOTSTRAP.index('["bash", str(component)]')
        transaction = BOOTSTRAP.index("transaction.apply(")
        self.assertLess(component, transaction)
        self.assertIn('"CONTROLLER_START": "false"', BOOTSTRAP)
        self.assertIn("restart_services", BOOTSTRAP)

    def test_bootstrap_reuses_existing_controller_secret_without_printing_it(self):
        self.assertIn(
            'existing.get("MQTT_PASSWORD") or secrets.token_urlsafe(32)',
            BOOTSTRAP,
        )
        self.assertNotIn("print(controller_password", BOOTSTRAP)
        self.assertNotIn("print(component_environment", BOOTSTRAP)

    def test_fleet_card_is_copied_atomically(self):
        self.assertIn("vps-sentinel-fleet-card.js", BOOTSTRAP)
        self.assertIn("os.replace(temporary, card_target)", BOOTSTRAP)
        self.assertIn("os.chmod(temporary, 0o644)", BOOTSTRAP)


if __name__ == "__main__":
    unittest.main()
