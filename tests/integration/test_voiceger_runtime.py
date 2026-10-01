import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from voiceger_accent_adapter.compatibility import SUPPORTED_VOICEGER_REVISION
from voiceger_accent_adapter.mixed_language import (
    DetectedSegment,
    build_mixed_audio_query,
)
from voiceger_accent_adapter.pronunciation import parse_pronunciation
from voiceger_accent_adapter.query_editing import (
    append_english_section,
    delete_utterance_section,
    english_word_preview_query,
    merge_english_section_text_groups,
    japanese_preview_query,
    japanese_pronunciation,
    replace_english_section_text,
    replace_japanese_section_text,
)
from voiceger_accent_adapter.styles import get_style
from voiceger_accent_adapter.session import UtteranceSession
from voiceger_accent_adapter.settings import Settings
from voiceger_accent_adapter.synthesis import synthesize_audio_query
from voiceger_accent_adapter.voiceger_adapter import VoicegerAdapter
from voiceger_accent_adapter.user_dictionary import UserDictionaryCore
from voiceger_accent_adapter.openjtalk_converter import text_to_pronunciation
from voiceger_accent_adapter.runtime_locks import OPENJTALK_LOCK
from voiceger_accent_adapter.voicevox_query import build_audio_query


RUN_INTEGRATION = os.environ.get("VOICEGER_RUN_INTEGRATION") == "1"


