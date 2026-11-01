"""Issue #322 atomic JA→EN query replacement and saved group boundaries."""

import unittest

from voiceger_editor.english_group_boundaries import bound_english_groups
from voiceger_editor.mixed_language import build_mixed_synthesis_plan
from voiceger_editor.pronunciation import parse_pronunciation
from voiceger_editor.query_ja_arpabet import convert_japanese_section_to_arpabet
from voiceger_editor.query_editing import replace_english_phoneme_groups
from voiceger_editor.voicevox_api_models import VoicegerSegment
from voiceger_editor.voicevox_query import (
    build_audio_query,
    pronunciation_to_accent_phrases,
)


class JapaneseArpabetQueryTests(unittest.TestCase):
    def test_pure_japanese_replaces_single_section_without_caption_reanalysis(self):
        original = build_audio_query(
            pronunciation=parse_pronunciation("ア'メ。")
        )
        before = original.model_dump()
        converted = convert_japanese_section_to_arpabet(
            original,
            "ズ'ンダモンハ/カシコ'イ/ノダ'！",
            pure_japanese_utterance_text="ずんだもんはかしこいのだ！",
        )
        self.assertEqual(before, original.model_dump())
        self.assertEqual(converted.accent_phrases, [])
        self.assertIsNone(converted.kana)
        self.assertIsNone(converted.pronunciationPitchEvents)
        self.assertEqual(len(converted.voicegerSegments), 1)
        segment = converted.voicegerSegments[0]
        self.assertEqual(segment.language, "en")
        self.assertEqual(segment.text, "ずんだもんはかしこいのだ！")
        self.assertEqual(
            [label for label, _phones in bound_english_groups(segment)],
            ["ズンダモンハ", "カシコイ", "ノダ", "!"],
        )
        self.assertEqual(
            build_mixed_synthesis_plan(converted).english_overrides[0][1],
            segment.phonemes,
        )

    def test_mixed_rebases_only_surviving_japanese_ranges(self):
        original = build_audio_query(
            pronunciation=parse_pronunciation("ア'メ/ノダ'。")
        )
        original.kana = None
        original.voicegerSegments = [
            VoicegerSegment(
                language="ja", text="雨",
                accentPhraseStart=0, accentPhraseCount=1,
                pronunciationTerminator="", pronunciationPunctuation=[],
            ),
            VoicegerSegment(
                language="en", text="hello",
                phonemes=["HH", "AH0", "L", "OW1"],
            ),
            VoicegerSegment(
                language="ja", text="のだ。",
                accentPhraseStart=1, accentPhraseCount=1,
                pronunciationTerminator="。", pronunciationPunctuation=[],
            ),
        ]
        original.pronunciationPunctuation = None
        before = original.model_dump()
        converted = convert_japanese_section_to_arpabet(
            original, "ア'メ", segment_index=0,
        )
        self.assertEqual(original.model_dump(), before)
        self.assertEqual(
            [s.language for s in converted.voicegerSegments],
            ["en", "en", "ja"],
        )
        self.assertEqual(converted.voicegerSegments[0].text, "雨")
        self.assertEqual(
            converted.voicegerSegments[1].model_dump(),
            original.voicegerSegments[1].model_dump(),
        )
        self.assertEqual(converted.voicegerSegments[2].accentPhraseStart, 0)
        self.assertEqual(
            converted.accent_phrases[0].model_dump(),
            original.accent_phrases[1].model_dump(),
        )
        self.assertEqual(
            build_mixed_synthesis_plan(converted).text,
            "雨helloのだ。",
        )

    def test_conversion_fails_atomically_on_unsupported_pitch(self):
        query = build_audio_query(pronunciation=parse_pronunciation("ア'メ。"))
        before = query.model_dump()
        with self.assertRaisesRegex(ValueError, "multi-peak"):
            convert_japanese_section_to_arpabet(
                query, "ア[メ]ノ[ダ]", pure_japanese_utterance_text="あめのだ",
            )
        self.assertEqual(query.model_dump(), before)

    def test_rejects_wrong_section_without_mutation(self):
        query = build_audio_query(pronunciation=parse_pronunciation("ア'メ"))
        query.kana = None
        query.voicegerSegments = [
            VoicegerSegment(
                language="en", text="hello",
                phonemes=["HH", "AH0", "L", "OW1"],
            )
        ]
        query.accent_phrases = []
        before = query.model_dump()
        with self.assertRaisesRegex(ValueError, "not Japanese"):
            convert_japanese_section_to_arpabet(
                query, "ア'メ", segment_index=0,
            )
        self.assertEqual(query.model_dump(), before)

    def test_edit_after_conversion_resizes_only_selected_group(self):
        original = build_audio_query(pronunciation=parse_pronunciation("ア'メ。"))
        converted = convert_japanese_section_to_arpabet(
            original, "ズ'ンダ/ノダ'！",
            pure_japanese_utterance_text="ずんだもんはかしこいのだ！",
        )
        segment = converted.voicegerSegments[0]
        groups = bound_english_groups(segment)
        changed = tuple(group for _label, group in groups)
        with_longer_first = (
            changed[0] + ("R", "AA0"), *changed[1:],
        )
        updated = replace_english_phoneme_groups(
            converted, segment_index=0, phoneme_groups=with_longer_first,
        )
        self.assertEqual(
            [len(phones) for _label, phones in bound_english_groups(updated.voicegerSegments[0])],
            [len(group) for group in with_longer_first],
        )
        self.assertEqual(
            [label for label, _ in bound_english_groups(updated.voicegerSegments[0])],
            [label for label, _ in groups],
        )
        self.assertEqual(
            [group for label, group in bound_english_groups(segment)],
            [group for label, group in groups],
        )
        self.assertEqual(
            updated.voicegerSegments[0].text, segment.text,
        )

    def test_no_empty_group_or_group_count_change_after_conversion(self):
        query = convert_japanese_section_to_arpabet(
            build_audio_query(pronunciation=parse_pronunciation("ア'メ。")),
            "ズ'ンダ/ノダ'！",
            pure_japanese_utterance_text="ずんだもんはかしこいのだ！",
        )
        before = query.model_dump()
        groups = tuple(group for label, group in bound_english_groups(query.voicegerSegments[0]))
        with self.assertRaisesRegex(ValueError, "must not become empty"):
            replace_english_phoneme_groups(
                query, segment_index=0,
                phoneme_groups=((), *groups[1:]),
            )
        with self.assertRaisesRegex(ValueError, "group count"):
            replace_english_phoneme_groups(
                query, segment_index=0,
                phoneme_groups=(groups[0] + groups[1], *groups[2:]),
            )
        self.assertEqual(query.model_dump(), before)

    def test_boundaries_roundtrip_and_fail_closed_on_corruption(self):
        query = build_audio_query(pronunciation=parse_pronunciation("ア'メ"))
        converted = convert_japanese_section_to_arpabet(
            query, "キョ'ーワ/ハレ'", pure_japanese_utterance_text="今日は晴れ",
        )
        segment = converted.voicegerSegments[0]
        restored = VoicegerSegment.model_validate(segment.model_dump())
        self.assertEqual(bound_english_groups(restored), bound_english_groups(segment))
        restored.phonemes = restored.phonemes[:-1]
        with self.assertRaisesRegex(ValueError, "boundaries"):
            bound_english_groups(restored)


if __name__ == "__main__":
    unittest.main()
