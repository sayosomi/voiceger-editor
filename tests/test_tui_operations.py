import io
from pathlib import Path
import subprocess
import sys
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from voiceger_editor.caption_batch import CaptionBatch, CaptionBatchItem
from voiceger_editor.settings import Settings
from voiceger_editor.tui_dictionary import (
    DictionaryOperationIntent,
    DictionaryOperationRequest,
)
from voiceger_editor.tui_editors import EditorState
from voiceger_editor.tui_operations import (
    BackgroundOperationProgress,
    BatchCandidateReplacedEffect,
    BatchGenerationProgressEvent,
    CandidateReplacedEffect,
    DictionaryOperationCompletedEffect,
    DictionaryOperationCompletedEvent,
    DiscardInitialBatchEffect,
    FocusEffect,
    GenerationOutcomeEffect,
    PlayPreviewEffect,
    PlayTakeEffect,
    PreviewFailedEvent,
    PreviewReadyEvent,
    SessionPreparationCompletedEffect,
    StopPlaybackEffect,
    TakeAcceptedEffect,
    TuiOperations,
    UpdateStatusEffect,
)
from voiceger_editor.tui_status import StatusKind, error_status, warning_status
from voiceger_editor.voicevox_api_models import AudioQuery
from tests.tui_operation_test_support import FakeSession, candidate




