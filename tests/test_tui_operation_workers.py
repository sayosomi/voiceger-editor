"""Focused worker-builder event ordering, error and cancellation coverage."""

from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from voiceger_editor.tui_operation_contracts import (
    BatchCandidateReadyEvent,
    BatchGenerationCancelledEvent,
    BatchGenerationFailedEvent,
    BatchGenerationProgressEvent,
    DictionaryOperationCompletedEvent,
    PreviewFailedEvent,
    PreviewReadyEvent,
    SessionPreparationCompletedEvent,
)
from voiceger_editor.tui_operation_workers import (
    make_batch_generation_work,
    make_dictionary_work,
    make_generation_work,
    make_preparation_work,
    make_preview_work,
)


class TuiOperationWorkerTests(unittest.TestCase):
    def test_individual_generation_emits_candidates_then_done(self):
        events = []
        values = [SimpleNamespace(number=1), SimpleNamespace(number=2)]
        work = make_generation_work(lambda: iter(values), cancellation_event=Event(), emit_event=events.append)
        work()
        self.assertEqual(events, [("candidate", values[0]), ("candidate", values[1]), ("done", None)])

    def test_individual_generation_cancellation_before_next_take(self):
        events = []
        cancel = Event()

        def emit(event):
            events.append(event)
            if event[0] == "candidate":
                cancel.set()

        make_generation_work(lambda: iter((1, 2)), cancellation_event=cancel, emit_event=emit)()
        self.assertEqual(events, [("candidate", 1), ("done", None)])

    def test_individual_generation_error_always_ends_with_done(self):
        events = []

        def failing_values():
            raise RuntimeError("generator failed")

        make_generation_work(failing_values, cancellation_event=Event(), emit_event=events.append)()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0][0], "error")
        self.assertEqual(str(events[0][1]), "generator failed")
        self.assertEqual(events[-1], ("done", None))

    def test_batch_generation_emits_typed_progress_and_candidate_events(self):
        events = []
        session = SimpleNamespace(
            is_prepared=True,
            has_active_batch=False,
            generate_takes=Mock(return_value=iter((object(), object()))),
        )
        item = SimpleNamespace(item_id="item-1", session=session)
        make_batch_generation_work(((item, 2),), overall_total=2, cancellation_event=Event(), emit_event=events.append)()
        self.assertEqual([type(event) for event in events[:-1]], [
            BatchGenerationProgressEvent, BatchCandidateReadyEvent,
            BatchGenerationProgressEvent, BatchCandidateReadyEvent,
        ])
        self.assertEqual(events[1].item_id, "item-1")
        self.assertEqual(events[1].overall_completed, 1)
        self.assertEqual(events[3].overall_completed, 2)
        self.assertEqual(events[-1], ("done", None))
        session.generate_takes.assert_called_once_with(take_count=2)

    def test_batch_cancels_after_inflight_take_and_emits_done(self):
        events = []
        cancel = Event()
        session = SimpleNamespace(
            is_prepared=True,
            has_active_batch=False,
            generate_takes=lambda **_kwargs: iter((1, 2)),
        )
        item = SimpleNamespace(item_id="one", session=session)

        def emit(event):
            events.append(event)
            if isinstance(event, BatchCandidateReadyEvent):
                cancel.set()

        make_batch_generation_work(((item, 2),), overall_total=2, cancellation_event=cancel, emit_event=emit)()
        self.assertEqual([type(event) for event in events[:-1]], [
            BatchGenerationProgressEvent, BatchCandidateReadyEvent,
            BatchGenerationCancelledEvent,
        ])
        self.assertEqual(events[-1], ("done", None))

    def test_batch_preparation_failure_reports_typed_event_then_done(self):
        events = []
        session = SimpleNamespace(
            is_prepared=False,
            prepare_from_caption=Mock(side_effect=ValueError("bad Caption")),
        )
        item = SimpleNamespace(item_id="bad", session=session)
        make_batch_generation_work(((item, 2),), overall_total=2, cancellation_event=Event(), emit_event=events.append)()
        self.assertIsInstance(events[0], BatchGenerationFailedEvent)
        self.assertEqual(events[0].item_id, "bad")
        self.assertEqual(str(events[0].error), "bad Caption")
        self.assertEqual(events[-1], ("done", None))

    def test_preview_returns_typed_ready_or_failure_followed_by_done(self):
        events = []
        query = object()
        session = SimpleNamespace(preview_synthesis=Mock(return_value={"audio": "wave", "sampling_rate": 24000}))
        make_preview_work(session, query, emit_event=events.append)()
        session.preview_synthesis.assert_called_once_with(query)
        self.assertEqual(events, [PreviewReadyEvent("wave", 24000), ("done", None)])

        events.clear()
        session.preview_synthesis.side_effect = RuntimeError("preview unavailable")
        make_preview_work(session, query, emit_event=events.append)()
        self.assertIsInstance(events[0], PreviewFailedEvent)
        self.assertEqual(str(events[0].error), "preview unavailable")
        self.assertEqual(events[-1], ("done", None))

    def test_preparation_reports_completion_without_generating_done_event(self):
        events = []
        session = SimpleNamespace(prepare_from_caption=Mock())
        make_preparation_work(session, rebuild=True, emit_event=events.append)()
        self.assertEqual(events, [SessionPreparationCompletedEvent(session, True)])
        session.prepare_from_caption.side_effect = RuntimeError("prepare failed")
        make_preparation_work(session, rebuild=False, emit_event=events.append)()
        self.assertEqual(len(events), 2)
        self.assertIsInstance(events[1], SessionPreparationCompletedEvent)
        self.assertEqual(str(events[1].error), "prepare failed")

    def test_dictionary_reports_completion_without_generating_done_event(self):
        events = []
        request = object()
        intent = SimpleNamespace(request=request, work=Mock(return_value="saved"))
        make_dictionary_work(intent, emit_event=events.append)()
        self.assertEqual(events, [DictionaryOperationCompletedEvent(request, value="saved")])
        intent.work.side_effect = RuntimeError("dictionary failed")
        make_dictionary_work(intent, emit_event=events.append)()
        self.assertEqual(len(events), 2)
        self.assertIsInstance(events[1], DictionaryOperationCompletedEvent)
        self.assertEqual(str(events[1].error), "dictionary failed")


if __name__ == "__main__":
    unittest.main()
