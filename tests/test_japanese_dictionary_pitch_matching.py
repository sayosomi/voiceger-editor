"""Issue #274: node-aligned multi-peak matching and query transport."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from voiceger_editor.japanese_dictionary_pitch_matching import match_pitch_words
from voiceger_editor.mixed_language import (
    DetectedSegment, build_mixed_audio_query, build_mixed_synthesis_plan,
)
from voiceger_editor.openjtalk_converter import (
    frontend_features_to_pronunciation, text_to_pronunciation,
)
from voiceger_editor.pronunciation import PitchEvent, format_pronunciation
from voiceger_editor.voiceger_tokens import pronunciation_to_voiceger_tokens


EVENTS = (
    PitchEvent(1, "["), PitchEvent(2, "]"),
    PitchEvent(4, "["), PitchEvent(5, "]"),
)


def word(surface="スタックチャン", pronunciation="スタックチャン",
         part_of_speech="名詞"):
    return SimpleNamespace(
        surface=surface, pronunciation=pronunciation,
        mora_count=6, accent_type=2, context_id=1348,
        part_of_speech=part_of_speech,
        part_of_speech_detail_1="固有名詞",
        part_of_speech_detail_2="一般",
    )


def node(surface, reading, *, acc=2, chain=-1):
    morae = {
        "スタック": 4, "チャン": 2, "スタックチャン": 6,
        "ヲ": 1, "ツクッタ": 4, "ノダ": 2,
        "ア": 1, "ト": 1, "メタン": 3, "シコク": 3,
    }
    return {
        "string": surface, "pron": reading, "acc": acc,
        "mora_size": morae[reading], "chain_flag": chain, "pos": "名詞",
    }


def punctuation(value="！"):
    return {
        "string": value, "pron": value, "acc": 0,
        "mora_size": 0, "chain_flag": -1, "pos": "記号",
    }


def split():
    return [
        node("スタック", "スタック"),
        node("チャン", "チャン"),
        node("を", "ヲ", chain=1),
        node("作った", "ツクッタ"),
        node("のだ", "ノダ"),
        punctuation(),
    ]


def snapshot():
    return {"word-1": (word(), EVENTS)}


def fake_phones(mora):
    return {
        "ス": ["s", "u"], "タ": ["t", "a"], "ッ": ["cl"],
        "ク": ["k", "u"], "チャ": ["ch", "a"], "ン": ["N"],
        "ヲ": ["o"],
    }.get(mora, ["a"])


class JapanesePitchMatchingTests(unittest.TestCase):
    def test_priority_five_split_word_merges_only_internal_boundaries(self):
        value = frontend_features_to_pronunciation(split(), pitch_words=snapshot())
        self.assertEqual(format_pronunciation(value),
                         "ス[タ]ック[チャ]ンヲ/ツク'ッタ/ノダ'！")
        self.assertEqual(pronunciation_to_voiceger_tokens(
            value, mora_g2p=fake_phones
        )[:16], [
            "s", "u", "[", "t", "a", "]", "cl", "k", "u",
            "[", "ch", "a", "]", "N", "o", "#",
        ])
        self.assertEqual(value.phrases[0].pitch_events, EVENTS)

    def test_single_node_and_start_middle_end_positions(self):
        cases = [
            [node("スタックチャン", "スタックチャン")],
            [node("ア", "ア", acc=1), node("スタック", "スタック"),
             node("チャン", "チャン")],
            [node("スタック", "スタック"), node("チャン", "チャン"),
             node("ト", "ト", chain=1)],
        ]
        for features in cases:
            with self.subTest(features=features):
                matched = match_pitch_words(features, snapshot())
                self.assertEqual([(match.start, match.end) for match in matched],
                                 [(0, 1)] if len(features) == 1 else
                                 [(1, 3)] if features[0]["string"] == "ア" else
                                 [(0, 2)])
                converted = frontend_features_to_pronunciation(
                    features, pitch_words=snapshot()
                )
                self.assertEqual(sum(bool(p.pitch_events)
                                     for p in converted.phrases), 1)

    def test_repeated_words_and_multiple_words(self):
        features = [
            node("スタック", "スタック"), node("チャン", "チャン"),
            node("ア", "ア"),
            node("スタック", "スタック"), node("チャン", "チャン"),
        ]
        matched = match_pitch_words(features, snapshot())
        self.assertEqual([(m.start, m.end) for m in matched], [(0, 2), (3, 5)])
        converted = frontend_features_to_pronunciation(
            features, pitch_words=snapshot()
        )
        self.assertEqual(len([p for p in converted.phrases if p.pitch_events]), 2)

    def test_nested_matches_choose_longest_and_ambiguity_skips(self):
        smaller = SimpleNamespace(
            surface="スタック", pronunciation="スタック",
            mora_count=4, accent_type=2, context_id=1348,
            part_of_speech="名詞", part_of_speech_detail_1="固有名詞",
            part_of_speech_detail_2="一般",
        )
        words = {**snapshot(), "short": (
            smaller, (PitchEvent(1, "["), PitchEvent(2, "]"),
                      PitchEvent(3, "[")),
        )}
        self.assertEqual(match_pitch_words(split(), words)[0].word_uuid,
                         "word-1")
        words["conflict"] = (word(part_of_speech="接尾辞"), EVENTS)
        with self.assertLogs(
            "voiceger_editor.japanese_dictionary_pitch_matching",
            level="WARNING",
        ):
            self.assertFalse(match_pitch_words(
                [node("スタックチャン", "スタックチャン")], words
            ))
        baseline = frontend_features_to_pronunciation(
            [node("スタックチャン", "スタックチャン")],
            pitch_words=words,
        )
        self.assertIsNone(baseline.phrases[0].pitch_events)

    def test_mismatch_punctuation_and_incomplete_mora_are_safe(self):
        wrong = snapshot()
        wrong["word-1"] = (word(pronunciation="スタックシャン"), EVENTS)
        self.assertFalse(match_pitch_words(split(), wrong))
        broken = [node("スタック", "スタック"),
                  punctuation("、"), node("チャン", "チャン")]
        self.assertFalse(match_pitch_words(broken, snapshot()))
        unsafe = split()
        unsafe[1]["mora_size"] = 100
        self.assertFalse(match_pitch_words(unsafe, snapshot()))
        self.assertEqual(
            format_pronunciation(frontend_features_to_pronunciation(
                broken, pitch_words=snapshot()
            )),
            format_pronunciation(frontend_features_to_pronunciation(broken)),
        )

    def test_unsafe_composed_contour_skips_only_failing_match(self):
        features = [node("ア", "ア", acc=2),
                    node("スタック", "スタック", chain=1),
                    node("チャン", "チャン", chain=1)]
        # The unmatched prefix has a rise, and the dictionary word also
        # begins with a rise. Their consecutive duplicate markers are unsafe.
        with self.assertLogs(
            "voiceger_editor.openjtalk_converter", level="WARNING"
        ):
            resolved = frontend_features_to_pronunciation(
                features, pitch_words=snapshot()
            )
        self.assertEqual(
            format_pronunciation(resolved),
            format_pronunciation(frontend_features_to_pronunciation(features)),
        )

    def test_text_frontend_injection_and_legacy_unchanged(self):
        value = text_to_pronunciation(
            "スタックチャンを作ったのだ！",
            run_frontend=lambda text: split(),
            pitch_words=snapshot(),
        )
        self.assertEqual(value.phrases[0].pitch_events, EVENTS)
        baseline = text_to_pronunciation(
            "スタックチャンを作ったのだ！", run_frontend=lambda text: split(),
        )
        self.assertTrue(all(p.pitch_events is None for p in baseline.phrases))

    def test_pure_and_mixed_query_transport_and_synthesis_plan(self):
        from voiceger_editor.voicevox_query import accent_phrases_to_pronunciation
        from voiceger_editor.voicevox_api_models import AudioQuery

        def analyze(value, **kwargs):
            if "スタックチャン" in value:
                return text_to_pronunciation(
                    value, run_frontend=lambda text: split(),
                    pitch_words=kwargs.get("pitch_words"),
                )
            return text_to_pronunciation(
                value, run_frontend=lambda text: [node("ア", "ア", acc=1)]
            )

        with patch("voiceger_editor.mixed_language.text_to_pronunciation",
                   side_effect=analyze), patch(
            "voiceger_editor.voicevox_query._mora_phones",
            side_effect=lambda _mora, _previous: (None, "a"),
        ):
            pure = build_mixed_audio_query(
                "スタックチャンを作ったのだ！",
                segments=[DetectedSegment("ja", "スタックチャンを作ったのだ！")],
                japanese_pitch_words=snapshot(),
            )
            self.assertEqual(pure.pronunciationPitchEvents[0].accentPhraseIndex, 0)
            self.assertEqual(
                AudioQuery.model_validate(pure.model_dump()).pronunciationPitchEvents,
                pure.pronunciationPitchEvents,
            )
            mixed = build_mixed_audio_query(
                "あスタックチャンを作ったのだ！hello",
                segments=[
                    DetectedSegment("ja", "あ"),
                    DetectedSegment("en", "hello"),
                    DetectedSegment("ja", "スタックチャンを作ったのだ！"),
                ],
                english_g2p=lambda text: ["HH", "AH0", "L", "OW1"],
                japanese_pitch_words=snapshot(),
            )

        self.assertEqual(mixed.voicegerSegments[2].accentPhraseStart, 1)
        self.assertEqual(mixed.pronunciationPitchEvents[0].accentPhraseIndex, 1)
        self.assertIsNone(mixed.voicegerSegments[1].pronunciationPunctuation)
        with patch(
            "voiceger_editor.voiceger_tokens._default_mora_g2p",
            side_effect=fake_phones,
        ):
            plan = build_mixed_synthesis_plan(mixed)
        self.assertEqual(len(plan.japanese_overrides), 2)
        self.assertIn("[", plan.japanese_overrides[1][1])
        recovered = accent_phrases_to_pronunciation(
            pure.accent_phrases,
            pitch_events=pure.pronunciationPitchEvents,
            punctuation=pure.pronunciationPunctuation,
        )
        self.assertEqual(recovered.phrases[0].pitch_events, EVENTS)


if __name__ == "__main__":
    unittest.main()
