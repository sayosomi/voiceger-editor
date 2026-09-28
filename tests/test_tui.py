import curses
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from voiceger_accent_adapter.settings import Settings
from voiceger_accent_adapter.tui import (
    TuiApp,
    build_argument_parser,
    settings_for_invocation,
)
from voiceger_accent_adapter.voicevox_api_models import (
    AccentPhrase,
    AudioQuery,
    Mora,
    VoicegerSegment,
)


def english_query(phonemes, text="example"):
    return AudioQuery(
        accent_phrases=[],
        voicegerSegments=[
            VoicegerSegment(language="en", text=text, phonemes=list(phonemes))
        ],
    )


def mixed_query(english_phonemes=("HH", "AH1")):
    return AudioQuery(
        accent_phrases=[
            AccentPhrase(
                moras=[Mora(text="ア", vowel="a", vowel_length=0.1, pitch=0.0)],
                accent=1,
            )
        ],
        voicegerSegments=[
            VoicegerSegment(
                language="ja",
                text="雨",
                accentPhraseStart=0,
                accentPhraseCount=1,
            ),
            VoicegerSegment(
                language="en",
                text="hello",
                phonemes=list(english_phonemes),
            ),
        ],
    )


def candidate(number):
    return SimpleNamespace(
        number=number,
        wav_path=Path(f"/tmp/take-{number}.wav"),
        audio=[0.0] * 320,
        sampling_rate=32000,
    )


class FakeSession:
    def __init__(self, query=None, candidates=()):
        self.query = query or english_query(["AA1", "IY0", "ER1"])
        self.source_text = "example"
        self.candidates = tuple(candidates)
        self.replace_query_calls = []
        self.replace_settings_calls = []
        self.replace_source_text_calls = []
        self.rebuild_calls = 0
        self.pronunciation_needs_rebuild = False
        self.rebuild_error = None
        self.discard_calls = 0
        self.close_calls = 0
        self.accept_calls = []

    @property
    def has_active_batch(self):
        return bool(self.candidates)

    def replace_query(self, query):
        self.replace_query_calls.append(query)
        self.query = query
        self.candidates = ()

    def replace_source_text(self, source_text):
        self.replace_source_text_calls.append(source_text)
        self.source_text = source_text
        self.pronunciation_needs_rebuild = getattr(
            self, "rebuild_required_for_source", False
        )
        segment_texts = getattr(self, "segment_texts_after_source_change", None)
        if segment_texts is not None and self.query.voicegerSegments is not None:
            for segment, text in zip(self.query.voicegerSegments, segment_texts):
                segment.text = text
        self.candidates = ()

    def rebuild_pronunciation(self):
        self.rebuild_calls += 1
        if self.rebuild_error is not None:
            raise self.rebuild_error
        self.pronunciation_needs_rebuild = False
        self.candidates = ()

    def generate_takes(self):
        if self.pronunciation_needs_rebuild:
            raise RuntimeError("pronunciation must be rebuilt before generation")
        return iter(())

    def replace_settings(self, settings):
        self.replace_settings_calls.append(settings)
        self.candidates = ()

    def discard_takes(self):
        self.discard_calls += 1
        self.candidates = ()

    def accept_take(self, number):
        self.accept_calls.append(number)
        return SimpleNamespace(wav_path=Path(f"/tmp/accepted-{number}.wav"), text_path=None)

    def close(self):
        self.close_calls += 1


class FakeScreen:
    def __init__(self, keys=(), rows=24, columns=80):
        self.keys = list(keys)
        self.rows = rows
        self.columns = columns
        self.drawn = []
        self.refresh_count = 0
        self.cursor = None
        self.timeouts = []

    def getmaxyx(self):
        return self.rows, self.columns

    def keypad(self, enabled):
        return None

    def timeout(self, milliseconds):
        self.timeouts.append(milliseconds)

    def addnstr(self, row, column, value, count, attr=0):
        self.drawn.append((row, column, value[:count], attr))

    def move(self, row, column):
        self.cursor = (row, column)

    def refresh(self):
        self.refresh_count += 1
        return None

    def erase(self):
        self.drawn.clear()
        self.cursor = None
        return None

    def get_wch(self):
        if not self.keys:
            raise curses.error("no more fake keys")
        return self.keys.pop(0)


def navigation_document(app, width):
    return app._renderer.navigation_document(app._render_state(), width)


def set_navigation_focus(app, key, *, moved=False):
    app._dispatch_navigation_actions(
        app._navigation.set_focus_key(
            app._navigation_context(), key, moved=moved
        )
    )


def navigation_items(app):
    return list(app._navigation.navigation_items(app._navigation_context()))


def focus_candidate(app, number):
    app._dispatch_navigation_actions(
        app._navigation.focus_candidate(app._navigation_context(), number)
    )


def english_grouping(app, segment_index):
    return app._editor_controller.english_grouping(
        app.session.query,
        segment_index,
    )


def editor_document(app, width):
    return app._renderer.editor_document(app._render_state(), width)


