import unittest
from dataclasses import replace
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from voiceger_accent_adapter.output import SavedOutput
from voiceger_accent_adapter.session import UtteranceSession
from voiceger_accent_adapter.settings import Settings
from voiceger_accent_adapter.styles import VoicegerStyle
from voiceger_accent_adapter.takes import TakeCandidate
from voiceger_accent_adapter.voicevox_api_models import (
    AccentPhrase,
    AudioQuery,
    Mora,
    VoicegerSegment,
)


def _query(*, speed_scale=1.0, mora_text="ア"):
    return AudioQuery(
        accent_phrases=[
            AccentPhrase(
                moras=[Mora(text=mora_text, vowel="a", vowel_length=0.1)],
                accent=1,
            )
        ],
        speedScale=speed_scale,
    )


def _mixed_pronunciation_query():
    return AudioQuery(
        accent_phrases=[
            AccentPhrase(
                moras=[Mora(text="古", vowel="a", vowel_length=0.1)],
                accent=1,
            ),
            AccentPhrase(
                moras=[Mora(text="締", vowel="i", vowel_length=0.1)],
                accent=1,
            ),
        ],
        voicegerSegments=[
            VoicegerSegment(
                language="ja",
                text="old-ja",
                accentPhraseStart=0,
                accentPhraseCount=1,
                pronunciationTerminator="",
            ),
            VoicegerSegment(
                language="en",
                text="old-en",
                phonemes=["HH", "AH1"],
            ),
            VoicegerSegment(
                language="ja",
                text="old-end",
                accentPhraseStart=1,
                accentPhraseCount=1,
                pronunciationTerminator="？",
            ),
        ],
    )


def _candidate(number, wav_path):
    return TakeCandidate(
        number=number,
        wav_path=Path(wav_path),
        sampling_rate=32000,
        frame_count=1280,
        source_text="candidate source",
        style_name="Neutral",
    )


class FakeAdapter:
    def __init__(self):
        self.voiceger_root = Path("/voiceger")
        self.english_phonemes = Mock(return_value=["HH", "AH0"])
        self.ensure_japanese_dictionary_active = Mock()


class FakeTakeBatch:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.take_count = kwargs["take_count"]
        self._candidates = []
        self.close_calls = 0
        self.closed = False
        self.regenerate_calls = []
        self.regenerate_all_calls = 0
        self.accept_calls = []
        self.accept_error = None
        self.accept_result = object()
        self.instances.append(self)
        self.initial_iterator = self._generate()

    @property
    def candidates(self):
        return tuple(self._candidates)

    def _generate(self):
        for number in range(1, self.take_count + 1):
            if self.closed:
                raise RuntimeError("take batch is closed")
            candidate = TakeCandidate(
                number=number,
                wav_path=Path(f"/tmp/take-{number}.wav"),
                sampling_rate=32000,
                frame_count=1280,
                source_text=self.kwargs["source_text"],
                style_name=self.kwargs["style_name"],
            )
            self._candidates.append(candidate)
            yield candidate

    def generate_all(self):
        if self.closed:
            raise RuntimeError("take batch is closed")
        return self.initial_iterator

    def regenerate(self, take_number):
        self.regenerate_calls.append(take_number)
        return TakeCandidate(
            number=take_number,
            wav_path=Path(f"/tmp/replacement-{take_number}.wav"),
            sampling_rate=32000,
            frame_count=1280,
            source_text=self.kwargs["source_text"],
            style_name=self.kwargs["style_name"],
        )

    def regenerate_all(self):
        self.regenerate_all_calls += 1
        return iter(("regenerated",))

    def accept(self, take_number, **save_settings):
        self.accept_calls.append((take_number, save_settings))
        if self.accept_error is not None:
            raise self.accept_error
        self.close()
        return self.accept_result

    def close(self):
        self.close_calls += 1
        self.closed = True
        self._candidates.clear()


