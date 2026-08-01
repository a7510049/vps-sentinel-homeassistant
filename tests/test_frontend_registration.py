from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "controller"))

from register_frontend import (
    DEFAULT_URL,
    FrontendConfigError,
    ensure_module_file,
    ensure_module_url,
)


class FrontendRegistrationTests(unittest.TestCase):
    def test_adds_frontend_block_when_missing(self):
        updated, changed = ensure_module_url("default_config:\n")
        self.assertTrue(changed)
        self.assertIn(
            "frontend:\n"
            "  extra_module_url:\n"
            f"    - {DEFAULT_URL}\n",
            updated,
        )

    def test_extends_existing_frontend_without_replacing_themes(self):
        source = (
            "frontend:\n"
            "  themes: !include_dir_merge_named themes\n"
            "\n"
            "automation: !include automations.yaml\n"
        )
        updated, changed = ensure_module_url(source)
        self.assertTrue(changed)
        self.assertIn("themes: !include_dir_merge_named themes", updated)
        self.assertLess(
            updated.index(DEFAULT_URL),
            updated.index("automation:"),
        )

    def test_registration_is_idempotent(self):
        source = (
            "frontend:\n"
            "  extra_module_url:\n"
            f"    - {DEFAULT_URL}\n"
        )
        updated, changed = ensure_module_url(source)
        self.assertFalse(changed)
        self.assertEqual(updated, source)

    def test_preserves_custom_include_instead_of_rewriting(self):
        source = "frontend: !include frontend.yaml\n"
        with self.assertRaisesRegex(FrontendConfigError, "!include"):
            ensure_module_url(source)

    def test_file_update_is_atomic_and_preserves_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "configuration.yaml"
            path.write_text("default_config:\n", encoding="utf-8")
            path.chmod(0o640)
            self.assertTrue(ensure_module_file(path))
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertFalse(ensure_module_file(path))


if __name__ == "__main__":
    unittest.main()
