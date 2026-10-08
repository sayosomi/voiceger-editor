import curses
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from voiceger_editor.caption_batch import CaptionBatchItem
from voiceger_editor.openjtalk_dictionary import expand_word_type, normalize_surface
from voiceger_editor.pronunciation import parse_pronunciation
from voiceger_editor.settings import Settings
from voiceger_editor.terms_acceptance import (
    ACCEPTANCE_COMMAND,
    OFFICIAL_TERMS_URL,
    TermsAcceptanceStatus,
    VoicegerTermsAcceptanceError,
)
from voiceger_editor.tui_editors import (
    OpenDictionaryIntent,
    PreviewIntent,
    ReplaceQueryIntent,
)
from voiceger_editor.tui_input import PasteText
from voiceger_editor.tui_operations import (
    BatchCandidateReplacedEffect,
    CandidateReplacedEffect,
    DiscardInitialBatchEffect,
    PlayPreviewEffect,
)
from voiceger_editor.tui_status import EMPTY_STATUS, StatusKind, error_status, info_status, warning_status
from voiceger_editor.tui import TuiApp, main
from voiceger_editor.user_dictionary import JapaneseWordType
from voiceger_editor.voicevox_api_models import (
    AccentPhrase,
    AudioQuery,
    Mora,
    VoicegerSegment,
)


from tests.tui_app_test_support import (
    TuiAppTestCase,
    FakeScreen,
    candidate,
    editor_document,
    english_grouping,
    english_query,
    focus_candidate,
    japanese_query,
    mixed_query,
    navigation_document,
    navigation_items,
    set_navigation_focus,
)

class TuiBatchIntegrationTests(TuiAppTestCase):
    def test_other_batch_item_shows_busy_generate_and_explains_owner(self):
        app = self.make_app(query=mixed_query())
        first_item_id = app._batch.open_item_id
        second = FakeSession(query=mixed_query())
        second.caption = "second caption"
        app._batch.batch.add_item(CaptionBatchItem(second))
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._worker_item_id = first_item_id
        app._operations.operation_completed = 2
        app._operations.operation_total = 4
        app._operations._cancellation_event = Event()

        app._handle_key("\x1b")
        app._batch.focus_key = ("caption", 1)
        app._handle_key("\n")
        app._screen = FakeScreen(rows=24, columns=100)
        app._render()

        rendered = self.rendered(app._screen)
        self.assertIn("Generate < 4 > takes [busy]", rendered)
        self.assertNotIn("Generating 3/4", rendered)

        app._handle_key("g")
        self.assertEqual(
            app._status,
            "Generate Caption 2 is unavailable while generation is active.",
        )
        self.assertIs(app._status.kind, StatusKind.WARNING)
        self.assertEqual(app._operations._worker_item_id, first_item_id)

    def test_generation_progress_does_not_overwrite_conflict_status(self):
        app = self.make_app(query=mixed_query())
        item_id = app._batch.open_item_id
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._worker_item_id = item_id
        app._operations._active_operation_id = 1
        app._operations.operation_completed = 2
        app._operations.operation_total = 4
        app._operations._cancellation_event = Event()
        app._status = warning_status(
            "Generate selected is unavailable while generation is active."
        )

        app._operations.events.put(("candidate", candidate(3)))
        app._consume_events()

        self.assertEqual(
            app._status,
            "Generate selected is unavailable while generation is active.",
        )
        self.assertIs(app._status.kind, StatusKind.WARNING)

        app._screen = FakeScreen(rows=24, columns=100)
        app._render()
        rendered = self.rendered(app._screen)
        self.assertIn(
            "Generating · Caption 1 · Take 4/4 · [Ctrl+C] Cancel generation",
            rendered,
        )
        self.assertIn(
            "Warning: Generate selected is unavailable while generation is active.",
            rendered,
        )

    def test_batch_list_generate_selected_shows_busy_and_explains_owner(self):
        app = self.make_app(query=mixed_query())
        first_item_id = app._batch.open_item_id
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._worker_item_id = first_item_id
        app._operations.operation_completed = 2
        app._operations.operation_total = 4
        app._operations._cancellation_event = Event()

        app._handle_key("\x1b")
        app._screen = FakeScreen(rows=24, columns=100)
        app._render()

        self.assertIn("[G] Generate selected [busy]", self.rendered(app._screen))

        app._handle_key("g")
        self.assertEqual(
            app._status,
            "Generate selected is unavailable while generation is active.",
        )
        self.assertIs(app._status.kind, StatusKind.WARNING)
        self.assertEqual(app._operations._worker_item_id, first_item_id)

    def test_regenerate_all_cannot_replace_an_active_generation_worker(self):
        app = self.make_app(query=mixed_query())
        item_id = app._batch.open_item_id
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._worker_item_id = item_id
        app._operations.operation_completed = 1
        app._operations.operation_total = 4
        original_worker = app._operations.worker
        app.session.regenerate_all_takes = Mock(
            side_effect=AssertionError("must not start a second synthesis")
        )

        effects = app._operations.start_regenerate_all(
            app.session,
            take_count=4,
            navigation_revision=app._navigation.revision,
            item_id=item_id,
        )

        self.assertEqual(
            str(effects[0].status),
            "Regenerate all Takes is unavailable while Take generation is active.",
        )
        self.assertIs(app._operations.worker, original_worker)
        app.session.regenerate_all_takes.assert_not_called()

    def test_clear_candidates_confirmation_cancel_and_confirmed_clear(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1), candidate(2)))
        app._operations.current_take = 2
        item = app._batch.batch.items[0]
        app._batch.batch.mark_accepted(item.item_id, 2)
        query_before = app.session.query.model_dump()
        settings_before = app.settings
        caption_before = app.session.caption
        candidates_before = app.session.candidates
        stop_playback = Mock()
        app._operations.stop_playback = stop_playback

        app._handle_key("c")
        self.assertEqual(
            app._editor_controller.editor.kind,
            "clear_candidates_confirmation",
        )
        app._handle_key("\x1b")
        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(app.session.candidates, candidates_before)
        self.assertEqual(app.session.discard_calls, 0)
        self.assertEqual(app._operations.current_take, 2)
        self.assertTrue(item.is_accepted)

        app._handle_key("c")
        app._handle_key("c")

        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(app.session.discard_calls, 1)
        self.assertEqual(app.session.candidates, ())
        self.assertIsNone(app._operations.current_take)
        self.assertFalse(item.is_accepted)
        self.assertEqual(app.session.caption, caption_before)
        self.assertEqual(app.session.query.model_dump(), query_before)
        self.assertEqual(app.settings, settings_before)
        self.assertEqual(stop_playback.call_count, 1)
        self.assertEqual(app._status, "Candidates cleared.")

    def test_clear_candidates_is_blocked_for_operation_owned_caption(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        item_id = app._batch.open_item_id
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._owned_item_ids = frozenset({item_id})

        app._handle_key("c")

        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(app.session.candidates, (candidate(1),))
        self.assertEqual(app.session.discard_calls, 0)
        self.assertIn("currently generating", app._status)
        self.assertIn("clearing candidates", app._status)