class UtteranceSessionTests(unittest.TestCase):
    def setUp(self):
        FakeTakeBatch.instances = []
        self.adapter = FakeAdapter()
        self.style = VoicegerStyle(
            id=1,
            name="Neutral",
            filename="01.wav",
        )
        self.other_style = VoicegerStyle(
            id=2,
            name="Sweet",
            filename="02.wav",
        )
        self.settings = Settings(
            output_dir=Path("/output"),
            take_count=3,
            style_id=1,
            speed=1.25,
            save_text=True,
        )

    def make_session(self, *, caption="  exact source  ", query=None):
        if query is None:
            query = _query(speed_scale=0.5)
        with patch(
            "voiceger_accent_adapter.session.get_style",
            return_value=self.style,
        ):
            return UtteranceSession(
                adapter=self.adapter,
                caption=caption,
                query=query,
                settings=self.settings,
            )

    def activate_batch(self, session):
        with patch(
            "voiceger_accent_adapter.session.TakeBatch",
            FakeTakeBatch,
        ):
            session.generate_takes()
        return FakeTakeBatch.instances[-1]

    def test_constructor_validates_source_and_defensively_copies_query(self):
        for source in (None, 1, "", " \t ", "line one\nline two", "line\rtwo"):
            with self.subTest(source=source):
                with patch(
                    "voiceger_accent_adapter.session.get_style",
                    return_value=self.style,
                ):
                    with self.assertRaises((TypeError, ValueError)):
                        UtteranceSession(
                            adapter=self.adapter,
                            caption=source,
                            query=_query(),
                            settings=self.settings,
                        )

        supplied = _query(mora_text="元")
        session = self.make_session(query=supplied)
        supplied.accent_phrases[0].moras[0].text = "変更後"

        self.assertEqual(session.caption, "  exact source  ")
        self.assertEqual(session.query.accent_phrases[0].moras[0].text, "元")

    def test_constructor_requires_settings_instance(self):
        with patch(
            "voiceger_accent_adapter.session.get_style",
            return_value=self.style,
        ):
            with self.assertRaisesRegex(TypeError, "Settings instance"):
                UtteranceSession(
                    adapter=self.adapter,
                    caption="text",
                    query=_query(),
                    settings=object(),
                )

    def test_settings_speed_owns_query_speed_and_query_property_is_defensive(self):
        session = self.make_session(query=_query(speed_scale=0.5))

        self.assertEqual(session.query.speedScale, self.settings.speed)
        externally_edited = session.query
        externally_edited.speedScale = 2.0
        externally_edited.accent_phrases[0].moras[0].text = "外部編集"

        self.assertEqual(session.query.speedScale, self.settings.speed)
        self.assertEqual(session.query.accent_phrases[0].moras[0].text, "ア")

    def test_caption_replacement_preserves_query_and_active_candidates(self):
        session = self.make_session(
            caption="old-ja old-en old-end",
            query=_mixed_pronunciation_query(),
        )
        old_query = session.query.model_dump()
        batch = self.activate_batch(session)
        batch._candidates.append(
            _candidate(1, "/tmp/existing.wav")
        )
        candidates_before = session.candidates

        session.replace_caption("new caption")

        self.assertEqual(session.caption, "new caption")
        self.assertEqual(session.query.model_dump(), old_query)
        self.assertFalse(session.utterance_manually_edited)
        self.assertFalse(batch.closed)
        self.assertTrue(session.has_active_batch)
        self.assertEqual(session.candidates, candidates_before)
        updated = session.query
        self.assertEqual(
            [segment.text for segment in updated.voicegerSegments],
            ["old-ja", "old-en", "old-end"],
        )

    def test_pure_japanese_utterance_source_does_not_follow_caption(self):
        session = self.make_session(caption="Caption A", query=_query(mora_text="雨"))
        old_query = session.query.model_dump()

        session.replace_caption("Caption B")

        self.assertEqual(session.caption, "Caption B")
        self.assertEqual(session.pure_japanese_utterance_text, "Caption A")
        self.assertEqual(session.query.model_dump(), old_query)
        self.assertFalse(session.utterance_manually_edited)
        self.assertEqual(session.synthesis_source_text, "Caption A")

    def test_synthesis_source_text_comes_from_current_mixed_query_not_caption(self):
        session = self.make_session(
            caption="Caption before query rebuild",
            query=_mixed_pronunciation_query(),
        )

        self.assertEqual(
            session.synthesis_source_text,
            "old-jaold-enold-end",
        )
        session.replace_caption("Later Caption")
        self.assertEqual(session.synthesis_source_text, "old-jaold-enold-end")

    def test_accept_uses_query_provenance_and_current_output_settings(self):
        fake_soundfile = ModuleType("soundfile")
        fake_soundfile.write = lambda path, _audio, _sampling_rate: Path(path).write_bytes(
            b"candidate wav bytes"
        )
        fake_soundfile.info = lambda _path: SimpleNamespace(frames=1280)
        synthesis_result = {"audio": [0.0, 0.5], "sampling_rate": 32000}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "current-output"
            session = self.make_session(
                caption="caption at batch creation",
                query=_mixed_pronunciation_query(),
            )
            with patch(
                "voiceger_accent_adapter.session.synthesize_audio_query",
                return_value=synthesis_result,
            ), patch.dict("sys.modules", {"soundfile": fake_soundfile}):
                candidate = next(session.generate_takes())
                candidate_wav = candidate.wav_path
                session.replace_caption("later Caption")
                with patch(
                    "voiceger_accent_adapter.session.get_style",
                    return_value=self.style,
                ):
                    session.replace_settings(
                        replace(
                            self.settings,
                            output_dir=output_dir,
                            save_text=True,
                            take_count=20,
                        )
                    )

                self.assertTrue(session.has_active_batch)
                self.assertTrue(candidate_wav.is_file())
                self.assertEqual(candidate.source_text, "old-jaold-enold-end")
                saved = session.accept_take(candidate.number)

            self.assertFalse(candidate_wav.exists())
            self.assertEqual(saved.wav_path.read_bytes(), b"candidate wav bytes")
            self.assertIn("_Neutral_old-jaold-enold-end.wav", saved.wav_path.name)
            self.assertNotIn("later Caption", saved.wav_path.name)
            self.assertEqual(
                saved.text_path.read_text(encoding="utf-8"), "old-jaold-enold-end"
            )
            self.assertEqual(saved.wav_path.parent, output_dir)
            self.assertFalse(session.has_active_batch)

    def test_final_session_close_removes_real_candidate_temporary_wav(self):
        fake_soundfile = ModuleType("soundfile")
        fake_soundfile.write = lambda path, _audio, _sampling_rate: Path(path).write_bytes(
            b"temporary wav bytes"
        )
        fake_soundfile.info = lambda _path: SimpleNamespace(frames=1280)
        session = self.make_session(query=_query())

        with patch(
            "voiceger_accent_adapter.session.synthesize_audio_query",
            return_value={"audio": [0.0], "sampling_rate": 32000},
        ), patch.dict("sys.modules", {"soundfile": fake_soundfile}):
            candidate = next(session.generate_takes())
            candidate_wav = candidate.wav_path
            self.assertTrue(candidate_wav.is_file())
            session.close()

        self.assertFalse(candidate_wav.exists())
        self.assertFalse(session.has_active_batch)

    def test_invalid_caption_preserves_session_and_active_batch(self):
        session = self.make_session(caption="old", query=_query())
        batch = self.activate_batch(session)
        batch._candidates.append(
            _candidate(1, "/tmp/existing.wav")
        )
        old_query = session.query.model_dump()
        old_candidates = session.candidates

        for invalid in ("", " \t ", "two\nlines", "line\rtwo"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    session.replace_caption(invalid)

        self.assertEqual(session.caption, "old")
        self.assertEqual(session.query.model_dump(), old_query)
        self.assertFalse(batch.closed)
        self.assertTrue(session.has_active_batch)
        self.assertEqual(session.candidates, old_candidates)

    def test_full_build_uses_current_caption_and_preserves_settings(self):
        session = self.make_session(caption="old", query=_query(mora_text="manual"))
        session.replace_caption("new caption")
        session.replace_query(_query(mora_text="edited"))
        automatic_query = _query(speed_scale=0.6, mora_text="automatic")

        with patch(
            "voiceger_accent_adapter.session.build_mixed_audio_query",
            return_value=automatic_query,
        ) as build_query:
            session.build_pronunciation_from_caption()

        build_query.assert_called_once_with(
            "new caption",
            english_g2p=self.adapter.english_phonemes,
            output_sampling_rate=32000,
        )
        self.adapter.ensure_japanese_dictionary_active.assert_called_once_with()
        self.assertFalse(session.has_active_batch)
        self.assertFalse(session.utterance_manually_edited)
        self.assertEqual(session.query.speedScale, self.settings.speed)
        self.assertEqual(session.settings, self.settings)
        self.assertEqual(session.pure_japanese_utterance_text, "new caption")
        self.assertEqual(
            session.query.accent_phrases[0].moras[0].text,
            "automatic",
        )

    def test_successful_full_build_discards_existing_takes(self):
        session = self.make_session(caption="old", query=_query(mora_text="manual"))
        batch = self.activate_batch(session)

        with patch(
            "voiceger_accent_adapter.session.build_mixed_audio_query",
            return_value=_query(mora_text="automatic"),
        ):
            session.build_pronunciation_from_caption()

        self.assertTrue(batch.closed)
        self.assertFalse(session.has_active_batch)
        self.assertEqual(
            session.query.accent_phrases[0].moras[0].text,
            "automatic",
        )

    def test_manual_edit_tracking_and_settings_preserve_dirty_state(self):
        session = self.make_session(caption="old", query=_query(mora_text="manual"))
        self.assertFalse(session.utterance_manually_edited)
        session.replace_caption("new caption")
        self.assertFalse(session.utterance_manually_edited)
        replacement_settings = Settings(style_id=2, speed=0.9)

        with patch(
            "voiceger_accent_adapter.session.get_style",
            return_value=self.other_style,
        ):
            session.replace_query(_query(mora_text="manual edit"))
            self.assertTrue(session.utterance_manually_edited)
            session.replace_caption("another caption")
            self.assertTrue(session.utterance_manually_edited)
            session.replace_settings(replacement_settings)

        self.assertTrue(session.utterance_manually_edited)
        self.assertEqual(session.caption, "another caption")
        self.assertEqual(session.query.accent_phrases[0].moras[0].text, "manual edit")
        self.assertEqual(session.query.speedScale, replacement_settings.speed)

    def test_unchanged_caption_keeps_active_batch(self):
        session = self.make_session(caption="same", query=_query())
        old_query = session.query
        batch = self.activate_batch(session)

        session.replace_caption("same")

        self.assertTrue(batch.closed is False)
        self.assertEqual(session.query, old_query)

    def test_failed_full_build_preserves_query_manual_state_and_takes(self):
        session = self.make_session(caption="old", query=_query(mora_text="manual"))
        session.replace_query(_query(mora_text="edited"))
        batch = self.activate_batch(session)
        batch._candidates.append(
            _candidate(1, "/tmp/existing.wav")
        )
        candidates = session.candidates
        old_query = session.query
        with patch(
            "voiceger_accent_adapter.session.build_mixed_audio_query",
            side_effect=RuntimeError("automatic analysis failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "automatic analysis failed"):
                session.build_pronunciation_from_caption()

        self.assertEqual(session.query, old_query)
        self.assertTrue(session.utterance_manually_edited)
        self.assertTrue(session.has_active_batch)
        self.assertFalse(batch.closed)
        self.assertEqual(session.candidates, candidates)

    def test_from_text_builds_query_with_exact_source_callback_and_sampling_rate(self):
        source = "  今日はhello  "
        built_query = _query(speed_scale=0.8)
        with patch(
            "voiceger_accent_adapter.session.build_mixed_audio_query",
            return_value=built_query,
        ) as build_query, patch(
            "voiceger_accent_adapter.session.get_style",
            return_value=self.style,
        ):
            session = UtteranceSession.from_text(
                adapter=self.adapter,
                caption=source,
                settings=self.settings,
            )

        build_query.assert_called_once_with(
            source,
            english_g2p=self.adapter.english_phonemes,
            output_sampling_rate=32000,
        )
        self.adapter.ensure_japanese_dictionary_active.assert_called_once_with()
        self.assertEqual(session.caption, source)
        self.assertEqual(session.pure_japanese_utterance_text, source)
        self.assertFalse(session.utterance_manually_edited)
        self.assertEqual(session.query.speedScale, self.settings.speed)

    def test_from_text_rejects_invalid_source_before_building_query(self):
        with patch(
            "voiceger_accent_adapter.session.build_mixed_audio_query"
        ) as build_query:
            with self.assertRaises(ValueError):
                UtteranceSession.from_text(
                    adapter=self.adapter,
                    caption="first\nsecond",
                    settings=self.settings,
                )

        build_query.assert_not_called()

    def test_replace_query_invalidates_batch_and_keeps_settings_speed(self):
        session = self.make_session()
        batch = self.activate_batch(session)
        replacement = _query(speed_scale=0.75, mora_text="新")

        session.replace_query(replacement)

        self.assertTrue(batch.closed)
        self.assertEqual(batch.close_calls, 1)
        self.assertFalse(session.has_active_batch)
        self.assertEqual(session.candidates, ())
        self.assertEqual(session.query.speedScale, self.settings.speed)
        self.assertEqual(session.query.accent_phrases[0].moras[0].text, "新")
        self.assertTrue(session.utterance_manually_edited)

    def test_committed_pure_text_replacement_keeps_caption_and_updates_actual_source(self):
        session = self.make_session(caption="Caption", query=_query(mora_text="雨"))
        batch = self.activate_batch(session)

        session.replace_query(
            _query(mora_text="明日"),
            pure_japanese_utterance_text="明日の発話",
        )

        self.assertEqual(session.caption, "Caption")
        self.assertEqual(session.pure_japanese_utterance_text, "明日の発話")
        self.assertTrue(session.utterance_manually_edited)
        self.assertTrue(batch.closed)
        self.assertFalse(session.has_active_batch)
        self.assertEqual(session.candidates, ())

    def test_invalid_replace_query_preserves_active_batch_and_candidates(self):
        session = self.make_session()
        batch = self.activate_batch(session)
        # Seed an existing completed candidate without synthesizing audio.
        batch._candidates.append(
            _candidate(1, "/tmp/existing.wav")
        )
        candidates_before = session.candidates

        with self.assertRaisesRegex(TypeError, "AudioQuery"):
            session.replace_query(object())

        self.assertFalse(batch.closed)
        self.assertTrue(session.has_active_batch)
        self.assertEqual(session.candidates, candidates_before)

    def test_replace_settings_resolves_style_updates_speed_and_invalidates_batch(self):
        session = self.make_session()
        batch = self.activate_batch(session)
        replacement_settings = Settings(
            output_dir=Path("/new-output"),
            take_count=2,
            style_id=2,
            speed=0.9,
            save_text=False,
        )

        with patch(
            "voiceger_accent_adapter.session.get_style",
            return_value=self.other_style,
        ) as resolve_style:
            session.replace_settings(replacement_settings)

        resolve_style.assert_called_once_with(
            self.adapter.voiceger_root,
            replacement_settings.style_id,
        )
        self.assertTrue(batch.closed)
        self.assertEqual(session.settings, replacement_settings)
        self.assertEqual(session.style, self.other_style)
        self.assertEqual(session.query.speedScale, replacement_settings.speed)
        self.assertFalse(session.has_active_batch)
        self.assertEqual(session.candidates, ())

    def test_synthesis_setting_changes_each_invalidate_the_active_batch(self):
        changes = (
            ({"style_id": 2}, self.other_style),
            ({"speed": 0.9}, self.style),
            ({"top_k": 37}, self.style),
            ({"top_p": 0.45}, self.style),
            ({"temperature": 0.80}, self.style),
        )
        for settings_changes, resolved_style in changes:
            with self.subTest(settings_changes=settings_changes):
                session = self.make_session()
                batch = self.activate_batch(session)
                batch._candidates.append(_candidate(1, "/tmp/existing.wav"))

                with patch(
                    "voiceger_accent_adapter.session.get_style",
                    return_value=resolved_style,
                ):
                    session.replace_settings(
                        replace(session.settings, **settings_changes)
                    )

                self.assertTrue(batch.closed)
                self.assertFalse(session.has_active_batch)
                self.assertEqual(session.candidates, ())

    def test_output_text_preference_and_take_count_changes_preserve_batch(self):
        session = self.make_session()
        batch = self.activate_batch(session)
        existing = _candidate(1, "/tmp/existing.wav")
        batch._candidates.append(existing)
        replacement_settings = Settings(
            output_dir=Path("/new-output"),
            take_count=100,
            style_id=self.settings.style_id,
            speed=self.settings.speed,
            save_text=False,
        )

        with patch(
            "voiceger_accent_adapter.session.get_style",
            return_value=self.style,
        ):
            session.replace_settings(replacement_settings)

        self.assertFalse(batch.closed)
        self.assertTrue(session.has_active_batch)
        self.assertEqual(session.candidates, (existing,))
        self.assertEqual(session.active_candidate_count, 1)
        self.assertEqual(session.settings, replacement_settings)

    def test_failed_style_resolution_preserves_settings_style_query_and_batch(self):
        session = self.make_session()
        batch = self.activate_batch(session)
        batch._candidates.append(
            _candidate(1, "/tmp/existing.wav")
        )
        old_settings = session.settings
        old_style = session.style
        old_query = session.query
        old_candidates = session.candidates
        replacement_settings = Settings(style_id=2, speed=1.8)

        with patch(
            "voiceger_accent_adapter.session.get_style",
            side_effect=ValueError("style is unavailable"),
        ):
            with self.assertRaisesRegex(ValueError, "unavailable"):
                session.replace_settings(replacement_settings)

        self.assertIs(session.settings, old_settings)
        self.assertIs(session.style, old_style)
        self.assertEqual(session.query, old_query)
        self.assertTrue(session.has_active_batch)
        self.assertEqual(session.candidates, old_candidates)
        self.assertFalse(batch.closed)

    def test_generate_takes_snapshots_synthesis_and_settings_not_caption(self):
        session = self.make_session(caption="  filename/source  ")
        query_snapshot = session.query
        iterator = object()
        batch_instance = Mock()
        batch_instance.generate_all.return_value = iterator

        with patch(
            "voiceger_accent_adapter.session.TakeBatch",
            return_value=batch_instance,
        ) as take_batch, patch(
            "voiceger_accent_adapter.session.synthesize_audio_query",
            return_value={"audio": object(), "sampling_rate": 32000},
        ) as synthesize:
            result = session.generate_takes(
                top_k=37,
                top_p=0.42,
                temperature=0.83,
            )
            take_batch.assert_called_once()
            kwargs = take_batch.call_args.kwargs
            self.assertEqual(kwargs["take_count"], self.settings.take_count)
            self.assertEqual(kwargs["style_name"], session.style.name)
            self.assertEqual(kwargs["source_text"], "  filename/source  ")
            self.assertNotIn("filename_text", kwargs)
            self.assertIs(kwargs["synthesize_one"](), synthesize.return_value)
            self.assertIs(kwargs["synthesize_one"](), synthesize.return_value)

        self.assertIs(result, iterator)
        self.assertTrue(session.has_active_batch)
        self.assertEqual(synthesize.call_count, 2)
        for call in synthesize.call_args_list:
            self.assertIs(call.kwargs["adapter"], self.adapter)
            self.assertEqual(call.kwargs["query"], query_snapshot)
            self.assertIsNot(call.kwargs["query"], session._query)
            self.assertIs(call.kwargs["style"], self.style)
            self.assertEqual(call.kwargs["top_k"], 37)
            self.assertEqual(call.kwargs["top_p"], 0.42)
            self.assertEqual(call.kwargs["temperature"], 0.83)

    def test_generate_takes_uses_active_sampling_settings_when_not_overridden(self):
        session = self.make_session(caption="sampling source")
        sampling_settings = replace(
            session.settings,
            top_k=37,
            top_p=0.45,
            temperature=0.80,
        )
        with patch(
            "voiceger_accent_adapter.session.get_style",
            return_value=self.style,
        ):
            session.replace_settings(sampling_settings)

        batch_instance = Mock()
        batch_instance.generate_all.return_value = iter(())
        with patch(
            "voiceger_accent_adapter.session.TakeBatch",
            return_value=batch_instance,
        ) as take_batch, patch(
            "voiceger_accent_adapter.session.synthesize_audio_query",
            return_value={"audio": object(), "sampling_rate": 32000},
        ) as synthesize:
            session.generate_takes()
            take_batch.call_args.kwargs["synthesize_one"]()

        call = synthesize.call_args.kwargs
        self.assertEqual(call["top_k"], 37)
        self.assertEqual(call["top_p"], 0.45)
        self.assertEqual(call["temperature"], 0.80)

    def test_preview_synthesis_success_preserves_session_and_candidates(self):
        session = self.make_session(caption="Caption")
        session.replace_query(_query(mora_text="手動"))
        batch = self.activate_batch(session)
        candidate = TakeCandidate(
            number=1,
            wav_path=Path("/tmp/current-take.wav"),
            sampling_rate=32000,
            frame_count=1280,
            source_text="source",
            style_name="Neutral",
        )
        batch._candidates.append(candidate)
        canonical_before = session.query.model_dump()
        candidates_before = session.candidates
        preview = _query(speed_scale=0.4, mora_text="Preview")
        preview_before = preview.model_dump()

        with patch(
            "voiceger_accent_adapter.session.synthesize_audio_query",
            return_value={"audio": "preview-audio", "sampling_rate": 22050},
        ) as synthesize:
            result = session.preview_synthesis(preview)

        self.assertEqual(
            result,
            {"audio": "preview-audio", "sampling_rate": 22050},
        )
        call = synthesize.call_args.kwargs
        self.assertEqual(call["query"].speedScale, self.settings.speed)
        self.assertEqual(call["query"].accent_phrases[0].moras[0].text, "Preview")
        self.assertIsNot(call["query"], preview)
        self.assertEqual(call["style"], self.style)
        self.assertEqual(call["top_k"], 20)
        self.assertEqual(call["top_p"], 1.0)
        self.assertEqual(call["temperature"], 1.0)
        self.assertEqual(preview.model_dump(), preview_before)
        self.assertEqual(session.query.model_dump(), canonical_before)
        self.assertEqual(session.caption, "Caption")
        self.assertTrue(session.utterance_manually_edited)
        self.assertTrue(session.has_active_batch)
        self.assertFalse(batch.closed)
        self.assertEqual(session.candidates, candidates_before)

    def test_preview_synthesis_failure_preserves_session_and_candidates(self):
        session = self.make_session(caption="Caption")
        session.replace_query(_query(mora_text="手動"))
        batch = self.activate_batch(session)
        candidate = TakeCandidate(
            number=1,
            wav_path=Path("/tmp/current-take.wav"),
            sampling_rate=32000,
            frame_count=1280,
            source_text="source",
            style_name="Neutral",
        )
        batch._candidates.append(candidate)
        canonical_before = session.query.model_dump()
        candidates_before = session.candidates
        preview = _query(speed_scale=0.4, mora_text="Preview")
        preview_before = preview.model_dump()

        with patch(
            "voiceger_accent_adapter.session.synthesize_audio_query",
            side_effect=RuntimeError("preview synthesis failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "preview synthesis failed"):
                session.preview_synthesis(preview)

        self.assertEqual(preview.model_dump(), preview_before)
        self.assertEqual(session.query.model_dump(), canonical_before)
        self.assertEqual(session.caption, "Caption")
        self.assertTrue(session.utterance_manually_edited)
        self.assertTrue(session.has_active_batch)
        self.assertFalse(batch.closed)
        self.assertEqual(session.candidates, candidates_before)

    def test_generate_takes_rejects_second_active_batch(self):
        session = self.make_session()
        batch = self.activate_batch(session)
        existing_batch_count = len(FakeTakeBatch.instances)

        with patch(
            "voiceger_accent_adapter.session.TakeBatch",
            FakeTakeBatch,
        ):
            with self.assertRaisesRegex(RuntimeError, "already active"):
                session.generate_takes()

        self.assertEqual(len(FakeTakeBatch.instances), existing_batch_count)
        self.assertIs(session._active_batch, batch)

    def test_invalidation_closes_batch_and_stops_existing_generation_iterator(self):
        session = self.make_session()
        with patch(
            "voiceger_accent_adapter.session.TakeBatch",
            FakeTakeBatch,
        ):
            iterator = session.generate_takes()
        session.replace_query(_query(mora_text="編集"))

        with self.assertRaisesRegex(RuntimeError, "closed"):
            next(iterator)

    def test_regeneration_methods_delegate_to_active_batch(self):
        session = self.make_session()
        batch = self.activate_batch(session)

        regenerated = session.regenerate_take(2)
        all_regenerated = session.regenerate_all_takes()

        self.assertEqual(batch.regenerate_calls, [2])
        self.assertEqual(regenerated.number, 2)
        self.assertEqual(list(all_regenerated), ["regenerated"])
        self.assertEqual(batch.regenerate_all_calls, 1)

    def test_successful_acceptance_clears_active_batch(self):
        session = self.make_session()
        batch = self.activate_batch(session)
        saved = SavedOutput(
            wav_path=Path("/output/accepted.wav"),
            text_path=None,
        )
        batch.accept_result = saved

        result = session.accept_take(2)

        self.assertIs(result, saved)
        self.assertEqual(
            batch.accept_calls,
            [
                (
                    2,
                    {
                        "output_dir": session.settings.output_dir,
                        "save_text": session.settings.save_text,
                    },
                )
            ],
        )
        self.assertFalse(session.has_active_batch)
        self.assertEqual(session.candidates, ())

    def test_acceptance_uses_current_save_preferences_without_caption_provenance(self):
        session = self.make_session(caption="old caption")
        batch = self.activate_batch(session)
        session.replace_caption("new caption")
        replacement_settings = replace(
            session.settings,
            output_dir=Path("/latest-output"),
            save_text=False,
        )
        with patch(
            "voiceger_accent_adapter.session.get_style",
            return_value=self.style,
        ):
            session.replace_settings(replacement_settings)

        session.accept_take(2)

        self.assertEqual(
            batch.accept_calls,
            [
                (
                    2,
                    {
                        "output_dir": Path("/latest-output"),
                        "save_text": False,
                    },
                )
            ],
        )

    def test_failed_acceptance_preserves_active_batch_and_candidates(self):
        session = self.make_session()
        batch = self.activate_batch(session)
        batch._candidates.append(
            _candidate(1, "/tmp/existing.wav")
        )
        candidates_before = session.candidates
        failure = OSError("cannot save output")
        batch.accept_error = failure

        with self.assertRaisesRegex(OSError, "cannot save") as raised:
            session.accept_take(1)

        self.assertIs(raised.exception, failure)
        self.assertTrue(session.has_active_batch)
        self.assertEqual(session.candidates, candidates_before)
        self.assertFalse(batch.closed)

    def test_discard_is_idempotent_and_clears_candidates(self):
        session = self.make_session()
        batch = self.activate_batch(session)
        batch._candidates.append(
            _candidate(1, "/tmp/existing.wav")
        )

        session.discard_takes()
        session.discard_takes()
        session.discard_takes()

        self.assertEqual(batch.close_calls, 1)
        self.assertTrue(batch.closed)
        self.assertFalse(session.has_active_batch)
        self.assertEqual(session.candidates, ())

    def test_batch_only_operations_require_active_batch(self):
        session = self.make_session()

        for operation in (
            lambda: session.regenerate_take(1),
            session.regenerate_all_takes,
            lambda: session.accept_take(1),
        ):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(RuntimeError, "no take batch"):
                    operation()

    def test_close_and_context_manager_discard_active_batch(self):
        session = self.make_session()
        batch = self.activate_batch(session)
        session.close()
        session.close()
        self.assertEqual(batch.close_calls, 1)

        with patch(
            "voiceger_accent_adapter.session.TakeBatch",
            FakeTakeBatch,
        ):
            with session as entered:
                self.assertIs(entered, session)
                session.generate_takes()
                context_batch = FakeTakeBatch.instances[-1]
        self.assertTrue(context_batch.closed)
        self.assertFalse(session.has_active_batch)


if __name__ == "__main__":
    unittest.main()
