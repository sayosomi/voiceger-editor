import unittest

from voiceger_accent_adapter.english_stress import (
    EnglishPhonemeEditorState,
    english_phonemes_to_editor_state,
)
from voiceger_accent_adapter.pronunciation import parse_pronunciation
from voiceger_accent_adapter.query_editing import (
    english_editor_state,
    japanese_pronunciation,
    move_english_primary_stress,
    replace_english_base_phonemes,
    replace_english_editor_state,
    replace_english_phoneme_groups,
    replace_japanese_pronunciation,
)
from voiceger_accent_adapter.voicevox_api_models import (
    AccentPhrase,
    AudioQuery,
    Mora,
    VoicegerSegment,
)


def _accent_phrases(notation):
    parsed = parse_pronunciation(notation)
    return [
        AccentPhrase(
            moras=[
                Mora(text=mora, vowel="a", vowel_length=0.1, pitch=0.0)
                for mora in phrase.morae
            ],
            accent=phrase.accent,
            is_interrogative=(
                parsed.terminator == "？"
                and phrase_index == len(parsed.phrases) - 1
            ),
        )
        for phrase_index, phrase in enumerate(parsed.phrases)
    ]


def _pure_query(notation="ア'メ。", **fields):
    return AudioQuery(
        accent_phrases=_accent_phrases(notation),
        kana=fields.pop("kana", notation),
        **fields,
    )


def _mixed_query(phrases, segments, **fields):
    accent_phrases = []
    for notation in phrases:
        accent_phrases.extend(_accent_phrases(notation))
    return AudioQuery(
        accent_phrases=accent_phrases,
        kana=None,
        voicegerSegments=segments,
        **fields,
    )


