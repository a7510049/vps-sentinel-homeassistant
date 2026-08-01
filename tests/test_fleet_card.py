from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
CARD_PATH = (
    ROOT / "home-assistant" / "www" / "vps-sentinel-fleet-card.js"
)
SOURCE = CARD_PATH.read_text(encoding="utf-8")


class FleetCardContractTests(unittest.TestCase):
    def test_uses_one_stable_fleet_entity(self):
        self.assertIn(
            'entity: "sensor.vps_sentinel_fleet_nodes"',
            SOURCE,
        )
        self.assertIn("state.attributes.nodes", SOURCE)
        self.assertNotIn("cpu_percent_entity", SOURCE)
        self.assertNotIn("config.vps_id", SOURCE)

    def test_supports_all_registry_states_with_text_labels(self):
        for status, label in {
            "critical": "嚴重",
            "offline": "離線",
            "stale": "資料過期",
            "warning": "注意",
            "normal": "正常",
        }.items():
            with self.subTest(status=status):
                self.assertIn(f"{status}:", SOURCE)
                self.assertIn(f'label: "{label}"', SOURCE)

    def test_has_search_filter_and_problem_first_sorting(self):
        self.assertIn('type="search"', SOURCE)
        self.assertIn('data-filter="problems"', SOURCE)
        self.assertIn('data-filter="offline"', SOURCE)
        self.assertIn(".rank -", SOURCE)

    def test_accessibility_and_mobile_rules_are_present(self):
        self.assertIn('aria-label="搜尋 VPS"', SOURCE)
        self.assertIn('aria-expanded="', SOURCE)
        self.assertIn(":focus-visible", SOURCE)
        self.assertIn("min-height: 44px", SOURCE)
        self.assertIn("@media (max-width: 600px)", SOURCE)
        self.assertIn("@media (prefers-reduced-motion: no-preference)", SOURCE)

    def test_has_loading_missing_empty_and_no_results_states(self):
        for message in [
            "正在載入",
            "找不到 Fleet 實體",
            "尚未加入 VPS",
            "沒有符合的節點",
        ]:
            with self.subTest(message=message):
                self.assertIn(message, SOURCE)

    def test_dynamic_values_are_escaped_before_html_rendering(self):
        self.assertIn("escape(value)", SOURCE)
        self.assertIn("replaceAll("&", "&amp;")", SOURCE)
        self.assertIn("this.escape(node.display_name", SOURCE)
        self.assertIn("this.escape(provider)", SOURCE)


if __name__ == "__main__":
    unittest.main()