class TuiOperationsTests(unittest.TestCase):
    def setUp(self):
        self.operations = TuiOperations()

    def consume(self, session=None, *, revision=0, segment=0, exiting=False):
        return self.operations.consume_pending_events(
            session,
            navigation_revision=revision,
            pronunciation_index=segment,
            exit_requested=exiting,
        )

    def test_initial_generation_guards_and_startup_errors(self):
        self.assertEqual(self.operations.start_generation(
            None, take_count=4, navigation_revision=0
        ), ())

        self.operations.busy = True
        self.assertEqual(
            self.operations.start_generation(
                FakeSession(), take_count=4, navigation_revision=0
            ),
            (
                UpdateStatusEffect(
                    warning_status(
                        "Generate Caption is unavailable while "
                        "another background operation is active."
                    )
                ),
            ),
        )
        self.operations.busy = False

        existing = FakeSession((candidate(1),))
        self.assertEqual(
            self.operations.start_generation(existing, take_count=4, navigation_revision=0),
            (
                UpdateStatusEffect(
                    "A take batch already exists; use g to regenerate all takes."
                ),
            ),
        )

        failing = FakeSession()
        failing.generate_error = RuntimeError("generator setup failed")
        self.assertEqual(
            self.operations.start_generation(failing, take_count=4, navigation_revision=0),
            (
                UpdateStatusEffect(
                    error_status(
                        "Could not start take generation: generator setup failed"
                    )
                ),
            ),
        )

    def test_operation_resource_and_item_ownership_are_reported_separately(self):
        self.assertFalse(self.operations.operation_resource_busy)
        self.assertEqual(self.operations.owned_item_ids, frozenset())
        self.assertFalse(self.operations.owns_item("item-1"))

        self.operations.busy = True
        self.operations.worker_operation = "initial"
        self.operations._owned_item_ids = frozenset({"item-1"})

        self.assertTrue(self.operations.operation_resource_busy)
        self.assertTrue(self.operations.owns_item("item-1"))
        self.assertFalse(self.operations.owns_item("item-2"))
        self.assertIsNone(
            self.operations.item_mutation_conflict_status(
                CaptionBatch(default_take_count=4),
                "item-2",
                action="editing Caption",
            )
        )

    def test_preview_worker_emits_ready_playback_effect_without_candidate_focus(self):
        session_candidate = candidate(3)
        session = FakeSession((session_candidate,))
        query = AudioQuery(accent_phrases=[])
        self.operations.current_take = 3
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            effects = self.operations.start_preview(session, query)
            self.operations.join_worker()

        self.assertEqual(
            effects,
            (UpdateStatusEffect("Synthesizing pronunciation Preview…"),),
        )
        self.assertTrue(self.operations.busy)
        self.assertEqual(self.operations.worker_operation, "preview")
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        event = self.operations.events.get_nowait()
        self.assertIsInstance(event, PreviewReadyEvent)
        self.assertEqual(event.audio, "preview")
        self.assertEqual(event.sampling_rate, 22050)
        done_event = self.operations.events.get_nowait()
        self.assertEqual(done_event, ("done", None))
        self.operations.events.put(event)
        self.operations.events.put(done_event)

        effects = self.consume(session)

        self.assertEqual(effects, (PlayPreviewEffect("preview", 22050),))
        self.assertFalse(self.operations.busy)
        self.assertIsNone(self.operations.worker_operation)
        self.assertEqual(self.operations.current_take, 3)
        self.assertEqual(session.candidates, [session_candidate])
        self.assertEqual(session.preview_calls[0].model_dump(), query.model_dump())
        self.assertFalse(any(isinstance(item, FocusEffect) for item in effects))
        self.assertFalse(any(isinstance(item, PlayTakeEffect) for item in effects))

    def test_preview_without_active_session_uses_standalone_context(self):
        query = AudioQuery(accent_phrases=[])
        adapter = Mock()
        settings = Settings()
        preview_session = FakeSession()

        with patch(
            "voiceger_editor.tui_operations.UtteranceSession",
            return_value=preview_session,
        ) as session_factory:
            effects = self.operations.start_preview(
                None,
                query,
                adapter=adapter,
                settings=settings,
            )
            self.operations.join_worker()

        self.assertEqual(
            effects,
            (UpdateStatusEffect("Synthesizing pronunciation Preview…"),),
        )
        session_factory.assert_called_once_with(
            adapter=adapter,
            caption="Dictionary Preview",
            query=query,
            settings=settings,
        )
        self.assertEqual(
            preview_session.preview_calls[0].model_dump(),
            query.model_dump(),
        )
        event = self.operations.events.get_nowait()
        self.assertIsInstance(event, PreviewReadyEvent)
        self.assertEqual(event.audio, "preview")
        self.assertEqual(event.sampling_rate, 22050)
        self.assertEqual(self.operations.events.get_nowait(), ("done", None))

    def test_preview_worker_failure_is_preview_specific_and_keeps_candidates(self):
        session_candidate = candidate(2)
        session = FakeSession((session_candidate,))
        session.preview_error = RuntimeError("model unavailable")
        self.operations.current_take = 2

        self.operations.start_preview(session, AudioQuery(accent_phrases=[]))
        self.assertTrue(self.operations.busy)
        self.operations.join_worker()
        event = self.operations.events.get_nowait()
        self.assertIsInstance(event, PreviewFailedEvent)
        self.assertEqual(str(event.error), "model unavailable")
        done_event = self.operations.events.get_nowait()
        self.assertEqual(done_event, ("done", None))
        self.operations.events.put(event)
        self.operations.events.put(done_event)

        effects = self.consume(session)

        self.assertEqual(
            effects,
            (UpdateStatusEffect(error_status("Preview failed: model unavailable")),),
        )
        self.assertFalse(self.operations.busy)
        self.assertEqual(self.operations.current_take, 2)
        self.assertEqual(session.candidates, [session_candidate])
        self.assertFalse(any(isinstance(item, FocusEffect) for item in effects))
        self.assertFalse(any(isinstance(item, DiscardInitialBatchEffect) for item in effects))

    def test_dictionary_operation_is_deferred_until_status_can_render_and_completes(self):
        editor = EditorState(
            kind="dictionary_japanese_entry",
            title="ADD JAPANESE DICTIONARY WORD",
            origin=("dictionary", None),
            selection="save",
        )
        request = DictionaryOperationRequest(
            operation="save_japanese",
            language="ja",
            editor_snapshot=editor,
            originating_editor=editor,
        )
        started = Event()
        release = Event()
        stdout = io.StringIO()
        stderr = io.StringIO()

        def work():
            started.set()
            if not release.wait(timeout=1):
                raise RuntimeError("test release timeout")
            print("hidden dictionary output")
            return "saved"

        intent = DictionaryOperationIntent(
            request,
            "Saving Japanese dictionary word…",
            work,
        )
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            effects = self.operations.start_dictionary_operation(intent)

        self.assertEqual(
            effects,
            (UpdateStatusEffect("Saving Japanese dictionary word…"),),
        )
        self.assertFalse(started.is_set())
        self.assertTrue(self.operations.busy)
        self.assertEqual(self.operations.worker_operation, "dictionary")
        self.assertIsNone(self.operations.worker)
        self.assertIsNotNone(self.operations._pending_worker)

        self.operations.start_pending_worker()
        self.assertTrue(started.wait(timeout=1))
        self.assertTrue(self.operations.busy)
        self.assertEqual(self.consume(), ())
        release.set()
        self.operations.join_worker()

        event = self.operations.events.get_nowait()
        self.assertIsInstance(event, DictionaryOperationCompletedEvent)
        self.assertIs(event.request, request)
        self.assertEqual(event.value, "saved")
        self.assertIsNone(event.error)
        self.assertTrue(self.operations.events.empty())
        self.operations.events.put(event)
        completion = self.consume()

        self.assertEqual(
            completion,
            (
                DictionaryOperationCompletedEffect(
                    request=request,
                    value="saved",
                ),
            ),
        )
        self.assertFalse(self.operations.busy)
        self.assertEqual(self.operations.operation_completed, 1)
        self.assertIsNone(self.operations.worker_operation)
        self.assertIsNone(self.operations.worker_target)
        self.assertIsNone(self.operations._cancellation_event)
        self.assertFalse(self.operations.cancellation_requested)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_dictionary_operation_failure_is_typed_and_clears_shared_busy_state(self):
        editor = EditorState(
            kind="dictionary_english_entry",
            title="ADD ENGLISH DICTIONARY WORD",
            origin=("dictionary", None),
            selection="save",
        )
        request = DictionaryOperationRequest(
            operation="save_english",
            language="en",
            editor_snapshot=editor,
            originating_editor=editor,
        )
        error = RuntimeError("persistence failed")
        intent = DictionaryOperationIntent(
            request,
            "Saving English dictionary word…",
            lambda: (_ for _ in ()).throw(error),
        )

        self.operations.start_dictionary_operation(intent)
        self.assertEqual(
            self.operations.start_preview(
                FakeSession(),
                AudioQuery(accent_phrases=[]),
            ),
            (
                UpdateStatusEffect(
                    warning_status(
                        "Pronunciation Preview is unavailable while "
                        "a Dictionary operation is active."
                    )
                ),
            ),
        )
        self.assertEqual(
            self.operations.request_shutdown(),
            (
                UpdateStatusEffect(
                    "Finishing the current Dictionary operation before cleanup…"
                ),
            ),
        )
        self.operations.start_pending_worker()
        self.operations.join_worker()

        completion = self.consume()
        self.assertEqual(
            completion,
            (
                DictionaryOperationCompletedEffect(
                    request=request,
                    error=error,
                ),
            ),
        )
        self.assertEqual(self.operations.worker_error, error)
        self.assertFalse(self.operations.busy)
        self.assertIsNone(self.operations.worker_operation)

    def test_initial_generation_initializes_progress_and_clears_current_take(self):
        session = FakeSession()
        session.generated = (candidate(1),)
        self.operations.current_take = 3
        effects = self.operations.start_generation(
            session,
            take_count=4,
            navigation_revision=8,
        )
        self.assertEqual(effects, (UpdateStatusEffect("Generating 1/4"),))
        self.assertTrue(self.operations.busy)
        self.assertEqual(self.operations.worker_operation, "initial")
        self.assertIsNone(self.operations.worker_target)
        self.assertEqual(self.operations.operation_focus_revision, 8)
        self.assertEqual(self.operations.operation_total, 4)
        self.assertEqual(self.operations.operation_completed, 0)
        self.assertIsNone(self.operations.current_take)
        self.operations.join_worker()

    def test_regenerate_all_progress_uses_requested_take_count(self):
        session = FakeSession((candidate(1), candidate(2), candidate(3)))

        effects = self.operations.start_regenerate_all(
            session,
            take_count=100,
            navigation_revision=2,
        )

        self.assertEqual(effects, (UpdateStatusEffect("Regenerating 1/100"),))
        self.assertEqual(self.operations.operation_total, 100)
        self.operations.join_worker()
        self.consume(session)

    def test_worker_suppresses_output_and_posts_candidate_then_done(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        def values():
            print("synthesis stdout")
            print("synthesis stderr", file=sys.stderr)
            yield candidate(1)
            print("more stdout")
            print("more stderr", file=sys.stderr)

        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            self.operations.run_worker(
                values,
                "Generating 1/1",
                operation="initial",
                take_count=1,
                navigation_revision=0,
            )
            worker = self.operations.worker
            self.operations.join_worker()

        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(worker.name, "voiceger-tui-synthesis")
        self.assertTrue(worker.daemon)
        self.assertEqual(self.operations.events.get_nowait()[0], "candidate")
        self.assertEqual(self.operations.events.get_nowait(), ("done", None))

    def test_worker_posts_error_and_always_posts_done(self):
        error = RuntimeError("iterator failed")

        def values():
            yield candidate(1)
            raise error

        self.operations.run_worker(
            values,
            "Generating 1/2",
            operation="initial",
            take_count=2,
            navigation_revision=0,
        )
        self.operations.join_worker()
        self.assertEqual(self.operations.events.get_nowait()[0], "candidate")
        self.assertEqual(self.operations.events.get_nowait(), ("error", error))
        self.assertEqual(self.operations.events.get_nowait(), ("done", None))

    def test_initial_cancellation_finishes_in_flight_take_and_starts_no_next_take(self):
        session = FakeSession()
        first = candidate(1)
        synthesis_started = Event()
        finish_synthesis = Event()
        second_started = Event()

        def values():
            synthesis_started.set()
            self.assertTrue(finish_synthesis.wait(timeout=5))
            session.candidates.append(first)
            yield first
            second_started.set()
            replacement = candidate(2)
            session.candidates.append(replacement)
            yield replacement

        session.generate_takes = lambda: values()
        self.operations.start_generation(
            session,
            take_count=100,
            navigation_revision=0,
            item_id="origin",
        )
        self.assertTrue(synthesis_started.wait(timeout=5))

        self.assertEqual(
            self.operations.request_batch_cancellation(),
            (UpdateStatusEffect("Cancelling…"),),
        )
        self.assertEqual(
            self.operations.request_batch_cancellation(),
            (UpdateStatusEffect("Cancelling…"),),
        )
        finish_synthesis.set()
        self.operations.join_worker()

        effects = self.consume(session)
        self.assertIn(
            UpdateStatusEffect("Generation cancelled. 1 take(s) ready."),
            effects,
        )
        self.assertIn(
            GenerationOutcomeEffect("origin", "cancelled"),
            effects,
        )
        self.assertFalse(any(isinstance(effect, DiscardInitialBatchEffect) for effect in effects))
        self.assertEqual(session.candidates, [first])
        self.assertFalse(second_started.is_set())
        self.assertFalse(self.operations.busy)
        self.assertFalse(self.operations.cancellation_requested)
        self.assertTrue(self.operations.cancellation_guard_armed)

        self.operations.clear_completed_cancellation_guard()
        self.assertFalse(self.operations.cancellation_guard_armed)

    def test_natural_generation_completion_keeps_ctrl_c_guard_armed(self):
        session = FakeSession()
        session.generated = (candidate(1),)
        self.operations.start_generation(
            session,
            take_count=1,
            navigation_revision=0,
            item_id="origin",
        )
        self.operations.join_worker()
        effects = self.consume(session)

        self.assertIn(
            GenerationOutcomeEffect("origin", "completed"),
            effects,
        )
        self.assertTrue(self.operations.cancellation_guard_armed)

    def test_shutdown_request_cancels_batch_and_join_retries_ctrl_c(self):
        cancellation_event = Event()
        worker = Mock()
        worker.ident = 1
        worker.is_alive.side_effect = [True, True, False]
        worker.join.side_effect = [KeyboardInterrupt(), None]
        self.operations.worker = worker
        self.operations.busy = True
        self.operations.worker_operation = "initial"
        self.operations._cancellation_event = cancellation_event

        self.assertEqual(
            self.operations.request_shutdown(),
            (UpdateStatusEffect("Cancelling current batch before cleanup…"),),
        )
        self.assertTrue(cancellation_event.is_set())

        cancellation_event.clear()
        self.operations.cancellation_requested = False
        self.operations.join_worker()

        self.assertTrue(cancellation_event.is_set())
        self.assertTrue(self.operations.cancellation_requested)
        self.assertEqual(worker.join.call_count, 2)

    def test_shutdown_request_waits_for_non_cancellable_single_synthesis(self):
        self.operations.busy = True
        self.operations.worker_operation = "regenerate_one"
        self.assertEqual(
            self.operations.request_shutdown(),
            (UpdateStatusEffect("Finishing the current synthesis before cleanup…"),),
        )

    def test_initial_cancellation_before_first_take_discards_empty_batch(self):
        session = FakeSession()
        iterator_requested = Event()
        release_iterator = Event()
        synthesized = []

        class DelayedIterable:
            def __iter__(self):
                iterator_requested.set()
                self.assert_released()
                return self

            def __next__(self):
                synthesized.append(1)
                raise StopIteration

            @staticmethod
            def assert_released():
                if not release_iterator.wait(timeout=5):
                    raise AssertionError("iterator release timed out")

        session.generate_takes = lambda: DelayedIterable()
        effects = self.operations.start_generation(
            session,
            take_count=100,
            navigation_revision=0,
        )
        self.assertEqual(effects, (UpdateStatusEffect("Generating 1/100"),))
        self.assertTrue(iterator_requested.wait(timeout=5))
        self.operations.request_batch_cancellation()
        release_iterator.set()
        self.operations.join_worker()

        completed = self.consume(session)
        self.assertIn(
            UpdateStatusEffect("Generation cancelled. 0 take(s) ready."),
            completed,
        )
        self.assertIn(DiscardInitialBatchEffect(), completed)
        self.assertEqual(session.candidates, [])
        self.assertEqual(synthesized, [])

    def test_regenerate_all_cancellation_keeps_replacements_and_starts_no_next(self):
        old_first, old_second = candidate(1), candidate(2)
        session = FakeSession((old_first, old_second))
        synthesis_started = Event()
        finish_synthesis = Event()
        second_started = Event()
        replacement = candidate(1)

        def values():
            synthesis_started.set()
            self.assertTrue(finish_synthesis.wait(timeout=5))
            session.candidates[0] = replacement
            yield replacement
            second_started.set()
            session.candidates[1] = candidate(2)
            yield session.candidates[1]

        session.regenerate_all_takes = lambda: values()
        effects = self.operations.start_regenerate_all(
            session,
            take_count=100,
            navigation_revision=0,
        )
        self.assertEqual(effects, (UpdateStatusEffect("Regenerating 1/100"),))
        self.assertTrue(synthesis_started.wait(timeout=5))
        self.assertEqual(
            self.operations.request_batch_cancellation(),
            (UpdateStatusEffect("Cancelling…"),),
        )
        finish_synthesis.set()
        self.operations.join_worker()

        completed = self.consume(session)
        self.assertIn(
            UpdateStatusEffect("Regeneration cancelled after 1 replacement(s)."),
            completed,
        )
        self.assertFalse(any(isinstance(effect, DiscardInitialBatchEffect) for effect in completed))
        self.assertEqual(session.candidates, [replacement, old_second])
        self.assertFalse(second_started.is_set())
        self.assertEqual(session.discard_calls, 0)

    def test_first_initial_candidate_returns_progress_focus_and_play_effects(self):
        first = candidate(1)
        self.operations.worker_operation = "initial"
        self.operations.operation_total = 2
        self.operations.operation_focus_revision = 4
        self.operations.busy = True
        self.operations.events.put(("candidate", first))
        effects = self.consume(FakeSession((first,)), revision=4, segment=1)
        self.assertEqual(
            effects,
            (
                UpdateStatusEffect("Generating 2/2 · 1 ready"),
                FocusEffect(("candidate", 1)),
                PlayTakeEffect(1),
            ),
        )
        self.assertEqual(self.operations.operation_completed, 1)
        self.assertEqual(self.operations.current_take, 1)

    def test_first_candidate_does_not_steal_focus_after_navigation_moves(self):
        first = candidate(1)
        self.operations.worker_operation = "initial"
        self.operations.operation_total = 3
        self.operations.operation_focus_revision = 4
        self.operations.busy = True
        self.operations.events.put(("candidate", first))
        effects = self.consume(FakeSession((first,)), revision=5)
        self.assertEqual(effects, (UpdateStatusEffect("Generating 2/3 · 1 ready"),))
        self.assertIsNone(self.operations.current_take)

    def test_later_initial_candidates_only_update_progress(self):
        second = candidate(2)
        self.operations.worker_operation = "initial"
        self.operations.operation_total = 3
        self.operations.operation_completed = 1
        self.operations.current_take = 1
        self.operations.busy = True
        self.operations.events.put(("candidate", second))
        self.assertEqual(
            self.consume(FakeSession((candidate(1), second))),
            (UpdateStatusEffect("Generating 3/3 · 2 ready"),),
        )
        self.assertEqual(self.operations.current_take, 1)

    def test_single_regeneration_replays_only_current_target_replacement(self):
        replacement = candidate(2)
        self.operations.worker_operation = "regenerate_one"
        self.operations.worker_target = 2
        self.operations.current_take = 2
        self.operations.operation_total = 1
        self.operations.busy = True
        self.operations.events.put(("candidate", replacement))
        self.assertEqual(
            self.consume(FakeSession((candidate(1), replacement))),
            (
                UpdateStatusEffect("Take 2 replacement ready."),
                CandidateReplacedEffect(2),
                PlayTakeEffect(2),
            ),
        )

    def test_manual_selection_during_single_regeneration_is_retained(self):
        replacement = candidate(2)
        self.operations.worker_operation = "regenerate_one"
        self.operations.worker_target = 2
        self.operations.current_take = 1
        self.operations.operation_total = 1
        self.operations.busy = True
        self.operations.events.put(("candidate", replacement))
        effects = self.consume(FakeSession((candidate(1), replacement)))
        self.assertEqual(
            effects,
            (
                UpdateStatusEffect("Take 2 replacement ready."),
                CandidateReplacedEffect(2),
            ),
        )
        self.assertEqual(self.operations.current_take, 1)

    def test_regenerate_all_preserves_selection_and_plays_only_its_replacement(self):
        one, two, three = candidate(1), candidate(2), candidate(3)
        self.operations.worker_operation = "regenerate_all"
        self.operations.operation_total = 3
        self.operations.current_take = 2
        self.operations.busy = True
        self.operations.events.put(("candidate", one))
        self.operations.events.put(("candidate", three))
        self.assertEqual(
            self.consume(FakeSession((one, two, three))),
            (
                UpdateStatusEffect("Regenerating 2/3 · 1 ready"),
                CandidateReplacedEffect(1),
                UpdateStatusEffect("Regenerating 3/3 · 2 ready"),
                CandidateReplacedEffect(3),
            ),
        )
        self.assertEqual(self.operations.current_take, 2)
        self.operations.events.put(("candidate", two))
        self.assertEqual(
            self.consume(FakeSession((one, two, three))),
            (
                UpdateStatusEffect("Regenerating 3/3 · 3 ready"),
                CandidateReplacedEffect(2),
                PlayTakeEffect(2),
            ),
        )

    def test_initial_failure_requests_playback_stop_batch_discard_and_focus_restore(self):
        first = candidate(1)
        error = RuntimeError("second synthesis failed")
        session = FakeSession((first,))
        self.operations.worker_operation = "initial"
        self.operations.operation_total = 2
        self.operations.current_take = 1
        self.operations.busy = True
        self.operations.events.put(("candidate", first))
        self.operations.events.put(("error", error))
        self.operations.events.put(("done", None))

        effects = self.consume(session, segment=3)
        self.assertEqual(
            effects,
            (
                UpdateStatusEffect("Generating 2/2 · 1 ready"),
                FocusEffect(("candidate", 1)),
                PlayTakeEffect(1),
                UpdateStatusEffect(error_status("Generation failed: second synthesis failed")),
                StopPlaybackEffect(),
                DiscardInitialBatchEffect(),
                FocusEffect(("pronunciation", 3)),
                UpdateStatusEffect(error_status("Generation failed: second synthesis failed")),
            ),
        )
        self.assertFalse(self.operations.busy)
        self.assertIsNone(self.operations.current_take)
        self.assertEqual(self.operations.worker_error, error)
        self.assertIsNone(self.operations.worker_operation)
        self.assertIsNone(self.operations.worker_target)

    def test_regeneration_failure_preserves_batch_and_status(self):
        existing = candidate(1)
        error = RuntimeError("replacement failed")
        session = FakeSession((existing,))
        self.operations.worker_operation = "regenerate_one"
        self.operations.worker_target = 1
        self.operations.current_take = 1
        self.operations.busy = True
        self.operations.events.put(("error", error))
        self.operations.events.put(("done", None))
        self.assertEqual(
            self.consume(session),
            (
                UpdateStatusEffect(error_status("Generation failed: replacement failed")),
                UpdateStatusEffect(error_status("Generation failed: replacement failed")),
            ),
        )
        self.assertEqual(session.candidates, [existing])
        self.assertEqual(session.discard_calls, 0)
        self.assertEqual(self.operations.current_take, 1)

    def test_done_statuses_cover_successful_regeneration_empty_and_exit(self):
        self.operations.worker_operation = "initial"
        self.operations.busy = True
        self.operations.operation_completed = 2
        self.operations.events.put(("done", None))
        self.assertEqual(
            self.consume(FakeSession((candidate(1), candidate(2)))),
            (UpdateStatusEffect("2 take(s) ready."),),
        )
        self.assertFalse(self.operations.busy)
        self.assertIsNone(self.operations.worker_operation)

        self.operations.worker_operation = "regenerate_all"
        self.operations.busy = True
        self.operations.events.put(("done", None))
        self.assertEqual(
            self.consume(FakeSession()),
            (UpdateStatusEffect("Take regeneration finished."),),
        )

        self.operations.worker_operation = "initial"
        self.operations.busy = True
        self.operations.operation_completed = 0
        self.operations.events.put(("done", None))
        self.assertEqual(
            self.consume(FakeSession()),
            (UpdateStatusEffect("No takes were generated. Select Generate to try again."),),
        )

        self.operations.worker_operation = "initial"
        self.operations.busy = True
        self.operations.operation_completed = 0
        self.operations.events.put(("done", None))
        self.assertEqual(self.consume(FakeSession(), exiting=True), ())

    def test_regenerate_all_startup_failure_keeps_existing_state(self):
        session = FakeSession((candidate(1),))
        session.regenerate_all_error = RuntimeError("regeneration unavailable")
        self.operations.current_take = 1
        self.assertEqual(
            self.operations.start_regenerate_all(
                session,
                take_count=session.active_candidate_count,
                navigation_revision=2,
            ),
            (
                UpdateStatusEffect(
                    error_status(
                        "Could not regenerate all takes: regeneration unavailable"
                    )
                ),
            ),
        )
        self.assertEqual(self.operations.current_take, 1)
        self.assertFalse(self.operations.busy)

    def test_session_preparation_waits_for_status_render_then_completes(self):
        session = SimpleNamespace(
            is_prepared=False,
            prepare_from_caption=Mock(),
        )

        start = self.operations.start_session_preparation(
            session,
            rebuild=False,
        )

        self.assertEqual(
            start,
            (UpdateStatusEffect("Preparing pronunciation…"),),
        )
        self.assertTrue(self.operations.busy)
        self.assertEqual(self.operations.worker_operation, "prepare")
        session.prepare_from_caption.assert_not_called()

        self.operations.start_pending_worker()
        self.operations.join_worker()
        completion = self.consume(session)

        session.prepare_from_caption.assert_called_once_with()
        self.assertFalse(self.operations.busy)
        self.assertEqual(
            completion,
            (
                SessionPreparationCompletedEffect(
                    session=session,
                    rebuild=False,
                ),
            ),
        )

    def test_already_prepared_auto_preparation_is_a_noop(self):
        session = SimpleNamespace(
            is_prepared=True,
            prepare_from_caption=Mock(),
        )

        self.assertEqual(
            self.operations.start_session_preparation(
                session,
                rebuild=False,
            ),
            (),
        )
        self.assertFalse(self.operations.busy)
        session.prepare_from_caption.assert_not_called()


class BatchFakeSession:
    def __init__(
        self,
        name,
        log,
        *,
        existing=False,
        fail_take=None,
        block_take=None,
        blocked_event=None,
        release_event=None,
        concurrency=None,
        prepared=True,
        prepare_error=None,
    ):
        self.name = name
        self.log = log
        self.is_prepared = prepared
        self.prepare_error = prepare_error
        self.prepare_calls = 0
        self.has_active_batch = existing
        self.fail_take = fail_take
        self.block_take = block_take
        self.blocked_event = blocked_event
        self.release_event = release_event
        self.concurrency = concurrency
        self.candidates = []
        self.generate_take_counts = []
        self.regenerate_take_counts = []

    def prepare_from_caption(self):
        self.prepare_calls += 1
        self.log.append((self.name, "prepare", "done", 0))
        if self.prepare_error is not None:
            raise self.prepare_error
        self.is_prepared = True

    def generate_takes(self, *, take_count=None):
        self.generate_take_counts.append(take_count)
        self.has_active_batch = True
        return self._values(take_count, "initial")

    def regenerate_all_takes(self, *, take_count=None):
        self.regenerate_take_counts.append(take_count)
        return self._values(take_count, "regenerate")

    def _values(self, take_count, mode):
        for number in range(1, take_count + 1):
            if self.concurrency is not None:
                self.concurrency["active"] += 1
                self.concurrency["max"] = max(
                    self.concurrency["max"], self.concurrency["active"]
                )
            self.log.append((self.name, mode, "start", number))
            try:
                if number == self.block_take:
                    if self.blocked_event is not None:
                        self.blocked_event.set()
                    if self.release_event is not None:
                        self.release_event.wait(timeout=2)
                if number == self.fail_take:
                    raise RuntimeError(f"{self.name} failed at take {number}")
                item = SimpleNamespace(number=number, owner=self.name)
                self.candidates = [
                    candidate
                    for candidate in self.candidates
                    if candidate.number != number
                ]
                self.candidates.append(item)
                self.log.append((self.name, mode, "done", number))
            finally:
                if self.concurrency is not None:
                    self.concurrency["active"] -= 1
            yield item


class TuiBatchGenerationTests(unittest.TestCase):
    def make_batch(self, *items, default_take_count=2):
        return CaptionBatch(
            default_take_count=default_take_count,
            items=items,
        )

    def consume(self, operations):
        return operations.consume_pending_events(
            None,
            navigation_revision=0,
            pronunciation_index=0,
            exit_requested=False,
        )

    def test_batch_progress_snapshot_tracks_stable_operation_and_item(self):
        first = CaptionBatchItem(BatchFakeSession("first", []), item_id="first")
        second = CaptionBatchItem(BatchFakeSession("second", []), item_id="second")
        batch = self.make_batch(first, second, default_take_count=4)
        operations = TuiOperations()
        operations.busy = True
        operations.worker_operation = "batch_generate"
        operations.operation_total = 8
        operations._active_operation_id = 41
        operations._owned_item_ids = frozenset({"first", "second"})
        operations._batch_progress_item_id = "first"
        operations._batch_progress_caption_number = 1
        operations._batch_progress_caption_total = 2
        operations._batch_progress_take_number = 1
        operations._batch_progress_take_completed = 0
        operations._batch_progress_take_total = 4

        self.assertEqual(
            operations.background_operation_progress,
            BackgroundOperationProgress(
                operation_id=41,
                operation="batch_generate",
                item_id="first",
                completed=0,
                total=8,
                take_number=1,
                take_completed=0,
                take_total=4,
                caption_number=1,
                caption_total=2,
            ),
        )

        operations.events.put(
            BatchGenerationProgressEvent(
                item_id="second",
                caption_number=2,
                caption_total=2,
                take_number=2,
                take_total=4,
                overall_completed=5,
                overall_total=8,
            )
        )
        operations.consume_pending_events(
            None,
            navigation_revision=0,
            pronunciation_index=0,
            exit_requested=False,
            batch=batch,
        )

        self.assertEqual(
            operations.background_operation_progress,
            BackgroundOperationProgress(
                operation_id=41,
                operation="batch_generate",
                item_id="second",
                completed=5,
                total=8,
                take_number=2,
                take_completed=1,
                take_total=4,
                caption_number=2,
                caption_total=2,
            ),
        )
        self.assertEqual(
            operations.active_item_generation_progress,
            ("second", 1, 4),
        )

    def test_terminal_individual_generation_status_uses_source_item_identity(self):
        session = FakeSession((candidate(1), candidate(2)))
        batch = self.make_batch(CaptionBatchItem(session, item_id="origin"))
        operations = TuiOperations()
        operations.busy = True
        operations.worker_operation = "initial"
        operations._worker_item_id = "origin"
        operations._owned_item_ids = frozenset({"origin"})
        operations._active_operation_id = 9
        operations.operation_completed = 2
        operations.operation_total = 2
        operations.events.put(("done", None))

        effects = operations.consume_pending_events(
            session,
            navigation_revision=0,
            pronunciation_index=0,
            exit_requested=False,
            batch=batch,
        )

        self.assertIn(
            UpdateStatusEffect("Caption 1 generation finished. 2 take(s) ready."),
            effects,
        )
        self.assertIn(GenerationOutcomeEffect("origin", "completed"), effects)
        self.assertIsNone(operations.background_operation_progress)
        self.assertEqual(operations.owned_item_ids, frozenset())

    def test_batch_generation_prepares_unprepared_item_before_synthesis(self):
        log = []
        session = BatchFakeSession(
            "only",
            log,
            prepared=False,
        )
        batch = self.make_batch(
            CaptionBatchItem(session, item_id="only"),
            default_take_count=1,
        )
        operations = TuiOperations()

        operations.start_batch_generation(batch, navigation_revision=0)
        operations.join_worker()
        consumed = self.consume(operations)

        self.assertTrue(session.is_prepared)
        self.assertEqual(session.prepare_calls, 1)
        self.assertEqual(
            log[:2],
            [
                ("only", "prepare", "done", 0),
                ("only", "initial", "start", 1),
            ],
        )
        self.assertEqual(session.generate_take_counts, [1])
        self.assertIn(
            GenerationOutcomeEffect("only", "completed"),
            consumed,
        )
        self.assertIsNone(operations.worker_error)
        self.assertEqual(
            [
                effect.status
                for effect in consumed
                if isinstance(effect, UpdateStatusEffect)
            ][-1],
            "Batch generation finished. 1/1 take(s) ready.",
        )

    def test_batch_generation_stops_when_item_preparation_fails(self):
        log = []
        session = BatchFakeSession(
            "only",
            log,
            prepared=False,
            prepare_error=RuntimeError("g2p failed"),
        )
        batch = self.make_batch(
            CaptionBatchItem(session, item_id="only"),
            default_take_count=2,
        )
        operations = TuiOperations()

        operations.start_batch_generation(batch, navigation_revision=0)
        operations.join_worker()
        consumed = self.consume(operations)

        self.assertFalse(session.is_prepared)
        self.assertEqual(session.prepare_calls, 1)
        self.assertEqual(session.generate_take_counts, [])
        statuses = [
            effect.status
            for effect in consumed
            if isinstance(effect, UpdateStatusEffect)
        ]
        self.assertEqual(
            statuses[-1],
            error_status(
                "Batch generation failed at Caption 1/1, Take 1/2: g2p failed"
            ),
        )
        self.assertIn(
            GenerationOutcomeEffect("only", "failed"),
            consumed,
        )

    def test_selected_items_generate_caption_major_with_effective_counts(self):
        log = []
        concurrency = {"active": 0, "max": 0}
        first = BatchFakeSession("first", log, concurrency=concurrency)
        second = BatchFakeSession(
            "second", log, existing=True, concurrency=concurrency
        )
        excluded = BatchFakeSession("excluded", log, concurrency=concurrency)
        batch = self.make_batch(
            CaptionBatchItem(first, item_id="first"),
            CaptionBatchItem(
                second,
                item_id="second",
                take_count_override=3,
            ),
            CaptionBatchItem(
                excluded,
                item_id="excluded",
                included_for_generation=False,
            ),
        )
        operations = TuiOperations()

        effects = operations.start_batch_generation(
            batch, navigation_revision=0
        )
        self.assertEqual(operations.operation_total, 5)
        self.assertEqual(
            operations.owned_item_ids,
            frozenset({"first", "second"}),
        )
        self.assertIn("2 selected Caption(s), 5 take(s) total", effects[0].status)

        batch.items[0].included_for_generation = False
        batch.items[2].included_for_generation = True
        self.assertEqual(
            operations.owned_item_ids,
            frozenset({"first", "second"}),
        )

        operations.join_worker()
        consumed = self.consume(operations)
        self.assertEqual(operations.owned_item_ids, frozenset())
        starts = [
            (name, mode, number)
            for name, mode, phase, number in log
            if phase == "start"
        ]
        self.assertEqual(
            starts,
            [
                ("first", "initial", 1),
                ("first", "initial", 2),
                ("second", "regenerate", 1),
                ("second", "regenerate", 2),
                ("second", "regenerate", 3),
            ],
        )
        self.assertEqual(first.generate_take_counts, [2])
        self.assertEqual(second.regenerate_take_counts, [3])
        self.assertEqual(excluded.generate_take_counts, [])
        self.assertEqual(concurrency["max"], 1)
        self.assertEqual(
            [(item.number, item.owner) for item in first.candidates],
            [(1, "first"), (2, "first")],
        )
        self.assertEqual(
            [(item.number, item.owner) for item in second.candidates],
            [(1, "second"), (2, "second"), (3, "second")],
        )
        statuses = [
            effect.status
            for effect in consumed
            if isinstance(effect, UpdateStatusEffect)
        ]
        self.assertIn(
            "Caption 2/2 · Take 3/3 · Overall 5/5",
            statuses,
        )
        self.assertEqual(
            statuses[-1],
            "Batch generation finished. 5/5 take(s) ready.",
        )
        replacements = [
            effect
            for effect in consumed
            if isinstance(effect, BatchCandidateReplacedEffect)
        ]
        self.assertEqual(
            replacements,
            [
                BatchCandidateReplacedEffect("second", 1),
                BatchCandidateReplacedEffect("second", 2),
                BatchCandidateReplacedEffect("second", 3),
            ],
        )

    def test_failed_replacement_reports_only_completed_candidate_replacements(self):
        log = []
        session = BatchFakeSession("only", log, existing=True, fail_take=2)
        batch = self.make_batch(
            CaptionBatchItem(session, item_id="only"),
            default_take_count=3,
        )
        operations = TuiOperations()

        operations.start_batch_generation(batch, navigation_revision=0)
        operations.join_worker()
        consumed = self.consume(operations)

        replacements = [
            effect
            for effect in consumed
            if isinstance(effect, BatchCandidateReplacedEffect)
        ]
        self.assertEqual(
            replacements,
            [BatchCandidateReplacedEffect("only", 1)],
        )

    def test_zero_selection_does_not_start_worker(self):
        session = BatchFakeSession("only", [])
        batch = self.make_batch(
            CaptionBatchItem(
                session,
                item_id="only",
                included_for_generation=False,
            )
        )
        operations = TuiOperations()

        self.assertEqual(
            operations.start_batch_generation(
                batch, navigation_revision=0
            ),
            (
                UpdateStatusEffect(
                    "Select at least one Caption before generating."
                ),
            ),
        )
        self.assertFalse(operations.busy)
        self.assertIsNone(operations.worker)
        self.assertEqual(session.generate_take_counts, [])

    def test_cancellation_waits_for_inflight_take_and_retains_completed_candidates(self):
        log = []
        blocked = Event()
        release = Event()
        session = BatchFakeSession(
            "only",
            log,
            block_take=2,
            blocked_event=blocked,
            release_event=release,
        )
        batch = self.make_batch(
            CaptionBatchItem(session, item_id="only"),
            default_take_count=3,
        )
        operations = TuiOperations()

        operations.start_batch_generation(batch, navigation_revision=0)
        self.assertTrue(blocked.wait(timeout=2))
        self.assertTrue(operations.can_cancel_batch)
        effects = operations.request_batch_cancellation()
        self.assertEqual(effects, (UpdateStatusEffect("Cancelling…"),))
        self.assertTrue(operations.worker_is_alive())

        release.set()
        operations.join_worker()
        consumed = self.consume(operations)

        self.assertEqual(
            [(item.number, item.owner) for item in session.candidates],
            [(1, "only"), (2, "only")],
        )
        self.assertNotIn(("only", "initial", "start", 3), log)
        statuses = [
            effect.status
            for effect in consumed
            if isinstance(effect, UpdateStatusEffect)
        ]
        self.assertEqual(
            statuses[-1],
            "Batch generation cancelled. 2/3 take(s) ready.",
        )
        self.assertIn(
            GenerationOutcomeEffect("only", "cancelled"),
            consumed,
        )
        self.assertFalse(operations.busy)
        self.assertEqual(operations.owned_item_ids, frozenset())

    def test_failure_preserves_item_specific_candidate_ownership_and_stops_later_items(self):
        log = []
        first = BatchFakeSession("first", log)
        failing = BatchFakeSession("failing", log, fail_take=2)
        later = BatchFakeSession("later", log)
        batch = self.make_batch(
            CaptionBatchItem(first, item_id="first"),
            CaptionBatchItem(failing, item_id="failing"),
            CaptionBatchItem(later, item_id="later"),
        )
        operations = TuiOperations()

        operations.start_batch_generation(batch, navigation_revision=0)
        operations.join_worker()
        consumed = self.consume(operations)

        self.assertEqual(
            [(item.number, item.owner) for item in first.candidates],
            [(1, "first"), (2, "first")],
        )
        self.assertEqual(
            [(item.number, item.owner) for item in failing.candidates],
            [(1, "failing")],
        )
        self.assertEqual(later.candidates, [])
        self.assertEqual(later.generate_take_counts, [])
        statuses = [
            effect.status
            for effect in consumed
            if isinstance(effect, UpdateStatusEffect)
        ]
        self.assertEqual(
            statuses[-1],
            "Batch generation failed at Caption 2/3, "
            "Take 2/2: failing failed at take 2",
        )
        self.assertIs(statuses[-1].kind, StatusKind.ERROR)
        outcomes = [
            effect
            for effect in consumed
            if isinstance(effect, GenerationOutcomeEffect)
        ]
        self.assertEqual(
            outcomes,
            [
                GenerationOutcomeEffect("first", "completed"),
                GenerationOutcomeEffect("failing", "failed"),
            ],
        )
        self.assertEqual(operations.operation_completed, 3)
        self.assertFalse(operations.busy)
        self.assertEqual(operations.owned_item_ids, frozenset())


if __name__ == "__main__":
    unittest.main()
