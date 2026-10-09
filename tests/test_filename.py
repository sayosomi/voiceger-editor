import unittest
from datetime import datetime

from voiceger_editor.filename import (
    DEFAULT_FILENAME_TEMPLATE,
    FilenameTemplateError,
    build_output_filename,
    render_output_basename,
    sanitize_filename_part,
    validate_filename_template,
)


class FileNameTests(unittest.TestCase):
    timestamp = datetime(2026, 10, 7, 19, 45, 23)

    def test_default_template_preserves_existing_minute_resolution_name(self):
        self.assertEqual(DEFAULT_FILENAME_TEMPLATE, "{YYYYMMDDHHmm}_{caption}")
        self.assertEqual(
            build_output_filename(
                text="今日はhelloと言うよ。",
                timestamp=self.timestamp,
            ),
            "202610071945_今日はhelloと言うよ。.wav",
        )

    def test_default_template_ignores_seconds(self):
        source = "同じ分です。"
        first = build_output_filename(
            text=source,
            timestamp=datetime(2026, 10, 1, 20, 45, 0),
        )
        second = build_output_filename(
            text=source,
            timestamp=datetime(2026, 10, 1, 20, 45, 59),
        )
        self.assertEqual(first, "202610012045_同じ分です。.wav")
        self.assertEqual(second, first)

    def test_supported_date_time_tokens_and_named_variables_render_together(self):
        self.assertEqual(
            render_output_basename(
                template="{YYYY}-{MM}-{DD}_{HH}{mm}{ss}_{style}_{caption}",
                text="今日は雨なのだ。",
                style="Neutral",
                timestamp=self.timestamp,
            ),
            "2026-10-07_194523_Neutral_今日は雨なのだ。",
        )

    def test_month_and_minute_tokens_are_distinct(self):
        self.assertEqual(
            render_output_basename(
                template="{MM}_{mm}",
                text="ignored",
                style="ignored",
                timestamp=self.timestamp,
            ),
            "10_45",
        )

    def test_unknown_variables_and_unsupported_date_time_tokens_are_rejected(self):
        invalid = (
            "{datetime}",
            "{date}",
            "{time}",
            "{take}",
            "{unknown}",
            "{text}",
            "{YY}",
            "{hh}",
            "{YYYYQQ}",
            "{YYYY",
            "YYYY}",
            "{}",
        )
        for template in invalid:
            with self.subTest(template=template):
                with self.assertRaises(FilenameTemplateError):
                    validate_filename_template(template)

    def test_removed_text_variable_has_explicit_error(self):
        with self.assertRaisesRegex(
            FilenameTemplateError,
            r"variable \{text\} is no longer supported; use \{caption\}",
        ):
            validate_filename_template("{text}")

    def test_extension_is_added_outside_template(self):
        basename = render_output_basename(
            template="{style}_{caption}",
            text="hello",
            style="Neutral",
            timestamp=self.timestamp,
        )
        self.assertEqual(basename, "Neutral_hello")
        self.assertEqual(
            build_output_filename(
                text="hello",
                style="Neutral",
                timestamp=self.timestamp,
                filename_template="{style}_{caption}",
            ),
            "Neutral_hello.wav",
        )

    def test_filename_does_not_truncate_source_longer_than_old_limit(self):
        source = "12345678901とても長い発話です。"
        result = build_output_filename(
            text=source,
            timestamp=datetime(2026, 9, 27, 17, 55, 6),
        )
        self.assertEqual(
            result,
            f"202609271755_{source}.wav",
        )
        self.assertNotIn("…", result)

    def test_rendered_user_fields_use_existing_sanitization(self):
        self.assertEqual(
            render_output_basename(
                template="{style}_{caption}",
                text='a/b:c?"d*e|f123456',
                style="Neu:tral",
                timestamp=self.timestamp,
            ),
            "Neutral_abcdef123456",
        )

    def test_invalid_filename_characters_are_removed(self):
        self.assertEqual(
            sanitize_filename_part('a/b:c?"d*e|f'),
            "abcdef",
        )

    def test_template_that_sanitizes_to_empty_is_rejected_at_render_time(self):
        with self.assertRaisesRegex(
            FilenameTemplateError,
            "empty basename",
        ):
            render_output_basename(
                template="///",
                text="ignored",
                style="ignored",
                timestamp=self.timestamp,
            )


if __name__ == "__main__":
    unittest.main()
