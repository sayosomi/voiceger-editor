import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from voiceger_editor.pronunciation import (
    format_pronunciation,
    parse_pronunciation,
)
from voiceger_editor.runtime_locks import OPENJTALK_LOCK
from voiceger_editor.voicevox_query import (
    accent_phrases_to_pronunciation,
    build_audio_query,
    _mora_phones,
)


class VoicevoxQueryTests(unittest.TestCase):
    def test_audio_query_keeps_kana_and_accent_phrases(self):
        pronunciation = parse_pronunciation("ア'メ")
        query = build_audio_query(
            pronunciation=pronunciation,
        )

        self.assertEqual(query.kana, "ア'メ")
        self.assertFalse(hasattr(query, "text"))
        self.assertEqual(query.accent_phrases[0].accent, 1)
        self.assertEqual(
            [m.text for m in query.accent_phrases[0].moras],
            ["ア", "メ"],
        )

    def test_audio_query_preserves_ordered_punctuation_metadata(self):
        pronunciation = parse_pronunciation("ア'メ、アメ'…ア'メ！")
        query = build_audio_query(pronunciation=pronunciation)

        self.assertEqual(
            [
                (entry.afterAccentPhrase, entry.mark)
                for entry in query.pronunciationPunctuation
            ],
            [(0, "、"), (1, "…"), (2, "！")],
        )
        rebuilt = accent_phrases_to_pronunciation(
            query.accent_phrases,
            punctuation=query.pronunciationPunctuation,
            terminator="。",
        )
        self.assertEqual(
            format_pronunciation(rebuilt),
            "ア'メ、アメ'…ア'メ！",
        )

    def test_explicit_empty_punctuation_overrides_legacy_terminator(self):
        query = build_audio_query(
            pronunciation=parse_pronunciation("ア'メ")
        )
        rebuilt = accent_phrases_to_pronunciation(
            query.accent_phrases,
            punctuation=[],
            terminator="。",
        )
        self.assertEqual(format_pronunciation(rebuilt), "ア'メ")

    def test_mora_g2p_holds_openjtalk_lock(self):
        def g2p(text, *, kana, join):
            self.assertTrue(OPENJTALK_LOCK._is_owned())
            self.assertEqual((text, kana, join), ("ア", False, False))
            return ["a"]

        with patch.dict(sys.modules, {"pyopenjtalk": SimpleNamespace(g2p=g2p)}):
            self.assertEqual(_mora_phones("ア", None), (None, "a"))

    def test_accent_phrase_edit_round_trips_to_pronunciation(self):
        pronunciation = parse_pronunciation("ア'メ")
        query = build_audio_query(
            pronunciation=pronunciation,
        )
        query.accent_phrases[0].accent = 2

        rebuilt = accent_phrases_to_pronunciation(
            query.accent_phrases,
            terminator=None,
        )
        self.assertEqual(rebuilt.phrases[0].accent, 2)


if __name__ == "__main__":
    unittest.main()
