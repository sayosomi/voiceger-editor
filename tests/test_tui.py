import curses
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event, Thread
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from voiceger_accent_adapter.settings import Settings
from voiceger_accent_adapter.tui import (
    _HELP_ITEMS,
    _adjustable_value,
    TuiApp,
    build_argument_parser,
    format_english_phonemes,
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

    def test_english_display_hides_stress_digits_and_marks_primary_anchors(self):
        rendered = format_english_phonemes(
            ["V", "OY1", "AH0", "JH", "ER2"],
            selected_primary=0,
        )
        self.assertEqual(rendered, "V ▶[OY] AH JH ER")
        self.assertNotIn("0", rendered)
        self.assertNotIn("1", rendered)
        self.assertNotIn("2", rendered)

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

    def test_one_navigation_order_covers_every_action(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1), candidate(2)))
        app._current_take = 2
        self.assertEqual(
            app._navigation_items(),
            [
                ("settings_summary", None),
                ("output", None),
                ("text", None),
                ("segment", 0),
                ("segment", 1),
                ("rebuild", None),
                ("generate", None),
                ("candidate", 1),
                ("candidate", 2),
                ("settings", None),
                ("help", None),
                ("quit", None),
            ],
        )

    def test_top_settings_and_output_rows_are_selectable_and_focused(self):
        app = self.make_app(query=mixed_query())
        screen = FakeScreen()
        app._screen = screen

        app._set_focus_key(("settings_summary", None))
        app._render()
        summary = next(item for item in screen.drawn if item[0] == 1)
        self.assertTrue(summary[2].startswith("▶ Style 1"))
        self.assertTrue(summary[3] & curses.A_REVERSE)

        app._set_focus_key(("output", None))
        app._render()
        output = next(item for item in screen.drawn if item[0] == 2)
        self.assertTrue(output[2].startswith("▶ Output:"))
        self.assertTrue(output[3] & curses.A_REVERSE)
        self.assertIn(("settings", None), app._navigation_items())
        self.assertEqual(
            app._navigation_items()[-3:],
            [("settings", None), ("help", None), ("quit", None)],
        )

    def test_settings_summary_opens_style_and_output_opens_path_input(self):
        app = self.make_app(query=mixed_query())
        app._set_focus_key(("settings_summary", None))
        app._handle_key("\n")
        self.assertEqual(app._editor.selection, "style_id")
        self.assertIsNone(app._editor.active_field)

        app._cancel_editor()
        app._set_focus_key(("output", None))
        app._handle_key("\n")
        self.assertEqual(app._editor.selection, "output_dir")
        self.assertEqual(app._editor.active_field, "output_dir")

        app._cancel_editor()
        app._set_focus_key(("settings", None))
        app._handle_key("\n")
        self.assertEqual(app._editor.selection, "style_id")
        self.assertIsNone(app._editor.active_field)

    def test_navigation_is_nonwrapping_at_both_ends(self):
        app = self.make_app(query=mixed_query())
        app._set_focus_key(("settings_summary", None))
        app._handle_key(curses.KEY_UP)
        self.assertEqual(app._focus_key, ("settings_summary", None))
        app._set_focus_key(("quit", None))
        app._handle_key(curses.KEY_DOWN)
        self.assertEqual(app._focus_key, ("quit", None))

    def test_up_and_down_move_one_selectable_item_at_a_time(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1), candidate(2)))
        app._play_take = Mock()
        expected = [
            ("settings_summary", None),
            ("output", None),
            ("text", None),
            ("segment", 0),
            ("segment", 1),
            ("rebuild", None),
        ]
        app._set_focus_key(expected[0])
        for key in expected[1:]:
            app._handle_key(curses.KEY_DOWN)
            self.assertEqual(app._focus_key, key)
        for key in reversed(expected[:-1]):
            app._handle_key(curses.KEY_UP)
            self.assertEqual(app._focus_key, key)

    def test_tab_jumps_through_major_stops_and_clamps_at_quit(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1), candidate(2)))
        app._play_take = Mock()
        stops = [
            ("settings_summary", None),
            ("output", None),
            ("text", None),
            ("segment", 0),
            ("rebuild", None),
            ("generate", None),
            ("candidate", 1),
            ("settings", None),
            ("help", None),
            ("quit", None),
        ]
        self.assertEqual(app._major_navigation_stops(), stops)
        app._set_focus_key(stops[0])
        for stop in stops[1:]:
            app._handle_key("\t")
            self.assertEqual(app._focus_key, stop)
        app._handle_key("\t")
        self.assertEqual(app._focus_key, stops[-1])

    def test_shift_tab_jumps_backward_through_major_stops_and_clamps_at_settings_summary(self):
        backtab = getattr(curses, "KEY_BTAB", None)
        if backtab is None:
            self.skipTest("curses.KEY_BTAB is not available")
        app = self.make_app(query=mixed_query(), candidates=(candidate(1), candidate(2)))
        app._play_take = Mock()
        stops = [
            ("settings_summary", None),
            ("output", None),
            ("text", None),
            ("segment", 0),
            ("rebuild", None),
            ("generate", None),
            ("candidate", 1),
            ("settings", None),
            ("help", None),
            ("quit", None),
        ]
        app._set_focus_key(stops[-1])
        for stop in reversed(stops[:-1]):
            app._handle_key(backtab)
            self.assertEqual(app._focus_key, stop)
        app._handle_key(backtab)
        self.assertEqual(app._focus_key, stops[0])

    def test_tab_and_shift_tab_treat_all_pronunciation_rows_as_one_stop(self):
        backtab = getattr(curses, "KEY_BTAB", None)
        if backtab is None:
            self.skipTest("curses.KEY_BTAB is not available")
        app = self.make_app(query=mixed_query())
        for segment_index in (0, 1):
            app._set_focus_key(("segment", segment_index))
            app._handle_key("\t")
            self.assertEqual(app._focus_key, ("rebuild", None))
            app._set_focus_key(("segment", segment_index))
            app._handle_key(backtab)
            self.assertEqual(app._focus_key, ("text", None))

    def test_rebuild_required_state_skips_editable_pronunciation_tab_stop(self):
        app = self.make_app(query=mixed_query())
        app.session.pronunciation_needs_rebuild = True
        self.assertNotIn(("segment", 0), app._navigation_items())
        app._set_focus_key(("text", None))
        app._handle_key("\t")
        self.assertEqual(app._focus_key, ("rebuild", None))

    def test_candidates_use_first_available_candidate_as_major_stop(self):
        backtab = getattr(curses, "KEY_BTAB", None)
        if backtab is None:
            self.skipTest("curses.KEY_BTAB is not available")
        app = self.make_app(
            query=mixed_query(), candidates=(candidate(2), candidate(5))
        )
        app._play_take = Mock()
        app._set_focus_key(("generate", None))
        app._handle_key(curses.KEY_DOWN)
        self.assertEqual(app._focus_key, ("candidate", 2))
        app._handle_key(curses.KEY_DOWN)
        self.assertEqual(app._focus_key, ("candidate", 5))
        app._handle_key(curses.KEY_UP)
        self.assertEqual(app._focus_key, ("candidate", 2))
        app._set_focus_key(("generate", None))
        app._handle_key("\t")
        self.assertEqual(app._focus_key, ("candidate", 2))

        for candidate_number in (2, 5):
            app._set_focus_key(("candidate", candidate_number))
            app._handle_key("\t")
            self.assertEqual(app._focus_key, ("settings", None))
            app._set_focus_key(("candidate", candidate_number))
            app._handle_key(backtab)
            self.assertEqual(app._focus_key, ("generate", None))

    def test_candidates_are_skipped_as_a_major_stop_when_none_exist(self):
        app = self.make_app(query=mixed_query())
        app._set_focus_key(("generate", None))
        app._handle_key("\t")
        self.assertEqual(app._focus_key, ("settings", None))
        self.assertFalse(any(name == "candidate" for name, _number in app._navigation_items()))

    def test_text_and_generate_are_reachable_with_only_vertical_arrows(self):
        app = self.make_app(query=mixed_query())
        app._set_focus_key(("settings_summary", None))
        app._handle_key(curses.KEY_UP)
        self.assertEqual(app._focus_key, ("settings_summary", None))
        while app._focus_key != ("generate", None):
            app._handle_key(curses.KEY_DOWN)
        app._start_generation = Mock()
        app._handle_key("\n")
        app._start_generation.assert_called_once_with()

    def test_help_and_quit_actions_activate_from_the_continuous_list(self):
        app = self.make_app(query=mixed_query())
        help_action = next(
            line for line, key in navigation_document(app, 80)
            if key == ("help", None)
        )
        self.assertIn("Help", help_action)
        app._set_focus_key(("help", None))
        app._handle_key("\n")
        self.assertTrue(app._help_open)
        app._handle_key("\x1b")
        app._set_focus_key(("quit", None))
        app._handle_key("\n")
        self.assertTrue(app._exit_requested)

        shortcut = self.make_app(query=mixed_query())
        shortcut._handle_key("?")
        self.assertTrue(shortcut._help_open)
        shortcut._handle_key("q")
        self.assertTrue(shortcut._exit_requested)

    def test_navigation_action_labels_expose_settings_help_and_quit_shortcuts(self):
        app = self.make_app(query=mixed_query())
        labels = {
            key: line
            for line, key in navigation_document(app, 80)
            if key is not None
        }
        self.assertIn("[s]", labels[("settings", None)])
        self.assertIn("[?]", labels[("help", None)])
        self.assertIn("[q]", labels[("quit", None)])

    def test_adjustable_feedback_forms_are_fixed_width_ascii_with_stable_value_column(self):
        for value in ("6", "1.00", "1 Neutral"):
            idle = _adjustable_value(value)
            left = _adjustable_value(value, -1)
            right = _adjustable_value(value, 1)
            self.assertEqual((idle, left, right), (
                f"< {value} >",
                f"<<{value} >",
                f"< {value}>>",
            ))
            self.assertEqual(len(idle), len(left))
            self.assertEqual(len(idle), len(right))
            self.assertEqual((idle.index(value), left.index(value), right.index(value)), (2, 2, 2))
            self.assertTrue(idle.isascii() and left.isascii() and right.isascii())
            self.assertEqual((idle[0], left[0], right[0]), ("<", "<", "<"))
            self.assertEqual((idle[-1], left[-1], right[-1]), (">", ">", ">"))

    def test_idle_generate_and_settings_rows_advertise_adjustable_values(self):
        app = self.make_app(query=mixed_query())
        app.settings = Settings(take_count=6)
        app._set_focus_key(("generate", None))
        generate = next(
            line for line, key in navigation_document(app, 100)
            if key == ("generate", None)
        )
        self.assertIn("[ Generate < 6 > takes ]", generate)

        app.session.candidates = (candidate(1),)
        regenerate = next(
            line for line, key in navigation_document(app, 100)
            if key == ("generate", None)
        )
        self.assertIn("[ Regenerate all < 6 > takes ]", regenerate)

        app._busy = True
        app._worker_operation = "initial"
        app._operation_total = 6
        app._operation_completed = 1
        busy_generate = next(
            line for line, key in navigation_document(app, 100)
            if key == ("generate", None)
        )
        self.assertIn("[ Generating 2/6 ]", busy_generate)
        self.assertNotIn("<", busy_generate)
        self.assertNotIn(">", busy_generate)

        app._worker_operation = "regenerate_all"
        busy_regenerate = next(
            line for line, key in navigation_document(app, 100)
            if key == ("generate", None)
        )
        self.assertIn("[ Regenerating 2/6 ]", busy_regenerate)
        self.assertNotIn("<", busy_regenerate)
        self.assertNotIn(">", busy_regenerate)

        settings = self.make_app(query=mixed_query())
        settings.settings = Settings(
            style_id=1,
            speed=1.0,
            take_count=4,
            output_dir=Path("/tmp/voiceger-output"),
            save_text=True,
        )
        settings._open_settings_editor()
        styles = (SimpleNamespace(id=1, name="Neutral"),)
        with patch("voiceger_accent_adapter.tui_rendering.available_styles", return_value=styles):
            document, _cursor_line, _cursor_column = editor_document(settings, 100)
        rows = {key: line for line, key in document if isinstance(key, str)}
        self.assertIn("Style: < 1 Neutral >", rows["style_id"])
        self.assertIn("Speed: < 1.00 >", rows["speed"])
        self.assertIn("Take count: < 4 >", rows["take_count"])
        self.assertIn("TXT sidecar: < ON >", rows["save_text"])
        self.assertIn("Output directory: /tmp/voiceger-output", rows["output_dir"])
        self.assertNotIn("<", rows["output_dir"])
        self.assertNotIn(">", rows["output_dir"])

        settings._editor = None
        settings._set_focus_key(("settings_summary", None))
        screen = FakeScreen(columns=100)
        settings._screen = screen
        with patch("voiceger_accent_adapter.tui_rendering.available_styles", return_value=styles):
            settings._render()
        summary = next(text for row, _column, text, _attr in screen.drawn if row == 1)
        output = next(text for row, _column, text, _attr in screen.drawn if row == 2)
        self.assertNotIn("<", summary)
        self.assertNotIn(">", summary)
        self.assertNotIn("<", output)
        self.assertNotIn(">", output)

    def test_pressed_generate_feedback_clears_after_render_and_at_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query())
            app.config_path = Path(directory) / "settings.json"
            app.settings = Settings(take_count=1)
            app._persisted_settings = app.settings
            app._set_focus_key(("generate", None))
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(app.settings.take_count, 1)
            left_label = next(
                line for line, key in navigation_document(app, 100)
                if key == ("generate", None)
            )
            self.assertIn("[ Generate <<1 > takes ]", left_label)

            screen = FakeScreen(columns=100)
            app._screen = screen
            app._render()
            self.assertTrue(any("[ Generate <<1 > takes ]" in text for _row, _column, text, _attr in screen.drawn))
            self.assertIsNone(app._pressed_adjustment)
            app._render()
            self.assertTrue(any("[ Generate < 1 > takes ]" in text for _row, _column, text, _attr in screen.drawn))

            app.settings = Settings(take_count=8)
            app._persisted_settings = app.settings
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(app.settings.take_count, 8)
            right_label = next(
                line for line, key in navigation_document(app, 100)
                if key == ("generate", None)
            )
            self.assertIn("[ Generate < 8>> takes ]", right_label)

            app._handle_key(curses.KEY_UP)
            app._handle_key(curses.KEY_DOWN)
            self.assertEqual(app._focus_key, ("generate", None))
            idle_label = next(
                line for line, key in navigation_document(app, 100)
                if key == ("generate", None)
            )
            self.assertIn("[ Generate < 8 > takes ]", idle_label)

    def test_settings_boundary_feedback_and_movement_do_not_leak_between_rows(self):
        app = self.make_app(query=mixed_query())
        app.settings = Settings(style_id=1, speed=0.01, take_count=1, save_text=False)
        styles = (
            SimpleNamespace(id=1, name="Neutral"),
            SimpleNamespace(id=2, name="Sweet"),
        )
        app._open_settings_editor()
        editor = app._editor

        with patch("voiceger_accent_adapter.tui.available_styles", return_value=styles), patch(
            "voiceger_accent_adapter.tui_rendering.available_styles",
            return_value=styles,
        ):
            editor.selection = "style_id"
            app._handle_editor_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["style_id"], "1")
            style_left = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "style_id"
            )
            self.assertIn("Style: <<1 Neutral >", style_left)
            value_column = style_left.index("1 Neutral")

            editor.selection = "style_id"
            editor.payload["draft_settings"]["style_id"] = "2"
            app._handle_editor_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["style_id"], "2")
            style_right = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "style_id"
            )
            self.assertIn("Style: < 2 Sweet>>", style_right)
            self.assertEqual(style_right.index("2 Sweet"), value_column)

            editor.selection = "speed"
            editor.payload["draft_settings"]["speed"] = "0.01"
            app._handle_editor_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["speed"], "0.01")
            speed_left = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "speed"
            )
            self.assertIn("Speed: <<0.01 >", speed_left)
            speed_screen = FakeScreen(columns=100)
            app._screen = speed_screen
            app._render()
            self.assertTrue(any("Speed: <<0.01 >" in text for _row, _column, text, _attr in speed_screen.drawn))
            self.assertIsNone(app._pressed_adjustment)
            app._render()
            self.assertTrue(any("Speed: < 0.01 >" in text for _row, _column, text, _attr in speed_screen.drawn))

            editor.selection = "take_count"
            editor.payload["draft_settings"]["take_count"] = "1"
            app._handle_editor_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["take_count"], "1")
            take_left = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "take_count"
            )
            self.assertIn("Take count: <<1 >", take_left)

            editor.selection = "take_count"
            editor.payload["draft_settings"]["take_count"] = "8"
            app._handle_editor_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["take_count"], "8")
            take_right = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "take_count"
            )
            self.assertIn("Take count: < 8>>", take_right)

            editor.selection = "save_text"
            editor.payload["draft_settings"]["save_text"] = False
            app._handle_editor_key(curses.KEY_LEFT)
            self.assertFalse(editor.payload["draft_settings"]["save_text"])
            txt_left = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "save_text"
            )
            self.assertIn("TXT sidecar: <<OFF >", txt_left)
            editor.selection = "save_text"
            editor.payload["draft_settings"]["save_text"] = True
            app._handle_editor_key(curses.KEY_RIGHT)
            self.assertTrue(editor.payload["draft_settings"]["save_text"])
            txt_right = next(
                line for line, key in editor_document(app, 100)[0]
                if key == "save_text"
            )
            self.assertIn("TXT sidecar: < ON>>", txt_right)

            editor.selection = "style_id"
            app._handle_editor_key(curses.KEY_RIGHT)
            app._handle_editor_key(curses.KEY_DOWN)
            self.assertEqual(editor.selection, "speed")
            document, _cursor_line, _cursor_column = editor_document(app, 100)
            speed = next(line for line, key in document if key == "speed")
            self.assertIn("Speed: < 0.01 >", speed)

            screen = FakeScreen(columns=100)
            app._screen = screen
            with patch("voiceger_accent_adapter.tui_rendering.available_styles", return_value=styles):
                app._render()
            self.assertIsNone(app._pressed_adjustment)
            app._render()
            rendered = self.rendered(screen)
            self.assertIn("Speed: < 0.01 >", rendered)
            self.assertNotIn("<<", rendered)
            self.assertNotIn(">>", rendered)

    def test_help_updates_tab_guidance_and_bolds_only_key_spans(self):
        app = self.make_app(query=mixed_query())
        app._help_open = True
        screen = FakeScreen(columns=100)
        app._screen = screen
        app._render()

        drawn = {(row, column, text): attr for row, column, text, attr in screen.drawn}
        for index, (shortcut, suffix) in enumerate(_HELP_ITEMS):
            if shortcut is None:
                normal_attr = drawn[(2 + index, 1, suffix)]
                self.assertFalse(normal_attr & curses.A_BOLD)
                continue
            shortcut_attr = drawn[(2 + index, 1, shortcut)]
            self.assertTrue(shortcut_attr & curses.A_BOLD)
            suffix_attr = drawn[
                (2 + index, 1 + len(shortcut), suffix)
            ]
            self.assertFalse(suffix_attr & curses.A_BOLD)

        rendered = "\n".join(
            "".join(
                text
                for _row, _column, text, _attr in sorted(
                    (item for item in screen.drawn if item[0] == row),
                    key=lambda item: item[1],
                )
            )
            for row in sorted({item[0] for item in screen.drawn})
        )
        self.assertIn("Up/Down: move one selectable Navigation item at a time", rendered)
        self.assertIn("Tab: move to the next major section/action", rendered)
        self.assertIn("Shift+Tab: move to the previous major section/action", rendered)
        self.assertNotIn("Tab: move down one action", rendered)
        footer = next(
            (row, text, attr)
            for row, _column, text, attr in screen.drawn
            if "Return to Navigation" in text
        )
        self.assertEqual(footer[0], screen.rows - 2)
        self.assertEqual(footer[1], "Esc / Enter / ? Return to Navigation  |  q Quit")
        self.assertTrue(footer[2] & curses.A_BOLD)

    def test_help_explanations_wrap_without_reaching_the_footer(self):
        app = self.make_app(query=mixed_query())
        app._help_open = True
        screen = FakeScreen(rows=60, columns=40)
        app._screen = screen
        app._render()

        first_item = [item for item in screen.drawn if item[0] in (2, 3)]
        self.assertIn((2, 1, "Up/Down", curses.A_BOLD), first_item)
        self.assertTrue(any(row == 2 and column > 1 for row, column, _text, _attr in first_item))
        explanation = "".join(
            text for row, column, text, _attr in first_item
            if column > 1 and row in (2, 3)
        )
        self.assertIn("item at a time", explanation)
        self.assertTrue(
            all(
                not (attr & curses.A_BOLD)
                for _row, column, _text, attr in first_item
                if column > 1
            )
        )
        self.assertTrue(
            all(
                row < screen.rows - 2
                for row, _column, text, _attr in screen.drawn
                if row >= 2 and "Return to Navigation" not in text
            )
        )

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

        while app._focus_key != ("quit", None):
            app._handle_key(curses.KEY_DOWN)
            self.assertEqual(app._status, "Saved output.wav.")

        self.assertNotIn("selected", app._status.lower())

    def test_pronunciation_rows_are_compact_selectable_actions(self):
        app = self.make_app(query=mixed_query(["HH", "AH1"]))
        app._set_focus_key(("segment", 0))
        rows = navigation_document(app, 80)
        labels = {key: line for line, key in rows if key is not None}

        self.assertEqual(labels[("segment", 0)], "▶ JA | 雨 | ア'")
        self.assertEqual(labels[("segment", 1)], "  EN | hello | HH [AH]")
        self.assertNotIn("segment 1", "\n".join(line for line, _key in rows))
        self.assertNotIn("segment 2", "\n".join(line for line, _key in rows))
        self.assertNotIn("[Enter: Edit]", labels[("segment", 0)])
        self.assertNotIn("[Enter: Edit]", labels[("segment", 1)])

        app._handle_key("\n")
        self.assertEqual(app._editor.kind, "japanese")
        app._editor = None
        app._set_focus_key(("segment", 1))
        app._handle_key("\n")
        self.assertEqual(app._editor.kind, "english_segment")

    def test_text_is_one_selectable_wrapped_row_without_source_or_edit_metadata(self):
        source = "今日はhelloと言うよ。" * 8
        app = self.make_app(query=mixed_query())
        app.session.source_text = source
        app._set_focus_key(("text", None))
        rows = navigation_document(app, 24)
        text_rows = [(line, key) for line, key in rows if key == ("text", None)]
        text_index = next(i for i, (_line, key) in enumerate(rows) if key == ("text", None))
        continuations = []
        for line, key in rows[text_index + 1:]:
            if key is not None:
                break
            if line.startswith(" " * len("▶ Text : ")):
                continuations.append(line.strip())
            else:
                break

        self.assertEqual(len(text_rows), 1)
        self.assertTrue(text_rows[0][0].startswith("▶ Text : "))
        self.assertEqual("".join([text_rows[0][0].removeprefix("▶ Text : ").strip(), *continuations]), source)
        visible = "\n".join(line for line, _key in rows)
        self.assertNotIn("Source:", visible)
        self.assertNotIn("[Enter: Edit]", visible)

    def test_no_candidates_are_rendered_on_one_compact_line(self):
        app = self.make_app(query=mixed_query())
        rows = navigation_document(app, 80)
        self.assertIn(("Candidates   No candidates yet.", None), rows)
        self.assertEqual(sum("No candidates yet." in line for line, _ in rows), 1)

    def test_navigation_render_has_no_footer_and_leaves_final_row_unused(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        app._status = "Saved output.wav."
        screen = FakeScreen(rows=24)
        app._screen = screen
        app._render()

        rendered = self.rendered(screen)
        self.assertNotIn("↑/↓ Move", rendered)
        self.assertNotIn("? Help", rendered)
        self.assertIn("Status: Saved output.wav.", rendered)
        self.assertIn(22, [row for row, _column, _text, _attr in screen.drawn])
        self.assertNotIn(23, [row for row, _column, _text, _attr in screen.drawn])

        app._play_take = Mock()
        app._focus_candidate(1)
        app._render()
        candidate_rendered = self.rendered(screen)
        self.assertNotIn("↑/↓ Move", candidate_rendered)
        self.assertNotIn("↑↓ Move/play", candidate_rendered)
        self.assertNotIn("Enter accepts and saves", candidate_rendered)
        self.assertNotIn("? Help", candidate_rendered)
        self.assertNotIn(23, [row for row, _column, _text, _attr in screen.drawn])

    def test_empty_and_error_status_render_in_the_status_row(self):
        app = self.make_app(query=mixed_query())
        screen = FakeScreen(rows=24)
        app._screen = screen

        app._status = ""
        app._render()
        self.assertFalse(any(text.startswith("Status:") for text in self.rendered(screen).splitlines()))
        self.assertTrue(
            any(row == 22 and text == "" for row, _column, text, _attr in screen.drawn)
        )

        app._status = "Error: Voiceger runtime failed."
        app._render()
        self.assertIn("Error: Voiceger runtime failed.", self.rendered(screen))
        status_rows = [row for row, _column, text, _attr in screen.drawn if "runtime failed" in text]
        self.assertEqual(status_rows, [22])

    def test_left_right_in_navigation_never_change_pronunciation(self):
        app = self.make_app(query=mixed_query(["AA1", "IY0", "ER2"]))
        before = app.session.query.model_dump()
        app._handle_key(curses.KEY_LEFT)
        app._handle_key(curses.KEY_RIGHT)
        self.assertEqual(app.session.query.model_dump(), before)

    def test_only_focused_navigation_action_gets_focus_attribute(self):
        app = self.make_app(query=mixed_query())
        app._set_focus_key(("segment", 1))
        screen = FakeScreen()
        app._screen = screen
        app._render()
        focused = [
            row
            for row, _column, _text, attr in screen.drawn
            if attr & curses.A_REVERSE
        ]
        self.assertEqual(len(focused), 1)

    def test_modal_text_editor_replaces_navigation_and_its_footer(self):
        app = self.make_app(query=mixed_query())
        app._set_focus_key(("text", None))
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

    def test_text_entry_supports_cursor_backspace_delete_and_vertical_wrapping(self):
        app = self.make_app(query=mixed_query())
        app._open_text_editor("ab")
        app._screen = FakeScreen(columns=12)
        for key in (curses.KEY_LEFT, "X", curses.KEY_DC, curses.KEY_HOME, "あ"):
            app._handle_editor_key(key)
        self.assertEqual(app._editor.input_value, "あaX")
        app._editor.input_value = "abcdefghijklmnopqrstuvw"
        app._editor.input_cursor = 5
        screen = FakeScreen(columns=12)
        app._screen = screen
        app._render()
        input_rows = [
            (row, text)
            for row, _column, text, _attr in screen.drawn
            if text.startswith("▶ Input:")
            or (text.startswith(" " * len("▶ Input: ")) and text.strip())
        ]
        self.assertGreater(len(input_rows), 2)
        self.assertIsNotNone(screen.cursor)
        before = app._editor.input_cursor
        app._handle_editor_key(curses.KEY_DOWN)
        self.assertEqual(app._editor.input_cursor, before + 2)
        app._handle_editor_key(curses.KEY_BACKSPACE)
        self.assertEqual(len(app._editor.input_value), 22)

    def test_text_editor_cancel_discards_unsaved_draft(self):
        app = self.make_app(query=mixed_query())
        original = app.session.source_text
        app._set_focus_key(("text", None))
        app._open_text_editor(original)
        app._handle_editor_key("!")
        app._handle_editor_key("\x1b")
        self.assertIsNone(app._editor)
        self.assertEqual(app._focus_key, ("text", None))
        self.assertEqual(app.session.source_text, original)
        self.assertEqual(app.session.replace_query_calls, [])

    def test_text_editor_applies_existing_session_source_without_reconstruction(self):
        app = self.make_app(query=mixed_query())
        session = app.session
        app._english_grouping(1)
        self.assertIn(1, app._english_groupings)
        query = session.query.model_dump()
        app._set_focus_key(("text", None))
        app._open_text_editor("new source")
        with patch(
            "voiceger_accent_adapter.tui.UtteranceSession.from_text",
            side_effect=AssertionError("existing session must be reused"),
        ) as from_text:
            app._handle_editor_key("\n")
        from_text.assert_not_called()
        self.assertIs(app.session, session)
        self.assertIsNone(app._editor)
        self.assertEqual(app._focus_key, ("text", None))
        self.assertEqual(session.replace_source_text_calls, ["new source"])
        self.assertEqual(session.replace_query_calls, [])
        self.assertEqual(session.query.model_dump(), query)
        self.assertEqual(app._english_groupings, {})
        self.assertIsNone(app._current_take)

    def test_same_signature_text_change_displays_updated_source_with_preserved_pronunciation(self):
        app = self.make_app(query=mixed_query())
        app.session.segment_texts_after_source_change = ["新しい日本語", "new English"]
        original_phones = app.session.query.voicegerSegments[1].phonemes[:]
        app._open_text_editor("新しい日本語 new English")
        app._handle_editor_key("\n")

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
        app._handle_editor_key("\n")

        items = app._navigation_items()
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

        app._set_focus_key(("generate", None))
        app._handle_key("\n")
        self.assertIn("must be rebuilt", app._status)

    def test_explicit_rebuild_stops_playback_resets_transients_and_focuses_segment(self):
        app = self.make_app(query=mixed_query())
        app.session.pronunciation_needs_rebuild = True
        app._english_groupings[1] = app._english_grouping(1)
        app._current_take = 2
        events = []
        app._stop_playback = Mock(side_effect=lambda: events.append("stop"))
        original_rebuild = app.session.rebuild_pronunciation

        def rebuild():
            events.append("rebuild")
            original_rebuild()

        app.session.rebuild_pronunciation = Mock(side_effect=rebuild)
        app._set_focus_key(("rebuild", None))
        app._handle_key("\n")

        self.assertEqual(events, ["stop", "rebuild"])
        self.assertEqual(app._english_groupings, {})
        self.assertIsNone(app._current_take)
        self.assertEqual(app._segment_index, 0)
        self.assertEqual(app._focus_key, ("segment", 0))
        self.assertIn("Pronunciation rebuilt", app._status)

    def test_failed_explicit_rebuild_preserves_query_and_required_state(self):
        app = self.make_app(query=mixed_query())
        app.session.pronunciation_needs_rebuild = True
        app._current_take = 2
        query = app.session.query.model_dump()
        app.session.rebuild_error = RuntimeError("analysis failed")
        app._set_focus_key(("rebuild", None))
        app._handle_key("\n")

        self.assertEqual(app.session.query.model_dump(), query)
        self.assertTrue(app.session.pronunciation_needs_rebuild)
        self.assertEqual(app._current_take, 2)
        self.assertIn("analysis failed", app._status)

    def test_text_apply_failure_preserves_draft_and_remains_editable(self):
        app = self.make_app(query=mixed_query())
        app._open_text_editor("bad draft")
        editor = app._editor
        app.session.replace_source_text = Mock(
            side_effect=ValueError("source replacement failed")
        )
        app._handle_editor_key("\n")
        self.assertIs(app._editor, editor)
        self.assertEqual(editor.active_field, "draft")
        self.assertEqual(editor.input_value, "bad draft")
        self.assertEqual(editor.payload["draft"], "bad draft")
        self.assertIn("source replacement failed", editor.error)
        app._handle_editor_key("!")
        self.assertEqual(editor.input_value, "bad draft!")

    def test_japanese_modal_accepts_literal_markers_and_ordinary_cursor_motion(self):
        app = self.make_app(query=mixed_query())
        app._edit_selected_segment(0)
        editor = app._editor
        self.assertEqual(editor.kind, "japanese")
        editor.input_value = "ア'メ。"
        editor.input_cursor = len(editor.input_value)
        app._handle_editor_key(curses.KEY_LEFT)
        self.assertEqual(editor.input_cursor, len("ア'メ"))
        app._handle_editor_key("/")
        self.assertEqual(editor.input_value, "ア'メ/。")
        app._handle_editor_key(curses.KEY_LEFT)
        app._handle_editor_key("'")
        self.assertEqual(editor.input_value, "ア'メ'/。")
        self.assertEqual(editor.active_field, "draft")

    def test_japanese_editor_applies_on_single_enter_from_active_input(self):
        app = self.make_app(query=mixed_query())
        app._edit_selected_segment(0)
        editor = app._editor
        self.assertEqual(editor.kind, "japanese")
        editor.input_value = editor.payload["draft"]
        app._handle_editor_key("\n")
        self.assertIsNone(app._editor)
        self.assertEqual(app._focus_key, ("segment", 0))
        self.assertEqual(len(app.session.replace_query_calls), 1)

    def test_japanese_editor_escape_discards_modal_in_one_press(self):
        app = self.make_app(query=mixed_query())
        original = app.session.query.model_dump()
        app._edit_selected_segment(0)
        editor = app._editor
        editor.input_value += "x"
        app._handle_editor_key("\x1b")
        self.assertIsNone(app._editor)
        self.assertEqual(app._focus_key, ("segment", 0))
        self.assertEqual(app.session.query.model_dump(), original)
        self.assertEqual(app.session.replace_query_calls, [])

    def test_japanese_validation_failure_keeps_the_modal_draft_open(self):
        app = self.make_app(query=mixed_query())
        original = app.session.query.model_dump()
        app._edit_selected_segment(0)
        editor = app._editor
        editor.input_value = "not a pronunciation"
        editor.input_cursor = len(editor.input_value)
        app._handle_editor_key("\n")
        self.assertIs(app._editor, editor)
        self.assertEqual(editor.active_field, "draft")
        self.assertEqual(editor.input_value, "not a pronunciation")
        self.assertEqual(editor.payload["draft"], "not a pronunciation")
        self.assertIn("Error:", editor.error)
        self.assertEqual(app.session.query.model_dump(), original)
        app._handle_editor_key("x")
        self.assertEqual(editor.input_value, "not a pronunciationx")

    def test_settings_are_reachable_and_editable_without_shortcuts(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query())
            app.config_path = Path(directory) / "config.json"
            app._handle_key("\n")
            self.assertEqual(app._editor.kind, "settings")
            app._editor.selection = "take_count"
            app._handle_key("\n")
            app._handle_key(curses.KEY_BACKSPACE)
            app._handle_key("2")
            app._handle_key("\n")
            editor = app._editor
            self.assertIsNotNone(editor)
            self.assertEqual(editor.kind, "settings")
            self.assertIsNone(editor.active_field)
            self.assertEqual(app.settings.take_count, 4)
            self.assertFalse(app.config_path.exists())
            for _ in range(3):
                app._handle_key(curses.KEY_DOWN)
            app._handle_key("\n")
            self.assertIsNone(app._editor)
            self.assertEqual(app.settings.take_count, 2)
            self.assertEqual(json.loads(app.config_path.read_text())["take_count"], 2)

    def test_settings_arrows_edit_only_the_draft_and_apply_rows_are_compact(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
            app.config_path = Path(directory) / "settings.json"
            original_settings = app.settings
            app._open_settings_editor()
            editor = app._editor

            editor.selection = "speed"
            app._handle_editor_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["speed"], "1.01")
            editor.payload["draft_settings"]["speed"] = "0.02"
            app._handle_editor_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["speed"], "0.01")
            app._handle_editor_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["speed"], "0.01")

            editor.selection = "take_count"
            editor.payload["draft_settings"]["take_count"] = "8"
            app._handle_editor_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["take_count"], "8")
            app._handle_editor_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["take_count"], "7")

            editor.selection = "save_text"
            app._handle_editor_key(curses.KEY_LEFT)
            self.assertFalse(editor.payload["draft_settings"]["save_text"])
            app._handle_editor_key(curses.KEY_RIGHT)
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
        editor = app._editor
        editor.payload["draft_settings"]["style_id"] = "4"
        with patch("voiceger_accent_adapter.tui.available_styles", return_value=styles):
            app._handle_editor_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["style_id"], "7")
            app._handle_editor_key(curses.KEY_RIGHT)
            self.assertEqual(editor.payload["draft_settings"]["style_id"], "7")
            app._handle_editor_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["style_id"], "4")
            editor.payload["draft_settings"]["style_id"] = "2"
            app._handle_editor_key(curses.KEY_LEFT)
            self.assertEqual(editor.payload["draft_settings"]["style_id"], "2")

    def test_generate_arrows_persist_count_clear_old_batch_and_respect_bounds_and_busy(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
            app.config_path = Path(directory) / "settings.json"
            app._set_focus_key(("generate", None))
            app._status = ""
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(app.settings.take_count, 3)
            self.assertEqual(app.session.replace_settings_calls[-1].take_count, 3)
            self.assertEqual(app.session.candidates, ())
            self.assertEqual(app._focus_key, ("generate", None))
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

            app._busy = True
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(app.settings.take_count, 8)
            self.assertIn("Wait for the current synthesis operation to finish", app._status)

    def test_settings_escape_from_active_field_discards_the_entire_modal_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query())
            app.config_path = Path(directory) / "config.json"
            original_settings = app.settings
            app._open_settings_editor("speed")
            editor = app._editor
            editor.payload["draft_settings"]["take_count"] = "2"
            app._handle_editor_key("\n")
            self.assertEqual(editor.active_field, "speed")
            app._handle_editor_key("9")
            app._handle_editor_key("\x1b")
            self.assertIsNone(app._editor)
            self.assertEqual(app.settings, original_settings)
            self.assertEqual(app.session.replace_settings_calls, [])
            self.assertFalse(app.config_path.exists())

    def test_active_field_footers_describe_settings_and_english_escape_scope(self):
        settings_app = self.make_app()
        settings_app._open_settings_editor("speed")
        settings_app._handle_editor_key("\n")
        settings_screen = FakeScreen()
        settings_app._screen = settings_screen
        settings_app._render()
        settings_footer = self.rendered(settings_screen)
        self.assertIn("Enter Finish field", settings_footer)
        self.assertIn("Esc Cancel Settings", settings_footer)
        self.assertNotIn("[Enter: Edit]", settings_footer)

        english_app = self.make_app(
            query=english_query(["HH", "AY1"], text="Hi"),
            groups=(("Hi", ("HH", "AY1")),),
        )
        english_app._edit_selected_segment(0)
        english_app._handle_editor_key("\n")
        english_app._handle_editor_key("\n")
        english_screen = FakeScreen()
        english_app._screen = english_screen
        english_app._render()
        english_footer = self.rendered(english_screen)
        self.assertIn("Enter Commit phonemes", english_footer)
        self.assertIn("Esc Cancel word editor", english_footer)

        japanese_app = self.make_app(query=mixed_query())
        japanese_app._edit_selected_segment(0)
        japanese_screen = FakeScreen()
        japanese_app._screen = japanese_screen
        japanese_app._render()
        japanese_footer = self.rendered(japanese_screen)
        self.assertIn("Enter Apply", japanese_footer)
        self.assertIn("Esc Cancel", japanese_footer)
        self.assertNotIn("Apply pronunciation changes", japanese_footer)
        self.assertNotIn("Cancel and discard pronunciation draft", japanese_footer)

    def test_invalid_settings_apply_keeps_editor_and_draft(self):
        app = self.make_app()
        app._open_settings_editor("take_count")
        app._editor.payload["draft_settings"]["take_count"] = "99"
        app._editor.selection = "apply"
        app._apply_editor()
        self.assertEqual(app._editor.payload["draft_settings"]["take_count"], "99")
        self.assertIn("take_count", app._editor.error)
        self.assertEqual(app.settings.take_count, 4)

    def test_candidate_focus_arrows_play_and_escape_returns_to_last_segment(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1), candidate(2)))
        app._segment_index = 1
        app._play_take = Mock()
        app._focus_candidate(1)
        app._handle_key(curses.KEY_DOWN)
        self.assertEqual(app._focus_key, ("candidate", 2))
        self.assertEqual(app._current_take, 2)
        app._handle_key(" ")
        app._play_take.assert_has_calls([call(1), call(2), call(2)])
        app._handle_key("\x1b")
        self.assertEqual(app._focus_key, ("segment", 1))
        self.assertEqual(app._current_take, 2)

    def test_acceptance_and_regeneration_are_unavailable_while_busy_but_replay_works(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        app._play_take = Mock()
        app._start_generation = Mock()
        app._start_regenerate_all = Mock()
        app._start_regeneration = Mock()
        app._busy = True

        for key in (
            ("text", None),
            ("segment", 0),
            ("generate", None),
            ("settings_summary", None),
            ("output", None),
            ("rebuild", None),
        ):
            app._set_focus_key(key)
            app._handle_key("\n")
            self.assertIsNone(app._editor)

        app._focus_candidate(1)
        app._handle_key("\n")
        self.assertEqual(app.session.accept_calls, [])
        app._start_generation.assert_not_called()
        app._start_regenerate_all.assert_not_called()
        app._start_regeneration.assert_not_called()
        app._set_focus_key(("candidate", 1))
        app._handle_key(" ")
        app._play_take.assert_called_with(1)

    def test_candidate_regeneration_uses_only_focused_candidate(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        app._current_take = 1
        app._start_regeneration = Mock()
        app._set_focus_key(("generate", None))
        app._handle_key("r")
        app._start_regeneration.assert_not_called()
        self.assertEqual(app._status, "Select a candidate before regenerating it.")

        app.session.candidates = (candidate(1), candidate(2))
        app._play_take = Mock()
        app._focus_candidate(2)
        app._handle_key("r")
        app._start_regeneration.assert_called_once_with(2)

    def test_candidate_rows_have_no_current_suffix_or_visible_selected_regenerate_action(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1), candidate(2)))
        app._current_take = 2
        app._set_focus_key(("candidate", 2))
        rows = navigation_document(app, 80)
        labels = [line for line, _key in rows]
        self.assertIn("  Take 1  0.01s", labels)
        self.assertIn("▶ Take 2  0.01s", labels)
        visible = "\n".join(labels)
        self.assertNotIn("(current)", visible)
        self.assertNotIn("Regenerate selected", visible)
        self.assertNotIn("regenerate_selected", [key for _line, key in rows])

    def test_busy_navigation_uses_compact_rows_without_unavailable_suffixes(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        app._current_take = 1
        app._busy = True
        app._worker_operation = "initial"
        app._operation_total = 4

        items = app._navigation_items()
        rows = navigation_document(app, 80)
        labels = {key: line for line, key in rows if key is not None}

        self.assertNotIn("regenerate_selected", [key[0] for key in items])
        self.assertIn("[ Generating 1/4 ]", labels[("generate", None)])
        self.assertNotIn("unavailable while generating", "\n".join(labels.values()))
        self.assertNotIn("Space replay", "\n".join(labels.values()))
        self.assertNotIn("(current)", "\n".join(labels.values()))

    def test_busy_candidate_remains_playable_without_inline_unavailable_cues(self):
        app = self.make_app(candidates=(candidate(1), candidate(2)))
        app._play_take = Mock()
        app._busy = True
        app._focus_candidate(1)
        app._handle_key(curses.KEY_DOWN)
        self.assertEqual(app._focus_key, ("candidate", 2))
        app._handle_key(" ")
        self.assertEqual(app._play_take.call_args_list, [call(1), call(2), call(2)])

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
        app._play_take = Mock()
        app._focus_candidate(1)
        app._handle_key("\n")
        self.assertEqual(app.session.accept_calls, [1])
        self.assertEqual(app._focus_key, ("segment", 0))

    def test_long_english_navigation_wraps_only_between_complete_tokens_at_80_columns(self):
        phones = [
            "HH", "AY1", "DH", "EH1", "R", "!", "AY1", "M", "Z", "AH1",
            "N", "D", "AH0", "M", "AA1", "N", "N", "AW1", "N", "OW1", "D", "AH0", "!",
        ]
        query = english_query(phones, text="Hi There! I'm Zundamon now noda!")
        groups = (
            ("Hi", tuple(phones[0:2])),
            ("There", tuple(phones[2:5])),
            ("!", tuple(phones[5:6])),
            ("I'm", tuple(phones[6:8])),
            ("Zundamon", tuple(phones[8:16])),
            ("now", tuple(phones[16:19])),
            ("noda", tuple(phones[19:22])),
            ("!", tuple(phones[22:])),
        )
        app = self.make_app(query=query, groups=groups)
        app.session.source_text = "Hi There! I'm Zundamon now noda!"
        app._set_focus_key(("segment", 0))
        screen = FakeScreen(columns=80)
        app._screen = screen
        app._render()
        rendered = self.rendered(screen)
        document = navigation_document(app, 80)
        segment_position = next(
            index for index, (_text, key) in enumerate(document)
            if key == ("segment", 0)
        )
        segment_lines = [document[segment_position][0]]
        for text, key in document[segment_position + 1 :]:
            if key is not None or text == "":
                break
            if text.startswith(" "):
                segment_lines.append(text)

        self.assertGreaterEqual(len(segment_lines), 2)
        for line in segment_lines:
            self.assertLessEqual(len(line), 79)
        pronunciation_text = " ".join(
            line.rsplit(" | ", 1)[-1] for line in segment_lines
        )
        visible_tokens = set(pronunciation_text.split())
        expected_tokens = set(format_english_phonemes(phones).split())
        self.assertTrue(expected_tokens.issubset(visible_tokens))
        self.assertNotIn("AY1", pronunciation_text)
        self.assertNotIn("EH1", pronunciation_text)
        self.assertNotIn("segment 1", rendered)
        self.assertNotIn("[Enter: Edit]", next(
            text for text, key in document if key == ("segment", 0)
        ))

    def test_english_segment_editor_has_word_rows_wrapping_and_fixed_punctuation(self):
        word_phones = (
            "HH", "AA1", "K", "IY0", "N", "G", "W", "ER1", "D", "S",
            "HH", "AA0", "R", "T", "P", "AA1", "T", "ER0", "N",
        )
        phones = list(word_phones * 4) + ["!"]
        app = self.make_app(
            query=english_query(phones, text="Hi! There"),
            groups=(("LongWord", tuple(phones[:-1])), ("!", ("!",))),
        )
        app._edit_selected_segment(0)
        screen = FakeScreen(columns=80)
        app._screen = screen
        app._render()
        rendered = self.rendered(screen)
        self.assertIn("EDIT ENGLISH SEGMENT", rendered)
        self.assertIn("Word 'LongWord'", rendered)
        self.assertIn("Fixed context '!'", rendered)
        self.assertIn("[AA]", rendered)
        self.assertIn("ER", rendered)
        drawn_lines = [text for _row, _column, text, _attr in screen.drawn]
        pronunciation_start = next(
            index for index, line in enumerate(drawn_lines)
            if "Pronunciation:" in line
        )
        continuation_indent = " " * len("    Pronunciation: ")
        pronunciation_lines = [drawn_lines[pronunciation_start]]
        for line in drawn_lines[pronunciation_start + 1 :]:
            if line.startswith(continuation_indent) and line.strip():
                pronunciation_lines.append(line)
            else:
                break
        self.assertGreaterEqual(len(pronunciation_lines), 2)
        joined_pronunciation = " ".join(pronunciation_lines)
        for token in ("HH", "[AA]", "K", "IY", "ER", "N"):
            self.assertIn(token, joined_pronunciation)
        self.assertNotIn("AA1", joined_pronunciation)

    def test_word_phoneme_edit_rebuilds_marker_rows_and_keeps_punctuation(self):
        phones = ["HH", "AY1", "!", "DH", "EH1", "R"]
        groups = (("Hi", ("HH", "AY1")), ("!", ("!",)), ("There", ("DH", "EH1", "R")))
        app = self.make_app(query=english_query(phones, text="Hi! There"), groups=groups)
        app._edit_selected_segment(0)
        app._handle_editor_key("\n")
        word_editor = app._editor
        self.assertEqual(word_editor.kind, "english_word")
        self.assertEqual(word_editor.payload["draft_state"].primary_stress_vowel_positions, (0,))
        app._handle_editor_key("\n")
        app._editor.input_value = "HH AA M"
        app._editor.input_cursor = len(app._editor.input_value)
        app._handle_editor_key("\n")
        state = app._editor.payload["draft_state"]
        self.assertEqual(state.base_phonemes, ("HH", "AA", "M"))
        self.assertEqual(state.primary_stress_vowel_positions, (0,))
        # A new vowel ordinal keeps the existing secondary marker where possible.
        app._editor.payload["draft_state"] = self.english_phoneme_state(["AA1", "IH2"])
        app._editor.selection = "phonemes"
        app._handle_editor_key("\n")
        app._editor.input_value = "AA K IH"
        app._handle_editor_key("\n")
        self.assertEqual(app._editor.payload["draft_state"].secondary_stress_vowel_positions, (1,))
        app._editor.selection = "done"
        app._handle_editor_key("\n")
        parent = app._editor
        self.assertEqual(parent.payload["groups"][0].phonemes, ("AA1", "K", "IH2"))
        self.assertEqual(parent.payload["groups"][1].phonemes, ("!",))
        # Segment-level Apply writes only the flat canonical sequence.
        parent.selection = "apply"
        app._apply_editor()
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
        parent = app._editor
        app._handle_editor_key("\n")
        word_editor = app._editor
        app._handle_editor_key("\n")
        word_editor.input_value = "HH AA K IY"
        word_editor.input_cursor = len(word_editor.input_value)
        app._handle_editor_key("\n")

        self.assertIs(app._editor, word_editor)
        self.assertIsNone(word_editor.active_field)
        self.assertEqual(
            word_editor.payload["draft_state"].base_phonemes,
            ("HH", "AA", "K", "IY"),
        )
        self.assertEqual(parent.payload["groups"][0].phonemes, ("HH", "AY1"))
        word_editor.selection = ("primary", 0)
        app._handle_editor_key("\n")
        app._handle_editor_key(curses.KEY_RIGHT)
        app._handle_editor_key("\n")
        self.assertEqual(
            word_editor.payload["draft_state"].primary_stress_vowel_positions,
            (1,),
        )
        self.assertIs(app._editor, word_editor)
        self.assertEqual(app.session.query.model_dump(), original_query)

    def test_escape_from_active_phoneme_input_cancels_the_word_editor_in_one_press(self):
        app = self.make_app(
            query=english_query(["HH", "AY1"], text="Hi"),
            groups=(("Hi", ("HH", "AY1")),),
        )
        app._edit_selected_segment(0)
        parent = app._editor
        original_groups = parent.payload["groups"]
        original_query = app.session.query.model_dump()
        app._handle_editor_key("\n")
        word_editor = app._editor
        app._handle_editor_key("\n")
        word_editor.input_value = "HH AA M"
        app._handle_editor_key("\x1b")
        self.assertIs(app._editor, parent)
        self.assertEqual(parent.payload["groups"], original_groups)
        self.assertEqual(app.session.query.model_dump(), original_query)

    def test_escape_from_english_segment_discards_word_draft_to_navigation(self):
        app = self.make_app(
            query=english_query(["HH", "AY1"], text="Hi"),
            groups=(("Hi", ("HH", "AY1")),),
        )
        app._set_focus_key(("segment", 0))
        original_query = app.session.query.model_dump()
        app._edit_selected_segment(0)
        parent = app._editor
        app._handle_editor_key("\n")
        app._handle_editor_key("\n")
        word_editor = app._editor
        word_editor.input_value = "HH AA"
        app._handle_editor_key("\n")
        word_editor.selection = "done"
        app._handle_editor_key("\n")
        self.assertIs(app._editor, parent)
        self.assertNotEqual(parent.payload["groups"][0].phonemes, ("HH", "AY1"))
        app._handle_editor_key("\x1b")
        self.assertIsNone(app._editor)
        self.assertEqual(app._focus_key, ("segment", 0))
        self.assertEqual(app.session.query.model_dump(), original_query)

    @staticmethod
    def english_phoneme_state(phonemes):
        from voiceger_accent_adapter.english_stress import english_phonemes_to_editor_state

        return english_phonemes_to_editor_state(phonemes)

    def test_primary_markers_are_independent_and_occupied_destination_fails_closed(self):
        groups = (("word", ("AA1", "K", "IY1", "ER2")),)
        app = self.make_app(query=english_query(groups[0][1]), groups=groups)
        app._edit_selected_segment(0)
        app._handle_editor_key("\n")
        editor = app._editor
        editor.selection = ("primary", 1)
        app._handle_editor_key("\n")
        app._handle_editor_key(curses.KEY_LEFT)
        app._handle_editor_key("\n")
        self.assertIn("already has primary stress", editor.error)
        self.assertEqual(editor.payload["draft_state"].primary_stress_vowel_positions, (0, 1))
        app._handle_editor_key(curses.KEY_RIGHT)
        app._handle_editor_key(curses.KEY_RIGHT)
        app._handle_editor_key("\n")
        self.assertEqual(editor.payload["draft_state"].primary_stress_vowel_positions, (0, 2))
        editor.selection = ("primary", 0)
        app._handle_editor_key("\n")
        app._handle_editor_key(curses.KEY_RIGHT)
        app._handle_editor_key("\n")
        self.assertEqual(editor.payload["draft_state"].primary_stress_vowel_positions, (1, 2))

    def test_group_cache_tracks_token_count_changes_without_realigning(self):
        app = self.make_app(
            query=english_query(["HH", "AY1"], text="Hi"),
            groups=(("Hi", ("HH", "AY1")),),
        )
        app._edit_selected_segment(0)
        app._handle_editor_key("\n")
        app._handle_editor_key("\n")
        editor = app._editor
        editor.input_value = "HH AA M"
        app._handle_editor_key("\n")
        editor.selection = "done"
        app._handle_editor_key("\n")
        parent = app._editor
        parent.selection = "apply"
        app._apply_editor()
        calls = app.adapter.english_word_phoneme_groups.call_count
        cached = app._english_grouping(0)
        self.assertEqual(cached.groups[0].phonemes, ("HH", "AA1", "M"))
        self.assertEqual(app.adapter.english_word_phoneme_groups.call_count, calls)

    def test_stale_or_mismatched_group_cache_is_discarded_and_never_guessed(self):
        app = self.make_app(
            query=english_query(["HH", "AY0"], text="Hi"),
            groups=(("Hi", ("HH", "AY1")),),
        )
        with self.assertRaisesRegex(ValueError, "do not exactly match"):
            app._english_grouping(0)
        self.assertNotIn(0, app._english_groupings)

    def test_source_changed_cache_reinitializes_only_from_matching_canonical_grouping(self):
        app = self.make_app(
            query=english_query(["HH", "AY1"], text="Hi"),
            groups=(("Hi", ("HH", "AY1")),),
        )
        self.assertEqual(app._english_grouping(0).source_text, "Hi")
        app.session.query.voicegerSegments[0].text = "Hello"
        app.adapter.english_word_phoneme_groups.return_value = (("Hello", ("HH", "AY1")),)
        grouping = app._english_grouping(0)
        self.assertEqual(grouping.source_text, "Hello")
        self.assertEqual(app.adapter.english_word_phoneme_groups.call_count, 2)

    def test_query_replacement_clears_a_group_cache_when_its_flat_mapping_changes(self):
        app = self.make_app(
            query=english_query(["HH", "AY1"], text="Hi"),
            groups=(("Hi", ("HH", "AY1")),),
        )
        app._english_grouping(0)
        updated = app.session.query.model_copy(deep=True)
        updated.voicegerSegments[0].phonemes = ["HH", "AA1"]
        app._apply_session_query(updated)
        self.assertNotIn(0, app._english_groupings)

    def test_shortcuts_are_typed_data_while_raw_input_is_active(self):
        app = self.make_app(query=mixed_query())
        app._open_text_editor("abc")
        original_settings = app.settings
        for key in ("q", "?", "s", "x", "t", "1", curses.KEY_F5):
            app._handle_key(key)
        self.assertFalse(app._exit_requested)
        self.assertTrue(app.settings is original_settings)
        self.assertEqual(app._editor.input_value, "abcq? sxt1".replace(" ", ""))

    def test_navigation_shortcuts_open_the_same_visible_actions(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        app._handle_key("t")
        self.assertEqual(app._editor.kind, "text")
        app._cancel_editor()
        app._handle_key("s")
        self.assertEqual(app._editor.kind, "settings")
        self.assertEqual(app._editor.selection, "style_id")
        app._cancel_editor()
        app._play_take = Mock()
        app._focus_candidate(1)
        app._start_regeneration = Mock()
        app._handle_key("r")
        app._start_regeneration.assert_called_once_with(1)

        settings_shortcut = self.make_app(query=mixed_query())
        settings_shortcut._handle_key("s")
        self.assertEqual(settings_shortcut._editor.kind, "settings")
        self.assertEqual(settings_shortcut._editor.selection, "style_id")

        help_shortcut = self.make_app(query=mixed_query())
        help_shortcut._handle_key("?")
        self.assertTrue(help_shortcut._help_open)

        quit_shortcut = self.make_app(query=mixed_query())
        quit_shortcut._handle_key("q")
        self.assertTrue(quit_shortcut._exit_requested)

    def test_worker_discards_python_stdout_and_stderr_during_iteration(self):
        app = self.make_app()
        stdout = io.StringIO()
        stderr = io.StringIO()

        def values():
            print("runtime stdout")
            print("runtime stderr", file=sys.stderr)
            yield candidate(1)
            print("runtime stdout after yield")
            print("runtime stderr after yield", file=sys.stderr)

        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            app._run_in_worker(lambda: values(), "Generating 1/1", operation="initial")
            app._worker.join(timeout=2)
        self.assertFalse(app._worker.is_alive())
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(app._events.get_nowait()[0], "candidate")

    def test_initial_candidate_autoplays_only_if_focus_did_not_move(self):
        first, second = candidate(1), candidate(2)
        app = self.make_app(candidates=(first,))
        app._worker_operation = "initial"
        app._operation_total = 2
        app._busy = True
        app._play_take = Mock()
        app._events.put(("candidate", first))
        app._consume_events()
        self.assertEqual(app._focus_key, ("candidate", 1))
        app._play_take.assert_called_once_with(1)

        moved = self.make_app(candidates=(first,))
        moved._worker_operation = "initial"
        moved._operation_total = 2
        moved._busy = True
        moved._play_take = Mock()
        moved._focus_candidate(1)
        moved._set_focus_key(("settings_summary", None), moved=True)
        moved._events.put(("candidate", second))
        moved._consume_events()
        self.assertEqual(moved._focus_key, ("settings_summary", None))
        moved._play_take.assert_called_once_with(1)

    def test_initial_generation_completion_keeps_a_meaningful_ready_status(self):
        app = self.make_app(candidates=(candidate(1), candidate(2)))
        app._worker_operation = "initial"
        app._busy = True
        app._events.put(("done", None))

        app._consume_events()

        self.assertFalse(app._busy)
        self.assertEqual(app._status, "2 take(s) ready.")
        self.assertNotIn("Focus a candidate", app._status)

    def test_later_initial_candidates_do_not_steal_focus_or_playback(self):
        first, second, third = candidate(1), candidate(2), candidate(3)
        app = self.make_app(candidates=(first,))
        app._worker_operation = "initial"
        app._operation_total = 3
        app._busy = True
        app._play_take = Mock()
        app._events.put(("candidate", first))
        app._consume_events()
        app._focus_candidate(2) if ("candidate", 2) in app._navigation_items() else None
        app.session.candidates = (first, second, third)
        app._events.put(("candidate", third))
        app._consume_events()
        self.assertEqual(app._current_take, 1 if app._focus_key == ("candidate", 1) else 2)
        self.assertEqual(app._play_take.call_count, 1)

    def test_manual_candidate_selection_during_initial_generation_is_retained(self):
        first, second, third = candidate(1), candidate(2), candidate(3)
        app = self.make_app(candidates=(first,))
        app._worker_operation = "initial"
        app._operation_total = 3
        app._busy = True
        app._play_take = Mock()
        app._focus_candidate(1)
        app.session.candidates = (first, second)
        app._focus_candidate(2)
        app.session.candidates = (first, second, third)
        app._events.put(("candidate", third))
        app._consume_events()
        self.assertEqual(app._current_take, 2)
        self.assertEqual(app._focus_key, ("candidate", 2))
        self.assertEqual(app._play_take.call_args_list, [call(1), call(2)])

    def test_initial_generation_failure_discards_partial_batch_and_returns_to_segment(self):
        first = candidate(1)
        app = self.make_app(candidates=(first,))
        app._worker_operation = "initial"
        app._operation_total = 1
        app._busy = True
        app._play_take = Mock()
        app._stop_playback = Mock()
        error = RuntimeError("second synthesis failed")
        app._events.put(("candidate", first))
        app._events.put(("error", error))
        app._events.put(("done", None))
        app._consume_events()
        self.assertEqual(app.session.discard_calls, 1)
        self.assertEqual(app.session.candidates, ())
        self.assertIsNone(app._current_take)
        self.assertEqual(app._focus_key, ("segment", 0))
        self.assertIn("second synthesis failed", app._status)
        app._stop_playback.assert_called_once_with()

    def test_single_regeneration_selects_and_plays_replacement(self):
        replacement = candidate(2)
        app = self.make_app(candidates=(candidate(1), replacement))
        app._worker_operation = "regenerate_one"
        app._worker_target = 2
        app._operation_total = 1
        app._current_take = 2
        app._set_focus_key(("candidate", 2))
        app._busy = True
        app._play_take = Mock()
        app._events.put(("candidate", replacement))
        app._consume_events()
        self.assertEqual(app._current_take, 2)
        self.assertEqual(app._focus_key, ("candidate", 2))
        app._play_take.assert_called_once_with(2)

    def test_manual_candidate_change_during_single_regeneration_is_not_stolen(self):
        one, replacement = candidate(1), candidate(2)
        app = self.make_app(candidates=(one, replacement))
        app._current_take = 2
        app._worker_operation = "regenerate_one"
        app._worker_target = 2
        app._operation_total = 1
        app._busy = True
        app._play_take = Mock()
        app._focus_candidate(1)
        app._play_take.reset_mock()
        app._events.put(("candidate", replacement))
        app._consume_events()
        self.assertEqual(app._current_take, 1)
        self.assertEqual(app._focus_key, ("candidate", 1))
        app._play_take.assert_not_called()

    def test_regenerate_all_preserves_selected_candidate_against_unrelated_arrivals(self):
        one, two, three = candidate(1), candidate(2), candidate(3)
        app = self.make_app(candidates=(one, two, three))
        app._play_take = Mock()
        app._focus_candidate(2)
        app._worker_operation = "regenerate_all"
        app._operation_total = 3
        app._busy = True
        app._play_take = Mock()
        app._events.put(("candidate", one))
        app._events.put(("candidate", three))
        app._consume_events()
        self.assertEqual(app._focus_key, ("candidate", 2))
        self.assertEqual(app._current_take, 2)
        app._play_take.assert_not_called()
        app._events.put(("candidate", two))
        app._consume_events()
        app._play_take.assert_called_once_with(2)

    def test_regeneration_failure_preserves_existing_batch(self):
        original = candidate(1)
        app = self.make_app(candidates=(original,))
        app._worker_operation = "regenerate_one"
        app._worker_target = 1
        app._busy = True
        error = RuntimeError("replacement failed")
        app._events.put(("error", error))
        app._events.put(("done", None))
        app._consume_events()
        self.assertEqual(app.session.candidates, (original,))
        self.assertEqual(app.session.discard_calls, 0)
        self.assertIn("replacement failed", app._status)

    def test_playback_stops_before_query_invalidation(self):
        app = self.make_app(query=english_query(["AA1", "IY0"]))
        events = []
        app._stop_playback = Mock(side_effect=lambda: events.append("stop"))
        app.session.replace_query = Mock(side_effect=lambda query: events.append("query"))
        app._apply_session_query(app.session.query.model_copy(deep=True))
        self.assertEqual(events, ["stop", "query"])

    def test_playback_stops_before_settings_invalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app()
            app.config_path = Path(directory) / "config.json"
            events = []
            app._stop_playback = Mock(side_effect=lambda: events.append("stop"))
            app.session.replace_settings = Mock(side_effect=lambda settings: events.append("settings"))
            app._change_settings(take_count=2)
        self.assertEqual(events, ["stop", "settings"])

    def test_source_replacement_stops_playback_before_session_invalidation(self):
        app = self.make_app(query=mixed_query())
        app._english_grouping(1)
        events = []
        session = app.session
        app._stop_playback = Mock(side_effect=lambda: events.append("stop"))
        session.replace_source_text = Mock(
            side_effect=lambda source: events.append("replace")
        )
        app._open_text_editor("new source")
        app._editor.payload["draft"] = "new source"
        app._editor.active_field = None
        app._apply_editor()
        self.assertEqual(events, ["stop", "replace"])
        self.assertIs(app.session, session)
        self.assertEqual(app._english_groupings, {})

    def test_stop_playback_terminates_and_reaps_child(self):
        app = self.make_app()
        child = Mock()
        child.poll.return_value = None
        app._player = child
        app._stop_playback()
        child.terminate.assert_called_once_with()
        child.wait.assert_called_once_with(timeout=0.25)
        self.assertIsNone(app._player)

    def test_stop_playback_kills_and_reaps_after_timeout(self):
        app = self.make_app()
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired("afplay", 0.25), 0]
        app._player = child
        app._stop_playback()
        child.terminate.assert_called_once_with()
        child.kill.assert_called_once_with()
        self.assertEqual(child.wait.call_count, 2)

    def test_macos_playback_falls_back_to_ffplay(self):
        app = self.make_app(candidates=(candidate(1),))
        with patch("voiceger_accent_adapter.tui.sys.platform", "darwin"), patch(
            "voiceger_accent_adapter.tui.shutil.which",
            side_effect=lambda name: None if name == "afplay" else "/usr/bin/ffplay",
        ), patch("voiceger_accent_adapter.tui.subprocess.Popen") as popen:
            app._play_take(1)
        popen.assert_called_once_with(
            ["/usr/bin/ffplay", "-nodisp", "-autoexit", "-loglevel", "error", "/tmp/take-1.wav"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def test_busy_shutdown_drains_worker_before_playback_and_session_cleanup(self):
        app = self.make_app()
        app._initial_text = "example"
        app._busy = True
        timeout_read = Event()
        worker_finished = Event()
        cleanup_order = []

        def finish_worker():
            timeout_read.wait()
            cleanup_order.append("worker-finished")
            app._events.put(("done", None))
            worker_finished.set()

        worker = Thread(target=finish_worker, name="test-tui-worker")
        app._worker = worker

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

        app._stop_playback = Mock(side_effect=stop_playback)
        app.session.close = Mock(side_effect=close_session)
        worker.start()
        screen = DrainScreen()
        with patch(
            "voiceger_accent_adapter.tui.UtteranceSession.from_text",
            return_value=app.session,
        ):
            app.run(screen)
        self.assertFalse(app._busy)
        self.assertEqual(
            cleanup_order,
            ["worker-finished", "playback-stopped", "session-closed"],
        )

    def test_run_exception_joins_worker_before_cleanup(self):
        app = self.make_app()
        app._initial_text = "example"
        app._busy = True
        worker_release = Event()
        cleanup_order = []

        def finish_worker():
            worker_release.wait()
            cleanup_order.append("worker-finished")

        worker = Thread(target=finish_worker, name="test-tui-worker")
        app._worker = worker

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
        app._stop_playback = Mock(side_effect=stop_playback)
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
