"""Deferred Take-acceptance and completion/status regression tests."""

from pathlib import Path
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from voiceger_editor.tui_operations import TakeAcceptedEffect, TuiOperations, UpdateStatusEffect
from voiceger_editor.tui_status import StatusKind, error_status, warning_status
from tests.tui_operation_test_support import FakeSession, candidate


class TuiTakeAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.operations = TuiOperations()

    def consume(self, session=None):
        return self.operations.consume_pending_events(
            session,
            navigation_revision=0,
            pronunciation_index=0,
            exit_requested=False,
        )

    def test_candidate_acceptance_waits_for_status_render_then_completes(self):
        session = FakeSession((candidate(3),))
        process = Mock()
        process.poll.return_value = None
        self.operations.playback_process = process
        self.operations.current_take = 3
        started = Event()
        release = Event()
        original_accept = session.accept_take

        def blocking_accept(number):
            started.set()
            if not release.wait(timeout=1):
                raise RuntimeError("test release timeout")
            return original_accept(number)

        session.accept_take = blocking_accept

        effects = self.operations.accept_take(
            session,
            3,
            item_id="item-1",
            pronunciation_index=2,
        )

        self.assertEqual(effects, (UpdateStatusEffect("Saving Take 3…"),))
        self.assertEqual(session.accept_calls, [])
        self.assertTrue(self.operations.busy)
        self.assertEqual(self.operations.worker_operation, "accept")
        self.assertEqual(self.operations.current_take, 3)
        self.assertIsNone(self.operations.playback_process)
        self.assertFalse(started.is_set())
        process.terminate.assert_called_once_with()

        self.operations.start_pending_worker()
        self.assertTrue(started.wait(timeout=1))
        self.assertEqual(self.consume(session), ())
        self.assertTrue(self.operations.busy)

        release.set()
        self.operations.join_worker()
        completion = self.consume(session)

        self.assertEqual(session.accept_calls, [3])
        self.assertFalse(self.operations.busy)
        self.assertEqual(self.operations.current_take, None)
        self.assertEqual(
            completion,
            (
                TakeAcceptedEffect("item-1", 3),
                UpdateStatusEffect("Saved saved.wav and saved.txt."),
            ),
        )

    def test_candidate_acceptance_reports_wav_lab_and_nonfatal_warning(self):
        session = FakeSession((candidate(3),))
        session.accepted = SimpleNamespace(
            wav_path=Path("/tmp/saved.wav"),
            text_path=None,
        )
        start = self.operations.accept_take(
            session,
            3,
            item_id="wav-item",
            pronunciation_index=0,
        )
        self.assertEqual(start, (UpdateStatusEffect("Saving Take 3…"),))
        self.operations.start_pending_worker()
        self.operations.join_worker()
        effects = self.consume(session)
        self.assertEqual(
            effects,
            (
                TakeAcceptedEffect("wav-item", 3),
                UpdateStatusEffect("Saved saved.wav."),
            ),
        )

        session = FakeSession((candidate(3),))
        session.accepted = SimpleNamespace(
            wav_path=Path("/tmp/saved.wav"),
            text_path=None,
            lab_path=Path("/tmp/saved.lab"),
            lab_warning=None,
        )
        self.operations.accept_take(
            session,
            3,
            item_id="lab-item",
            pronunciation_index=0,
        )
        self.operations.start_pending_worker()
        self.operations.join_worker()
        effects = self.consume(session)
        self.assertEqual(
            effects[-1],
            UpdateStatusEffect("Saved saved.wav and saved.lab."),
        )

        session = FakeSession((candidate(3),))
        session.accepted = SimpleNamespace(
            wav_path=Path("/tmp/saved.wav"),
            text_path=None,
            lab_path=None,
            lab_warning="LAB generation failed: Julius executable not found",
        )
        self.operations.accept_take(
            session,
            3,
            item_id="warning-item",
            pronunciation_index=0,
        )
        self.operations.start_pending_worker()
        self.operations.join_worker()
        effects = self.consume(session)
        self.assertEqual(
            effects[-1],
            UpdateStatusEffect(
                warning_status(
                    "Saved saved.wav. "
                    "LAB generation failed: Julius executable not found"
                )
            ),
        )
        self.assertIs(effects[-1].status.kind, StatusKind.WARNING)

    def test_candidate_acceptance_failure_preserves_candidate_and_state(self):
        original = candidate(3)
        session = FakeSession((original,))
        session.accept_error = RuntimeError("save failed")
        self.operations.current_take = 3

        start = self.operations.accept_take(
            session,
            3,
            item_id="item-1",
            pronunciation_index=0,
        )
        self.assertEqual(start, (UpdateStatusEffect("Saving Take 3…"),))
        self.assertEqual(session.accept_calls, [])

        self.operations.start_pending_worker()
        self.operations.join_worker()
        effects = self.consume(session)

        self.assertEqual(
            effects,
            (
                UpdateStatusEffect(
                    error_status("Take 3 was not saved: save failed")
                ),
            ),
        )
        self.assertFalse(self.operations.busy)
        self.assertEqual(self.operations.current_take, 3)
        self.assertEqual(session.candidates, [original])

        session.accept_calls.clear()
        self.operations.busy = True
        self.operations.worker_operation = "initial"
        blocked = self.operations.accept_take(
            session,
            3,
            item_id="item-1",
            pronunciation_index=0,
        )
        self.assertEqual(len(blocked), 1)
        self.assertIn("Save Take 3 is unavailable", str(blocked[0].status))
        self.assertEqual(session.accept_calls, [])
        self.operations.busy = False
        self.operations.worker_operation = None


if __name__ == "__main__":
    unittest.main()
