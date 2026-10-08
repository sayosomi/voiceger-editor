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

class TuiBatchItemIntegrationTests(TuiAppTestCase):
    def test_candidate_regeneration_uses_only_focused_candidate(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        app._operations.current_take = 1
        app._operations.start_regeneration = Mock(return_value=())
        set_navigation_focus(app, ("generate", None))
        app._handle_key("r")
        app._operations.start_regeneration.assert_not_called()
        self.assertEqual(app._status, "Select a candidate before regenerating it.")

        app.session.candidates = (candidate(1), candidate(2))
        app._operations.play_take = Mock(return_value=())
        focus_candidate(app, 2)
        navigation_revision = app._navigation.revision
        app._handle_key("r")
        app._operations.start_regeneration.assert_called_once_with(
            app.session,
            2,
            take_count=app.settings.take_count,
            navigation_revision=navigation_revision,
            item_id=app._batch.open_item_id,
        )

    def test_busy_candidate_remains_playable_without_inline_unavailable_cues(self):
        app = self.make_app(candidates=(candidate(1), candidate(2)))
        app._operations.play_take = Mock(return_value=())
        app._operations.busy = True
        focus_candidate(app, 1)
        app._handle_key(curses.KEY_DOWN)
        self.assertEqual(app._navigation.focus_key, ("candidate", 2))
        app._handle_key(" ")
        self.assertEqual(
            app._operations.play_take.call_args_list,
            [call(app.session, 1), call(app.session, 2), call(app.session, 2)],
        )

        screen = FakeScreen()
        app._screen = screen
        app._render()
        rendered = self.rendered(screen)
        self.assertIn("Take 2", rendered)
        self.assertNotIn("unavailable while generating", rendered)
        self.assertNotIn("Enter unavailable", rendered)
        self.assertNotIn("Enter accepts and saves", rendered)
        self.assertNotIn("↑↓ Move/play", rendered)
        self.assertNotIn("↑/↓ Move", rendered)
        self.assertNotIn("? Help", rendered)
        self.assertNotIn(23, [row for row, _column, _text, _attr in screen.drawn])

    def test_enter_on_candidate_accepts_and_saves_when_not_busy(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        session = app.session
        item = app._batch.batch.items[0]
        app._operations.play_take = Mock(return_value=())
        focus_candidate(app, 1)

        app._handle_key("\n")

        self.assertEqual(session.accept_calls, [])
        self.assertFalse(item.is_accepted)
        self.assertIn("Saving Take 1…", app._status)

        app._operations.start_pending_worker()
        app._operations.join_worker()
        app._consume_events()

        self.assertEqual(session.accept_calls, [1])
        self.assertTrue(item.is_accepted)
        self.assertEqual(item.accepted_take_number, 1)
        self.assertEqual([item.number for item in session.candidates], [1])
        self.assertTrue(app._batch.in_item)
        self.assertIs(app.session, session)
        self.assertEqual(app._navigation.focus_key, ("candidate", 1))

    def test_primary_batch_item_shortcuts_activate_settled_visible_actions(self):
        caption = self.make_app(query=mixed_query())
        caption._handle_key("e")
        self.assertEqual(caption._editor_controller.editor.kind, "caption")

        build = self.make_app(query=mixed_query())
        build._batch_item_controller.request_build_pronunciation = Mock()
        build._handle_key("p")
        build._batch_item_controller.request_build_pronunciation.assert_called_once_with(
            build._batch_item_bindings
        )

        add = self.make_app(query=mixed_query())
        add._handle_key("a")
        self.assertEqual(add._editor_controller.editor.kind, "add_section")

        generate = self.make_app(query=mixed_query())
        generate._operations.start_generation = Mock(return_value=())
        generate._handle_key("g")
        generate._operations.start_generation.assert_called_once_with(
            generate.session,
            take_count=generate.settings.take_count,
            navigation_revision=generate._navigation.revision,
            item_id=generate._batch.open_item_id,
        )

        regenerate = self.make_app(
            query=mixed_query(), candidates=(candidate(1),)
        )
        regenerate._operations.start_regenerate_all = Mock(return_value=())
        regenerate._handle_key("g")
        regenerate._operations.start_regenerate_all.assert_called_once_with(
            regenerate.session,
            take_count=regenerate.settings.take_count,
            navigation_revision=regenerate._navigation.revision,
            item_id=regenerate._batch.open_item_id,
        )

        output = self.make_app(query=mixed_query())
        output._handle_key("f")
        self.assertIsNone(output._editor_controller.editor)
        self.assertTrue(output._output_path_controller.active)
        self.assertEqual(output._output_path_controller.state.owner, "batch_item")

        for removed in (
            curses.KEY_F5, "\x07", "R", "b", "t", "v", "n", "x", "l"
        ):
            with self.subTest(removed=removed):
                legacy = self.make_app(query=mixed_query())
                legacy._operations.start_generation = Mock(return_value=())
                legacy._operations.start_regenerate_all = Mock(return_value=())
                legacy._handle_key(removed)
                legacy._operations.start_generation.assert_not_called()
                legacy._operations.start_regenerate_all.assert_not_called()
                self.assertIsNone(legacy._editor_controller.editor)

    def test_batch_item_shortcuts_open_shared_actions_and_candidate_regeneration(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        app._handle_key("e")
        self.assertEqual(app._editor_controller.editor.kind, "caption")
        app._handle_key("\x1b")
        app._handle_key("s")
        self.assertEqual(app._editor_controller.editor.kind, "settings")
        self.assertEqual(app._editor_controller.editor.selection, "style_id")
        app._handle_key("\x1b")
        app._operations.play_take = Mock(return_value=())
        focus_candidate(app, 1)
        navigation_revision = app._navigation.revision
        app._operations.start_regeneration = Mock(return_value=())
        app._handle_key("r")
        app._operations.start_regeneration.assert_called_once_with(
            app.session,
            1,
            take_count=app.settings.take_count,
            navigation_revision=navigation_revision,
            item_id=app._batch.open_item_id,
        )

        help_shortcut = self.make_app(query=mixed_query())
        help_shortcut._handle_key("?")
        self.assertTrue(help_shortcut._help_open)

        quit_shortcut = self.make_app(query=mixed_query())
        quit_shortcut._handle_key("q")
        self.assertTrue(quit_shortcut._exit_requested)
