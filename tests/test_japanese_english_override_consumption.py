"""Converted Japanese-source EN overrides must be consumed in segment order."""

import unittest
from types import SimpleNamespace

from voiceger_editor.mixed_pronunciation_overrides import MixedPronunciationOverrides


class ConvertedEnglishOverrideTests(unittest.TestCase):
    def test_identical_normalized_japanese_text_consumes_each_override_once(self):
        english = SimpleNamespace(text_normalize=lambda _text: "")
        japanese = SimpleNamespace(
            text_normalize=lambda value: value,
            g2p=lambda *args: ("untouched",),
        )
        inference = SimpleNamespace(
            clean_text_inf=lambda *args: ("fallback",),
            cleaned_text_to_sequence=lambda phones, version: tuple(phones),
        )
        override = MixedPronunciationOverrides(
            japanese=japanese,
            english=english,
            inference_webui=inference,
            japanese_overrides=[],
            english_overrides=[
                ("雨", ["AA1"]),
                ("晴れ", ["HH", "EH1"]),
            ],
        )
        first, _word2ph, _text = override.clean_text_inf("雨", "en", "v2")
        self.assertEqual(first, ("AA1",))
        self.assertEqual(override.remaining_english, 1)
        second, _word2ph, _text = override.clean_text_inf("晴れ", "en", "v2")
        self.assertEqual(second, ("HH", "EH1"))
        self.assertEqual(override.remaining_english, 0)

    def test_nonmatching_english_text_does_not_consume_override(self):
        english = SimpleNamespace(text_normalize=lambda value: value)
        japanese = SimpleNamespace(
            text_normalize=lambda value: value,
            g2p=lambda *args: ("untouched",),
        )
        inference = SimpleNamespace(
            clean_text_inf=lambda *args: ("fallback", None, "other"),
            cleaned_text_to_sequence=lambda phones, version: tuple(phones),
        )
        override = MixedPronunciationOverrides(
            japanese=japanese, english=english, inference_webui=inference,
            japanese_overrides=[],
            english_overrides=[("hello", ["HH", "AH0"])],
        )
        self.assertEqual(
            override.clean_text_inf("not-hello", "en", "v2"),
            ("fallback", None, "other"),
        )
        self.assertEqual(override.remaining_english, 1)


if __name__ == "__main__":
    unittest.main()
