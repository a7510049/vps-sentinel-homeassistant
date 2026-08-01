from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
UPGRADE = (ROOT / "scripts" / "upgrade.sh").read_text(encoding="utf-8")
ROLLBACK = UPGRADE.split("rollback() {", 1)[1].split(
    "\n}\n\nupgrade_started=false",
    1,
)[0]


class UpgradeRoleMatrixTests(unittest.TestCase):
    def test_rollback_has_independent_agent_and_controller_guards(self):
        agent_guard = 'if [[ "${has_agent}" == "true" ]]; then'
        controller_guard = (
            'if [[ "${has_controller}" == "true" && '
            '-d "${backup}/controller" ]]; then'
        )
        self.assertIn(agent_guard, ROLLBACK)
        self.assertIn(controller_guard, ROLLBACK)

        agent_section = ROLLBACK.split(agent_guard, 1)[1].split(
            'if [[ -f "${backup}/homeassistant-fleet-card.js" ]]',
            1,
        )[0]
        self.assertIn('"${backup}/vps_monitor.py"', agent_section)
        self.assertIn('"${backup}/requirements.txt"', agent_section)
        self.assertIn('"${INSTALL_DIR}/.version"', agent_section)
        self.assertTrue(agent_section.rstrip().endswith("fi"))

        controller_section = ROLLBACK.split(controller_guard, 1)[1]
        self.assertIn('"${backup}/controller/."', controller_section)
        self.assertIn('"${CONTROLLER_SERVICE}"', controller_section)

    def test_role_matrix_never_requires_an_absent_component_backup(self):
        requirements = {
            "agent": {"agent"},
            "controller": {"controller"},
            "combined": {"agent", "controller"},
        }
        for role, installed in requirements.items():
            with self.subTest(role=role):
                self.assertEqual("agent" in installed, role != "controller")
                self.assertEqual("controller" in installed, role != "agent")

        pre_guard = ROLLBACK.split(
            'if [[ "${has_agent}" == "true" ]]; then',
            1,
        )[0]
        self.assertNotIn('"${backup}/vps_monitor.py"', pre_guard)
        self.assertNotIn('"${backup}/requirements.txt"', pre_guard)


if __name__ == "__main__":
    unittest.main()