class QueryEditingTests(unittest.TestCase):
    def test_pure_japanese_notation_uses_synthesis_terminator_rule(self):
        question = _pure_query("ア'メ", kana="アメ？")
        fallback = _pure_query("ア'メ", kana=None)
        fallback.accent_phrases[-1].is_interrogative = True

        self.assertEqual(japanese_pronunciation(question), "ア'メ？")
        self.assertEqual(japanese_pronunciation(fallback), "ア'メ？")

    def test_grouped_english_draft_commits_to_existing_flat_segment(self):
        query = _mixed_query(
            [],
            [VoicegerSegment(language="en", text="Hi!", phonemes=["HH", "AY1", "!"])],
        )

        updated = replace_english_phoneme_groups(
            query,
            segment_index=0,
            phoneme_groups=(("HH", "IY1"), ("!",)),
        )

        self.assertEqual(query.voicegerSegments[0].phonemes, ["HH", "AY1", "!"])
        self.assertEqual(
            updated.voicegerSegments[0].phonemes,
            ["HH", "IY1", "!"],
        )

    def test_pure_japanese_replacement_returns_a_copy_and_preserves_controls(self):
        query = _pure_query(
            "ア'メ？",
            speedScale=1.25,
            pitchScale=0.2,
            intonationScale=0.8,
            volumeScale=0.6,
            prePhonemeLength=0.2,
            postPhonemeLength=0.3,
            pauseLength=0.4,
            pauseLengthScale=1.4,
            outputSamplingRate=44100,
            outputStereo=True,
        )
        original_fields = query.model_dump()

        updated = replace_japanese_pronunciation(query, "アメ'？")

        self.assertIsNot(updated, query)
        self.assertIsNot(updated.accent_phrases, query.accent_phrases)
        self.assertEqual(japanese_pronunciation(updated), "アメ'？")
        self.assertEqual(updated.kana, "アメ'？")
        self.assertEqual(updated.accent_phrases[0].accent, 2)
        self.assertEqual(query.model_dump(), original_fields)
        for field in (
            "speedScale",
            "pitchScale",
            "intonationScale",
            "volumeScale",
            "prePhonemeLength",
            "postPhonemeLength",
            "pauseLength",
            "pauseLengthScale",
            "outputSamplingRate",
            "outputStereo",
        ):
            self.assertEqual(getattr(updated, field), getattr(query, field))

    def test_pure_replacement_can_change_terminator_independently_of_text(self):
        for replacement in ("オ'ト", "オ'ト。", "オ'ト？", "オ'ト！"):
            with self.subTest(replacement=replacement):
                query = _pure_query("ア'メ。")
                updated = replace_japanese_pronunciation(query, replacement)

                self.assertEqual(updated.kana, replacement)
                self.assertEqual(japanese_pronunciation(updated), replacement)
                self.assertEqual(
                    updated.accent_phrases[-1].is_interrogative,
                    replacement.endswith("？"),
                )

    def test_pure_japanese_rejects_explicit_segment_index(self):
        query = _pure_query()

        with self.assertRaisesRegex(ValueError, "pure Japanese"):
            japanese_pronunciation(query, segment_index=0)
        with self.assertRaisesRegex(ValueError, "pure Japanese"):
            replace_japanese_pronunciation(
                query,
                "アメ'。",
                segment_index=0,
            )

    def test_mixed_japanese_requires_segment_index_and_validates_target(self):
        query = _mixed_query(
            ["ア'メ"],
            [
                VoicegerSegment(
                    language="ja",
                    text="雨",
                    accentPhraseStart=0,
                    accentPhraseCount=1,
                ),
                VoicegerSegment(language="en", text="hello", phonemes=["HH", "AH0"]),
            ],
        )

        with self.assertRaisesRegex(ValueError, "require segment_index"):
            japanese_pronunciation(query)
        with self.assertRaisesRegex(ValueError, "require segment_index"):
            replace_japanese_pronunciation(query, "アメ'")
        with self.assertRaisesRegex(ValueError, "integer"):
            japanese_pronunciation(query, segment_index=True)
        with self.assertRaisesRegex(ValueError, "out of range"):
            japanese_pronunciation(query, segment_index=2)
        with self.assertRaisesRegex(ValueError, "not Japanese"):
            replace_japanese_pronunciation(query, "オ'ト", segment_index=1)

    def test_mixed_japanese_rendering_uses_explicit_then_legacy_terminator(self):
        query = _mixed_query(
            ["ア'メ", "サ'ク"],
            [
                VoicegerSegment(
                    language="ja",
                    text="雨が",
                    accentPhraseStart=0,
                    accentPhraseCount=1,
                    pronunciationTerminator="！",
                ),
                VoicegerSegment(language="en", text="hello", phonemes=["HH", "AH0"]),
                VoicegerSegment(
                    language="ja",
                    text="咲く。",
                    accentPhraseStart=1,
                    accentPhraseCount=1,
                ),
            ],
        )

        self.assertEqual(japanese_pronunciation(query, segment_index=0), "ア'メ！")
        self.assertEqual(japanese_pronunciation(query, segment_index=2), "サ'ク。")

    def test_mixed_japanese_replacement_with_same_phrase_count(self):
        query = _mixed_query(
            ["ア'メ", "サ'ク。"],
            [
                VoicegerSegment(language="ja", text="雨", accentPhraseStart=0, accentPhraseCount=1),
                VoicegerSegment(language="en", text="hello", phonemes=["HH", "AH0"]),
                VoicegerSegment(language="ja", text="咲く。", accentPhraseStart=1, accentPhraseCount=1),
            ],
        )

        updated = replace_japanese_pronunciation(
            query,
            "オ'ト",
            segment_index=0,
        )

        self.assertEqual(japanese_pronunciation(updated, segment_index=0), "オ'ト")
        self.assertEqual(updated.voicegerSegments[0].accentPhraseCount, 1)
        self.assertEqual(updated.voicegerSegments[2].accentPhraseStart, 1)
        self.assertIsNone(updated.kana)

    def test_mixed_japanese_replacement_with_more_phrases_reindexes_later_japanese(self):
        query = _mixed_query(
            ["ア'メ", "サ'ク。"],
            [
                VoicegerSegment(language="ja", text="first", accentPhraseStart=0, accentPhraseCount=1),
                VoicegerSegment(language="en", text="hello", phonemes=["HH", "AH0", "L"]),
                VoicegerSegment(language="ja", text="last。", accentPhraseStart=1, accentPhraseCount=1),
            ],
            speedScale=1.3,
        )
        english_before = query.voicegerSegments[1].model_dump()
        original_fields = query.model_dump()

        updated = replace_japanese_pronunciation(
            query,
            "ア'/メ'/オ'",
            segment_index=0,
        )

        self.assertEqual(updated.voicegerSegments[0].accentPhraseCount, 3)
        self.assertEqual(updated.voicegerSegments[2].accentPhraseStart, 3)
        self.assertEqual(updated.voicegerSegments[2].accentPhraseCount, 1)
        self.assertEqual(japanese_pronunciation(updated, segment_index=0), "ア'/メ'/オ'")
        self.assertEqual(updated.voicegerSegments[1].model_dump(), english_before)
        self.assertEqual(query.model_dump(), original_fields)
        self.assertEqual(updated.speedScale, query.speedScale)
        self.assertIsNone(updated.kana)

    def test_mixed_japanese_replacement_with_fewer_phrases_reindexes_later_japanese(self):
        query = _mixed_query(
            ["ア'/メ'/オ'", "サ'ク。"],
            [
                VoicegerSegment(language="ja", text="first", accentPhraseStart=0, accentPhraseCount=3),
                VoicegerSegment(language="en", text="hello", phonemes=["HH", "AH0"]),
                VoicegerSegment(language="ja", text="last。", accentPhraseStart=3, accentPhraseCount=1),
            ],
        )

        updated = replace_japanese_pronunciation(
            query,
            "ア'メ",
            segment_index=0,
        )

        self.assertEqual(updated.voicegerSegments[0].accentPhraseCount, 1)
        self.assertEqual(updated.voicegerSegments[2].accentPhraseStart, 1)
        self.assertEqual(updated.voicegerSegments[2].accentPhraseCount, 1)
        self.assertEqual(len(updated.accent_phrases), 2)

    def test_mixed_replacement_preserves_unrelated_segment_data_and_controls(self):
        query = _mixed_query(
            ["ア'メ", "サ'ク。"],
            [
                VoicegerSegment(language="ja", text="first", accentPhraseStart=0, accentPhraseCount=1),
                VoicegerSegment(language="en", text="hello", phonemes=["HH", "AH0", "L"]),
                VoicegerSegment(language="ko", text="안녕", phonemes=["custom", "tokens"]),
                VoicegerSegment(language="ja", text="last。", accentPhraseStart=1, accentPhraseCount=1),
            ],
            speedScale=1.15,
            volumeScale=0.75,
        )
        preserved_segments = [
            query.voicegerSegments[index].model_dump() for index in (1, 2)
        ]

        updated = replace_japanese_pronunciation(query, "オ'ト/ア'メ", segment_index=0)

        self.assertEqual(
            [updated.voicegerSegments[index].model_dump() for index in (1, 2)],
            preserved_segments,
        )
        self.assertEqual(updated.voicegerSegments[0].text, "first")
        self.assertEqual(updated.voicegerSegments[0].language, "ja")
        self.assertEqual(updated.voicegerSegments[3].accentPhraseStart, 2)
        self.assertEqual(updated.speedScale, 1.15)
        self.assertEqual(updated.volumeScale, 0.75)
        self.assertIsNone(updated.kana)

    def test_malformed_japanese_references_fail_without_mutating_query(self):
        cases = {
            "missing count": [
                VoicegerSegment(language="ja", text="first", accentPhraseStart=0),
            ],
            "zero count": [
                VoicegerSegment(language="ja", text="first", accentPhraseStart=0, accentPhraseCount=0),
            ],
            "non-contiguous": [
                VoicegerSegment(language="ja", text="first", accentPhraseStart=0, accentPhraseCount=1),
                VoicegerSegment(language="en", text="hello"),
                VoicegerSegment(language="ja", text="last", accentPhraseStart=2, accentPhraseCount=1),
            ],
            "out of bounds": [
                VoicegerSegment(language="ja", text="first", accentPhraseStart=0, accentPhraseCount=2),
            ],
        }
        phrase_inputs = {
            "missing count": ["ア'メ"],
            "zero count": ["ア'メ"],
            "non-contiguous": ["ア'メ", "サ'ク"],
            "out of bounds": ["ア'メ"],
        }

        for name, segments in cases.items():
            with self.subTest(name=name):
                query = _mixed_query(phrase_inputs[name], segments)
                original_fields = query.model_dump()
                with self.assertRaises(ValueError):
                    replace_japanese_pronunciation(
                        query,
                        "オ'ト",
                        segment_index=0,
                    )
                self.assertEqual(query.model_dump(), original_fields)

    def test_mixed_replacement_persists_any_explicit_terminator_without_text_change(self):
        query = _mixed_query(
            ["ア'メ。"],
            [VoicegerSegment(language="ja", text="雨。", accentPhraseStart=0, accentPhraseCount=1)],
        )

        for replacement, expected in (
            ("オ'ト", ""),
            ("オ'ト。", "。"),
            ("オ'ト？", "？"),
            ("オ'ト！", "！"),
        ):
            with self.subTest(replacement=replacement):
                updated = replace_japanese_pronunciation(
                    query,
                    replacement,
                    segment_index=0,
                )
                self.assertEqual(updated.voicegerSegments[0].text, "雨。")
                self.assertEqual(
                    updated.voicegerSegments[0].pronunciationTerminator,
                    expected,
                )
                self.assertEqual(
                    japanese_pronunciation(updated, segment_index=0),
                    replacement,
                )

    def test_english_editor_state_hides_stress_suffixes(self):
        query = _mixed_query(
            ["ア'メ"],
            [
                VoicegerSegment(language="ja", text="雨", accentPhraseStart=0, accentPhraseCount=1),
                VoicegerSegment(
                    language="en",
                    text="hello",
                    phonemes=["HH", "AH0", "L", "OW1"],
                ),
            ],
        )

        state = english_editor_state(query, segment_index=1)

        self.assertEqual(state.base_phonemes, ("HH", "AH", "L", "OW"))
        self.assertEqual(state.vowel_stresses, (0, 1))

    def test_english_editor_state_replacement_updates_only_selected_segment(self):
        query = _mixed_query(
            ["ア'メ"],
            [
                VoicegerSegment(language="ja", text="雨", accentPhraseStart=0, accentPhraseCount=1),
                VoicegerSegment(language="en", text="hello", phonemes=["HH", "AH0"]),
                VoicegerSegment(language="en", text="world", phonemes=["W", "ER1", "L", "D"]),
            ],
            speedScale=1.2,
        )
        before = query.model_dump()
        replacement_state = english_phonemes_to_editor_state(["B", "OW1", "K"])

        updated = replace_english_editor_state(
            query,
            segment_index=1,
            state=replacement_state,
        )

        self.assertEqual(updated.voicegerSegments[1].phonemes, ["B", "OW1", "K"])
        self.assertEqual(updated.voicegerSegments[2].model_dump(), query.voicegerSegments[2].model_dump())
        self.assertEqual(updated.voicegerSegments[0].model_dump(), query.voicegerSegments[0].model_dump())
        self.assertEqual(updated.accent_phrases, query.accent_phrases)
        self.assertEqual(updated.speedScale, query.speedScale)
        self.assertEqual(query.model_dump(), before)

    def test_english_base_phoneme_replacement_preserves_stress_and_defaults_new_vowels(self):
        query = _mixed_query(
            ["ア'メ"],
            [
                VoicegerSegment(language="ja", text="雨", accentPhraseStart=0, accentPhraseCount=1),
                VoicegerSegment(language="en", text="hello", phonemes=["AH1", "EH2"]),
            ],
        )

        updated = replace_english_base_phonemes(
            query,
            segment_index=1,
            base_phonemes=["b", "ow", "iy"],
        )

        self.assertEqual(
            updated.voicegerSegments[1].phonemes,
            ["B", "OW1", "IY2"],
        )
        self.assertEqual(query.voicegerSegments[1].phonemes, ["AH1", "EH2"])

        expanded = replace_english_base_phonemes(
            updated,
            segment_index=1,
            base_phonemes=["OW", "IY", "AA", "EH"],
        )
        self.assertEqual(
            expanded.voicegerSegments[1].phonemes,
            ["OW1", "IY2", "AA0", "EH0"],
        )

        shortened = replace_english_base_phonemes(
            expanded,
            segment_index=1,
            base_phonemes=["EH", "AA"],
        )
        self.assertEqual(shortened.voicegerSegments[1].phonemes, ["EH1", "AA2"])

    def test_english_base_phoneme_replacement_rejects_stress_suffixed_input(self):
        query = _mixed_query(
            ["ア'メ"],
            [
                VoicegerSegment(language="ja", text="雨", accentPhraseStart=0, accentPhraseCount=1),
                VoicegerSegment(language="en", text="hello", phonemes=["AH1"]),
            ],
        )
        original_fields = query.model_dump()

        with self.assertRaisesRegex(ValueError, "stress digits"):
            replace_english_base_phonemes(
                query,
                segment_index=1,
                base_phonemes=["AH0"],
            )
        self.assertEqual(query.model_dump(), original_fields)

    def test_moving_primary_stress_preserves_other_markers_and_secondary_stress(self):
        query = _mixed_query(
            ["ア'メ"],
            [
                VoicegerSegment(language="ja", text="雨", accentPhraseStart=0, accentPhraseCount=1),
                VoicegerSegment(
                    language="en",
                    text="word",
                    phonemes=["AH1", "EH0", "OW2", "IY1"],
                ),
                VoicegerSegment(language="en", text="other", phonemes=["B", "AH0"]),
            ],
        )
        original_fields = query.model_dump()

        updated = move_english_primary_stress(
            query,
            segment_index=1,
            source_vowel_position=0,
            target_vowel_position=1,
        )

        self.assertEqual(
            updated.voicegerSegments[1].phonemes,
            ["AH0", "EH1", "OW2", "IY1"],
        )
        self.assertEqual(
            updated.voicegerSegments[2].phonemes,
            query.voicegerSegments[2].phonemes,
        )
        self.assertEqual(query.model_dump(), original_fields)

    def test_wrong_language_missing_phonemes_and_invalid_indices_fail_unchanged(self):
        wrong_language = _mixed_query(
            ["ア'メ"],
            [VoicegerSegment(language="ja", text="雨", accentPhraseStart=0, accentPhraseCount=1)],
        )
        missing_phonemes = _mixed_query(
            ["ア'メ"],
            [
                VoicegerSegment(language="ja", text="雨", accentPhraseStart=0, accentPhraseCount=1),
                VoicegerSegment(language="en", text="hello"),
            ],
        )
        for query, segment_index, pattern in (
            (wrong_language, 0, "not English"),
            (missing_phonemes, 1, "no phonemes"),
            (missing_phonemes, 4, "out of range"),
            (missing_phonemes, True, "integer"),
        ):
            with self.subTest(segment_index=segment_index, pattern=pattern):
                original_fields = query.model_dump()
                with self.assertRaisesRegex(ValueError, pattern):
                    english_editor_state(query, segment_index=segment_index)
                self.assertEqual(query.model_dump(), original_fields)

        original_fields = missing_phonemes.model_dump()
        with self.assertRaisesRegex(ValueError, "no phonemes"):
            replace_english_editor_state(
                missing_phonemes,
                segment_index=1,
                state=EnglishPhonemeEditorState(("AH",), (0,)),
            )
        self.assertEqual(missing_phonemes.model_dump(), original_fields)

    def test_invalid_query_type_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "AudioQuery"):
            japanese_pronunciation(object())
        with self.assertRaisesRegex(TypeError, "AudioQuery"):
            english_editor_state(object(), segment_index=0)

    def test_english_editor_requires_mixed_query(self):
        with self.assertRaisesRegex(ValueError, "voicegerSegments"):
            english_editor_state(_pure_query(), segment_index=0)


if __name__ == "__main__":
    unittest.main()
