from pathlib import Path
import re
import unittest


ROOT = Path(__file__).parents[1]
MANAGE = (ROOT / "manage.sh").read_text(encoding="utf-8")
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
SUBTOOLS = {
    name: (ROOT / name).read_text(encoding="utf-8")
    for name in ["doctor.sh", "backup.sh", "automations.sh", "uninstall.sh"]
}
HA_UPDATE = (ROOT / "update.sh").read_text(encoding="utf-8")
SENTINEL_UPGRADE = (ROOT / "upgrade.sh").read_text(encoding="utf-8")


class CommandInterfaceTests(unittest.TestCase):
    def test_release_version_is_0_7(self):
        self.assertEqual(VERSION, "0.7.0")

    def test_header_does_not_use_width_sensitive_box_drawing(self):
        self.assertNotIn("╭", MANAGE)
        self.assertNotIn("╰", MANAGE)

    def test_dashboard_gives_cpu_memory_and_disk_equal_priority(self):
        dashboard = MANAGE.split(
            'cat > "${DASHBOARD_FILE}" <<YAML', 1
        )[1].split("\nYAML", 1)[0]
        gauges = [
            "sensor.${vps_id}_cpu_percent",
            "sensor.${vps_id}_memory_percent",
            "sensor.${vps_id}_disk_percent",
        ]
        for entity in gauges:
            self.assertIn(entity, dashboard)
        self.assertNotIn("記憶體已使用", dashboard)

    def test_dashboard_uses_responsive_native_sections(self):
        dashboard = MANAGE.split(
            'cat > "${DASHBOARD_FILE}" <<YAML', 1
        )[1].split("\nYAML", 1)[0]
        self.assertIn("- type: sections", dashboard)
        self.assertIn("max_columns: 3", dashboard)
        self.assertNotIn("type: horizontal-stack", dashboard)
        self.assertEqual(dashboard.count("type: bar-gauge"), 3)

    def test_dashboard_keeps_mobile_resources_compact(self):
        dashboard = MANAGE.split(
            'cat > "${DASHBOARD_FILE}" <<YAML', 1
        )[1].split("\nYAML", 1)[0]
        self.assertNotIn("path: resources", dashboard)
        self.assertNotIn("type: trend-graph", dashboard)
        self.assertNotIn("navigation_path:", dashboard)
        self.assertEqual(dashboard.count("vertical: false"), 3)

    def test_upgrade_version_comparison_stays_on_one_condition_line(self):
        self.assertIn(
            'if [[ "${downloaded_version}" != "${latest_version}" ]]; then',
            SENTINEL_UPGRADE,
        )

    def test_main_menu_has_four_stable_sections(self):
        expected = [
            "📊 查看系統狀態",
            "⚙️  調整監控設定",
            "🏠 管理 Home Assistant",
            "🧰 系統維護",
        ]
        for label in expected:
            self.assertIn(label, MANAGE)

    def test_submenus_use_zero_to_return(self):
        submenu_names = [
            "settings_menu",
            "home_assistant_menu",
            "maintenance_menu",
        ]
        for index, name in enumerate(submenu_names):
            start = MANAGE.index(f"{name}()")
            if index + 1 < len(submenu_names):
                end = MANAGE.index(f"{submenu_names[index + 1]}()")
            else:
                end = MANAGE.index("print_help()")
            self.assertIn("0. 返回主選單", MANAGE[start:end])

    def test_documented_commands_have_dispatch_entries(self):
        help_text = MANAGE[
            MANAGE.index("指令："):MANAGE.index("\nHELP\n", MANAGE.index("指令："))
        ]
        documented = re.findall(
            r"^  ([a-z-]+)\s{2,}.+$",
            help_text,
            flags=re.MULTILINE,
        )
        dispatch = MANAGE[
            MANAGE.index("run_command()"):MANAGE.index("main_menu()")
        ]
        for command in documented:
            if command == "help":
                continue
            self.assertIn(f"{command})", dispatch)

    def test_full_removal_is_not_on_main_menu(self):
        main_menu = MANAGE[MANAGE.index("main_menu()"):]
        displayed_menu = main_menu[:main_menu.index('read -r -p "請選擇 [1]')]
        self.assertNotIn("完整移除", displayed_menu)

    def test_subtools_default_to_safe_return_or_cancel(self):
        for name, script in SUBTOOLS.items():
            with self.subTest(script=name):
                self.assertRegex(script, r'請選擇 \[0\]')

    def test_uninstaller_does_nothing_on_empty_choice(self):
        uninstall = SUBTOOLS["uninstall.sh"]
        self.assertIn('choice="${choice:-0}"', uninstall)
        self.assertRegex(
            uninstall,
            r'0\)\s+echo "已取消，沒有刪除任何資料。',
        )

    def test_successful_updates_keep_only_latest_project_backup(self):
        self.assertIn("tail -n +2", HA_UPDATE)
        self.assertIn("tail -n +2", SENTINEL_UPGRADE)

    def test_cleanup_never_uses_global_docker_prune(self):
        self.assertNotIn("docker system prune", HA_UPDATE)
        self.assertNotIn("docker image prune", HA_UPDATE)
        self.assertIn("vps-sentinel-rollback", HA_UPDATE)

    def test_cleanup_failure_does_not_fail_successful_update(self):
        self.assertIn('if ! rm -f -- "${old_backup}"', HA_UPDATE)
        self.assertIn('if ! rm -rf -- "${old_backup}"', SENTINEL_UPGRADE)
        self.assertIn("部分舊備份需要稍後手動清理", HA_UPDATE)
        self.assertIn("部分舊版備份需要稍後手動清理", SENTINEL_UPGRADE)


if __name__ == "__main__":
    unittest.main()
