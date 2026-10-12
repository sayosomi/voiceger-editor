"""Core multi-peak Japanese prosody and adapter transport regressions."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from voiceger_editor.mixed_language import build_mixed_synthesis_plan
from voiceger_editor.pronunciation import (
    AccentPhrase,
    PitchEvent,
    PronunciationSyntaxError,
    format_pronunciation,
    parse_pronunciation,
)
from voiceger_editor.query_editing import (
    japanese_pronunciation,
    japanese_preview_query,
    delete_utterance_section,
    move_japanese_accent,
    replace_japanese_pronunciation,
    replace_japanese_section_text,
)
from voiceger_editor.voiceger_tokens import pronunciation_to_voiceger_tokens
from voiceger_editor.voicevox_api_models import (
    AudioQuery, JapanesePitchEvent, PronunciationPitchEvents, VoicegerSegment,
)
from voiceger_editor.voicevox_query import (
    accent_phrases_to_pronunciation, build_audio_query, pronunciation_punctuation,
)

LEGACY = "スタ'ックチャンヲ/ツク'ッタ/ノダ'！"
MULTI = "ス[タ]ック[チャ]ンヲ/ツク'ッタ/ノダ'！"
SOUND = {
    "ス": ["s", "u"], "タ": ["t", "a"], "ッ": ["cl"], "ク": ["k", "u"],
    "チャ": ["ch", "a"], "ン": ["N"], "ヲ": ["o"], "ツ": ["ts", "u"],
    "ノ": ["n", "o"], "ダ": ["d", "a"], "ア": ["a"], "メ": ["m", "e"],
    "キョ": ["ky", "o"], "ワ": ["w", "a"], "ト": ["t", "o"],
    "シ": ["sh", "i"], "コ": ["k", "o"],
    "ホ": ["h", "o"], "カ": ["k", "a"], "リ": ["r", "i"],
}
LEGACY_TOKENS = [
    "s", "u", "[", "t", "a", "]", "cl", "k", "u", "ch", "a",
    "N", "o", "#", "ts", "u", "[", "k", "u", "]", "cl", "t", "a",
    "#", "n", "o", "[", "d", "a", "!",
]
MULTI_TOKENS = [
    "s", "u", "[", "t", "a", "]", "cl", "k", "u", "[", "ch",
    "a", "]", "N", "o", "#", "ts", "u", "[", "k", "u", "]",
    "cl", "t", "a", "#", "n", "o", "[", "d", "a", "!",
]


def fake_g2p(mora):
    return SOUND[mora]


class MultiPeakTests(unittest.TestCase):
    def test_exact_old_stream_is_unchanged_and_second_peak_has_no_hash(self):
        self.assertEqual(
            pronunciation_to_voiceger_tokens(
                parse_pronunciation(LEGACY), mora_g2p=fake_g2p
            ), LEGACY_TOKENS,
        )
        parsed = parse_pronunciation(MULTI)
        self.assertEqual(parsed.phrases[0].morae,
                         ("ス", "タ", "ッ", "ク", "チャ", "ン", "ヲ"))
        self.assertEqual(parsed.phrases[0].accent, 2)
        self.assertEqual(
            tuple((event.after_mora, event.symbol)
                  for event in parsed.phrases[0].pitch_events),
            ((1, "["), (2, "]"), (4, "["), (5, "]")),
        )
        self.assertEqual(
            pronunciation_to_voiceger_tokens(parsed, mora_g2p=fake_g2p),
            MULTI_TOKENS,
        )
        self.assertEqual(format_pronunciation(parsed), MULTI)

    def test_initial_high_and_final_close_are_visual_boundaries_only(self):
        legacy = parse_pronunciation("シ]コク[メ]タン")
        bracketed = parse_pronunciation("[シ]コク[メ]タン")
        self.assertEqual(legacy.phrases[0], bracketed.phrases[0])
        self.assertEqual(
            bracketed.phrases[0].pitch_events,
            (PitchEvent(1, "]"), PitchEvent(3, "["), PitchEvent(4, "]")),
        )
        self.assertEqual(format_pronunciation(legacy), "[シ]コク[メ]タン")
        with patch.dict(sys.modules, {"pyopenjtalk": SimpleNamespace(
            g2p=lambda mora, *, kana, join: fake_g2p(mora)
        )}):
            a = build_audio_query(pronunciation=legacy)
            b = build_audio_query(pronunciation=bracketed)
            self.assertEqual(a.model_dump(mode="json"), b.model_dump(mode="json"))

    def test_final_close_does_not_emit_a_fall_or_change_dictionary_accent(self):
        source = "[シ]コク[メタン]"
        phrase = parse_pronunciation(source).phrases[0]
        self.assertEqual(phrase.accent, 1)
        self.assertEqual(
            phrase.pitch_events,
            (PitchEvent(1, "]"), PitchEvent(3, "[")),
        )
        self.assertEqual(format_pronunciation(parse_pronunciation(source)), source)
        tokens = pronunciation_to_voiceger_tokens(
            parse_pronunciation(source), mora_g2p=fake_g2p,
        )
        self.assertEqual(tokens.count("]"), 1)
        self.assertEqual(tokens.count("["), 1)
        self.assertEqual(tokens[-1], "N")
        with patch.dict(sys.modules, {"pyopenjtalk": SimpleNamespace(
            g2p=lambda mora, *, kana, join: fake_g2p(mora)
        )}):
            query = build_audio_query(pronunciation=parse_pronunciation(source))
            rebuilt = accent_phrases_to_pronunciation(
                query.accent_phrases,
                pitch_events=query.pronunciationPitchEvents,
            )
        self.assertEqual(format_pronunciation(rebuilt), source)

    def test_reject_inconsistent_boundary_brackets(self):
        invalid = (
            "[ス[タ]ック[チャ]ン",  # initially high, but first event rises
            "シ]コク[メ]タン]",  # already low at the final boundary
            "[シ]コク[メ]タン]",  # redundant closing bracket
            "[シ]コク[メタン']",  # legacy and explicit markers mixed
        )
        for text in invalid:
            with self.subTest(text=text):
                with self.assertRaises(PronunciationSyntaxError):
                    parse_pronunciation(text)

    def test_multiple_real_boundaries_and_punctuation_remain_distinct(self):
        text = "ア[メ]ア[メ]ア、ツク'ッタ/ノダ'！"
        self.assertEqual(format_pronunciation(parse_pronunciation(text)), text)
        self.assertEqual(
            pronunciation_to_voiceger_tokens(
                parse_pronunciation(text), mora_g2p=fake_g2p
            ).count("#"),
            1,
        )

    def test_heiban_atamadaka_and_nakadaka_legacy_are_unchanged(self):
        for text in ("ア'メ", "アメ'", "ツク'ッタ"):
            with self.subTest(text=text):
                self.assertEqual(format_pronunciation(parse_pronunciation(text)), text)
                self.assertIsNone(parse_pronunciation(text).phrases[0].pitch_events)

    def test_small_kana_sokuon_and_long_vowels_preserve_mora_alignment(self):
        text = "キョ[ー]ト[ワ]アメ"
        parsed = parse_pronunciation(text)
        self.assertEqual(parsed.phrases[0].morae,
                         ("キョ", "ー", "ト", "ワ", "ア", "メ"))
        self.assertEqual(format_pronunciation(parsed), text)
        self.assertEqual(
            pronunciation_to_voiceger_tokens(parsed, mora_g2p=fake_g2p),
            ["ky", "o", "[", "o", "]", "t", "o", "[",
             "w", "a", "]", "a", "m", "e"],
        )
        self.assertEqual(parse_pronunciation("ア]メ[ア]メ").phrases[0].accent, 1)

    def test_reject_malformed_event_sequences(self):
        for text in (
            "ス[タ]", "ス[タ]ク'", "ス'タ[ク]ア", "ス[[タ]ク[ア]",
            "ス[タ]]ク[ア]", "スタ[ク]ア[メ]", "ス[タ[ク]ア",
            "ス[タ]キ[ョ]ア", "ス[タ]ク[ア]", "ス[タ]ク[ア]メ[",
            "ス[タ]ク[ア]/", "ス[タ]ク[ア]メ]",
        ):
            with self.subTest(text=text), self.assertRaises(PronunciationSyntaxError):
                parse_pronunciation(text)

    def test_core_rejects_misaligned_events_and_legacy_accent(self):
        for events, accent in (
            ((PitchEvent(1, "["), PitchEvent(2, "]"),
              PitchEvent(2, "[")), 2),
            ((PitchEvent(1, "["), PitchEvent(2, "["),
              PitchEvent(3, "]")), 3),
            ((PitchEvent(2, "["), PitchEvent(3, "]"),
              PitchEvent(4, "[")), 3),
            ((PitchEvent(1, "["), PitchEvent(2, "]"),
              PitchEvent(3, "[")), 1),
            ((PitchEvent(1, "["), PitchEvent(2, "]"),
              PitchEvent(4, "[")), 2),
        ):
            with self.subTest(events=events, accent=accent):
                with self.assertRaises(ValueError):
                    AccentPhrase(("ス", "タ", "ク", "ア"), accent, events)

    def test_query_json_roundtrip_and_legacy_compatibility(self):
        with patch.dict(sys.modules, {"pyopenjtalk": SimpleNamespace(
            g2p=lambda mora, *, kana, join: fake_g2p(mora)
        )}):
            query = build_audio_query(pronunciation=parse_pronunciation(MULTI))
            dump = query.model_dump(mode="json")
            self.assertEqual(dump["kana"], LEGACY)
            self.assertEqual(dump["accent_phrases"][0]["accent"], 2)
            self.assertNotIn("voicegerPitchEvents", dump["accent_phrases"][0])
            self.assertEqual(dump["pronunciationPitchEvents"][0], {
                "accentPhraseIndex": 0,
                "events": [
                    {"afterMora": 1, "symbol": "["},
                    {"afterMora": 2, "symbol": "]"},
                    {"afterMora": 4, "symbol": "["},
                    {"afterMora": 5, "symbol": "]"},
                ],
            })
            rebuilt = AudioQuery.model_validate(dump)
            self.assertEqual(format_pronunciation(accent_phrases_to_pronunciation(
                rebuilt.accent_phrases,
                punctuation=rebuilt.pronunciationPunctuation,
                pitch_events=rebuilt.pronunciationPitchEvents,
            )), MULTI)
            self.assertEqual(japanese_pronunciation(rebuilt), MULTI)
            preview = japanese_preview_query(rebuilt, MULTI)
            self.assertEqual(japanese_pronunciation(preview), MULTI)
            legacy = build_audio_query(pronunciation=parse_pronunciation(LEGACY))
            legacy_dump = legacy.model_dump(mode="json")
            self.assertNotIn("pronunciationPitchEvents", legacy_dump)
            self.assertIsNone(AudioQuery.model_validate(legacy_dump).pronunciationPitchEvents)

    def test_invalid_query_metadata_fails_instead_of_dropping_tokens(self):
        with patch.dict(sys.modules, {"pyopenjtalk": SimpleNamespace(
            g2p=lambda mora, *, kana, join: fake_g2p(mora)
        )}):
            query = build_audio_query(pronunciation=parse_pronunciation(LEGACY))
        for records in (
            [PronunciationPitchEvents(accentPhraseIndex=90, events=[
                JapanesePitchEvent(afterMora=1, symbol="["),
                JapanesePitchEvent(afterMora=2, symbol="]"),
                JapanesePitchEvent(afterMora=3, symbol="["),
            ])],
            [PronunciationPitchEvents(accentPhraseIndex=0, events=[
                JapanesePitchEvent(afterMora=1, symbol="["),
                JapanesePitchEvent(afterMora=3, symbol="]"),
                JapanesePitchEvent(afterMora=4, symbol="["),
            ])],
        ):
            with self.subTest(records=records), self.assertRaises(ValueError):
                accent_phrases_to_pronunciation(
                    query.accent_phrases, pitch_events=records
                )

    def test_misaligned_query_mora_is_rejected(self):
        with patch.dict(sys.modules, {"pyopenjtalk": SimpleNamespace(
            g2p=lambda mora, *, kana, join: fake_g2p(mora)
        )}):
            query = build_audio_query(pronunciation=parse_pronunciation(MULTI))
        broken = query.model_copy(deep=True)
        broken.accent_phrases[0].moras[4].text = "チ"
        broken.accent_phrases[0].moras.insert(
            5, broken.accent_phrases[0].moras[4].model_copy(
                update={"text": "ャ"}
            )
        )
        with self.assertRaises(ValueError):
            accent_phrases_to_pronunciation(
                broken.accent_phrases,
                pitch_events=broken.pronunciationPitchEvents,
            )

    def test_accent_phrases_endpoint_rejects_lossy_extended_notation(self):
        from fastapi import HTTPException
        from voiceger_editor.api import accent_phrases

        with patch("voiceger_editor.api._resolve_style"):
            with self.assertRaises(HTTPException) as context:
                accent_phrases(text=MULTI, speaker=3, is_kana=True)
        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("cannot return", context.exception.detail)

    def test_mixed_query_preserves_global_indices_and_english(self):
        with patch.dict(sys.modules, {"pyopenjtalk": SimpleNamespace(
            g2p=lambda mora, *, kana, join: fake_g2p(mora)
        )}):
            query = build_audio_query(
                pronunciation=parse_pronunciation("ア'メ/ス[タ]ック[チャ]ンヲ/ノダ'！")
            )
            query.voicegerSegments = [
                VoicegerSegment(language="ja", text="アメ",
                    accentPhraseStart=0, accentPhraseCount=1,
                    pronunciationTerminator="", pronunciationPunctuation=[]),
                VoicegerSegment(language="en", text="OpenAI"),
                VoicegerSegment(language="ja", text="スタックチャンヲノダ！",
                    accentPhraseStart=1, accentPhraseCount=2,
                    pronunciationTerminator="！",
                    pronunciationPunctuation=pronunciation_punctuation(
                        parse_pronunciation("ス[タ]ック[チャ]ンヲ/ノダ'！")
                    )),
            ]
            query.kana = None
            self.assertEqual(
                build_mixed_synthesis_plan(query).japanese_overrides[1][1],
                pronunciation_to_voiceger_tokens(
                    parse_pronunciation("ス[タ]ック[チャ]ンヲ/ノダ'！"),
                    mora_g2p=fake_g2p,
                ),
            )
            self.assertEqual(
                japanese_pronunciation(query, segment_index=2),
                "ス[タ]ック[チャ]ンヲ/ノダ'！",
            )
            preview = japanese_preview_query(
                query, "ス[タ]ック[チャ]ンヲ/ノダ'！", segment_index=2
            )
            self.assertEqual(japanese_pronunciation(preview),
                             "ス[タ]ック[チャ]ンヲ/ノダ'！")
            self.assertEqual(preview.pronunciationPitchEvents[0].accentPhraseIndex, 0)
            edited = replace_japanese_pronunciation(
                query, "ス[タ]ック[チャ]ンヲ", segment_index=0
            )
            self.assertEqual(edited.voicegerSegments[2].accentPhraseStart, 1)
            self.assertEqual(
                [e.accentPhraseIndex for e in edited.pronunciationPitchEvents],
                [0, 1],
            )
            with self.assertRaises(ValueError):
                move_japanese_accent(
                    edited, accent_phrase_index=0, direction=1, segment_index=0
                )
            after_delete, pure_text = delete_utterance_section(
                query, segment_index=0
            )
            self.assertIsNone(pure_text)
            self.assertEqual(after_delete.voicegerSegments[1].accentPhraseStart, 0)
            self.assertEqual(
                after_delete.pronunciationPitchEvents[0].accentPhraseIndex, 0
            )
            self.assertEqual(
                japanese_pronunciation(after_delete, segment_index=1),
                "ス[タ]ック[チャ]ンヲ/ノダ'！",
            )
            broken = query.model_copy(deep=True)
            broken.pronunciationPitchEvents.append(
                broken.pronunciationPitchEvents[0].model_copy(
                    update={"accentPhraseIndex": 100}
                )
            )
            with self.assertRaises(ValueError):
                build_mixed_synthesis_plan(broken)


if __name__ == "__main__":
    unittest.main()
