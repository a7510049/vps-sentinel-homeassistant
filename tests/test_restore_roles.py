from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
BACKUP = (ROOT / "scripts" / "backup.sh").read_text(encoding="utf-8")
VALIDATE = BACKUP.split("start_and_validate() {", 1)[1].split(
    "\n}\n\nlist_backups()",
    1,
)[0]
CREATE = BACKUP.split("create_backup() {", 1)[1].split(
    "\n}\n\nrestore_backup()",
    1,
)[0]


class RestoreRoleMatrixTests(unittest.TestCase):
    def test_each_runtime_is_validated_only_when_installed(self):
        guards = {
            "home_assistant": 'if [[ -n "${compose}" ]]; then',
            "broker": 'if [[ -f "${MQTT_CONF}" || -f "${MQTT_PASSWD}" ||',
            "controller": 'if [[ -f "${CONTROLLER_ENV}" ]]; then',
            "agent": 'if [[ -f "${ENV_FILE}" ]]; then',
        }
        for component, guard in guards.items():
            with self.subTest(component=component):
                self.assertIn(guard, VALIDATE)

        broker = VALIDATE.split(guards["broker"], 1)[1].split("fi", 1)[0]
        self.assertIn("systemctl restart mosquitto", broker)
        controller = VALIDATE.split(guards["controller"], 1)[1].split("fi", 1)[0]
        self.assertIn("systemctl restart vps-sentinel-controller", controller)
        agent = VALIDATE.split(guards["agent"], 1)[1].split("fi", 1)[0]
        self.assertIn("systemctl restart vps-monitor", agent)
        self.assertIn("mqtt_probe || return 1", agent)

    def test_agent_only_restore_does_not_require_local_home_assistant_or_broker(self):
        first_guard = VALIDATE.index('if [[ -n "${compose}" ]]')
        preconditions = VALIDATE[:first_guard]
        self.assertNotIn("systemctl restart mosquitto", preconditions)
        self.assertNotIn("docker compose up", preconditions)

        roles = {
            "agent": {"agent"},
            "controller": {"home_assistant", "broker", "controller"},
            "combined": {"home_assistant", "broker", "controller", "agent"},
        }
        self.assertNotIn("home_assistant", roles["agent"])
        self.assertNotIn("broker", roles["agent"])
        self.assertIn("agent", roles["agent"])

    def test_agent_backup_does_not_create_a_phantom_home_assistant_tree(self):
        initial_directories = CREATE.split('compose="$(compose_path)"', 1)[0]
        self.assertNotIn('homeassistant/config', initial_directories)

        compose_block = CREATE.split(
            'if [[ -n "${compose}" ]]; then',
            1,
        )[1].split("fi", 1)[0]
        self.assertIn('"${staging}/homeassistant"', compose_block)

        config_block = CREATE.split(
            'if [[ -d "${HA_DIR}/config" ]]; then',
            1,
        )[1].split("fi", 1)[0]
        self.assertIn('"${staging}/homeassistant/config"', config_block)

    def test_empty_archive_cannot_report_success(self):
        self.assertIn('[[ "${has_component}" == "true" ]] || return 1', VALIDATE)
        home_assistant_validation = VALIDATE.rsplit(
            'if [[ -n "${compose}" ]]; then',
            1,
        )[1]
        self.assertIn("wait_for_home_assistant || return 1", home_assistant_validation)
        self.assertIn("--script check_config", home_assistant_validation)


if __name__ == "__main__":
    unittest.main()
