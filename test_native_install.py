import json
from pathlib import Path
import tempfile
import unittest
from uuid import UUID

from native_install import (
    LEGACY_CSS_END,
    LEGACY_CSS_START,
    LEGACY_IMPORT,
    LEGACY_PREF_END,
    LEGACY_PREF_START,
    OWNER,
    update,
)


ROOT = Path(__file__).parent


class NativeInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="url context native ")
        self.addCleanup(temporary.cleanup)
        self.profile = Path(temporary.name) / "profile"
        self.profile.mkdir()
        (self.profile / "prefs.js").write_text("// profile\n")
        self.chrome = self.profile / "chrome"
        self.chrome.mkdir()
        self.registry = self.profile / "zen-themes.json"
        self.manifest = json.loads((ROOT / "manifest.json").read_text())
        self.target = self.chrome / "zen-themes" / self.manifest["id"]

    def install(self, action="install"):
        update(self.profile, action, ROOT)

    def test_native_install_preserves_registry_and_round_trips(self):
        existing = {
            "other-mod": {
                "id": "other-mod",
                "name": "Other Mod",
                "enabled": False,
                "custom": "keep",
            }
        }
        self.registry.write_text(json.dumps(existing))
        self.install()

        registry = json.loads(self.registry.read_text())
        entry = registry[self.manifest["id"]]
        self.assertEqual(registry["other-mod"], existing["other-mod"])
        self.assertEqual(entry["name"], "Splendid Url Context")
        self.assertTrue(entry["enabled"])
        self.assertEqual((self.target / "chrome.css").read_bytes(),
                         (ROOT / "zen-url-context.css").read_bytes())
        self.assertNotIn("preferences", entry)
        self.assertFalse((self.target / "preferences.json").exists())
        self.assertEqual((self.target / "readme.md").read_bytes(), (ROOT / "README.md").read_bytes())
        self.assertEqual((self.target / ".zen-url-context-owner").read_text(),
                         OWNER + self.manifest["id"] + "\n")

        entry["enabled"] = False
        entry["custom"] = "preserved"
        self.registry.write_text(json.dumps(registry))
        self.install()
        updated = json.loads(self.registry.read_text())[self.manifest["id"]]
        self.assertFalse(updated["enabled"])
        self.assertEqual(updated["custom"], "preserved")

        self.install("uninstall")
        self.assertEqual(json.loads(self.registry.read_text()), existing)
        self.assertFalse(self.target.exists())

    def test_install_migrates_only_marked_legacy_blocks(self):
        user_css = self.chrome / "userChrome.css"
        user_css.write_text(
            "/* user CSS */\n"
            f"{LEGACY_CSS_START}\n"
            '@import url("zen-url-context.css");\n'
            f"{LEGACY_CSS_END}\n"
            "/* keep CSS */\n"
        )
        user_js = self.profile / "user.js"
        user_js.write_text(
            "// user prefs\n"
            f"{LEGACY_PREF_START}\n"
            'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);\n'
            f"{LEGACY_PREF_END}\n"
        )
        legacy_css = self.chrome / "zen-url-context.css"
        legacy_css.write_text("/* Zen Mod: URL Context Quick Actions */\n")

        self.install()

        self.assertEqual(user_css.read_text(), "/* user CSS */\n/* keep CSS */\n")
        self.assertEqual(user_js.read_text(), "// user prefs\n")
        self.assertTrue(legacy_css.exists())
        self.assertIn(self.manifest["id"], json.loads(self.registry.read_text()))

    def test_install_migrates_crlf_legacy_blocks(self):
        user_css = self.chrome / "userChrome.css"
        user_css.write_bytes(
            f'{LEGACY_CSS_START}\r\n{LEGACY_IMPORT}\r\n'
            f"{LEGACY_CSS_END}\r\n/* keep */\r\n".encode()
        )
        user_js = self.profile / "user.js"
        user_js.write_bytes(
            f"{LEGACY_PREF_START}\r\nuser_pref(\"toolkit.legacyUserProfileCustomizations.stylesheets\", true);\r\n"
            f"{LEGACY_PREF_END}\r\n// keep\r\n".encode()
        )

        self.install()

        self.assertEqual(user_css.read_bytes(), b"/* keep */\r\n")
        self.assertEqual(user_js.read_bytes(), b"// keep\r\n")

    def test_unmanaged_legacy_import_is_rejected(self):
        user_css = self.chrome / "userChrome.css"
        user_css.write_text('@import url("zen-url-context.css");\n')
        with self.assertRaisesRegex(ValueError, "unmanaged URL Context import"):
            self.install()
        self.assertFalse(self.registry.exists())
        self.assertFalse(self.target.exists())

    def test_unmanaged_target_collision_is_rejected(self):
        self.target.mkdir(parents=True)
        (self.target / "custom.css").write_text("keep")
        with self.assertRaisesRegex(ValueError, "unmanaged mod directory"):
            self.install()
        self.assertEqual((self.target / "custom.css").read_text(), "keep")

    def test_real_package_manifest(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual(manifest["name"], "Splendid Url Context")
        self.assertEqual(str(UUID(manifest["id"])), manifest["id"])


if __name__ == "__main__":
    unittest.main()