class TuiTests(unittest.TestCase):
    @staticmethod
    def make_app(*, query=None, candidates=(), groups=None):
        adapter = Mock()
        adapter.voiceger_root = Path("/nonexistent/voiceger")
        query = query or english_query(["AA1", "IY0", "ER1"])
        if groups is None:
            segment = next(
                item for item in (query.voicegerSegments or []) if item.language == "en"
            )
            groups = ((segment.text, tuple(segment.phonemes or ())),)
        adapter.english_word_phoneme_groups.return_value = groups
        app = TuiApp(adapter=adapter, settings=Settings())
        app.session = FakeSession(query=query, candidates=candidates)
        app.session.source_text = "今日は" + next(
            (segment.text for segment in (query.voicegerSegments or []) if segment.language == "en"),
            "example",
        )
        return app

    @staticmethod
    def rendered(screen):
        return "\n".join(text for _row, _column, text, _attr in screen.drawn)

    def test_command_line_options_still_override_persisted_defaults(self):
        args = build_argument_parser().parse_args(
            ["example", "--take-count", "8", "--style", "2", "--speed", "1.25", "--save-text"]
        )
        base = Settings()
        effective = settings_for_invocation(args, base)
        self.assertEqual(effective.take_count, 8)
        self.assertEqual(effective.style_id, 2)
        self.assertEqual(effective.speed, 1.25)
        self.assertTrue(effective.save_text)
        self.assertEqual(base, Settings())

    def test_settings_change_persists_only_interactive_fields_over_cli_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "settings.json"
            app = TuiApp(
                adapter=Mock(),
                settings=Settings(take_count=8),
                persisted_settings=Settings(),
                config_path=config_path,
            )
            app._change_settings(save_text=True)
            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["take_count"], 4)
            self.assertTrue(persisted["save_text"])
            self.assertEqual(app.settings.take_count, 8)

    def test_top_settings_and_output_rows_are_selectable_and_focused(self):
        app = self.make_app(query=mixed_query())
        screen = FakeScreen()
        app._screen = screen

        set_navigation_focus(app, ("settings_summary", None))
        app._render()
        summary = next(item for item in screen.drawn if item[0] == 1)
        self.assertTrue(summary[2].startswith("▶ Style 1"))
        self.assertTrue(summary[3] & curses.A_REVERSE)

        set_navigation_focus(app, ("output", None))
        app._render()
        output = next(item for item in screen.drawn if item[0] == 2)
        self.assertTrue(output[2].startswith("▶ Output:"))
        self.assertTrue(output[3] & curses.A_REVERSE)
        self.assertIn(("settings", None), navigation_items(app))
        self.assertEqual(
            navigation_items(app)[-3:],
            [("settings", None), ("help", None), ("quit", None)],
        )

    def test_settings_summary_opens_style_and_output_opens_path_input(self):
        app = self.make_app(query=mixed_query())
        set_navigation_focus(app, ("settings_summary", None))
        app._handle_key("\n")
        self.assertEqual(app._editor_controller.editor.selection, "style_id")
        self.assertIsNone(app._editor_controller.editor.active_field)

        app._handle_key("\x1b")
        set_navigation_focus(app, ("output", None))
        app._handle_key("\n")
        self.assertEqual(app._editor_controller.editor.selection, "output_dir")
        self.assertEqual(app._editor_controller.editor.active_field, "output_dir")

        app._handle_key("\x1b")
        set_navigation_focus(app, ("settings", None))
        app._handle_key("\n")
        self.assertEqual(app._editor_controller.editor.selection, "style_id")
        self.assertIsNone(app._editor_controller.editor.active_field)

    def test_enter_on_pronunciation_rows_opens_language_specific_editors(self):
        app = self.make_app(query=mixed_query(["HH", "AH1"]))
        set_navigation_focus(app, ("segment", 0))
        app._handle_key("\n")
        self.assertEqual(app._editor_controller.editor.kind, "japanese")

        app._editor_controller.editor = None
        set_navigation_focus(app, ("segment", 1))
        app._handle_key("\n")
        self.assertEqual(app._editor_controller.editor.kind, "english_segment")

    def test_rebuild_required_state_skips_editable_pronunciation_tab_stop(self):
        app = self.make_app(query=mixed_query())
        app.session.pronunciation_needs_rebuild = True
        self.assertNotIn(("segment", 0), navigation_items(app))
        set_navigation_focus(app, ("text", None))
        app._handle_key("\t")
        self.assertEqual(app._navigation.focus_key, ("rebuild", None))

    def test_text_and_generate_are_reachable_with_only_vertical_arrows(self):
        app = self.make_app(query=mixed_query())
        set_navigation_focus(app, ("settings_summary", None))
        app._handle_key(curses.KEY_UP)
        self.assertEqual(app._navigation.focus_key, ("settings_summary", None))
        while app._navigation.focus_key != ("generate", None):
            app._handle_key(curses.KEY_DOWN)
        navigation_revision = app._navigation.revision
        app._operations.start_generation = Mock(return_value=())
        app._handle_key("\n")
        app._operations.start_generation.assert_called_once_with(
            app.session,
            take_count=app.settings.take_count,
            navigation_revision=navigation_revision,
        )

    def test_help_and_quit_actions_activate_from_the_continuous_list(self):
        app = self.make_app(query=mixed_query())
        help_action = next(
            line for line, key in navigation_document(app, 80)
            if key == ("help", None)
        )
        self.assertIn("Help", help_action)
        set_navigation_focus(app, ("help", None))
        app._handle_key("\n")
        self.assertTrue(app._help_open)
        app._handle_key("\x1b")
        set_navigation_focus(app, ("quit", None))
        app._handle_key("\n")
        self.assertTrue(app._exit_requested)

        shortcut = self.make_app(query=mixed_query())
        shortcut._handle_key("?")
        self.assertTrue(shortcut._help_open)
        shortcut._handle_key("q")
        self.assertTrue(shortcut._exit_requested)

    def test_pressed_generate_feedback_requires_a_movable_change(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query())
            app.config_path = Path(directory) / "settings.json"
            app.settings = Settings(take_count=4)
            app._persisted_settings = app.settings
            set_navigation_focus(app, ("generate", None))
            screen = FakeScreen(columns=100)
            app._screen = screen

            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(app.settings.take_count, 3)
            self.assertEqual(
                app._pressed_adjustment, ("navigation", "generate", -1)
            )
            left_label = next(
                line for line, key in navigation_document(app, 100)
                if key == ("generate", None)
            )
            self.assertIn("[ Generate <<3 > takes ]", left_label)

            app._render()
            self.assertTrue(any("[ Generate <<3 > takes ]" in text for _row, _column, text, _attr in screen.drawn))
            self.assertIsNone(app._pressed_adjustment)
            app._render()
            self.assertTrue(any("[ Generate < 3 > takes ]" in text for _row, _column, text, _attr in screen.drawn))

            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(app.settings.take_count, 4)
            right_label = next(
                line for line, key in navigation_document(app, 100)
                if key == ("generate", None)
            )
            self.assertIn("[ Generate < 4>> takes ]", right_label)
            app._render()
            self.assertTrue(any("[ Generate < 4>> takes ]" in text for _row, _column, text, _attr in screen.drawn))
            self.assertIsNone(app._pressed_adjustment)
            app._render()
            self.assertTrue(any("[ Generate < 4 > takes ]" in text for _row, _column, text, _attr in screen.drawn))

            app.settings = Settings(take_count=1)
            app._pressed_adjustment = ("navigation", "generate", 1)
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(app.settings.take_count, 1)
            self.assertIsNone(app._pressed_adjustment)
            left_label = next(
                line for line, key in navigation_document(app, 100)
                if key == ("generate", None)
            )
            self.assertIn("[ Generate < 1 > takes ]", left_label)

            app.settings = Settings(take_count=8)
            app._pressed_adjustment = ("navigation", "generate", -1)
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(app.settings.take_count, 8)
            self.assertIsNone(app._pressed_adjustment)
            right_label = next(
                line for line, key in navigation_document(app, 100)
                if key == ("generate", None)
            )
            self.assertIn("[ Generate < 8 > takes ]", right_label)

            app._handle_key(curses.KEY_UP)
            app._handle_key(curses.KEY_DOWN)
            self.assertEqual(app._navigation.focus_key, ("generate", None))
            idle_label = next(
                line for line, key in navigation_document(app, 100)
                if key == ("generate", None)
            )
            self.assertIn("[ Generate < 8 > takes ]", idle_label)

    def test_settings_feedback_requires_a_movable_change_and_clears_after_render(self):
        app = self.make_app(query=mixed_query())
        app.settings = Settings(style_id=1, speed=0.01, take_count=1, save_text=False)
        styles = (
            SimpleNamespace(id=1, name="Neutral"),
            SimpleNamespace(id=2, name="Sweet"),
        )
        app._open_settings_editor()
        editor = app._editor_controller.editor

        with patch("voiceger_accent_adapter.tui.available_styles", return_value=styles), patch(
            "voiceger_accent_adapter.tui_rendering.available_styles",
            return_value=styles,
        ):
            editor.selection = "style_id"
            app._pressed_adjustment = ("settings", "speed", 1)
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["style_id"], "1")
            self.assertIsNone(app._pressed_adjustment)
            style_left = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "style_id"
            )
            self.assertIn("Style: < 1 Neutral >", style_left)
            value_column = style_left.index("1 Neutral")

            editor.selection = "style_id"
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["style_id"], "2")
            self.assertEqual(app._pressed_adjustment, ("settings", "style_id", 1))
            style_right = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "style_id"
            )
            self.assertIn("Style: < 2 Sweet>>", style_right)
            self.assertEqual(style_right.index("2 Sweet"), value_column)

            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["style_id"], "1")
            style_left_moved = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "style_id"
            )
            self.assertIn("Style: <<1 Neutral >", style_left_moved)

            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["style_id"], "2")
            editor.selection = "style_id"
            app._pressed_adjustment = ("settings", "style_id", -1)
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["style_id"], "2")
            self.assertIsNone(app._pressed_adjustment)
            style_right = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "style_id"
            )
            self.assertIn("Style: < 2 Sweet >", style_right)

            editor.selection = "speed"
            editor.payload["draft_settings"]["speed"] = "0.01"
            app._pressed_adjustment = ("settings", "style_id", 1)
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["speed"], "0.01")
            self.assertIsNone(app._pressed_adjustment)
            speed_left = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "speed"
            )
            self.assertIn("Speed: < 0.01 >", speed_left)

            editor.payload["draft_settings"]["speed"] = "0.50"
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["speed"], "0.49")
            speed_moved_left = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "speed"
            )
            self.assertIn("Speed: <<0.49 >", speed_moved_left)

            editor.payload["draft_settings"]["speed"] = "0.50"
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["speed"], "0.51")
            self.assertEqual(app._pressed_adjustment, ("settings", "speed", 1))
            speed_right = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "speed"
            )
            self.assertIn("Speed: < 0.51>>", speed_right)
            speed_screen = FakeScreen(columns=100)
            app._screen = speed_screen
            app._render()
            self.assertTrue(any("Speed: < 0.51>>" in text for _row, _column, text, _attr in speed_screen.drawn))
            self.assertIsNone(app._pressed_adjustment)
            app._render()
            self.assertTrue(any("Speed: < 0.51 >" in text for _row, _column, text, _attr in speed_screen.drawn))

            editor.selection = "take_count"
            editor.payload["draft_settings"]["take_count"] = "1"
            app._pressed_adjustment = ("settings", "speed", 1)
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["take_count"], "1")
            self.assertIsNone(app._pressed_adjustment)
            take_left = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "take_count"
            )
            self.assertIn("Take count: < 1 >", take_left)

            editor.selection = "take_count"
            editor.payload["draft_settings"]["take_count"] = "8"
            app._pressed_adjustment = ("settings", "take_count", -1)
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["take_count"], "8")
            self.assertIsNone(app._pressed_adjustment)
            take_right = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "take_count"
            )
            self.assertIn("Take count: < 8 >", take_right)

            editor.payload["draft_settings"]["take_count"] = "4"
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["take_count"], "5")
            self.assertEqual(app._pressed_adjustment, ("settings", "take_count", 1))
            take_moved = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "take_count"
            )
            self.assertIn("Take count: < 5>>", take_moved)
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["take_count"], "4")
            take_moved_left = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "take_count"
            )
            self.assertIn("Take count: <<4 >", take_moved_left)

            editor.selection = "save_text"
            editor.payload["draft_settings"]["save_text"] = False
            app._pressed_adjustment = ("settings", "take_count", 1)
            app._handle_key(curses.KEY_LEFT)
            self.assertFalse(editor.payload["draft_settings"]["save_text"])
            self.assertIsNone(app._pressed_adjustment)
            txt_left = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "save_text"
            )
            self.assertIn("TXT sidecar: < OFF >", txt_left)
            editor.selection = "save_text"
            editor.payload["draft_settings"]["save_text"] = True
            app._pressed_adjustment = ("settings", "save_text", -1)
            app._handle_key(curses.KEY_RIGHT)
            self.assertTrue(editor.payload["draft_settings"]["save_text"])
            self.assertIsNone(app._pressed_adjustment)
            txt_right = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "save_text"
            )
            self.assertIn("TXT sidecar: < ON >", txt_right)

            editor.payload["draft_settings"]["save_text"] = False
            app._handle_key(curses.KEY_RIGHT)
            self.assertTrue(editor.payload["draft_settings"]["save_text"])
            self.assertEqual(app._pressed_adjustment, ("settings", "save_text", 1))
            txt_moved = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "save_text"
            )
            self.assertIn("TXT sidecar: < ON>>", txt_moved)
            app._handle_key(curses.KEY_LEFT)
            self.assertFalse(editor.payload["draft_settings"]["save_text"])
            txt_moved_left = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "save_text"
            )
            self.assertIn("TXT sidecar: <<OFF >", txt_moved_left)

            editor.selection = "style_id"
            app._handle_key(curses.KEY_RIGHT)
            app._handle_key(curses.KEY_DOWN)
            self.assertEqual(editor.selection, "speed")
            document, _cursor_line, _cursor_column = editor_document(app, 100)
            speed = next(line for line, key in document if key == "speed")
            self.assertIn("Speed: < 0.51 >", speed)

            screen = FakeScreen(columns=100)
            app._screen = screen
            with patch("voiceger_accent_adapter.tui_rendering.available_styles", return_value=styles):
                app._render()
            self.assertIsNone(app._pressed_adjustment)
            app._render()
            rendered = self.rendered(screen)
            self.assertIn("Speed: < 0.51 >", rendered)
            self.assertNotIn("<<", rendered)
            self.assertNotIn(">>", rendered)

    def test_run_sets_fast_escape_delay_and_keeps_100ms_polling_with_blank_ready_status(self):
        app = self.make_app()
        app._initial_text = "example"
        screen = FakeScreen(keys=("q",))
        with patch(
            "voiceger_accent_adapter.tui.UtteranceSession.from_text",
            return_value=app.session,
        ), patch("voiceger_accent_adapter.tui.curses.set_escdelay") as set_escdelay:
            app.run(screen)

        set_escdelay.assert_called_once_with(25)
        self.assertEqual(screen.timeouts, [100])
        self.assertEqual(app._status, "")

    def test_ordinary_navigation_movement_preserves_existing_status(self):
        app = self.make_app(query=mixed_query())
        app._status = "Saved output.wav."

        while app._navigation.focus_key != ("quit", None):
            app._handle_key(curses.KEY_DOWN)
            self.assertEqual(app._status, "Saved output.wav.")

        self.assertNotIn("selected", app._status.lower())

    def test_left_right_in_navigation_never_change_pronunciation(self):
        app = self.make_app(query=mixed_query(["AA1", "IY0", "ER2"]))
        before = app.session.query.model_dump()
        app._handle_key(curses.KEY_LEFT)
        app._handle_key(curses.KEY_RIGHT)
        self.assertEqual(app.session.query.model_dump(), before)

    def test_modal_text_editor_replaces_navigation_and_its_footer(self):
        app = self.make_app(query=mixed_query())
        set_navigation_focus(app, ("text", None))
        app._handle_key("\n")
        screen = FakeScreen()
        app._screen = screen
        app._render()
        rendered = self.rendered(screen)
        self.assertIn("EDIT TEXT", rendered)
        self.assertNotIn("NAVIGATION", rendered)
        self.assertNotIn("? Help   q Quit", rendered)
        self.assertIn("Enter Apply", rendered)
        self.assertIn("Esc Cancel", rendered)
        self.assertIn("compatible pronunciation is preserved", rendered)
        self.assertIn("Rebuild pronunciation is an explicit Navigation action", rendered)
        self.assertNotIn("rebuild its pronunciation", rendered)
        self.assertNotIn("Apply text and rebuild pronunciation", rendered)
        self.assertNotIn("Cancel and discard text draft", rendered)

    def test_text_editor_applies_existing_session_source_without_reconstruction(self):
        app = self.make_app(query=mixed_query())
        session = app.session
        english_grouping(app, 1)
        self.assertIn(1, app._editor_controller.grouping_cache)
        query = session.query.model_dump()
        set_navigation_focus(app, ("text", None))
        app._open_text_editor("new source")
        with patch(
            "voiceger_accent_adapter.tui.UtteranceSession.from_text",
            side_effect=AssertionError("existing session must be reused"),
        ) as from_text:
            app._handle_key("\n")
        from_text.assert_not_called()
        self.assertIs(app.session, session)
        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(app._navigation.focus_key, ("text", None))
        self.assertEqual(session.replace_source_text_calls, ["new source"])
        self.assertEqual(session.replace_query_calls, [])
        self.assertEqual(session.query.model_dump(), query)
        self.assertEqual(app._editor_controller.grouping_cache, {})
        self.assertIsNone(app._operations.current_take)

    def test_text_editor_close_restores_remembered_segment_after_source_reset(self):
        app = self.make_app(query=mixed_query())
        set_navigation_focus(app, ("segment", 1))
        app._open_text_editor("updated source")
        app._handle_key("\n")

        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(app._navigation.focus_key, ("segment", 1))
        self.assertEqual(app._navigation.segment_index, 1)

        app.session.candidates = (candidate(3),)
        app._operations.play_take = Mock(return_value=())
        focus_candidate(app, 3)
        app._handle_key("\x1b")
        self.assertEqual(app._navigation.focus_key, ("segment", 1))

    def test_same_signature_text_change_displays_updated_source_with_preserved_pronunciation(self):
        app = self.make_app(query=mixed_query())
        app.session.segment_texts_after_source_change = ["新しい日本語", "new English"]
        original_phones = app.session.query.voicegerSegments[1].phonemes[:]
        app._open_text_editor("新しい日本語 new English")
        app._handle_key("\n")

        rows = navigation_document(app, 100)
        rendered = "\n".join(line for line, _key in rows)
        self.assertIn("新しい日本語", rendered)
        self.assertIn("new English", rendered)
        self.assertIn("ア'", rendered)
        self.assertEqual(app.session.query.voicegerSegments[1].phonemes, original_phones)
        self.assertFalse(app.session.pronunciation_needs_rebuild)

    def test_rebuild_required_text_hides_old_segments_and_fails_closed(self):
        app = self.make_app(query=mixed_query())
        app.session.rebuild_required_for_source = True
        app._open_text_editor("new-source-signature")
        app._handle_key("\n")

        items = navigation_items(app)
        rows = navigation_document(app, 80)
        rendered = "\n".join(line for line, _key in rows)
        self.assertNotIn(("segment", 0), items)
        self.assertNotIn(("segment", 1), items)
        self.assertIn(("rebuild", None), items)
        self.assertIn(("generate", None), items)
        self.assertIn("Pronunciation   Rebuild required", rendered)
        self.assertNotIn("JA |", rendered)
        self.assertNotIn("EN |", rendered)
        self.assertNotIn("[Enter: Edit]", rendered)

        set_navigation_focus(app, ("generate", None))
        app._handle_key("\n")
        self.assertIn("must be rebuilt", app._status)

    def test_explicit_rebuild_stops_playback_resets_transients_and_focuses_segment(self):
        app = self.make_app(query=mixed_query())
        app.session.pronunciation_needs_rebuild = True
        app._editor_controller.grouping_cache[1] = english_grouping(app, 1)
        app._operations.current_take = 2
        events = []
        app._operations.stop_playback = Mock(side_effect=lambda: events.append("stop"))
        original_rebuild = app.session.rebuild_pronunciation

        def rebuild():
            events.append("rebuild")
            original_rebuild()

        app.session.rebuild_pronunciation = Mock(side_effect=rebuild)
        set_navigation_focus(app, ("rebuild", None))
        app._handle_key("\n")

        self.assertEqual(events, ["stop", "rebuild"])
        self.assertEqual(app._editor_controller.grouping_cache, {})
        self.assertIsNone(app._operations.current_take)
        self.assertEqual(app._navigation.segment_index, 0)
        self.assertEqual(app._navigation.focus_key, ("segment", 0))
        self.assertIn("Pronunciation rebuilt", app._status)

    def test_failed_explicit_rebuild_preserves_query_and_required_state(self):
        app = self.make_app(query=mixed_query())
        app.session.pronunciation_needs_rebuild = True
        app._operations.current_take = 2
        query = app.session.query.model_dump()
        app.session.rebuild_error = RuntimeError("analysis failed")
        set_navigation_focus(app, ("rebuild", None))
        app._handle_key("\n")

        self.assertEqual(app.session.query.model_dump(), query)
        self.assertTrue(app.session.pronunciation_needs_rebuild)
        self.assertEqual(app._operations.current_take, 2)
        self.assertIn("analysis failed", app._status)

    def test_text_apply_failure_preserves_draft_and_remains_editable(self):
        app = self.make_app(query=mixed_query())
        app._open_text_editor("bad draft")
        editor = app._editor_controller.editor
        app.session.replace_source_text = Mock(
            side_effect=ValueError("source replacement failed")
        )
        app._handle_key("\n")
        self.assertIs(app._editor_controller.editor, editor)
        self.assertEqual(editor.active_field, "draft")
        self.assertEqual(editor.input_value, "bad draft")
        self.assertEqual(editor.payload["draft"], "bad draft")
        self.assertIn("source replacement failed", editor.error)
        app._handle_key("!")
        self.assertEqual(editor.input_value, "bad draft!")

    def test_japanese_modal_accepts_literal_markers_and_ordinary_cursor_motion(self):
        app = self.make_app(query=mixed_query())
        app._edit_selected_segment(0)
        editor = app._editor_controller.editor
        self.assertEqual(editor.kind, "japanese")
        editor.input_value = "ア'メ。"
        editor.input_cursor = len(editor.input_value)
        app._handle_key(curses.KEY_LEFT)
        self.assertEqual(editor.input_cursor, len("ア'メ"))
        app._handle_key("/")
        self.assertEqual(editor.input_value, "ア'メ/。")
        app._handle_key(curses.KEY_LEFT)
        app._handle_key("'")
        self.assertEqual(editor.input_value, "ア'メ'/。")
        self.assertEqual(editor.active_field, "draft")

    def test_japanese_editor_applies_on_single_enter_from_active_input(self):
        app = self.make_app(query=mixed_query())
        app._edit_selected_segment(0)
        editor = app._editor_controller.editor
        self.assertEqual(editor.kind, "japanese")
        editor.input_value = editor.payload["draft"]
        app._handle_key("\n")
        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(app._navigation.focus_key, ("segment", 0))
        self.assertEqual(len(app.session.replace_query_calls), 1)

    def test_settings_are_reachable_and_editable_without_shortcuts(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query())
            app.config_path = Path(directory) / "config.json"
            app._handle_key("\n")
            self.assertEqual(app._editor_controller.editor.kind, "settings")
            app._editor_controller.editor.selection = "take_count"
            app._handle_key("\n")
            app._handle_key(curses.KEY_BACKSPACE)
            app._handle_key("2")
            app._handle_key("\n")
            editor = app._editor_controller.editor
            self.assertIsNotNone(editor)
            self.assertEqual(editor.kind, "settings")
            self.assertIsNone(editor.active_field)
            self.assertEqual(app.settings.take_count, 4)
            self.assertFalse(app.config_path.exists())
            for _ in range(3):
                app._handle_key(curses.KEY_DOWN)
            app._handle_key("\n")
            self.assertIsNone(app._editor_controller.editor)
            self.assertEqual(app.settings.take_count, 2)
            self.assertEqual(json.loads(app.config_path.read_text())["take_count"], 2)

    def test_settings_arrows_edit_only_the_draft_and_apply_rows_are_compact(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
            app.config_path = Path(directory) / "settings.json"
            original_settings = app.settings
            app._open_settings_editor()
            editor = app._editor_controller.editor

            editor.selection = "speed"
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["speed"], "1.01")
            editor.payload["draft_settings"]["speed"] = "0.02"
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["speed"], "0.01")
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["speed"], "0.01")

            editor.selection = "take_count"
            editor.payload["draft_settings"]["take_count"] = "8"
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["take_count"], "8")
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["take_count"], "7")

            editor.selection = "save_text"
            app._handle_key(curses.KEY_LEFT)
            self.assertFalse(editor.payload["draft_settings"]["save_text"])
            app._handle_key(curses.KEY_RIGHT)
            self.assertTrue(editor.payload["draft_settings"]["save_text"])
            self.assertEqual(app.settings, original_settings)
            self.assertEqual(app.session.replace_settings_calls, [])
            self.assertEqual(app.session.candidates, (candidate(1),))
            self.assertFalse(app.config_path.exists())

            screen = FakeScreen()
            app._screen = screen
            app._render()
            rendered = self.rendered(screen)
            for label in ("Style:", "Speed:", "Take count:", "Output directory:", "TXT sidecar:"):
                self.assertIn(label, rendered)
            self.assertIn("Apply and save settings", rendered)
            self.assertNotIn("[Enter: Edit]", rendered)
            self.assertNotIn("[Enter: Toggle]", rendered)
            self.assertNotIn("Cancel and discard settings", rendered)
            self.assertNotIn("↑/↓ Select field/action", rendered)
            self.assertNotIn(22, [row for row, _column, _text, _attr in screen.drawn])

    def test_settings_style_arrows_follow_available_order_without_wrapping(self):
        styles = (
            SimpleNamespace(id=2, name="Sweet"),
            SimpleNamespace(id=4, name="Sexy"),
            SimpleNamespace(id=7, name="Exhausted"),
        )
        app = self.make_app()
        app._open_settings_editor("style_id")
        editor = app._editor_controller.editor
        editor.payload["draft_settings"]["style_id"] = "4"
        with patch("voiceger_accent_adapter.tui.available_styles", return_value=styles):
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["style_id"], "7")
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["style_id"], "7")
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["style_id"], "4")
            editor.payload["draft_settings"]["style_id"] = "2"
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["style_id"], "2")

    def test_generate_arrows_persist_count_clear_old_batch_and_respect_bounds_and_busy(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
            app.config_path = Path(directory) / "settings.json"
            set_navigation_focus(app, ("generate", None))
            app._status = ""
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(app.settings.take_count, 3)
            self.assertEqual(app.session.replace_settings_calls[-1].take_count, 3)
            self.assertEqual(app.session.candidates, ())
            self.assertEqual(app._navigation.focus_key, ("generate", None))
            self.assertEqual(app._status, "")
            self.assertEqual(json.loads(app.config_path.read_text())["take_count"], 3)

            app.settings = Settings(take_count=1)
            app._persisted_settings = app.settings
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(app.settings.take_count, 1)
            app.settings = Settings(take_count=8)
            app._persisted_settings = app.settings
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(app.settings.take_count, 8)

            app._operations.busy = True
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(app.settings.take_count, 8)
            self.assertIn("Wait for the current synthesis operation to finish", app._status)

    def test_settings_escape_from_active_field_discards_the_entire_modal_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query())
            app.config_path = Path(directory) / "config.json"
            original_settings = app.settings
            app._open_settings_editor("speed")
            editor = app._editor_controller.editor
            editor.payload["draft_settings"]["take_count"] = "2"
            app._handle_key("\n")
            self.assertEqual(editor.active_field, "speed")
            app._handle_key("9")
            app._handle_key("\x1b")
            self.assertIsNone(app._editor_controller.editor)
            self.assertEqual(app.settings, original_settings)
            self.assertEqual(app.session.replace_settings_calls, [])
            self.assertFalse(app.config_path.exists())

    def test_candidate_focus_arrows_play_and_escape_returns_to_last_segment(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1), candidate(2)))
        app._navigation.segment_index = 1
        app._operations.play_take = Mock(return_value=())
        focus_candidate(app, 1)
        app._handle_key(curses.KEY_DOWN)
        self.assertEqual(app._navigation.focus_key, ("candidate", 2))
        self.assertEqual(app._operations.current_take, 2)
        app._handle_key(" ")
        app._operations.play_take.assert_has_calls(
            [call(app.session, 1), call(app.session, 2), call(app.session, 2)]
        )
        app._handle_key("\x1b")
        self.assertEqual(app._navigation.focus_key, ("segment", 1))
        self.assertEqual(app._operations.current_take, 2)

    def test_acceptance_and_regeneration_are_unavailable_while_busy_but_replay_works(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        app._operations.play_take = Mock(return_value=())
        app._operations.start_generation = Mock(return_value=())
        app._operations.start_regenerate_all = Mock(return_value=())
        app._operations.start_regeneration = Mock(return_value=())
        app._operations.busy = True

        for key in (
            ("text", None),
            ("segment", 0),
            ("generate", None),
            ("settings_summary", None),
            ("output", None),
            ("rebuild", None),
        ):
            set_navigation_focus(app, key)
            app._handle_key("\n")
            self.assertIsNone(app._editor_controller.editor)

        focus_candidate(app, 1)
        app._handle_key("\n")
        self.assertEqual(app.session.accept_calls, [])
        app._operations.start_generation.assert_not_called()
        app._operations.start_regenerate_all.assert_not_called()
        app._operations.start_regeneration.assert_not_called()
        set_navigation_focus(app, ("candidate", 1))
        app._handle_key(" ")
        app._operations.play_take.assert_called_with(app.session, 1)

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
        app._operations.play_take = Mock(return_value=())
        focus_candidate(app, 1)
        app._handle_key("\n")
        self.assertEqual(app.session.accept_calls, [1])
        self.assertEqual(app._navigation.focus_key, ("segment", 0))

    def test_word_phoneme_edit_rebuilds_marker_rows_and_keeps_punctuation(self):
        phones = ["HH", "AY1", "!", "DH", "EH1", "R"]
        groups = (("Hi", ("HH", "AY1")), ("!", ("!",)), ("There", ("DH", "EH1", "R")))
        app = self.make_app(query=english_query(phones, text="Hi! There"), groups=groups)
        app._edit_selected_segment(0)
        app._handle_key("\n")
        word_editor = app._editor_controller.editor
        self.assertEqual(word_editor.kind, "english_word")
        self.assertEqual(word_editor.payload["draft_state"].primary_stress_vowel_positions, (0,))
        app._handle_key("\n")
        app._editor_controller.editor.input_value = "HH AA M"
        app._editor_controller.editor.input_cursor = len(app._editor_controller.editor.input_value)
        app._handle_key("\n")
        state = app._editor_controller.editor.payload["draft_state"]
        self.assertEqual(state.base_phonemes, ("HH", "AA", "M"))
        self.assertEqual(state.primary_stress_vowel_positions, (0,))
        # A new vowel ordinal keeps the existing secondary marker where possible.
        app._editor_controller.editor.payload["draft_state"] = self.english_phoneme_state(["AA1", "IH2"])
        app._editor_controller.editor.selection = "phonemes"
        app._handle_key("\n")
        app._editor_controller.editor.input_value = "AA K IH"
        app._handle_key("\n")
        self.assertEqual(app._editor_controller.editor.payload["draft_state"].secondary_stress_vowel_positions, (1,))
        app._editor_controller.editor.selection = "done"
        app._handle_key("\n")
        parent = app._editor_controller.editor
        self.assertEqual(parent.payload["groups"][0].phonemes, ("AA1", "K", "IH2"))
        self.assertEqual(parent.payload["groups"][1].phonemes, ("!",))
        # Segment-level Apply writes only the flat canonical sequence.
        parent.selection = "apply"
        app._handle_key("\n")
        self.assertEqual(
            app.session.query.voicegerSegments[0].phonemes,
            ["AA1", "K", "IH2", "!", "DH", "EH1", "R"],
        )

    def test_enter_finishes_phonemes_into_word_draft_and_keeps_stress_editable(self):
        app = self.make_app(
            query=english_query(["HH", "AY1"], text="Hi"),
            groups=(("Hi", ("HH", "AY1")),),
        )
        original_query = app.session.query.model_dump()
        app._edit_selected_segment(0)
        parent = app._editor_controller.editor
        app._handle_key("\n")
        word_editor = app._editor_controller.editor
        app._handle_key("\n")
        word_editor.input_value = "HH AA K IY"
        word_editor.input_cursor = len(word_editor.input_value)
        app._handle_key("\n")

        self.assertIs(app._editor_controller.editor, word_editor)
        self.assertIsNone(word_editor.active_field)
        self.assertEqual(
            word_editor.payload["draft_state"].base_phonemes,
            ("HH", "AA", "K", "IY"),
        )
        self.assertEqual(parent.payload["groups"][0].phonemes, ("HH", "AY1"))
        word_editor.selection = ("primary", 0)
        app._handle_key("\n")
        app._handle_key(curses.KEY_RIGHT)
        app._handle_key("\n")
        self.assertEqual(
            word_editor.payload["draft_state"].primary_stress_vowel_positions,
            (1,),
        )
        self.assertIs(app._editor_controller.editor, word_editor)
        self.assertEqual(app.session.query.model_dump(), original_query)

    def test_escape_from_active_phoneme_input_cancels_the_word_editor_in_one_press(self):
        app = self.make_app(
            query=english_query(["HH", "AY1"], text="Hi"),
            groups=(("Hi", ("HH", "AY1")),),
        )
        app._edit_selected_segment(0)
        parent = app._editor_controller.editor
        original_groups = parent.payload["groups"]
        original_query = app.session.query.model_dump()
        app._handle_key("\n")
        word_editor = app._editor_controller.editor
        app._handle_key("\n")
        word_editor.input_value = "HH AA M"
        app._handle_key("\x1b")
        self.assertIs(app._editor_controller.editor, parent)
        self.assertEqual(parent.payload["groups"], original_groups)
        self.assertEqual(app.session.query.model_dump(), original_query)

    def test_escape_from_english_segment_discards_word_draft_to_navigation(self):
        app = self.make_app(
            query=english_query(["HH", "AY1"], text="Hi"),
            groups=(("Hi", ("HH", "AY1")),),
        )
        set_navigation_focus(app, ("segment", 0))
        original_query = app.session.query.model_dump()
        app._edit_selected_segment(0)
        parent = app._editor_controller.editor
        app._handle_key("\n")
        app._handle_key("\n")
        word_editor = app._editor_controller.editor
        word_editor.input_value = "HH AA"
        app._handle_key("\n")
        word_editor.selection = "done"
        app._handle_key("\n")
        self.assertIs(app._editor_controller.editor, parent)
        self.assertNotEqual(parent.payload["groups"][0].phonemes, ("HH", "AY1"))
        app._handle_key("\x1b")
        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(app._navigation.focus_key, ("segment", 0))
        self.assertEqual(app.session.query.model_dump(), original_query)

    @staticmethod
    def english_phoneme_state(phonemes):
        from voiceger_accent_adapter.english_stress import english_phonemes_to_editor_state

        return english_phonemes_to_editor_state(phonemes)

    def test_primary_markers_are_independent_and_occupied_destination_fails_closed(self):
        groups = (("word", ("AA1", "K", "IY1", "ER2")),)
        app = self.make_app(query=english_query(groups[0][1]), groups=groups)
        app._edit_selected_segment(0)
        app._handle_key("\n")
        editor = app._editor_controller.editor
        editor.selection = ("primary", 1)
        app._handle_key("\n")
        app._handle_key(curses.KEY_LEFT)
        app._handle_key("\n")
        self.assertIn("already has primary stress", editor.error)
        self.assertEqual(editor.payload["draft_state"].primary_stress_vowel_positions, (0, 1))
        app._handle_key(curses.KEY_RIGHT)
        app._handle_key(curses.KEY_RIGHT)
        app._handle_key("\n")
        self.assertEqual(editor.payload["draft_state"].primary_stress_vowel_positions, (0, 2))
        editor.selection = ("primary", 0)
        app._handle_key("\n")
        app._handle_key(curses.KEY_RIGHT)
        app._handle_key("\n")
        self.assertEqual(editor.payload["draft_state"].primary_stress_vowel_positions, (1, 2))

    def test_group_cache_tracks_token_count_changes_without_realigning(self):
        app = self.make_app(
            query=english_query(["HH", "AY1"], text="Hi"),
            groups=(("Hi", ("HH", "AY1")),),
        )
        app._edit_selected_segment(0)
        app._handle_key("\n")
        app._handle_key("\n")
        editor = app._editor_controller.editor
        editor.input_value = "HH AA M"
        app._handle_key("\n")
        editor.selection = "done"
        app._handle_key("\n")
        parent = app._editor_controller.editor
        parent.selection = "apply"
        app._handle_key("\n")
        calls = app.adapter.english_word_phoneme_groups.call_count
        cached = english_grouping(app, 0)
        self.assertEqual(cached.groups[0].phonemes, ("HH", "AA1", "M"))
        self.assertEqual(app.adapter.english_word_phoneme_groups.call_count, calls)

    def test_source_changed_cache_reinitializes_only_from_matching_canonical_grouping(self):
        app = self.make_app(
            query=english_query(["HH", "AY1"], text="Hi"),
            groups=(("Hi", ("HH", "AY1")),),
        )
        self.assertEqual(english_grouping(app, 0).source_text, "Hi")
        app.session.query.voicegerSegments[0].text = "Hello"
        app.adapter.english_word_phoneme_groups.return_value = (("Hello", ("HH", "AY1")),)
        grouping = english_grouping(app, 0)
        self.assertEqual(grouping.source_text, "Hello")
        self.assertEqual(app.adapter.english_word_phoneme_groups.call_count, 2)

    def test_query_replacement_clears_a_group_cache_when_its_flat_mapping_changes(self):
        app = self.make_app(
            query=english_query(["HH", "AY1"], text="Hi"),
            groups=(("Hi", ("HH", "AY1")),),
        )
        english_grouping(app, 0)
        updated = app.session.query.model_copy(deep=True)
        updated.voicegerSegments[0].phonemes = ["HH", "AA1"]
        app._apply_session_query(updated)
        self.assertNotIn(0, app._editor_controller.grouping_cache)

    def test_shortcuts_are_typed_data_while_raw_input_is_active(self):
        app = self.make_app(query=mixed_query())
        app._open_text_editor("abc")
        original_settings = app.settings
        for key in ("q", "?", "s", "x", "t", "1", curses.KEY_F5):
            app._handle_key(key)
        self.assertFalse(app._exit_requested)
        self.assertTrue(app.settings is original_settings)
        self.assertEqual(app._editor_controller.editor.input_value, "abcq? sxt1".replace(" ", ""))

    def test_navigation_shortcuts_open_the_same_visible_actions(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        app._handle_key("t")
        self.assertEqual(app._editor_controller.editor.kind, "text")
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
        )

        settings_shortcut = self.make_app(query=mixed_query())
        settings_shortcut._handle_key("s")
        self.assertEqual(settings_shortcut._editor_controller.editor.kind, "settings")
        self.assertEqual(settings_shortcut._editor_controller.editor.selection, "style_id")

        help_shortcut = self.make_app(query=mixed_query())
        help_shortcut._handle_key("?")
        self.assertTrue(help_shortcut._help_open)

        quit_shortcut = self.make_app(query=mixed_query())
        quit_shortcut._handle_key("q")
        self.assertTrue(quit_shortcut._exit_requested)

    def test_initial_candidate_autoplays_only_if_focus_did_not_move(self):
        first, second = candidate(1), candidate(2)
        app = self.make_app(candidates=(first,))
        app._operations.worker_operation = "initial"
        app._operations.operation_total = 2
        app._operations.busy = True
        app._operations.play_take = Mock(return_value=())
        app._operations.events.put(("candidate", first))
        app._consume_events()
        self.assertEqual(app._navigation.focus_key, ("candidate", 1))
        app._operations.play_take.assert_called_once_with(app.session, 1)

        moved = self.make_app(candidates=(first,))
        moved._operations.worker_operation = "initial"
        moved._operations.operation_total = 2
        moved._operations.busy = True
        moved._operations.play_take = Mock(return_value=())
        focus_candidate(moved, 1)
        set_navigation_focus(moved, ("settings_summary", None), moved=True)
        moved._operations.events.put(("candidate", second))
        moved._consume_events()
        self.assertEqual(moved._navigation.focus_key, ("settings_summary", None))
        moved._operations.play_take.assert_called_once_with(moved.session, 1)

    def test_manual_candidate_selection_during_initial_generation_is_retained(self):
        first, second, third = candidate(1), candidate(2), candidate(3)
        app = self.make_app(candidates=(first,))
        app._operations.worker_operation = "initial"
        app._operations.operation_total = 3
        app._operations.busy = True
        app._operations.play_take = Mock(return_value=())
        focus_candidate(app, 1)
        app.session.candidates = (first, second)
        focus_candidate(app, 2)
        app.session.candidates = (first, second, third)
        app._operations.events.put(("candidate", third))
        app._consume_events()
        self.assertEqual(app._operations.current_take, 2)
        self.assertEqual(app._navigation.focus_key, ("candidate", 2))
        self.assertEqual(
            app._operations.play_take.call_args_list,
            [call(app.session, 1), call(app.session, 2)],
        )

    def test_initial_generation_failure_discards_partial_batch_and_returns_to_segment(self):
        first = candidate(1)
        app = self.make_app(candidates=(first,))
        app._operations.worker_operation = "initial"
        app._operations.operation_total = 1
        app._operations.busy = True
        app._operations.play_take = Mock(return_value=())
        app._operations.stop_playback = Mock()
        error = RuntimeError("second synthesis failed")
        app._operations.events.put(("candidate", first))
        app._operations.events.put(("error", error))
        app._operations.events.put(("done", None))
        app._consume_events()
        self.assertEqual(app.session.discard_calls, 1)
        self.assertEqual(app.session.candidates, ())
        self.assertIsNone(app._operations.current_take)
        self.assertEqual(app._navigation.focus_key, ("segment", 0))
        self.assertIn("second synthesis failed", app._status)
        app._operations.stop_playback.assert_called_once_with()

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
            app._change_settings(take_count=2)
        self.assertEqual(events, ["stop", "settings"])

    def test_source_replacement_stops_playback_before_session_invalidation(self):
        app = self.make_app(query=mixed_query())
        english_grouping(app, 1)
        events = []
        session = app.session
        app._operations.stop_playback = Mock(side_effect=lambda: events.append("stop"))
        session.replace_source_text = Mock(
            side_effect=lambda source: events.append("replace")
        )
        app._open_text_editor("new source")
        app._editor_controller.editor.payload["draft"] = "new source"
        app._editor_controller.editor.active_field = None
        app._dispatch_editor_intents(
            app._editor_controller.apply(
                app.settings,
                app.session.query,
                app.session.source_text,
            )
        )
        self.assertEqual(events, ["stop", "replace"])
        self.assertIs(app.session, session)
        self.assertEqual(app._editor_controller.grouping_cache, {})

    def test_busy_shutdown_drains_worker_before_playback_and_session_cleanup(self):
        app = self.make_app()
        app._initial_text = "example"
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
            "voiceger_accent_adapter.tui.UtteranceSession.from_text",
            return_value=app.session,
        ):
            app.run(screen)
        self.assertFalse(app._operations.busy)
        self.assertEqual(
            cleanup_order,
            ["worker-finished", "playback-stopped", "session-closed"],
        )

    def test_run_exception_joins_worker_before_cleanup(self):
        app = self.make_app()
        app._initial_text = "example"
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
            "voiceger_accent_adapter.tui.UtteranceSession.from_text",
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
