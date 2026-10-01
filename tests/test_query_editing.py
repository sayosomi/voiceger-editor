import unittest
from unittest.mock import patch

from voiceger_accent_adapter.english_stress import (
    EnglishPhonemeEditorState,
    english_phonemes_to_editor_state,
)
from voiceger_accent_adapter.pronunciation import parse_pronunciation
from voiceger_accent_adapter.query_editing import (
    english_editor_state,
    english_section_text_preview_query,
    english_word_preview_query,
    append_english_section,
    append_japanese_section,
    delete_utterance_section,
    merge_english_section_text_groups,
    japanese_pronunciation,
    japanese_preview_query,
    move_english_primary_stress,
    move_japanese_accent,
    replace_english_base_phonemes,
    replace_english_editor_state,
    replace_english_section_text,
    replace_english_phoneme_groups,
    replace_japanese_pronunciation,
    replace_japanese_section_text,
    replace_japanese_accent_phrase,
    japanese_section_text_preview_query,
    retain_unchanged_english_word_phonemes,
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
    def test_mixed_japanese_preview_isolates_selected_segment_and_controls(self):
        query = _mixed_query(
            ["キョ'ウ", "サ'ク", "ア'メ"],
            [
                VoicegerSegment(
                    language="ja",
                    text="今日",
                    accentPhraseStart=0,
                    accentPhraseCount=1,
                    pronunciationTerminator="。",
                ),
                VoicegerSegment(
                    language="en",
                    text="hello",
                    phonemes=["HH", "AH1", "L", "OW0"],
                ),
                VoicegerSegment(
                    language="ja",
                    text="咲く雨",
                    accentPhraseStart=1,
                    accentPhraseCount=2,
                    pronunciationTerminator="？",
                ),
            ],
            speedScale=1.3,
            outputSamplingRate=44100,
            volumeScale=0.7,
        )
        original = query.model_dump()

        preview = japanese_preview_query(
            query,
            "オ'ト！",
            segment_index=2,
        )

        self.assertIsNone(preview.voicegerSegments)
        self.assertEqual(len(preview.accent_phrases), 1)
        self.assertEqual(japanese_pronunciation(preview), "オ'ト！")
        self.assertEqual(preview.kana, "オ'ト！")
        self.assertEqual(preview.speedScale, 1.3)
        self.assertEqual(preview.outputSamplingRate, 44100)
        self.assertEqual(preview.volumeScale, 0.7)
        self.assertEqual(query.model_dump(), original)

    def test_pure_japanese_preview_keeps_the_whole_current_utterance(self):
        query = _pure_query("ア'メ/キョ'ウ。", speedScale=1.2)
        original = query.model_dump()

        preview = japanese_preview_query(query, "アメ'/サ'ク？")

        self.assertIsNone(preview.voicegerSegments)
        self.assertEqual(len(preview.accent_phrases), 2)
        self.assertEqual(japanese_pronunciation(preview), "アメ'/サ'ク？")
        self.assertEqual(preview.speedScale, 1.2)
        self.assertEqual(query.model_dump(), original)

    def test_english_word_preview_isolates_segment_and_changes_only_selected_group(self):
        groups = (
            ("HH", "AH1", "L", "OW0"),
            ("S", "W", "IY1", "T"),
            ("W", "ER0", "L", "D"),
        )
        query = _mixed_query(
            ["ア'メ", "サ'ク"],
            [
                VoicegerSegment(
                    language="ja",
                    text="前",
                    accentPhraseStart=0,
                    accentPhraseCount=1,
                ),
                VoicegerSegment(
                    language="en",
                    text="hello sweet world",
                    phonemes=[phoneme for group in groups for phoneme in group],
                ),
                VoicegerSegment(
                    language="ja",
                    text="後",
                    accentPhraseStart=1,
                    accentPhraseCount=1,
                ),
            ],
            speedScale=1.15,
            outputSamplingRate=44100,
            volumeScale=0.65,
        )
        original = query.model_dump()

        preview = english_word_preview_query(
            query,
            segment_index=1,
            group_index=1,
            phoneme_groups=groups,
            draft_phonemes=("S", "W", "EH1", "T"),
        )

        self.assertEqual(preview.accent_phrases, [])
        self.assertIsNone(preview.kana)
        self.assertEqual(len(preview.voicegerSegments), 1)
        segment = preview.voicegerSegments[0]
        self.assertEqual(segment.language, "en")
        self.assertEqual(segment.text, "hello sweet world")
        self.assertEqual(
            segment.phonemes,
            [*groups[0], "S", "W", "EH1", "T", *groups[2]],
        )
        self.assertEqual(preview.speedScale, 1.15)
        self.assertEqual(preview.outputSamplingRate, 44100)
        self.assertEqual(preview.volumeScale, 0.65)
        self.assertEqual(query.model_dump(), original)

    def test_japanese_accent_move_changes_one_mora_and_boundary_is_noop(self):
        query = _pure_query("キョ'ウ/ア'メ。", speedScale=1.25)
        original = query.model_dump()

        moved = move_japanese_accent(
            query, accent_phrase_index=0, direction=1
        )

        self.assertEqual([phrase.accent for phrase in moved.accent_phrases], [2, 1])
        self.assertEqual(japanese_pronunciation(moved), "キョウ'/ア'メ。")
        self.assertEqual(query.model_dump(), original)
        self.assertIs(
            move_japanese_accent(
                moved, accent_phrase_index=0, direction=1
            ),
            moved,
        )
        self.assertEqual(moved.speedScale, 1.25)

    def test_mixed_japanese_accent_move_preserves_other_phrases_and_segments(self):
        query = _mixed_query(
            ["キョ'ウ/ア'メ", "サ'ク"],
            [
                VoicegerSegment(
                    language="ja",
                    text="今日雨",
                    accentPhraseStart=0,
                    accentPhraseCount=2,
                    pronunciationTerminator="？",
                ),
                VoicegerSegment(language="en", text="hello", phonemes=["HH", "AH1"]),
                VoicegerSegment(
                    language="ja",
                    text="咲く",
                    accentPhraseStart=2,
                    accentPhraseCount=1,
                    pronunciationTerminator="。",
                ),
            ],
            speedScale=1.4,
        )
        before = query.model_dump()

        updated = move_japanese_accent(
            query,
            accent_phrase_index=1,
            direction=1,
            segment_index=0,
        )

        self.assertEqual(
            [phrase.accent for phrase in updated.accent_phrases], [1, 2, 1]
        )
        self.assertEqual(len(updated.accent_phrases), len(query.accent_phrases))
        self.assertEqual(updated.voicegerSegments, query.voicegerSegments)
        self.assertEqual(updated.speedScale, query.speedScale)
        self.assertEqual(query.model_dump(), before)
        self.assertEqual(
            updated.voicegerSegments[0].pronunciationTerminator, "？"
        )

    def test_replacing_phrase_reading_keeps_phrase_and_segment_structure(self):
        query = _mixed_query(
            ["キョ'ウ/ア'メ", "サ'ク"],
            [
                VoicegerSegment(
                    language="ja",
                    text="今日雨",
                    accentPhraseStart=0,
                    accentPhraseCount=2,
                    pronunciationTerminator="？",
                ),
                VoicegerSegment(language="en", text="hello", phonemes=["HH", "AH1"]),
                VoicegerSegment(
                    language="ja",
                    text="咲く",
                    accentPhraseStart=2,
                    accentPhraseCount=1,
                ),
            ],
        )
        before = query.model_dump()

        updated = replace_japanese_accent_phrase(
            query,
            accent_phrase_index=0,
            morae=("ミャ", "ク"),
            accent=1,
            segment_index=0,
        )

        self.assertEqual(len(updated.accent_phrases), 3)
        self.assertEqual([mora.text for mora in updated.accent_phrases[0].moras], ["ミャ", "ク"])
        self.assertEqual(updated.accent_phrases[0].accent, 1)
        self.assertEqual(updated.accent_phrases[0].is_interrogative, query.accent_phrases[0].is_interrogative)
        self.assertEqual(updated.voicegerSegments[0].accentPhraseCount, 2)
        self.assertEqual(updated.voicegerSegments[2].accentPhraseStart, 2)
        self.assertEqual(updated.voicegerSegments[0].pronunciationTerminator, "？")
        self.assertEqual(query.model_dump(), before)
        with self.assertRaisesRegex(ValueError, "complete mora"):
            replace_japanese_accent_phrase(
                query,
                accent_phrase_index=0,
                morae=("キ", "ョ", "ウ"),
                accent=1,
                segment_index=0,
            )

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

    def test_pure_punctuation_only_replacement_updates_query_metadata(self):
        query = _pure_query("ア'メ/アメ'。")
        original_accents = [phrase.accent for phrase in query.accent_phrases]
        original_readings = [
            [mora.text for mora in phrase.moras]
            for phrase in query.accent_phrases
        ]

        updated = replace_japanese_pronunciation(
            query,
            "ア'メ、アメ'。",
        )

        self.assertEqual(
            [phrase.accent for phrase in updated.accent_phrases],
            original_accents,
        )
        self.assertEqual(
            [
                [mora.text for mora in phrase.moras]
                for phrase in updated.accent_phrases
            ],
            original_readings,
        )
        self.assertEqual(
            [
                (entry.afterAccentPhrase, entry.mark)
                for entry in updated.pronunciationPunctuation
            ],
            [(0, "、"), (1, "。")],
        )
        self.assertEqual(japanese_pronunciation(updated), "ア'メ、アメ'。")
        self.assertNotEqual(updated.model_dump(), query.model_dump())

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

    def test_mixed_replacement_preserves_internal_punctuation_metadata(self):
        query = _mixed_query(
            ["ア'メ/アメ'"],
            [
                VoicegerSegment(
                    language="ja",
                    text="雨、飴！",
                    accentPhraseStart=0,
                    accentPhraseCount=2,
                ),
                VoicegerSegment(
                    language="en",
                    text="hello",
                    phonemes=["HH", "AH0"],
                ),
            ],
        )

        updated = replace_japanese_pronunciation(
            query,
            "ア'メ、アメ'！",
            segment_index=0,
        )

        punctuation = updated.voicegerSegments[0].pronunciationPunctuation
        self.assertEqual(
            [
                (entry.afterAccentPhrase, entry.mark)
                for entry in punctuation
            ],
            [(0, "、"), (1, "！")],
        )
        self.assertEqual(
            japanese_pronunciation(updated, segment_index=0),
            "ア'メ、アメ'！",
        )
        self.assertEqual(updated.voicegerSegments[0].text, "雨、飴！")
        self.assertEqual(
            updated.voicegerSegments[1].phonemes,
            ["HH", "AH0"],
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
            target_vowel_position=2,
        )

        self.assertEqual(
            updated.voicegerSegments[1].phonemes,
            ["AH2", "EH0", "OW1", "IY1"],
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

    def test_local_japanese_text_replacement_preserves_unrelated_segments_and_reindexes(self):
        query = _mixed_query(
            ["ア'メ", "サ'ク", "キョ'ウ"],
            [
                VoicegerSegment(
                    language="ja", text="前", accentPhraseStart=0,
                    accentPhraseCount=1, pronunciationTerminator="",
                ),
                VoicegerSegment(language="en", text="hello", phonemes=["HH", "AH1"]),
                VoicegerSegment(
                    language="ja", text="選択", accentPhraseStart=1,
                    accentPhraseCount=1, pronunciationTerminator="。",
                ),
                VoicegerSegment(language="en", text="world", phonemes=["W", "ER0"]),
                VoicegerSegment(
                    language="ja", text="後", accentPhraseStart=2,
                    accentPhraseCount=1, pronunciationTerminator="？",
                ),
            ],
            speedScale=1.25,
            outputSamplingRate=44100,
        )
        original = query.model_dump()
        before_phrases = query.accent_phrases[0].model_dump()
        after_phrases = query.accent_phrases[2].model_dump()
        unrelated_segments = [
            query.voicegerSegments[index].model_dump() for index in (0, 1, 3, 4)
        ]

        with patch(
            "voiceger_accent_adapter.query_editing.text_to_pronunciation",
            return_value=parse_pronunciation("ミ'ズ/サ'ク！"),
        ):
            updated = replace_japanese_section_text(
                query,
                "新しい文",
                segment_index=2,
            )

        self.assertEqual(updated.voicegerSegments[2].text, "新しい文")
        self.assertEqual(updated.voicegerSegments[2].accentPhraseStart, 1)
        self.assertEqual(updated.voicegerSegments[2].accentPhraseCount, 2)
        self.assertEqual(updated.voicegerSegments[2].pronunciationTerminator, "！")
        self.assertEqual(updated.voicegerSegments[4].accentPhraseStart, 3)
        self.assertEqual(updated.accent_phrases[0].model_dump(), before_phrases)
        self.assertEqual(updated.accent_phrases[3].model_dump(), after_phrases)
        self.assertEqual(
            [updated.voicegerSegments[index].model_dump() for index in (0, 1, 3, 4)],
            [
                *unrelated_segments[:3],
                {**unrelated_segments[3], "accentPhraseStart": 3},
            ],
        )
        self.assertEqual(updated.speedScale, 1.25)
        self.assertEqual(updated.outputSamplingRate, 44100)
        self.assertEqual(query.model_dump(), original)

    def test_pure_japanese_text_replacement_preserves_query_controls(self):
        query = _pure_query("ア'メ。", speedScale=1.3, outputSamplingRate=44100)
        original = query.model_dump()

        with patch(
            "voiceger_accent_adapter.query_editing.text_to_pronunciation",
            return_value=parse_pronunciation("キョ'ウ！"),
        ):
            updated = replace_japanese_section_text(query, "今日はいい天気")

        self.assertIsNone(updated.voicegerSegments)
        self.assertEqual(japanese_pronunciation(updated), "キョ'ウ！")
        self.assertEqual(updated.kana, "キョ'ウ！")
        self.assertEqual(updated.speedScale, 1.3)
        self.assertEqual(updated.outputSamplingRate, 44100)
        self.assertEqual(query.model_dump(), original)

    def test_japanese_text_preview_isolates_only_the_rebuilt_section(self):
        query = _mixed_query(
            ["ア'メ", "サ'ク", "キョ'ウ"],
            [
                VoicegerSegment(language="ja", text="前", accentPhraseStart=0, accentPhraseCount=1),
                VoicegerSegment(language="en", text="hello", phonemes=["HH", "AH1"]),
                VoicegerSegment(language="ja", text="選択", accentPhraseStart=1, accentPhraseCount=1),
                VoicegerSegment(language="ja", text="後", accentPhraseStart=2, accentPhraseCount=1),
            ],
            speedScale=1.4,
        )
        original = query.model_dump()

        with patch(
            "voiceger_accent_adapter.query_editing.text_to_pronunciation",
            return_value=parse_pronunciation("ミ'ズ/サ'ク？"),
        ):
            preview = japanese_section_text_preview_query(
                query,
                "新しい文",
                segment_index=2,
            )

        self.assertIsNone(preview.voicegerSegments)
        self.assertEqual(len(preview.accent_phrases), 2)
        self.assertEqual(japanese_pronunciation(preview), "ミ'ズ/サ'ク？")
        self.assertEqual(preview.speedScale, 1.4)
        self.assertEqual(query.model_dump(), original)

    def test_english_retention_keeps_manual_phonemes_after_insertions_and_deletions(self):
        old = (
            ("hello", ("HH", "AH2", "L", "OW0")),
            ("sweet", ("S", "W", "IY2", "T")),
            ("world", ("W", "ER1", "L", "D")),
        )
        inserted = retain_unchanged_english_word_phonemes(
            old,
            (
                ("very", ("V", "EH1", "R", "IY0")),
                ("HELLO", ("HH", "AH1", "L", "OW0")),
                ("Sweet", ("S", "W", "IY1", "T")),
                ("world", ("W", "ER0", "L", "D")),
            ),
        )
        self.assertEqual(inserted[0][1], ("V", "EH1", "R", "IY0"))
        self.assertEqual(inserted[1][1], old[0][1])
        self.assertEqual(inserted[2][1], old[1][1])
        self.assertEqual(inserted[3][1], old[2][1])

        deleted = retain_unchanged_english_word_phonemes(
            (
                ("remove", ("R", "IY1", "M", "UW0", "V")),
                ("sweet", old[1][1]),
                ("world", old[2][1]),
                ("later", ("L", "EY1", "T", "ER0")),
            ),
            (
                ("sweet", ("S", "W", "IY1", "T")),
                ("world", ("W", "ER0", "L", "D")),
            ),
        )
        self.assertEqual(deleted, (old[1], old[2]))

    def test_english_replacement_uses_new_g2p_for_replace_opcode_groups(self):
        merged = retain_unchanged_english_word_phonemes(
            (("color", ("K", "AH2", "L", "ER0")),),
            (("colour", ("K", "AH1", "L", "ER0")),),
        )
        self.assertEqual(merged, (("colour", ("K", "AH1", "L", "ER0")),))

    def test_english_repeated_word_retention_follows_sequence_matcher_order(self):
        old = (
            ("go", ("G", "OW1")),
            ("go", ("G", "OW2")),
        )
        merged = retain_unchanged_english_word_phonemes(
            old,
            (
                ("go", ("G", "OW0")),
                ("GO", ("G", "OW0")),
                ("go", ("G", "OW0")),
            ),
        )
        self.assertEqual(
            merged,
            (
                old[0],
                ("GO", old[1][1]),
                ("go", ("G", "OW0")),
            ),
        )

    def test_english_text_preview_isolated_and_uses_retained_groups_without_mutation(self):
        old_groups = (
            ("hello", ("HH", "AH2", "L", "OW0")),
            ("sweet", ("S", "W", "IY2", "T")),
        )
        query = _mixed_query(
            ["ア'メ", "サ'ク"],
            [
                VoicegerSegment(language="ja", text="前", accentPhraseStart=0, accentPhraseCount=1),
                VoicegerSegment(
                    language="en", text="hello sweet",
                    phonemes=[phone for _label, group in old_groups for phone in group],
                ),
                VoicegerSegment(language="ja", text="後", accentPhraseStart=1, accentPhraseCount=1),
            ],
            speedScale=1.2,
        )
        original = query.model_dump()
        new_groups = (
            ("very", ("V", "EH1", "R", "IY0")),
            ("hello", ("HH", "AH1", "L", "OW0")),
            ("sweet", ("S", "W", "IY1", "T")),
        )

        preview = english_section_text_preview_query(
            query,
            segment_index=1,
            text="very hello sweet",
            old_groups=old_groups,
            new_groups=new_groups,
        )

        self.assertEqual(preview.accent_phrases, [])
        self.assertIsNone(preview.kana)
        self.assertEqual(len(preview.voicegerSegments), 1)
        self.assertEqual(preview.voicegerSegments[0].text, "very hello sweet")
        self.assertEqual(
            preview.voicegerSegments[0].phonemes,
            [*new_groups[0][1], *old_groups[0][1], *old_groups[1][1]],
        )
        self.assertEqual(preview.speedScale, 1.2)
        self.assertEqual(query.model_dump(), original)

    def test_append_from_pure_japanese_preserves_existing_manual_phrases(self):
        query = _pure_query("アメ'/キョ'ウ？", speedScale=1.35)
        original_phrases = [phrase.model_dump() for phrase in query.accent_phrases]

        updated = append_english_section(
            query,
            "hello",
            phoneme_groups=(("hello", ("HH", "AH1", "L", "OW0")),),
            pure_japanese_utterance_text="今日はいい天気？",
        )

        self.assertEqual(len(updated.voicegerSegments), 2)
        self.assertEqual(updated.voicegerSegments[0].text, "今日はいい天気？")
        self.assertEqual(updated.voicegerSegments[0].accentPhraseStart, 0)
        self.assertEqual(updated.voicegerSegments[0].accentPhraseCount, 2)
        self.assertEqual(updated.voicegerSegments[0].pronunciationTerminator, "？")
        self.assertEqual(updated.accent_phrases[0].model_dump(), original_phrases[0])
        self.assertEqual(updated.accent_phrases[1].model_dump(), original_phrases[1])
        self.assertIsNone(updated.kana)
        self.assertEqual(updated.speedScale, 1.35)
        self.assertEqual(query.voicegerSegments, None)

    def test_delete_reindexes_japanese_and_normalizes_lone_japanese_section(self):
        query = _mixed_query(
            ["ア'メ", "サ'ク", "キョ'ウ"],
            [
                VoicegerSegment(
                    language="ja", text="前", accentPhraseStart=0,
                    accentPhraseCount=1, pronunciationTerminator="",
                ),
                VoicegerSegment(language="en", text="hello", phonemes=["HH", "AH1"]),
                VoicegerSegment(
                    language="ja", text="後", accentPhraseStart=1,
                    accentPhraseCount=2, pronunciationTerminator="？",
                ),
            ],
            speedScale=1.1,
        )
        original = query.model_dump()
        surviving_phrases = [phrase.model_dump() for phrase in query.accent_phrases[1:]]

        after_english, pure_text = delete_utterance_section(query, segment_index=1)
        self.assertIsNone(pure_text)
        self.assertEqual(after_english.voicegerSegments[1].accentPhraseStart, 1)
        self.assertEqual(after_english.voicegerSegments[1].accentPhraseCount, 2)

        pure, pure_text = delete_utterance_section(after_english, segment_index=0)

        self.assertIsNone(pure.voicegerSegments)
        self.assertEqual(pure_text, "後")
        self.assertEqual([phrase.model_dump() for phrase in pure.accent_phrases], surviving_phrases)
        self.assertEqual(pure.kana, "サ'ク/キョ'ウ？")
        self.assertEqual(pure.speedScale, 1.1)
        self.assertEqual(query.model_dump(), original)

    def test_deleting_the_only_explicit_section_is_rejected(self):
        query = _mixed_query(
            ["ア'メ"],
            [VoicegerSegment(language="ja", text="雨", accentPhraseStart=0, accentPhraseCount=1)],
        )
        with self.assertRaisesRegex(ValueError, "only utterance section"):
            delete_utterance_section(query, segment_index=0)


if __name__ == "__main__":
    unittest.main()
