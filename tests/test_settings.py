import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from voiceger_editor.settings import (
    Settings,
    SettingsError,
    default_config_path,
    load_settings,
    save_settings,
)


class SettingsTests(unittest.TestCase):
    def test_missing_config_and_default_values(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "missing" / "config.json"

            settings = load_settings(config_path)

        self.assertEqual(settings, Settings())
        self.assertEqual(
            settings.output_dir,
            Path.home() / ".voiceger-editor" / "output",
        )
        self.assertEqual(settings.filename_template, "{YYYYMMDDHHmm}_{text}")
        self.assertEqual(settings.take_count, 4)
        self.assertEqual(settings.style_id, 3)
        self.assertEqual(settings.speed, 1.0)
        self.assertEqual(settings.top_k, 20)
        self.assertEqual(settings.top_p, 1.0)
        self.assertEqual(settings.temperature, 1.0)
        self.assertFalse(settings.save_text)
        self.assertFalse(settings.save_lab)

    def test_save_creates_parent_directories_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "deep" / "nested" / "config.json"
            settings = Settings(
                output_dir=Path(directory) / "生成音声",
                filename_template="{YYYY-MM-DD}_{HHmmss}_{style}_{text}",
                take_count=8,
                style_id=38,
                speed=1.25,
                top_k=37,
                top_p=0.45,
                temperature=0.80,
                save_text=True,
                save_lab=True,
            )

            saved_path = save_settings(settings, config_path)
            first_contents = config_path.read_bytes()
            save_settings(settings, config_path)

            self.assertEqual(saved_path, config_path)
            self.assertEqual(first_contents, config_path.read_bytes())
            self.assertEqual(load_settings(config_path), settings)
            self.assertEqual(
                json.loads(first_contents.decode("utf-8")),
                {
                    "output_dir": str(settings.output_dir),
                    "filename_template": "{YYYY-MM-DD}_{HHmmss}_{style}_{text}",
                    "take_count": 8,
                    "style_id": 38,
                    "speed": 1.25,
                    "top_k": 37,
                    "top_p": 0.45,
                    "temperature": 0.8,
                    "save_text": True,
                    "save_lab": True,
                },
            )
            self.assertTrue(first_contents.endswith(b"\n"))

    def test_legacy_config_without_sampling_keys_uses_voiceger_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "legacy.json"
            config_path.write_text(
                '{"take_count": 2, "style_id": 3, "speed": 1.2, "save_text": true}',
                encoding="utf-8",
            )

            settings = load_settings(config_path)

        self.assertEqual(settings.take_count, 2)
        self.assertEqual(settings.style_id, 3)
        self.assertEqual(settings.speed, 1.2)
        self.assertEqual(settings.top_k, 20)
        self.assertEqual(settings.top_p, 1.0)
        self.assertEqual(settings.temperature, 1.0)
        self.assertEqual(settings.filename_template, "{YYYYMMDDHHmm}_{text}")

    def test_custom_config_path_can_be_loaded_and_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "custom.json"
            settings = Settings(take_count=2)

            save_settings(settings, config_path=config_path)

            self.assertEqual(load_settings(config_path=config_path), settings)

    def test_validation_rejects_invalid_settings_values(self):
        invalid_values = [
            {"take_count": 0},
            {"take_count": 101},
            {"take_count": 1.5},
            {"take_count": True},
            {"style_id": 0},
            {"style_id": False},
            {"speed": 0},
            {"speed": -0.5},
            {"speed": float("nan")},
            {"speed": float("inf")},
            {"speed": 10**1000},
            {"speed": True},
            {"top_k": 0},
            {"top_k": 101},
            {"top_k": 1.5},
            {"top_k": True},
            {"top_p": -0.01},
            {"top_p": 1.01},
            {"top_p": float("nan")},
            {"top_p": float("inf")},
            {"top_p": True},
            {"temperature": -0.01},
            {"temperature": 1.01},
            {"temperature": float("nan")},
            {"temperature": float("inf")},
            {"temperature": True},
            {"save_text": 1},
            {"save_lab": 1},
            {"filename_template": ""},
            {"filename_template": "{take}_{text}"},
            {"filename_template": "{YYYYQQ}_{text}"},
            {"output_dir": ""},
            {"output_dir": "invalid\x00path"},
        ]
        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(SettingsError):
                    Settings(**values)

    def test_take_count_accepts_inclusive_one_to_hundred_bounds(self):
        self.assertEqual(Settings(take_count=1).take_count, 1)
        self.assertEqual(Settings(take_count=100).take_count, 100)
        for invalid in (0, 101, True, False):
            with self.subTest(take_count=invalid):
                with self.assertRaises(SettingsError):
                    Settings(take_count=invalid)

    def test_invalid_persisted_values_are_not_discarded(self):
        invalid_documents = [
            '{"take_count": 101}',
            '{"top_k": 0}',
            '{"top_p": 1.01}',
            '{"temperature": -0.01}',
            '{"save_text": "yes"}',
            '{"save_lab": "yes"}',
            '{"filename_template": "{datetime}_{text}"}',
            '{"future_setting": true}',
        ]
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            for contents in invalid_documents:
                with self.subTest(contents=contents):
                    config_path.write_text(contents, encoding="utf-8")
                    with self.assertRaises(SettingsError):
                        load_settings(config_path)

    def test_malformed_json_fails_with_path_and_location(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text('{"take_count":', encoding="utf-8")

            with self.assertRaisesRegex(
                SettingsError,
                r"config\.json: malformed JSON at line 1",
            ):
                load_settings(config_path)

    def test_non_object_and_duplicate_keys_fail_clearly(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            for contents, message in (
                ("[]", "config must be a JSON object"),
                ('{"speed": 1, "speed": 2}', "duplicate setting 'speed'"),
            ):
                with self.subTest(contents=contents):
                    config_path.write_text(contents, encoding="utf-8")
                    with self.assertRaisesRegex(SettingsError, message):
                        load_settings(config_path)

    def test_config_path_uses_windows_appdata_and_ignores_xdg(self):
        with patch("voiceger_editor.settings.sys.platform", "win32"), patch.dict(
            os.environ,
            {
                "APPDATA": "C:/Users/example/AppData/Roaming",
                "XDG_CONFIG_HOME": "/tmp/xdg",
            },
            clear=True,
        ):
            self.assertEqual(
                default_config_path(),
                Path("C:/Users/example/AppData/Roaming")
                / "voiceger-editor"
                / "config.json",
            )

    def test_config_path_windows_falls_back_to_userprofile(self):
        with patch("voiceger_editor.settings.sys.platform", "win32"), patch.dict(
            os.environ,
            {
                "USERPROFILE": "C:/Users/example",
                "XDG_CONFIG_HOME": "/tmp/xdg",
            },
            clear=True,
        ):
            self.assertEqual(
                default_config_path(),
                Path("C:/Users/example")
                / "AppData"
                / "Roaming"
                / "voiceger-editor"
                / "config.json",
            )

    def test_config_path_uses_macos_application_support(self):
        home = Path("/home/example")
        with patch("voiceger_editor.settings.Path.home", return_value=home), patch(
            "voiceger_editor.settings.sys.platform", "darwin"
        ), patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/xdg"}, clear=True):
            self.assertEqual(
                default_config_path(),
                home
                / "Library"
                / "Application Support"
                / "voiceger-editor"
                / "config.json",
            )

    def test_config_path_honors_xdg_config_home(self):
        with patch("voiceger_editor.settings.sys.platform", "linux"), patch.dict(
            os.environ,
            {"XDG_CONFIG_HOME": "/tmp/custom-config"},
            clear=True,
        ):
            self.assertEqual(
                default_config_path(),
                Path("/tmp/custom-config") / "voiceger-editor" / "config.json",
            )

    def test_config_path_falls_back_to_home_config_directory(self):
        home = Path("/home/example")
        with patch("voiceger_editor.settings.Path.home", return_value=home), patch(
            "voiceger_editor.settings.sys.platform", "linux"
        ), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                default_config_path(),
                home / ".config" / "voiceger-editor" / "config.json",
            )


if __name__ == "__main__":
    unittest.main()