@unittest.skipUnless(
    RUN_INTEGRATION,
    "set VOICEGER_RUN_INTEGRATION=1 to run real Voiceger integration tests",
)
class VoicegerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.voiceger_root = Path(
            os.environ.get("VOICEGER_ROOT", str(Path.home() / "voiceger_v2"))
        ).expanduser().resolve()
        cls.adapter = VoicegerAdapter(voiceger_root=cls.voiceger_root)
        cls.style = get_style(cls.voiceger_root, 1)

    def assert_full_synthesis_succeeds(self, query):
        result = synthesize_audio_query(
            adapter=self.adapter,
            query=query,
            style=self.style,
        )
        self.assertEqual(result["sampling_rate"], 32000)
        duration = len(result["audio"]) / result["sampling_rate"]
        self.assertGreater(duration, 0.1)
        self.assertLess(duration, 20.0)
        return result

    def test_recorded_voiceger_revision(self):
        revision = subprocess.check_output(
            [
                "git",
                "-C",
                str(self.voiceger_root),
                "rev-parse",
                "HEAD",
            ],
            text=True,
        ).strip()

        self.assertEqual(revision, SUPPORTED_VOICEGER_REVISION)

    def test_english_word_groups_flatten_to_voiceger_public_g2p(self):
        text = "Hi There! I'm Zundamon now noda!"

        groups = self.adapter.english_word_phoneme_groups(text)

        self.assertEqual(
            [phoneme for _label, group in groups for phoneme in group],
            self.adapter.english_phonemes(text),
        )

    def test_manual_japanese_accent_synthesizes_without_runaway(self):
        query = build_audio_query(
            pronunciation=parse_pronunciation("キョ'ーワ/アメデスネ'。"),
        )
        result = synthesize_audio_query(
            adapter=self.adapter,
            query=query,
            style=self.style,
        )

        self.assertEqual(result["sampling_rate"], 32000)
        duration = len(result["audio"]) / result["sampling_rate"]
        self.assertGreater(duration, 0.5)
        self.assertLess(duration, 10.0)
        self.assertEqual(
            result["resolved_pronunciation"],
            "キョ'ーワ/アメデスネ'。",
        )

    def test_manual_japanese_exclamation_synthesizes_without_runaway(self):
        query = build_audio_query(
            pronunciation=parse_pronunciation("キョ'ーワ/アメデスネ'！"),
        )
        result = synthesize_audio_query(
            adapter=self.adapter,
            query=query,
            style=self.style,
        )

        self.assertEqual(result["sampling_rate"], 32000)
        duration = len(result["audio"]) / result["sampling_rate"]
        self.assertGreater(duration, 0.5)
        self.assertLess(duration, 10.0)
        self.assertEqual(
            result["resolved_pronunciation"],
            "キョ'ーワ/アメデスネ'！",
        )

    def test_japanese_english_mixed_synthesizes_without_runaway(self):
        query = build_mixed_audio_query(
            "今日はhelloと言うよ。",
            english_g2p=self.adapter.english_phonemes,
        )
        self.assertIsNotNone(query.voicegerSegments)

        english_segment = next(
            segment
            for segment in query.voicegerSegments
            if segment.language == "en"
        )
        self.assertTrue(english_segment.phonemes)

        for index, token in enumerate(english_segment.phonemes):
            if token[-1:] in {"0", "1", "2"}:
                english_segment.phonemes[index] = (
                    token[:-1] + ("2" if token[-1] != "2" else "1")
                )
                break
        else:
            self.fail("English G2P returned no stress-bearing vowel")

        result = synthesize_audio_query(
            adapter=self.adapter,
            query=query,
            style=self.style,
            capture_mixed_lab_provenance=True,
        )

        self.assertEqual(result["sampling_rate"], 32000)
        duration = len(result["audio"]) / result["sampling_rate"]
        self.assertGreater(duration, 0.5)
        self.assertLess(duration, 15.0)
        self.assertIsNotNone(
            result.get("mixed_lab_provenance"),
            result.get("mixed_lab_provenance_warning"),
        )
        self.assertIsNone(result.get("mixed_lab_provenance_warning"))

    def test_selected_japanese_segment_preview_synthesizes_without_runaway(self):
        query = build_mixed_audio_query(
            "今日はhello sweet worldなのだ。",
            english_g2p=self.adapter.english_phonemes,
        )
        japanese_index = next(
            index
            for index, segment in enumerate(query.voicegerSegments or [])
            if segment.language == "ja"
        )
        preview_query = japanese_preview_query(
            query,
            japanese_pronunciation(query, segment_index=japanese_index),
            segment_index=japanese_index,
        )

        self.assertIsNone(preview_query.voicegerSegments)
        result = synthesize_audio_query(
            adapter=self.adapter,
            query=preview_query,
            style=self.style,
        )

        self.assertEqual(result["sampling_rate"], 32000)
        duration = len(result["audio"]) / result["sampling_rate"]
        self.assertGreater(duration, 0.1)
        self.assertLess(duration, 10.0)

    def test_english_containing_segment_preview_synthesizes_without_runaway(self):
        query = build_mixed_audio_query(
            "今日はhello sweet worldなのだ。",
            english_g2p=self.adapter.english_phonemes,
        )
        english_index = next(
            index
            for index, segment in enumerate(query.voicegerSegments or [])
            if segment.language == "en"
        )
        segment = query.voicegerSegments[english_index]
        raw_groups = self.adapter.english_word_phoneme_groups(segment.text)
        groups = tuple(tuple(phonemes) for _word, phonemes in raw_groups)
        group_index = next(
            index
            for index, (word, _phonemes) in enumerate(raw_groups)
            if word.lower() == "sweet"
        )
        draft = tuple(raw_groups[group_index][1])
        for token_index, token in enumerate(draft):
            if token[-1:] in {"0", "1", "2"}:
                replacement = "0" if token[-1] != "0" else "1"
                draft = (
                    *draft[:token_index],
                    token[:-1] + replacement,
                    *draft[token_index + 1 :],
                )
                break

        preview_query = english_word_preview_query(
            query,
            segment_index=english_index,
            group_index=group_index,
            phoneme_groups=groups,
            draft_phonemes=draft,
        )

        self.assertEqual(len(preview_query.voicegerSegments), 1)
        self.assertEqual(preview_query.voicegerSegments[0].text, segment.text)
        result = synthesize_audio_query(
            adapter=self.adapter,
            query=preview_query,
            style=self.style,
        )

        self.assertEqual(result["sampling_rate"], 32000)
        duration = len(result["audio"]) / result["sampling_rate"]
        self.assertGreater(duration, 0.1)
        self.assertLess(duration, 15.0)

    def test_local_japanese_section_text_replacement_synthesizes_full_utterance(self):
        query = build_mixed_audio_query(
            "今日はhello sweet worldなのだ。",
            english_g2p=self.adapter.english_phonemes,
        )
        japanese_index = next(
            index
            for index, segment in enumerate(query.voicegerSegments or [])
            if segment.language == "ja"
        )

        updated = replace_japanese_section_text(
            query,
            "明日はいい天気。",
            segment_index=japanese_index,
        )

        self.assertEqual(
            updated.voicegerSegments[japanese_index].text,
            "明日はいい天気。",
        )
        self.assert_full_synthesis_succeeds(updated)

    def test_local_english_section_text_retains_manual_words_and_synthesizes(self):
        query = build_mixed_audio_query(
            "今日はhello sweet worldなのだ。",
            english_g2p=self.adapter.english_phonemes,
        )
        english_index = next(
            index
            for index, segment in enumerate(query.voicegerSegments or [])
            if segment.language == "en"
        )
        segment = query.voicegerSegments[english_index]
        old_groups = list(self.adapter.english_word_phoneme_groups(segment.text))
        sweet_index = next(
            index
            for index, (label, _phones) in enumerate(old_groups)
            if label.casefold() == "sweet"
        )
        sweet_phones = list(old_groups[sweet_index][1])
        for phone_index, phone in enumerate(sweet_phones):
            if phone[-1:] in {"0", "1", "2"}:
                sweet_phones[phone_index] = phone[:-1] + (
                    "2" if phone[-1] != "2" else "1"
                )
                break
        else:
            self.fail("Voiceger G2P returned no stressed vowel for sweet")
        old_groups[sweet_index] = (old_groups[sweet_index][0], tuple(sweet_phones))
        old_snapshot = tuple((label, tuple(phones)) for label, phones in old_groups)
        segment.phonemes = [
            phone for _label, group in old_snapshot for phone in group
        ]
        new_text = "very hello sweet world"
        generated = self.adapter.english_word_phoneme_groups(new_text)
        merged = merge_english_section_text_groups(
            query,
            segment_index=english_index,
            old_groups=old_snapshot,
            new_groups=generated,
        )
        retained_sweet = next(
            group for label, group in merged if label.casefold() == "sweet"
        )
        self.assertEqual(retained_sweet, tuple(sweet_phones))

        updated = replace_english_section_text(
            query,
            segment_index=english_index,
            text=new_text,
            phoneme_groups=merged,
        )
        self.assert_full_synthesis_succeeds(updated)

    def test_adding_english_to_pure_japanese_synthesizes_explicit_query(self):
        pure_text = "明日はいい天気。"
        query = build_mixed_audio_query(
            pure_text,
            english_g2p=self.adapter.english_phonemes,
        )
        self.assertIsNone(query.voicegerSegments)
        groups = self.adapter.english_word_phoneme_groups("hello world")

        updated = append_english_section(
            query,
            "hello world",
            phoneme_groups=groups,
            pure_japanese_utterance_text=pure_text,
        )

        self.assertEqual(len(updated.voicegerSegments), 2)
        self.assertEqual(updated.voicegerSegments[0].text, pure_text)
        self.assert_full_synthesis_succeeds(updated)

    def test_deleting_back_to_one_japanese_section_synthesizes_pure_query(self):
        japanese_text = "明日も晴れ。"
        query = build_mixed_audio_query(
            "今日はhello明日も晴れ。",
            segments=(
                DetectedSegment("ja", "今日は"),
                DetectedSegment("en", "hello"),
                DetectedSegment("ja", japanese_text),
            ),
            english_g2p=self.adapter.english_phonemes,
        )

        after_english, _pure_text = delete_utterance_section(
            query,
            segment_index=1,
        )
        pure, pure_text = delete_utterance_section(
            after_english,
            segment_index=0,
        )

        self.assertIsNone(pure.voicegerSegments)
        self.assertEqual(pure_text, japanese_text)
        self.assert_full_synthesis_succeeds(pure)

    def test_user_dictionary_live_reload_survives_voiceger_runtime_loading(self):
        adapter = VoicegerAdapter(voiceger_root=self.voiceger_root)
        text = "テストアクセント辞書固有語は雨。"
        surface = "テストアクセント辞書固有語"

        def reading(value):
            pronunciation = text_to_pronunciation(value)
            return "".join(
                mora
                for phrase in pronunciation.phrases
                for mora in phrase.morae
            )

        with TemporaryDirectory(prefix="voiceger-adapter-user-dict-") as temporary:
            adapter.user_dictionary = UserDictionaryCore(
                self.voiceger_root,
                data_directory=Path(temporary),
            )
            adapter.ensure_japanese_dictionary_active()
            before = reading(text)
            adapter.user_dictionary.add_japanese_word(
                surface=surface,
                pronunciation="ズンダモン",
                accent_type=3,
            )
            after_live_reload = reading(text)
            self.assertNotEqual(before, after_live_reload)
            self.assertTrue(after_live_reload.startswith("ズンダモンワ"))

            # Simulate the process-global dictionary reset performed by a
            # Voiceger Japanese runtime import, then verify _ensure_runtime
            # reapplies the merged adapter dictionary before returning.
            import pyopenjtalk

            opaque_voiceger_dictionary = (
                self.voiceger_root
                / "GPT-SoVITS"
                / "GPT_SoVITS"
                / "text"
                / "ja_userdic"
                / "user.dict"
            )
            with OPENJTALK_LOCK:
                pyopenjtalk.update_global_jtalk_with_user_dict(
                    str(opaque_voiceger_dictionary)
                )
            self.assertNotEqual(reading(text), after_live_reload)

            adapter._ensure_runtime()
            session = UtteranceSession.from_text(
                adapter=adapter,
                caption=text,
                settings=Settings(style_id=1),
            )
            query_reading = "".join(
                mora.text
                for phrase in session.query.accent_phrases
                for mora in phrase.moras
            )
            self.assertTrue(query_reading.startswith("ズンダモンワ"))
            self.assertEqual(query_reading, reading(text))


if __name__ == "__main__":
    unittest.main()
