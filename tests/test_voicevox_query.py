import unittest

from voiceger_accent_adapter.pronunciation import parse_pronunciation
from voiceger_accent_adapter.voicevox_query import (
    accent_phrases_to_pronunciation,
    build_audio_query,
)


class VoicevoxQueryTests(unittest.TestCase):
    def test_audio_query_keeps_kana_and_accent_phrases(self):
        pronunciation = parse_pronunciation("ア'メ")
        query = build_audio_query(
            text="雨",
            pronunciation=pronunciation,
        )

        self.assertEqual(query.kana, "ア'メ")
        self.assertEqual(query.text, "雨")
        self.assertEqual(query.accent_phrases[0].accent, 1)
        self.assertEqual(
            [m.text for m in query.accent_phrases[0].moras],
            ["ア", "メ"],
        )

    def test_accent_phrase_edit_round_trips_to_pronunciation(self):
        pronunciation = parse_pronunciation("ア'メ")
        query = build_audio_query(
            text="雨",
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
