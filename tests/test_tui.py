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
    FakeSession,
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


class TuiTests(TuiAppTestCase):
    def test_top_settings_and_output_rows_are_selectable_and_focused(self):
        app = self.make_app(query=mixed_query())
        screen = FakeScreen()
        app._screen = screen

        set_navigation_focus(app, ("settings_summary", None))
        app._render()
        summary = next(item for item in screen.drawn if item[0] == 1)
        self.assertTrue(summary[2].startswith("▶ "))
        self.assertIn(" | 1.00x | Takes 4 | TXT OFF | LAB OFF", summary[2])
        self.assertTrue(summary[3] & curses.A_REVERSE)

        set_navigation_focus(app, ("output", None))
        app._render()
        output = next(item for item in screen.drawn if item[0] == 2)
        self.assertTrue(output[2].startswith("▶ [F] Output:"))
        self.assertTrue(output[3] & curses.A_REVERSE)
        self.assertIn(("settings", None), navigation_items(app))
        self.assertEqual(
            navigation_items(app)[-4:],
            [
                ("settings", None),
                ("dictionary", None),
                ("help", None),
                ("quit", None),
            ],
        )

    def test_main_dictionary_shortcut_opens_dictionary_menu(self):
        app = self.make_app(query=mixed_query())

        app._handle_key("d")

        self.assertTrue(app._dictionary_controller.active)
        self.assertEqual(app._dictionary_controller.editor.kind, "dictionary_menu")
        self.assertIsNone(app._editor_controller.editor)

    def test_export_output_edits_shared_setting_without_leaving_export(self):
        app = self.make_app(query=mixed_query())

        app._handle_key("d")
        app._handle_key("x")
        export_editor = app._dictionary_controller.editor
        self.assertEqual(export_editor.kind, "dictionary_export")

        app._handle_key("f")
        self.assertIs(app._dictionary_controller.editor, export_editor)
        self.assertTrue(app._output_path_controller.active)
        self.assertEqual(
            app._output_path_controller.state.owner,
            "dictionary_export",
        )
        self.assertIsNone(app._editor_controller.editor)

        app._handle_key("\x1b")
        self.assertFalse(app._output_path_controller.active)
        self.assertIs(app._dictionary_controller.editor, export_editor)

        app._handle_key("f")
        app._output_path_controller.state.value = "/tmp/shared-output"
        app._output_path_controller.state.cursor = len("/tmp/shared-output")
        with patch("voiceger_editor.tui.save_settings") as save:
            app._handle_key("\n")
        save.assert_called_once()
        self.assertFalse(app._output_path_controller.active)
        self.assertEqual(app.settings.output_dir, Path("/tmp/shared-output"))
        self.assertIs(app._dictionary_controller.editor, export_editor)
        self.assertEqual(export_editor.selection, "output")

    def test_export_output_edit_remains_available_during_generation(self):
        app = self.make_app(query=mixed_query())
        app._handle_key("d")
        app._handle_key("x")
        export_editor = app._dictionary_controller.editor
        app._operations.busy = True
        app._operations.worker_operation = "initial"

        app._handle_key("f")

        self.assertIs(app._dictionary_controller.editor, export_editor)
        self.assertTrue(app._output_path_controller.active)
        self.assertEqual(
            app._output_path_controller.state.owner,
            "dictionary_export",
        )

    def test_pronunciation_editor_dictionary_actions_preserve_editor_state(self):
        app = self.make_app(query=mixed_query())
        app._edit_selected_pronunciation(0)
        pronunciation_editor = app._editor_controller.editor
        self.assertEqual(pronunciation_editor.kind, "japanese")
        app._handle_key("\n")
        opening_draft = pronunciation_editor.input_value

        app._handle_key("s")

        self.assertEqual(
            app._dictionary_controller.editor.kind,
            "dictionary_japanese_entry",
        )
        self.assertEqual(
            app._dictionary_controller.editor.payload["surface"],
            "雨",
        )
        self.assertEqual(
            app._dictionary_controller.editor.payload["pronunciation"],
            "ア",
        )
        self.assertIs(app._editor_controller.editor, pronunciation_editor)
        self.assertEqual(pronunciation_editor.input_value, opening_draft)

        app._handle_key("s")

        self.assertIn("Saving Japanese dictionary word…", app._status)
        self.assertTrue(app._dictionary_controller.active)
        app.adapter.user_dictionary.add_japanese_word.assert_not_called()
        self.complete_dictionary_operation(app)

        app.adapter.user_dictionary.add_japanese_word.assert_called_once()
        self.assertFalse(app._dictionary_controller.active)
        self.assertEqual(app._status, "Japanese dictionary word saved.")
        self.assertIs(app._editor_controller.editor, pronunciation_editor)
        self.assertEqual(pronunciation_editor.input_value, opening_draft)
        self.assertEqual(app.session.replace_query_calls, [])
        self.assertEqual(app.session.build_calls, 0)

        app._handle_key("d")
        self.assertEqual(
            app._dictionary_controller.editor.kind,
            "dictionary_menu",
        )
        self.assertIs(app._editor_controller.editor, pronunciation_editor)

    def test_english_pronunciation_editor_save_prefills_dictionary_entry(self):
        app = self.make_app(
            query=english_query(["R", "EH1", "K", "ER0", "D"], text="record"),
            groups=(("record", ("R", "EH1", "K", "ER0", "D")),),
        )
        set_navigation_focus(app, ("pronunciation", 0))
        app._handle_key("\n")
        pronunciation_editor = app._editor_controller.editor
        self.assertEqual(pronunciation_editor.kind, "english_word")
        app._handle_key("\n")

        app._handle_key("s")

        dictionary_editor = app._dictionary_controller.editor
        self.assertEqual(dictionary_editor.kind, "dictionary_english_entry")
        self.assertEqual(dictionary_editor.payload["surface"], "record")
        self.assertEqual(
            dictionary_editor.payload["phonemes"],
            ("R", "EH1", "K", "ER0", "D"),
        )
        self.assertIs(app._editor_controller.editor, pronunciation_editor)
        self.assertEqual(app.session.replace_query_calls, [])

    def test_settings_summary_opens_style_and_output_edits_inline(self):
        app = self.make_app(query=mixed_query())
        set_navigation_focus(app, ("settings_summary", None))
        app._handle_key("\n")
        self.assertEqual(app._editor_controller.editor.selection, "style_id")
        self.assertIsNone(app._editor_controller.editor.active_field)

        app._handle_key("\x1b")
        set_navigation_focus(app, ("output", None))
        app._handle_key("\n")
        self.assertIsNone(app._editor_controller.editor)
        self.assertTrue(app._output_path_controller.active)
        self.assertEqual(app._output_path_controller.state.owner, "batch_item")

        app._handle_key("\x1b")
        set_navigation_focus(app, ("settings", None))
        app._handle_key("\n")
        self.assertEqual(app._editor_controller.editor.selection, "style_id")
        self.assertIsNone(app._editor_controller.editor.active_field)

    def test_enter_on_pronunciation_rows_opens_language_specific_editors(self):
        app = self.make_app(query=mixed_query(["HH", "AH1"]))
        set_navigation_focus(app, ("pronunciation", 0))
        app._handle_key("\n")
        self.assertEqual(app._editor_controller.editor.kind, "japanese")
        self.assertEqual(app._editor_controller.editor.title, "EDIT PRONUNCIATION")

        app._editor_controller.editor = None
        set_navigation_focus(app, ("pronunciation", 1))
        app._handle_key("\n")
        self.assertEqual(app._editor_controller.editor.kind, "english_word")
        self.assertEqual(app._editor_controller.editor.title, "EDIT PRONUNCIATION")
        self.assertNotIn("english_segment", app._editor_controller.editor.kind)

    def test_main_add_section_is_placed_after_pronunciation_and_opens_its_editor(self):
        app = self.make_app(query=mixed_query())
        items = navigation_items(app)
        pronunciation_positions = [
            index for index, key in enumerate(items) if key[0] == "pronunciation"
        ]
        self.assertEqual(
            items[pronunciation_positions[-1] + 1], ("add_section", None)
        )
        self.assertEqual(
            items[pronunciation_positions[-1] + 2], ("generate", None)
        )
        set_navigation_focus(app, ("add_section", None))
        app._handle_key("\n")
        self.assertEqual(app._editor_controller.editor.kind, "add_section")
        self.assertEqual(app._editor_controller.editor.title, "ADD SECTION")

    def test_caption_divergence_keeps_pronunciation_rows_selectable(self):
        app = self.make_app(query=mixed_query())
        app.session.utterance_manually_edited = True
        self.assertIn(("pronunciation", 0), navigation_items(app))
        set_navigation_focus(app, ("caption", None))
        app._handle_key("\t")
        self.assertEqual(app._navigation.focus_key, ("build_pronunciation", None))

    def test_text_and_generate_are_reachable_with_only_vertical_arrows(self):
        app = self.make_app(query=mixed_query())
        set_navigation_focus(app, ("settings_summary", None))
        app._handle_key(curses.KEY_UP)
        self.assertEqual(app._navigation.focus_key, ("batch_item", None))
        app._handle_key(curses.KEY_UP)
        self.assertEqual(app._navigation.focus_key, ("batch_item", None))
        while app._navigation.focus_key != ("generate", None):
            app._handle_key(curses.KEY_DOWN)
        navigation_revision = app._navigation.revision
        app._operations.start_generation = Mock(return_value=())
        app._handle_key("\n")
        app._operations.start_generation.assert_called_once_with(
            app.session,
            take_count=app.settings.take_count,
            navigation_revision=navigation_revision,
            item_id=app._batch.open_item_id,
        )

    def test_help_and_quit_actions_activate_from_the_continuous_list(self):
        app = self.make_app(query=mixed_query())
        app._screen = FakeScreen(rows=12, columns=80)
        help_action = next(
            line for line, key in navigation_document(app, 80)
            if key == ("help", None)
        )
        self.assertIn("Help", help_action)
        set_navigation_focus(app, ("help", None))
        app._handle_key("\n")
        self.assertTrue(app._help_open)
        self.assertEqual(app._help_scroll, 0)
        self.assertEqual(app._navigation.focus_key, ("help", None))
        app._handle_key(curses.KEY_UP)
        self.assertEqual(app._help_scroll, 0)
        app._handle_key(curses.KEY_DOWN)
        self.assertEqual(app._help_scroll, 1)
        height, width = app._screen.getmaxyx()
        max_scroll = app._renderer.help_max_scroll(height, width)
        self.assertGreater(max_scroll, 0)
        page_step = max(1, height - 3)
        app._handle_key(curses.KEY_NPAGE)
        expected_after_page_down = min(max_scroll, 1 + page_step)
        self.assertEqual(app._help_scroll, expected_after_page_down)
        app._handle_key(curses.KEY_PPAGE)
        self.assertEqual(
            app._help_scroll,
            max(0, expected_after_page_down - page_step),
        )
        self.assertTrue(app._help_open)
        app._handle_key("\n")
        self.assertFalse(app._help_open)
        self.assertEqual(app._navigation.focus_key, ("help", None))

        app._handle_key("?")
        self.assertTrue(app._help_open)
        self.assertEqual(app._help_scroll, 0)
        app._handle_key("?")
        self.assertFalse(app._help_open)
        self.assertEqual(app._navigation.focus_key, ("help", None))
        app._handle_key("?")
        self.assertTrue(app._help_open)
        app._handle_key("\x1b")
        self.assertFalse(app._help_open)
        self.assertEqual(app._navigation.focus_key, ("help", None))
        set_navigation_focus(app, ("quit", None))
        app._handle_key("\n")
        self.assertTrue(app._exit_requested)

        for key in ("q", "Q", "\x03"):
            with self.subTest(key=key):
                shortcut = self.make_app(query=mixed_query())
                shortcut._handle_key("?")
                self.assertTrue(shortcut._help_open)
                shortcut._handle_key(key)
                self.assertFalse(shortcut._help_open)
                self.assertTrue(shortcut._exit_requested)

    def test_help_and_cancelled_editor_leave_candidates_available(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1), candidate(2)))
        candidates_before = app.session.candidates

        app._handle_key("?")
        app._handle_key("\x1b")
        app._open_settings_editor()
        app._handle_key("\x1b")

        self.assertEqual(app.session.candidates, candidates_before)
        self.assertEqual(app.session.discard_calls, 0)

    def test_escape_keeps_local_back_behavior_during_generation(self):
        for operation in ("initial", "regenerate_all"):
            with self.subTest(operation=operation):
                app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
                app._help_open = True
                app._operations.busy = True
                app._operations.worker_operation = operation
                cancellation_event = Event()
                app._operations._cancellation_event = cancellation_event

                app._handle_key("\x1b")

                self.assertFalse(app._help_open)
                self.assertFalse(cancellation_event.is_set())
                self.assertTrue(app._operations.busy)

    def test_escape_returns_to_batch_list_without_cancelling_generation(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        cancellation_event = Event()
        app._operations._cancellation_event = cancellation_event
        revision = app._navigation.revision

        app._handle_key("\x1b")

        self.assertFalse(app._batch.in_item)
        self.assertIsNone(app.session)
        self.assertTrue(app._operations.busy)
        self.assertFalse(cancellation_event.is_set())
        self.assertGreater(app._navigation.revision, revision)

    def test_generation_finishes_on_originating_caption_after_leaving_item(self):
        app = self.make_app(query=mixed_query())
        session = app.session
        item_id = app._batch.open_item_id
        started = Event()
        release = Event()
        generated = candidate(1)

        def generate_takes():
            def values():
                started.set()
                release.wait(timeout=5)
                session.candidates = (generated,)
                yield generated
            return values()

        session.generate_takes = generate_takes
        app._dispatch_operation_effects(
            app._operations.start_generation(
                session,
                take_count=1,
                navigation_revision=app._navigation.revision,
                item_id=item_id,
            )
        )
        self.assertTrue(started.wait(timeout=5))

        app._handle_key("\x1b")
        release.set()
        app._operations.join_worker()
        app._consume_events()

        self.assertFalse(app._batch.in_item)
        self.assertIsNone(app.session)
        self.assertEqual(
            app._batch.batch.get_item(item_id).session.candidates,
            (generated,),
        )
        self.assertEqual(
            app._status,
            "Caption 1 generation finished. 1 take(s) ready.",
        )

    def test_main_only_generation_and_candidate_shortcuts_do_not_escape_editor(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        app._open_settings_editor()
        editor = app._editor_controller.editor
        app._navigation.activate_item = Mock(return_value=())
        app._navigation.focus_candidate = Mock(return_value=())
        app._navigation.activate_regenerate_focused = Mock(return_value=())

        for key in ("g", curses.KEY_F5, "\x07", "1", "R"):
            app._handle_key(key)

        app._navigation.activate_item.assert_not_called()
        app._navigation.focus_candidate.assert_not_called()
        app._navigation.activate_regenerate_focused.assert_not_called()
        self.assertIs(app._editor_controller.editor, editor)

        app._handle_key("r")
        app._navigation.activate_regenerate_focused.assert_not_called()
        self.assertIs(app._editor_controller.editor, editor)

    def test_help_from_editor_restores_exact_editor_state_and_focus(self):
        app = self.make_app(query=mixed_query())
        app._open_settings_editor()
        editor = app._editor_controller.editor
        editor.selection = "output_dir"
        editor.payload["draft_settings"]["output_dir"] = "/tmp/custom"
        snapshot = dict(editor.payload["draft_settings"])

        app._handle_key("?")
        self.assertTrue(app._help_open)
        self.assertIs(app._editor_controller.editor, editor)

        screen = FakeScreen()
        app._screen = screen
        app._render()
        self.assertIn("HELP", self.rendered(screen))
        self.assertNotIn("EDIT SETTINGS", self.rendered(screen))

        app._handle_key("\x1b")
        self.assertFalse(app._help_open)
        self.assertIs(app._editor_controller.editor, editor)
        self.assertEqual(editor.selection, "output_dir")
        self.assertEqual(editor.payload["draft_settings"], snapshot)

        app._handle_key("q")
        self.assertTrue(app._exit_requested)

    def test_batch_list_enter_opens_item_and_escape_returns_to_same_list_entry(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        session = app.session
        app._batch.close_item()
        app.session = None
        app._batch.focus_key = ("caption", 0)

        app._handle_key(" ")
        self.assertFalse(app._batch.batch.items[0].included_for_generation)
        app._handle_key(" ")
        self.assertTrue(app._batch.batch.items[0].included_for_generation)

        app._handle_key("\n")
        self.assertTrue(app._batch.in_item)
        self.assertIs(app.session, session)
        self.assertEqual(app._batch.item_title, "BATCH ITEM")
        self.assertEqual(app._batch.item_position, (1, 1))
        self.assertEqual(app._navigation.focus_key, ("candidate", 1))

        screen = FakeScreen()
        app._screen = screen
        with patch("voiceger_editor.tui_rendering.available_styles", return_value=()):
            app._render()
        rendered = self.rendered(screen)
        self.assertIn("BATCH ITEM", rendered)
        self.assertIn("< 1 / 1 >", rendered)

        app._handle_key("\x1b")
        self.assertFalse(app._batch.in_item)
        self.assertIsNone(app.session)
        self.assertEqual(app._batch.focus_key, ("caption", 0))
        self.assertEqual(session.candidates, (candidate(1),))

    def test_batch_item_delete_is_visible_cancelable_and_returns_to_batch_list(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        session = app.session
        stop_playback = Mock()
        app._operations.stop_playback = stop_playback

        screen = FakeScreen(columns=100)
        app._screen = screen
        with patch("voiceger_editor.tui_rendering.available_styles", return_value=()):
            app._render()
        self.assertIn("[X] Delete caption", self.rendered(screen))

        app._handle_key("x")
        self.assertTrue(app._batch.delete_confirmation_active)
        self.assertTrue(app._batch.in_item)
        self.assertIs(app.session, session)

        screen.drawn.clear()
        app._render()
        rendered = self.rendered(screen)
        self.assertIn("DELETE CAPTION?", rendered)
        self.assertIn("[D] Delete caption", rendered)
        self.assertIn("Cancel", rendered)
        self.assertNotIn("Esc Cancel", rendered)

        app._handle_key("\x1b")
        self.assertFalse(app._batch.delete_confirmation_active)
        self.assertTrue(app._batch.in_item)
        self.assertIs(app.session, session)
        self.assertEqual(session.close_calls, 0)

        app._handle_key("x")
        app._handle_key("d")
        self.assertFalse(app._batch.in_item)
        self.assertIsNone(app.session)
        self.assertEqual(app._batch.batch.items, ())
        self.assertEqual(app._batch.focus_key, ("add_captions", None))
        self.assertEqual(session.close_calls, 1)
        self.assertEqual(stop_playback.call_count, 2)

    def test_accepting_batch_item_stays_on_same_item_until_explicit_navigation(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        accepted_session = app.session
        accepted_item = app._batch.batch.items[0]
        next_session = FakeSession(
            query=mixed_query(),
            candidates=(candidate(1), candidate(2)),
        )
        next_session.caption = "next caption"
        app._batch.batch.add_item(CaptionBatchItem(next_session))
        focus_candidate(app, 1)

        app._handle_key("\n")

        self.assertEqual(accepted_session.accept_calls, [])
        self.assertFalse(accepted_item.is_accepted)
        self.assertIn("Saving Take 1…", app._status)

        app._operations.start_pending_worker()
        app._operations.join_worker()
        app._consume_events()

        self.assertEqual(accepted_session.accept_calls, [1])
        self.assertTrue(accepted_item.is_accepted)
        self.assertEqual(accepted_item.accepted_take_number, 1)
        self.assertTrue(app._batch.in_item)
        self.assertIs(app.session, accepted_session)
        self.assertEqual(app._batch.item_position, (1, 2))
        self.assertEqual(app._navigation.focus_key, ("candidate", 1))
        self.assertEqual(
            [item.number for item in next_session.candidates],
            [1, 2],
        )
        self.assertIn("Saved accepted-1.wav.", app._status)

    def test_single_item_generation_effects_keep_stable_caption_ownership(self):
        app = self.make_app(
            query=mixed_query(),
            candidates=(candidate(1), candidate(2)),
        )
        first = app._batch.batch.items[0]
        first_session = first.session
        second_session = FakeSession(
            query=mixed_query(),
            candidates=(candidate(1), candidate(2)),
        )
        second_session.caption = "second"
        second = CaptionBatchItem(second_session)
        app._batch.batch.add_item(second)
        app._batch.batch.mark_accepted(first.item_id, 1)
        app._batch.batch.mark_accepted(second.item_id, 1)
        app._batch.open_item(1)
        app.session = second_session

        app._dispatch_operation_effects(
            (CandidateReplacedEffect(1, item_id=first.item_id),)
        )

        self.assertFalse(first.is_accepted)
        self.assertTrue(second.is_accepted)

        app._dispatch_operation_effects(
            (DiscardInitialBatchEffect(item_id=first.item_id),)
        )

        self.assertEqual(first_session.discard_calls, 1)
        self.assertEqual(second_session.discard_calls, 0)
        self.assertTrue(second.is_accepted)

    def test_failed_generation_start_preserves_existing_acceptance(self):
        app = self.make_app(query=mixed_query(), candidates=())
        item = app._batch.batch.items[0]
        app._batch.batch.mark_accepted(item.item_id, 1)
        app.session.generate_error = RuntimeError("cannot start")

        app._handle_key("g")

        self.assertTrue(item.is_accepted)
        self.assertEqual(item.accepted_take_number, 1)
        self.assertIn(
            "Could not start take generation: cannot start",
            app._status,
        )
        self.assertIs(app._status.kind, StatusKind.ERROR)

    def test_failed_batch_item_acceptance_stays_on_same_item(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        session = app.session
        item = app._batch.batch.items[0]
        session.accept_error = RuntimeError("disk full")
        focus_candidate(app, 1)

        app._handle_key("\n")

        self.assertTrue(app._batch.in_item)
        self.assertIs(app.session, session)
        self.assertFalse(item.is_accepted)
        self.assertEqual(session.accept_calls, [])
        self.assertIn("Saving Take 1…", app._status)

        app._operations.start_pending_worker()
        app._operations.join_worker()
        app._consume_events()

        self.assertFalse(item.is_accepted)
        self.assertEqual(
            [candidate.number for candidate in session.candidates],
            [1],
        )
        self.assertIn(
            "Take 1 was not saved: disk full",
            app._status,
        )
        self.assertIs(app._status.kind, StatusKind.ERROR)

    def test_batch_list_add_caption_uses_existing_caption_editor(self):
        app = self.make_app(batch_item=False)
        app.session = None
        new_session = FakeSession(query=mixed_query())
        new_session.caption = "new caption"
        app._new_session = Mock(return_value=new_session)

        app._handle_key("a")

        editor = app._editor_controller.editor
        self.assertEqual(editor.kind, "caption")
        self.assertEqual(editor.title, "ADD CAPTIONS")
        self.assertEqual(editor.origin, ("add_captions", None))
        self.assertTrue(editor.payload["multiline"])
        self.assertEqual(editor.active_field, "draft")
        editor.input_value = "new caption"
        editor.input_cursor = len(editor.input_value)
        app._handle_key("\n")
        app._handle_key(curses.KEY_DOWN)
        app._handle_key("\n")

        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(
            [item.caption for item in app._batch.batch.items],
            ["new caption"],
        )
        self.assertFalse(app._batch.in_item)
        self.assertIsNone(app.session)

    def test_run_without_initial_caption_starts_on_batch_list(self):
        for initial_caption in (None, "", "   "):
            with self.subTest(initial_caption=initial_caption):
                app = self.make_app(batch_item=False)
                app.session = None
                app._initial_caption = initial_caption
                screen = FakeScreen(keys=("q",))
                with patch("voiceger_editor.tui.curses.set_escdelay"):
                    app.run(screen)

                self.assertIsNone(app.session)
                self.assertIsNone(app._editor_controller.editor)
                self.assertEqual(app._batch.focus_key, ("add_captions", None))
                rendered = self.rendered(screen)
                self.assertIn("BATCH LIST", rendered)
                self.assertIn("Takes < 4 >", rendered)
                self.assertIn("[A] Add captions", rendered)
                self.assertNotIn("Voiceger Accent Adapter", rendered)
                self.assertNotIn("EDIT CAPTION TEXT", rendered)

    def test_run_sets_fast_escape_delay_and_keeps_100ms_polling_with_blank_ready_status(self):
        app = self.make_app(batch_item=False)
        app._initial_caption = "example"
        screen = FakeScreen(keys=("q",))
        with patch(
            "voiceger_editor.tui.UtteranceSession.from_caption",
            return_value=app.session,
        ), patch("voiceger_editor.tui.curses.set_escdelay") as set_escdelay:
            app.run(screen)

        set_escdelay.assert_called_once_with(25)
        self.assertEqual(screen.timeouts, [100])
        self.assertEqual(app._status, "")

    def test_preview_temporary_wav_is_cleaned_during_tui_shutdown(self):
        app = self.make_app(batch_item=False)
        app._initial_caption = "example"
        process = Mock()
        process.poll.return_value = None
        popen = Mock(return_value=process)
        app._operations._platform = lambda: "linux"
        app._operations._which = lambda _name: "/usr/bin/ffplay"
        app._operations._popen = popen
        app._operations.play_preview([0.0] * 80, 32000)
        preview_path = Path(popen.call_args.args[0][-1])
        self.assertTrue(preview_path.is_file())

        with patch(
            "voiceger_editor.tui.UtteranceSession.from_caption",
            return_value=app.session,
        ), patch("voiceger_editor.tui.curses.set_escdelay"):
            app.run(FakeScreen(keys=("q",)))

        self.assertFalse(preview_path.exists())
        self.assertFalse(preview_path.parent.exists())
        self.assertIsNone(app._operations.playback_process)
        process.terminate.assert_called_once_with()

    def test_ordinary_navigation_movement_preserves_existing_status(self):
        app = self.make_app(query=mixed_query())
        app._status = info_status("Saved output.wav.")

        while app._navigation.focus_key != ("quit", None):
            app._handle_key(curses.KEY_DOWN)
            self.assertEqual(app._status, "Saved output.wav.")

        self.assertNotIn("selected", app._status.lower())

    def test_caption_apply_leaves_query_candidates_cache_and_playback_untouched(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(3),))
        session = app.session
        candidates = session.candidates
        english_grouping(app, 1)
        self.assertIn(1, app._editor_controller.grouping_cache)
        query = session.query.model_dump()
        app._operations.current_take = 3
        app._operations.stop_playback = Mock()
        set_navigation_focus(app, ("caption", None))
        app._open_caption_editor()
        app._editor_controller.editor.input_value = "new caption"
        with patch(
            "voiceger_editor.tui.UtteranceSession.from_caption",
            side_effect=AssertionError("existing session must be reused"),
        ) as from_caption:
            app._handle_key("\n")
            app._handle_key(curses.KEY_DOWN)
            app._handle_key("\n")
        from_caption.assert_not_called()
        self.assertIs(app.session, session)
        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(app._navigation.focus_key, ("caption", None))
        self.assertEqual(session.replace_caption_calls, ["new caption"])
        self.assertEqual(session.replace_query_calls, [])
        self.assertEqual(session.query.model_dump(), query)
        self.assertEqual(session.caption, "new caption")
        self.assertEqual(session.candidates, candidates)
        self.assertFalse(session.utterance_manually_edited)
        self.assertIn(1, app._editor_controller.grouping_cache)
        self.assertEqual(app._operations.current_take, 3)
        app._operations.stop_playback.assert_not_called()

    def test_preview_intent_dispatches_preview_without_replacing_canonical_query(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(3),))
        session = app.session
        transient = AudioQuery(accent_phrases=[])
        app._operations.start_preview = Mock(return_value=())
        canonical = session.query.model_dump()
        candidates = session.candidates

        app._dispatch_editor_intents((PreviewIntent(transient),))

        app._operations.start_preview.assert_called_once_with(
            session,
            transient,
            adapter=app.adapter,
            settings=app.settings,
        )
        self.assertEqual(session.replace_query_calls, [])
        self.assertEqual(session.query.model_dump(), canonical)
        self.assertEqual(session.candidates, candidates)
        self.assertFalse(session.utterance_manually_edited)

        app._operations.play_preview = Mock(return_value=())
        app._dispatch_operation_effects((PlayPreviewEffect("audio", 22050),))
        app._operations.play_preview.assert_called_once_with("audio", 22050)

    def test_preview_intent_from_batch_list_passes_standalone_synthesis_context(self):
        app = self.make_app(query=mixed_query(), batch_item=False)
        app.session = None
        transient = AudioQuery(accent_phrases=[])
        app._operations.start_preview = Mock(return_value=())

        app._dispatch_editor_intents((PreviewIntent(transient),))

        app._operations.start_preview.assert_called_once_with(
            None,
            transient,
            adapter=app.adapter,
            settings=app.settings,
        )

    def test_committed_utterance_text_intent_preserves_caption_and_clears_takes(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(3),))
        session = app.session
        old_caption = session.caption
        updated = session.query
        updated.voicegerSegments[0].text = "変更された日本語"
        updated.accent_phrases[0].moras[0].text = "イ"
        app._operations.current_take = 3

        app._dispatch_editor_intents(
            (
                ReplaceQueryIntent(
                    query=updated,
                    editor_kind="section_text",
                    success_status="Section text updated.",
                ),
            )
        )

        self.assertEqual(session.caption, old_caption)
        self.assertEqual(session.query.voicegerSegments[0].text, "変更された日本語")
        self.assertEqual(session.replace_query_calls, [updated])
        self.assertEqual(session.candidates, ())
        self.assertTrue(session.utterance_manually_edited)
        self.assertIsNone(app._operations.current_take)

    def test_first_caption_apply_adds_initial_batch_item_without_opening_it(self):
        adapter = Mock()
        adapter.voiceger_root = Path("/nonexistent/voiceger")
        seeded_session = FakeSession(query=mixed_query())
        seeded_session.caption = "initial caption"
        app = TuiApp(adapter=adapter, settings=Settings())
        app._handle_key("a")
        editor = app._editor_controller.editor
        self.assertEqual(editor.title, "ADD CAPTIONS")
        self.assertTrue(editor.payload["multiline"])
        editor.input_value = "initial caption"
        editor.input_cursor = len(editor.input_value)
        with patch(
            "voiceger_editor.tui.UtteranceSession.from_caption",
            return_value=seeded_session,
        ) as from_caption:
            app._handle_key("\n")
            app._handle_key(curses.KEY_DOWN)
            app._handle_key("\n")

        from_caption.assert_called_once_with(
            adapter=adapter,
            caption="initial caption",
            settings=app.settings,
        )
        self.assertIsNone(app.session)
        self.assertEqual(len(app._batch.batch.items), 1)
        self.assertIs(app._batch.batch.items[0].session, seeded_session)
        self.assertFalse(app._batch.in_item)
        self.assertEqual(app._status, "Caption added.")

    def test_add_captions_multiline_editor_creates_one_selected_item_per_non_empty_line(self):
        adapter = Mock()
        adapter.voiceger_root = Path("/nonexistent/voiceger")
        captions = (
            "今日は雨なのだ。",
            "このずんだ餅はvery sweetなのだ。",
            "明日も元気なのだ。",
        )
        sessions = []
        for caption in captions:
            session = FakeSession(query=mixed_query())
            session.caption = caption
            sessions.append(session)
        app = TuiApp(adapter=adapter, settings=Settings())

        app._handle_key("a")
        app._handle_key(
            PasteText(
                f"{captions[0]}\n\n{captions[1]}\n{captions[2]}"
            )
        )

        editor = app._editor_controller.editor
        self.assertEqual(
            editor.input_value,
            f"{captions[0]}\n\n{captions[1]}\n{captions[2]}",
        )
        self.assertEqual(editor.active_field, "draft")

        with patch(
            "voiceger_editor.tui.UtteranceSession.from_caption",
            side_effect=sessions,
        ) as from_caption:
            app._handle_key("\n")
            self.assertIsNone(editor.active_field)
            app._handle_key(curses.KEY_DOWN)
            self.assertEqual(editor.selection, "apply")
            app._handle_key("\n")

        items = app._batch.batch.items
        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual([item.caption for item in items], list(captions))
        self.assertEqual(
            [item.included_for_generation for item in items],
            [True, True, True],
        )
        self.assertEqual(len({item.item_id for item in items}), 3)
        self.assertEqual([item.session for item in items], sessions)
        self.assertEqual(
            [call.kwargs["caption"] for call in from_caption.call_args_list],
            list(captions),
        )
        self.assertEqual(app._status, "3 Captions added.")

    def test_add_captions_remains_available_during_background_generation(self):
        app = self.make_app(query=mixed_query(), batch_item=True)
        generating_item_id = app._batch.open_item_id
        cancellation_event = Event()
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._worker_item_id = generating_item_id
        app._operations._owned_item_ids = frozenset({generating_item_id})
        app._operations._cancellation_event = cancellation_event
        app._operations.operation_total = 4

        app._handle_key("\x1b")
        app._handle_key("a")

        editor = app._editor_controller.editor
        self.assertIsNotNone(editor)
        self.assertEqual(editor.title, "ADD CAPTIONS")
        self.assertEqual(editor.active_field, "draft")

        added = FakeSession(query=mixed_query())
        added.caption = "background-added caption"
        with patch(
            "voiceger_editor.tui.UtteranceSession.from_caption",
            return_value=added,
        ):
            app._handle_key(PasteText("background-added caption"))
            app._handle_key("\n")
            app._handle_key(curses.KEY_DOWN)
            app._handle_key("\n")

        self.assertTrue(app._operations.busy)
        self.assertEqual(app._operations._worker_item_id, generating_item_id)
        self.assertFalse(cancellation_event.is_set())
        self.assertEqual(
            [item.caption for item in app._batch.batch.items],
            [app._batch.batch.items[0].caption, "background-added caption"],
        )

        app._batch.focus_key = ("caption", 1)
        app._handle_key("\n")
        self.assertIs(app.session, added)
        set_navigation_focus(app, ("caption", None))
        app._handle_key("\n")
        self.assertEqual(app._editor_controller.editor.title, "EDIT CAPTION TEXT")
        app._editor_controller.editor.input_value = "edited while first generates"
        app._handle_key("\n")
        app._handle_key(curses.KEY_DOWN)
        app._handle_key("\n")

        self.assertEqual(added.caption, "edited while first generates")
        self.assertTrue(app._operations.busy)
        self.assertEqual(app._operations._worker_item_id, generating_item_id)
        self.assertEqual(
            app._operations.owned_item_ids,
            frozenset({generating_item_id}),
        )

    def test_batch_list_apply_adds_multiple_lightweight_caption_sessions(self):
        adapter = Mock()
        adapter.voiceger_root = Path("/nonexistent/voiceger")
        first = FakeSession(query=mixed_query())
        first.caption = "first caption"
        second = FakeSession(query=mixed_query())
        second.caption = "second caption"
        app = TuiApp(adapter=adapter, settings=Settings())

        with patch(
            "voiceger_editor.tui.UtteranceSession.from_caption",
            side_effect=[first, second],
        ) as from_caption:
            result = app._apply_caption(
                "first caption\n\nsecond caption"
            )

        self.assertIsNone(result.error)
        self.assertEqual(result.added_caption_count, 2)
        self.assertEqual(
            [item.caption for item in app._batch.batch.items],
            ["first caption", "second caption"],
        )
        self.assertEqual(
            [item.included_for_generation for item in app._batch.batch.items],
            [True, True],
        )
        self.assertNotEqual(
            app._batch.batch.items[0].item_id,
            app._batch.batch.items[1].item_id,
        )
        self.assertEqual(
            [call.kwargs["caption"] for call in from_caption.call_args_list],
            ["first caption", "second caption"],
        )

    def test_existing_caption_multiline_replacement_does_not_split_batch_item(self):
        app = self.make_app(query=mixed_query(), batch_item=True)
        session = app.session
        item = app._batch.batch.items[0]
        replacement = "first line\nsecond line"

        result = app._apply_caption(replacement)

        self.assertIsNone(result.error)
        self.assertEqual(result.added_caption_count, 0)
        self.assertEqual(len(app._batch.batch.items), 1)
        self.assertIs(app._batch.batch.items[0], item)
        self.assertIs(app._batch.batch.items[0].session, session)
        self.assertEqual(session.caption, replacement)

    def test_pure_japanese_source_display_uses_utterance_after_caption_changes(self):
        query = japanese_query((("ナ",), 1), (("ノ", "ダ"), 2))
        query.voicegerSegments = None
        app = self.make_app(query=query, groups=())
        app.session.caption = "Caption B"
        app.session._pure_japanese_utterance_text = "Utterance A"

        rows = app._pronunciation_rows()
        self.assertEqual(rows[0].source_text, "Utterance A")
        rendered = "\n".join(line for line, _key in navigation_document(app, 100))
        self.assertIn("Caption : Caption B", rendered)
        set_navigation_focus(app, ("pronunciation", 0))
        app._handle_key("\n")
        self.assertEqual(app._editor_controller.editor.payload["source_text"], "Utterance A")

    def test_clean_build_uses_visible_deferred_preparation_lifecycle(self):
        app = self.make_app(query=mixed_query())
        app.session.candidates = (candidate(2),)
        app.session.utterance_manually_edited = False
        english_grouping(app, 1)
        clear_groupings = Mock(wraps=app._editor_controller.clear_groupings)
        app._editor_controller.clear_groupings = clear_groupings
        app._operations.current_take = 2
        app._operations.stop_playback = Mock()
        set_navigation_focus(app, ("build_pronunciation", None))

        app._handle_key("\n")

        self.assertEqual(app.session.build_calls, 0)
        self.assertEqual(app._operations.worker_operation, "prepare")
        self.assertEqual(app._status, "Rebuilding pronunciation…")
        clear_groupings.assert_not_called()

        app._operations.start_pending_worker()
        app._operations.join_worker()
        app._consume_events()

        self.assertEqual(app.session.build_calls, 1)
        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(app.session.candidates, ())
        clear_groupings.assert_called_once_with()
        self.assertIsNone(app._operations.current_take)
        app._operations.stop_playback.assert_called_once_with()
        self.assertEqual(app._navigation.focus_key, ("pronunciation", 0))
        self.assertEqual(app._status, "Pronunciation rebuilt from Caption.")

    def test_dirty_build_confirmation_starts_deferred_rebuild_only_after_confirm(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(2),))
        app.session.utterance_manually_edited = True
        english_grouping(app, 1)
        clear_groupings = Mock(wraps=app._editor_controller.clear_groupings)
        app._editor_controller.clear_groupings = clear_groupings
        app._operations.current_take = 2
        app._operations.stop_playback = Mock()
        set_navigation_focus(app, ("build_pronunciation", None))
        app._handle_key("\n")
        self.assertEqual(app.session.build_calls, 0)

        app._handle_key("r")

        self.assertEqual(app.session.build_calls, 0)
        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(app._status, "Rebuilding pronunciation…")
        app._operations.start_pending_worker()
        app._operations.join_worker()
        app._consume_events()

        self.assertEqual(app.session.build_calls, 1)
        self.assertFalse(app.session.utterance_manually_edited)
        self.assertEqual(app.session.candidates, ())
        clear_groupings.assert_called_once_with()
        self.assertIsNone(app._operations.current_take)
        self.assertEqual(app._navigation.focus_key, ("pronunciation", 0))
        self.assertEqual(app._status, "Pronunciation rebuilt from Caption.")

    def test_failed_confirmed_build_preserves_state_and_is_retryable(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(2),))
        app.session.utterance_manually_edited = True
        app.session.rebuild_error = RuntimeError("analysis failed")
        app._operations.current_take = 2
        query = app.session.query.model_dump()
        candidates = app.session.candidates
        set_navigation_focus(app, ("build_pronunciation", None))
        app._handle_key("\n")
        app._handle_key("r")

        app._operations.start_pending_worker()
        app._operations.join_worker()
        app._consume_events()

        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(app.session.query.model_dump(), query)
        self.assertEqual(app.session.candidates, candidates)
        self.assertTrue(app.session.utterance_manually_edited)
        self.assertEqual(app._operations.current_take, 2)
        self.assertEqual(
            app._status,
            error_status("Pronunciation was not rebuilt: analysis failed"),
        )

        app.session.rebuild_error = None
        app._handle_key("p")
        self.assertEqual(app._editor_controller.editor.kind, "build_confirmation")

    def test_caption_apply_failure_preserves_draft_and_remains_editable(self):
        app = self.make_app(query=mixed_query())
        app._open_caption_editor()
        editor = app._editor_controller.editor
        editor.input_value = "bad draft"
        app.session.replace_caption = Mock(
            side_effect=ValueError("caption replacement failed")
        )
        app._handle_key("\n")
        app._handle_key(curses.KEY_DOWN)
        app._handle_key("\n")
        self.assertIs(app._editor_controller.editor, editor)
        self.assertIsNone(editor.active_field)
        self.assertEqual(editor.input_value, "bad draft")
        self.assertEqual(editor.payload["draft"], "bad draft")
        self.assertIn("caption replacement failed", editor.error)
        app._handle_key(curses.KEY_UP)
        app._handle_key("\n")
        app._handle_key("!")
        self.assertEqual(editor.input_value, "bad draft!")

    def test_japanese_punctuation_only_apply_uses_question_input_and_clears_candidates(self):
        app = self.make_app(
            query=japanese_query((("ナ", "ノ", "ダ"), 3), terminator="。"),
            candidates=(candidate(1),),
        )
        opening_caption = app.session.caption
        source_text = app.session.query.voicegerSegments[0].text
        app._edit_selected_pronunciation(0)
        editor = app._editor_controller.editor

        app._handle_key(curses.KEY_END)
        app._handle_key(curses.KEY_BACKSPACE)
        app._handle_key("?")

        self.assertFalse(app._help_open)
        self.assertEqual(editor.input_value, "ナノダ'?")
        self.assertEqual(editor.active_field, "pronunciation")

        self.finish_and_apply_pronunciation(app)

        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(len(app.session.replace_query_calls), 1)
        self.assertEqual(app.session.candidates, ())
        self.assertEqual(app.session.caption, opening_caption)
        segment = app.session.query.voicegerSegments[0]
        self.assertEqual(segment.text, source_text)
        self.assertEqual(segment.pronunciationTerminator, "？")
        self.assertEqual(
            [
                (entry.afterAccentPhrase, entry.mark)
                for entry in segment.pronunciationPunctuation
            ],
            [(0, "？")],
        )

    def test_japanese_ascii_punctuation_only_apply_is_canonical_and_visible(self):
        previous_marks = {".": "！", ",": "。", "?": "！", "!": "？"}
        for alias, canonical in ((".", "。"), (",", "、"), ("?", "？"), ("!", "！")):
            with self.subTest(alias=alias):
                app = self.make_app(
                    query=japanese_query(
                        (("ナ", "ノ", "ダ"), 3),
                        terminator=previous_marks[alias],
                    ),
                    candidates=(candidate(1),),
                )
                opening_caption = app.session.caption
                source_text = app.session.query.voicegerSegments[0].text
                app._edit_selected_pronunciation(0)
                editor = app._editor_controller.editor

                app._handle_key(curses.KEY_END)
                app._handle_key(curses.KEY_BACKSPACE)
                app._handle_key(alias)
                self.assertFalse(app._help_open)
                app._handle_key("\n")
                self.assertEqual(editor.input_value, "ナノダ'" + canonical)
                self.finish_and_apply_pronunciation(app)

                updated = app.session.query
                segment = updated.voicegerSegments[0]
                self.assertEqual(len(app.session.replace_query_calls), 1)
                self.assertEqual(app.session.caption, opening_caption)
                self.assertEqual(segment.text, source_text)
                self.assertEqual(app.session.candidates, ())
                self.assertEqual(
                    [
                        (entry.afterAccentPhrase, entry.mark)
                        for entry in segment.pronunciationPunctuation
                    ],
                    [(0, canonical)],
                )

                rendered = app._renderer.navigation_document(
                    app._render_state(), 80
                )
                main_row = next(
                    line for line in rendered
                    if line.key == ("pronunciation", 0)
                )
                self.assertTrue(main_row.text.endswith(canonical))

                set_navigation_focus(app, ("pronunciation", 0))
                app._handle_key("\n")
                reopened = app._editor_controller.editor
                self.assertEqual(reopened.input_value, "ナノダ'" + canonical)

    def test_japanese_query_application_failure_keeps_draft_editable_for_retry(self):
        app = self.make_app(query=japanese_query((("ナ", "ノ", "ダ"), 3)))
        original_query = app.session.query.model_copy(deep=True)
        actual_replace = app.session.replace_query
        attempts = 0

        def fail_once(replacement):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ValueError("query replacement failed")
            actual_replace(replacement)

        app.session.replace_query = fail_once
        app._edit_selected_pronunciation(0)
        editor = app._editor_controller.editor
        app._handle_key(curses.KEY_HOME)
        app._handle_key(curses.KEY_RIGHT)
        app._handle_key("'")
        app._handle_key(curses.KEY_END)
        app._handle_key(curses.KEY_LEFT)
        app._handle_key(curses.KEY_LEFT)
        app._handle_key(curses.KEY_DC)
        self.assertEqual(editor.input_value, "ナ'ノダ。")
        self.finish_and_apply_pronunciation(app)

        self.assertIs(app._editor_controller.editor, editor)
        self.assertIsNone(editor.active_field)
        self.assertEqual(editor.input_value, "ナ'ノダ。")
        self.assertIn("query replacement failed", editor.error)
        self.assertEqual(app.session.query.model_dump(), original_query.model_dump())
        app._handle_key(curses.KEY_UP)
        app._handle_key(curses.KEY_UP)
        app._handle_key("\n")
        app._handle_key(curses.KEY_END)
        app._handle_key(curses.KEY_LEFT)
        app._handle_key("ア")
        self.assertEqual(editor.input_value, "ナ'ノダア。")
        self.assertEqual(editor.error, "")
        self.finish_and_apply_pronunciation(app)
        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(attempts, 2)
        self.assertEqual(app.session.query.voicegerSegments[0].text, "なのだ。")
        self.assertEqual(len(app.session.replace_query_calls), 1)

    def test_english_query_application_failure_keeps_draft_editable_and_clears_on_typing(self):
        app = self.make_app(
            query=english_query(["HH", "AY1"], text="Hi"),
            candidates=(candidate(1),),
            groups=(("Hi", ("HH", "AY1")),),
        )
        original_query = app.session.query.model_copy(deep=True)
        actual_replace = app.session.replace_query
        attempts = 0

        def fail_once(replacement):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ValueError("query replacement failed")
            actual_replace(replacement)

        app.session.replace_query = fail_once
        set_navigation_focus(app, ("pronunciation", 0))
        app._handle_key("\n")
        editor = app._editor_controller.editor
        self.assertEqual(editor.active_field, "phonemes")
        editor.input_value = "HH AA1"
        editor.input_cursor = len(editor.input_value)
        self.finish_and_apply_pronunciation(app)

        self.assertIs(app._editor_controller.editor, editor)
        self.assertEqual(editor.input_value, "HH AA1")
        self.assertIn("query replacement failed", editor.error)
        self.assertEqual(app.session.query.model_dump(), original_query.model_dump())
        self.assertEqual(len(app.session.candidates), 1)

        app._handle_key(curses.KEY_UP)
        app._handle_key(curses.KEY_UP)
        app._handle_key("\n")
        app._handle_key(" ")
        self.assertEqual(editor.input_value, "HH AA1 ")
        self.assertEqual(editor.error, "")
        self.finish_and_apply_pronunciation(app)

        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(app.session.query.voicegerSegments[0].phonemes, ["HH", "AA1"])
        self.assertEqual(app.session.candidates, ())
        self.assertEqual(app._navigation.focus_key, ("pronunciation", 0))

    def test_generate_arrows_persist_count_preserve_batch_and_work_during_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
            app.config_path = Path(directory) / "settings.json"
            app._operations.current_take = 1
            set_navigation_focus(app, ("generate", None))
            app._status = EMPTY_STATUS
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(app.settings.take_count, 3)
            self.assertEqual(app.session.replace_settings_calls[-1].take_count, 3)
            self.assertEqual(app.session.candidates, (candidate(1),))
            self.assertEqual(app._operations.current_take, 1)
            self.assertEqual(app._navigation.focus_key, ("generate", None))
            self.assertEqual(app._status, "")
            self.assertEqual(json.loads(app.config_path.read_text())["take_count"], 3)

            app.settings = Settings(take_count=1)
            app._persisted_settings = app.settings
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(app.settings.take_count, 1)
            app.settings = Settings(take_count=100)
            app._persisted_settings = app.settings
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(app.settings.take_count, 100)

            app._operations.busy = True
            app._operations.worker_operation = "initial"
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(app.settings.take_count, 99)
            self.assertEqual(app.session.replace_settings_calls[-1].take_count, 99)

    def test_batch_item_escape_returns_to_list_and_preserves_candidates(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1), candidate(2)))
        session = app.session
        app._operations.play_take = Mock(return_value=())
        focus_candidate(app, 1)
        app._handle_key(curses.KEY_DOWN)
        self.assertEqual(app._navigation.focus_key, ("candidate", 2))
        self.assertEqual(app._operations.current_take, 2)
        app._handle_key(" ")
        app._operations.play_take.assert_has_calls(
            [call(session, 1), call(session, 2), call(session, 2)]
        )

        app._handle_key("\x1b")

        self.assertFalse(app._batch.in_item)
        self.assertIsNone(app.session)
        self.assertIs(app._batch.batch.items[0].session, session)
        self.assertEqual(session.candidates, (candidate(1), candidate(2)))
        self.assertIsNone(app._operations.current_take)
        self.assertEqual(app._batch.focus_key, ("caption", 0))

    def test_owned_caption_mutations_and_second_generation_are_blocked_but_light_work_remains(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        item_id = app._batch.open_item_id
        app._operations.play_take = Mock(return_value=())
        app._operations.start_generation = Mock(return_value=())
        app._operations.start_regenerate_all = Mock(return_value=())
        app._operations.start_regeneration = Mock(return_value=())
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._worker_item_id = item_id
        app._operations._owned_item_ids = frozenset({item_id})

        for key in (
            ("caption", None),
            ("pronunciation", 0),
            ("build_pronunciation", None),
        ):
            set_navigation_focus(app, key)
            app._handle_key("\n")
            self.assertIsNone(app._editor_controller.editor)
            self.assertIn("currently generating", app._status)

        set_navigation_focus(app, ("generate", None))
        app._handle_key("\n")
        self.assertIn("already generating", app._status)
        app._operations.start_generation.assert_not_called()
        app._operations.start_regenerate_all.assert_not_called()

        set_navigation_focus(app, ("settings_summary", None))
        app._handle_key("\n")
        self.assertIsNotNone(app._editor_controller.editor)
        self.assertEqual(app._editor_controller.editor.kind, "settings")
        app._handle_key("\x1b")

        set_navigation_focus(app, ("output", None))
        app._handle_key("\n")
        self.assertTrue(app._output_path_controller.active)
        app._handle_key("\x1b")

        focus_candidate(app, 1)
        app._handle_key("\n")
        self.assertEqual(app.session.accept_calls, [])
        self.assertIn("Save Take 1 is unavailable", app._status)

        set_navigation_focus(app, ("candidate", 1))
        app._handle_key("r")
        app._operations.start_regeneration.assert_not_called()

        app._handle_key(" ")
        app._operations.play_take.assert_called_with(app.session, 1)

    def test_shortcuts_are_typed_data_while_raw_input_is_active(self):
        app = self.make_app(query=mixed_query())
        app._open_caption_editor("abc")
        original_settings = app.settings
        for key in ("q", "?", "s", "x", "t", "1", "a", "b", "g", curses.KEY_F5):
            app._handle_key(key)
        self.assertFalse(app._exit_requested)
        self.assertTrue(app.settings is original_settings)
        self.assertEqual(app._editor_controller.editor.input_value, "abcq?sxt1abg")

    def test_playback_stops_before_query_invalidation(self):
        app = self.make_app(query=english_query(["AA1", "IY0"]))
        events = []
        app._operations.stop_playback = Mock(side_effect=lambda: events.append("stop"))
        app.session.replace_query = Mock(side_effect=lambda query: events.append("query"))
        app._apply_session_query(app.session.query.model_copy(deep=True))
        self.assertEqual(events, ["stop", "query"])

    def test_playback_stops_before_settings_invalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app()
            app.config_path = Path(directory) / "config.json"
            events = []
            app._operations.stop_playback = Mock(side_effect=lambda: events.append("stop"))
            app.session.replace_settings = Mock(side_effect=lambda settings: events.append("settings"))
            app._change_settings(speed=0.9)
        self.assertEqual(events, ["stop", "settings"])

    def test_caption_replacement_does_not_stop_playback_or_clear_grouping(self):
        app = self.make_app(query=mixed_query())
        english_grouping(app, 1)
        events = []
        session = app.session
        app._operations.stop_playback = Mock(side_effect=lambda: events.append("stop"))
        session.replace_caption = Mock(side_effect=lambda caption: events.append("replace"))
        result = app._apply_caption("new caption")
        self.assertIsNone(result.error)
        self.assertEqual(events, ["replace"])
        self.assertIs(app.session, session)
        self.assertIn(1, app._editor_controller.grouping_cache)

    def test_busy_shutdown_drains_worker_before_playback_and_session_cleanup(self):
        app = self.make_app(batch_item=False)
        app._initial_caption = "example"
        app._operations.busy = True
        timeout_read = Event()
        worker_finished = Event()
        cleanup_order = []

        def finish_worker():
            timeout_read.wait()
            cleanup_order.append("worker-finished")
            app._operations.events.put(("done", None))
            worker_finished.set()

        worker = Thread(target=finish_worker, name="test-tui-worker")
        app._operations.worker = worker

        class DrainScreen(FakeScreen):
            reads = 0

            def get_wch(self):
                self.reads += 1
                if self.reads == 1:
                    return "q"
                timeout_read.set()
                if not worker_finished.wait(timeout=2):
                    raise AssertionError("worker did not finish during shutdown")
                raise curses.error("input timed out")

        def stop_playback():
            self.assertFalse(worker.is_alive())
            cleanup_order.append("playback-stopped")

        def close_session():
            self.assertFalse(worker.is_alive())
            cleanup_order.append("session-closed")

        app._operations.stop_playback = Mock(side_effect=stop_playback)
        app.session.close = Mock(side_effect=close_session)
        worker.start()
        screen = DrainScreen()
        with patch(
            "voiceger_editor.tui.UtteranceSession.from_caption",
            return_value=app.session,
        ):
            app.run(screen)
        self.assertFalse(app._operations.busy)
        self.assertEqual(
            cleanup_order,
            ["worker-finished", "playback-stopped", "session-closed"],
        )

    def test_run_exception_joins_worker_before_cleanup(self):
        app = self.make_app(batch_item=False)
        app._initial_caption = "example"
        app._operations.busy = True
        worker_release = Event()
        cleanup_order = []

        def finish_worker():
            worker_release.wait()
            cleanup_order.append("worker-finished")

        worker = Thread(target=finish_worker, name="test-tui-worker")
        app._operations.worker = worker

        def fail_render():
            worker_release.set()
            raise RuntimeError("render failed")

        def stop_playback():
            self.assertFalse(worker.is_alive())
            cleanup_order.append("playback-stopped")

        def close_session():
            self.assertFalse(worker.is_alive())
            cleanup_order.append("session-closed")

        app._render = Mock(side_effect=fail_render)
        app._operations.stop_playback = Mock(side_effect=stop_playback)
        app.session.close = Mock(side_effect=close_session)
        worker.start()
        with patch(
            "voiceger_editor.tui.UtteranceSession.from_caption",
            return_value=app.session,
        ):
            with self.assertRaisesRegex(RuntimeError, "render failed"):
                app.run(FakeScreen())
        self.assertEqual(
            cleanup_order,
            ["worker-finished", "playback-stopped", "session-closed"],
        )


if __name__ == "__main__":
    unittest.main()
