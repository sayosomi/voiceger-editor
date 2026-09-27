import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from voiceger_accent_adapter.mixed_language import DetectedSegment
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


class FakeAdapter:
    def __init__(self):
        self.voiceger_root = Path("/voiceger")
        self.english_phonemes = Mock(return_value=["HH", "AH0"])


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
                audio=object(),
                sampling_rate=32000,
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
            audio=object(),
            sampling_rate=32000,
        )

    def regenerate_all(self):
        self.regenerate_all_calls += 1
        return iter(("regenerated",))

    def accept(self, take_number):
        self.accept_calls.append(take_number)
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

    def make_session(self, *, source_text="  exact source  ", query=None):
        if query is None:
            query = _query(speed_scale=0.5)
        with patch(
            "voiceger_accent_adapter.session.get_style",
            return_value=self.style,
        ):
            return UtteranceSession(
                adapter=self.adapter,
                source_text=source_text,
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
                            source_text=source,
                            query=_query(),
                            settings=self.settings,
                        )

        supplied = _query(mora_text="元")
        session = self.make_session(query=supplied)
        supplied.accent_phrases[0].moras[0].text = "変更後"

        self.assertEqual(session.source_text, "  exact source  ")
        self.assertEqual(session.query.accent_phrases[0].moras[0].text, "元")

    def test_constructor_requires_settings_instance(self):
        with patch(
            "voiceger_accent_adapter.session.get_style",
            return_value=self.style,
        ):
            with self.assertRaisesRegex(TypeError, "Settings instance"):
                UtteranceSession(
                    adapter=self.adapter,
                    source_text="text",
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

    def test_same_signature_source_replacement_preserves_pronunciation_and_discards_takes(self):
        session = self.make_session(
            source_text="old-ja old-en old-end",
            query=_mixed_pronunciation_query(),
        )
        old_query = session.query
        batch = self.activate_batch(session)
        batch._candidates.append(
            TakeCandidate(1, Path("/tmp/existing.wav"), object(), 32000)
        )
        detected = [
            DetectedSegment("ja", "new-ja"),
            DetectedSegment("en", "new-en"),
            DetectedSegment("ja", "new-end!"),
        ]

        with patch(
            "voiceger_accent_adapter.session.detect_language_segments",
            return_value=detected,
        ) as detect, patch(
            "voiceger_accent_adapter.session.build_mixed_audio_query"
        ) as build_query:
            session.replace_source_text("new-ja new-en new-end!")

        detect.assert_called_once_with("new-ja new-en new-end!")
        build_query.assert_not_called()
        self.adapter.english_phonemes.assert_not_called()
        self.assertEqual(session.source_text, "new-ja new-en new-end!")
        self.assertFalse(session.pronunciation_needs_rebuild)
        self.assertTrue(batch.closed)
        self.assertFalse(session.has_active_batch)
        self.assertEqual(session.candidates, ())
        updated = session.query
        self.assertEqual(
            [segment.text for segment in updated.voicegerSegments],
            ["new-ja", "new-en", "new-end!"],
        )
        self.assertEqual(updated.accent_phrases, old_query.accent_phrases)
        self.assertEqual(
            [segment.pronunciationTerminator for segment in updated.voicegerSegments],
            ["", None, "？"],
        )
        self.assertEqual(
            updated.voicegerSegments[1].phonemes,
            old_query.voicegerSegments[1].phonemes,
        )
        self.assertEqual(
            [
                (segment.accentPhraseStart, segment.accentPhraseCount)
                for segment in updated.voicegerSegments
            ],
            [
                (segment.accentPhraseStart, segment.accentPhraseCount)
                for segment in old_query.voicegerSegments
            ],
        )

    def test_changed_signature_marks_rebuild_required_and_keeps_old_query(self):
        session = self.make_session(source_text="雨", query=_query(mora_text="旧"))
        old_query = session.query
        batch = self.activate_batch(session)
        batch._candidates.append(
            TakeCandidate(1, Path("/tmp/existing.wav"), object(), 32000)
        )

        with patch(
            "voiceger_accent_adapter.session.detect_language_segments",
            return_value=[DetectedSegment("en", "hello")],
        ), patch(
            "voiceger_accent_adapter.session.build_mixed_audio_query"
        ) as build_query:
            session.replace_source_text("hello")
            self.assertEqual(session.source_text, "hello")
            self.assertTrue(session.pronunciation_needs_rebuild)
            self.assertEqual(session.query, old_query)
            self.assertTrue(batch.closed)
            self.assertFalse(session.has_active_batch)
            self.assertEqual(session.candidates, ())

            with self.assertRaisesRegex(
                RuntimeError,
                "pronunciation must be rebuilt after the source-text structure changed",
            ):
                session.generate_takes()

        build_query.assert_not_called()

    def test_source_replacement_detection_failure_preserves_session_and_batch(self):
        session = self.make_session(source_text="old", query=_query())
        old_query = session.query
        batch = self.activate_batch(session)

        with patch(
            "voiceger_accent_adapter.session.detect_language_segments",
            side_effect=RuntimeError("segmentation failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "segmentation failed"):
                session.replace_source_text("new")

        self.assertEqual(session.source_text, "old")
        self.assertEqual(session.query, old_query)
        self.assertFalse(session.pronunciation_needs_rebuild)
        self.assertFalse(batch.closed)
        self.assertTrue(session.has_active_batch)

    def test_explicit_rebuild_installs_automatic_query_and_preserves_settings_speed(self):
        session = self.make_session(source_text="old", query=_query(mora_text="manual"))
        with patch(
            "voiceger_accent_adapter.session.detect_language_segments",
            return_value=[DetectedSegment("en", "new")],
        ):
            session.replace_source_text("new")
        automatic_query = _query(speed_scale=0.6, mora_text="automatic")

        with patch(
            "voiceger_accent_adapter.session.build_mixed_audio_query",
            return_value=automatic_query,
        ) as build_query:
            session.rebuild_pronunciation()

        build_query.assert_called_once_with(
            "new",
            english_g2p=self.adapter.english_phonemes,
            output_sampling_rate=32000,
        )
        self.assertFalse(session.has_active_batch)
        self.assertFalse(session.pronunciation_needs_rebuild)
        self.assertEqual(session.query.speedScale, self.settings.speed)
        self.assertEqual(
            session.query.accent_phrases[0].moras[0].text,
            "automatic",
        )

    def test_successful_explicit_rebuild_discards_existing_takes(self):
        session = self.make_session(source_text="old", query=_query(mora_text="manual"))
        batch = self.activate_batch(session)

        with patch(
            "voiceger_accent_adapter.session.build_mixed_audio_query",
            return_value=_query(mora_text="automatic"),
        ):
            session.rebuild_pronunciation()

        self.assertTrue(batch.closed)
        self.assertFalse(session.has_active_batch)
        self.assertEqual(
            session.query.accent_phrases[0].moras[0].text,
            "automatic",
        )

    def test_manual_query_and_settings_replacement_do_not_clear_rebuild_state(self):
        session = self.make_session(source_text="old", query=_query(mora_text="manual"))
        with patch(
            "voiceger_accent_adapter.session.detect_language_segments",
            return_value=[DetectedSegment("en", "new")],
        ):
            session.replace_source_text("new")
        replacement_settings = Settings(style_id=2, speed=0.9)

        with patch(
            "voiceger_accent_adapter.session.build_mixed_audio_query"
        ) as build_query, patch(
            "voiceger_accent_adapter.session.get_style",
            return_value=self.other_style,
        ):
            session.replace_query(_query(mora_text="manual edit"))
            session.replace_settings(replacement_settings)

        build_query.assert_not_called()
        self.assertTrue(session.pronunciation_needs_rebuild)
        self.assertEqual(session.query.accent_phrases[0].moras[0].text, "manual edit")
        self.assertEqual(session.query.speedScale, replacement_settings.speed)

    def test_unchanged_source_text_is_a_no_op(self):
        session = self.make_session(source_text="same", query=_query())
        old_query = session.query
        batch = self.activate_batch(session)

        with patch(
            "voiceger_accent_adapter.session.detect_language_segments"
        ) as detect:
            session.replace_source_text("same")

        detect.assert_not_called()
        self.assertTrue(batch.closed is False)
        self.assertEqual(session.query, old_query)
        self.assertFalse(session.pronunciation_needs_rebuild)

    def test_invalid_source_replacement_preserves_active_batch(self):
        session = self.make_session(source_text="old", query=_query())
        batch = self.activate_batch(session)

        with patch(
            "voiceger_accent_adapter.session.detect_language_segments"
        ) as detect:
            with self.assertRaises(ValueError):
                session.replace_source_text("two\nlines")

        detect.assert_not_called()
        self.assertEqual(session.source_text, "old")
        self.assertFalse(session.pronunciation_needs_rebuild)
        self.assertFalse(batch.closed)
        self.assertTrue(session.has_active_batch)

    def test_failed_explicit_rebuild_preserves_query_stale_state_and_takes(self):
        session = self.make_session(source_text="old", query=_query(mora_text="manual"))
        with patch(
            "voiceger_accent_adapter.session.detect_language_segments",
            return_value=[DetectedSegment("en", "new")],
        ):
            session.replace_source_text("new")
        old_query = session.query
        with patch(
            "voiceger_accent_adapter.session.build_mixed_audio_query",
            side_effect=RuntimeError("automatic analysis failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "automatic analysis failed"):
                session.rebuild_pronunciation()

        self.assertEqual(session.query, old_query)
        self.assertTrue(session.pronunciation_needs_rebuild)
        self.assertFalse(session.has_active_batch)

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
                source_text=source,
                settings=self.settings,
            )

        build_query.assert_called_once_with(
            source,
            english_g2p=self.adapter.english_phonemes,
            output_sampling_rate=32000,
        )
        self.assertEqual(session.source_text, source)
        self.assertEqual(session.query.speedScale, self.settings.speed)

    def test_from_text_rejects_invalid_source_before_building_query(self):
        with patch(
            "voiceger_accent_adapter.session.build_mixed_audio_query"
        ) as build_query:
            with self.assertRaises(ValueError):
                UtteranceSession.from_text(
                    adapter=self.adapter,
                    source_text="first\nsecond",
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

    def test_invalid_replace_query_preserves_active_batch_and_candidates(self):
        session = self.make_session()
        batch = self.activate_batch(session)
        # Seed an existing completed candidate without synthesizing audio.
        batch._candidates.append(
            TakeCandidate(1, Path("/tmp/existing.wav"), object(), 32000)
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

    def test_failed_style_resolution_preserves_settings_style_query_and_batch(self):
        session = self.make_session()
        batch = self.activate_batch(session)
        batch._candidates.append(
            TakeCandidate(1, Path("/tmp/existing.wav"), object(), 32000)
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

    def test_generate_takes_uses_settings_source_and_exact_synthesis_snapshot(self):
        session = self.make_session(source_text="  filename/source  ")
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
            self.assertEqual(kwargs["output_dir"], self.settings.output_dir)
            self.assertEqual(kwargs["save_text"], self.settings.save_text)
            self.assertEqual(kwargs["source_text"], session.source_text)
            self.assertEqual(kwargs["style_name"], session.style.name)
            self.assertEqual(kwargs["filename_text"], session.source_text)
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
        self.assertEqual(batch.accept_calls, [2])
        self.assertFalse(session.has_active_batch)
        self.assertEqual(session.candidates, ())

    def test_failed_acceptance_preserves_active_batch_and_candidates(self):
        session = self.make_session()
        batch = self.activate_batch(session)
        batch._candidates.append(
            TakeCandidate(1, Path("/tmp/existing.wav"), object(), 32000)
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
            TakeCandidate(1, Path("/tmp/existing.wav"), object(), 32000)
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
