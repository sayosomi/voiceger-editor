import curses
import io
import json
from argparse import Namespace
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
    TuiApp,
    _take_key_action,
    build_argument_parser,
    format_english_phonemes,
    settings_for_invocation,
)
from voiceger_accent_adapter.voicevox_api_models import AudioQuery, VoicegerSegment


def english_query(phonemes):
    return AudioQuery(
        accent_phrases=[],
        voicegerSegments=[
            VoicegerSegment(language="en", text="example", phonemes=phonemes)
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
        self.discard_calls = 0
        self.close_calls = 0

    @property
    def has_active_batch(self):
        return bool(self.candidates)

    def replace_query(self, query):
        self.replace_query_calls.append(query)
        self.query = query

    def replace_settings(self, settings):
        self.replace_settings_calls.append(settings)

    def discard_takes(self):
        self.discard_calls += 1
        self.candidates = ()

    def close(self):
        self.close_calls += 1


class FakeScreen:
    def __init__(self, keys=()):
        self.keys = list(keys)
        self.rows = 24
        self.columns = 100
        self.drawn = []
        self.refresh_count = 0

    def getmaxyx(self):
        return self.rows, self.columns

    def keypad(self, enabled):
        return None

    def timeout(self, milliseconds):
        return None

    def addnstr(self, row, column, value, count, attr=0):
        self.drawn.append((row, column, value[:count], attr))

    def move(self, *args):
        return None

    def refresh(self):
        self.refresh_count += 1
        return None

    def erase(self):
        self.drawn.clear()
        return None

    def get_wch(self):
        if not self.keys:
            raise curses.error("no more fake keys")
        return self.keys.pop(0)


class TuiTests(unittest.TestCase):
    @staticmethod
    def make_app(*, query=None, candidates=()):
        adapter = Mock()
        adapter.voiceger_root = Path("/nonexistent/voiceger")
        app = TuiApp(adapter=adapter, settings=Settings())
        app.session = FakeSession(query=query, candidates=candidates)
        return app

    def test_english_display_hides_stress_digits_and_marks_primary_anchor(self):
        rendered = format_english_phonemes(
            ["V", "OY1", "AH0", "JH", "ER2"],
            selected_primary=0,
        )

        self.assertEqual(rendered, "V ▶[OY] AH JH ER")
        self.assertNotIn("0", rendered)
        self.assertNotIn("1", rendered)
        self.assertNotIn("2", rendered)

    def test_english_display_marks_other_primary_stress_without_stress_digits(self):
        rendered = format_english_phonemes(
            ["AA1", "K", "IY1", "ER2"],
            selected_primary=0,
        )

        self.assertEqual(rendered, "▶[AA] K [IY] ER")

    def test_take_review_key_map_uses_arrows_and_not_j_or_k(self):
        numbers = [1, 2, 4]
        self.assertEqual(
            _take_key_action(
                curses.KEY_DOWN,
                candidate_numbers=numbers,
                current_number=2,
            ),
            ("select", 4),
        )
        self.assertEqual(
            _take_key_action(
                curses.KEY_UP,
                candidate_numbers=numbers,
                current_number=4,
            ),
            ("select", 2),
        )
        self.assertEqual(
            _take_key_action("4", candidate_numbers=numbers, current_number=1),
            ("select", 4),
        )
        self.assertEqual(
            _take_key_action("r", candidate_numbers=numbers, current_number=2),
            ("regenerate", 2),
        )
        self.assertEqual(
            _take_key_action("R", candidate_numbers=numbers, current_number=2),
            ("regenerate_all", None),
        )
        self.assertIsNone(
            _take_key_action("j", candidate_numbers=numbers, current_number=2)
        )
        self.assertIsNone(
            _take_key_action("k", candidate_numbers=numbers, current_number=2)
        )

    def test_take_review_maps_space_and_enter(self):
        self.assertEqual(
            _take_key_action(" ", candidate_numbers=[3], current_number=3),
            ("replay", 3),
        )
        self.assertEqual(
            _take_key_action("\n", candidate_numbers=[3], current_number=3),
            ("accept", 3),
        )

    def test_command_line_options_override_persisted_defaults(self):
        args = build_argument_parser().parse_args(
            [
                "example",
                "--take-count", "8",
                "--style", "2",
                "--speed", "1.25",
                "--output-dir", "/tmp/voice-output",
                "--save-text",
            ]
        )
        base = Settings(take_count=4, style_id=1, speed=1.0, save_text=False)

        effective = settings_for_invocation(args, base)

        self.assertEqual(effective.take_count, 8)
        self.assertEqual(effective.style_id, 2)
        self.assertEqual(effective.speed, 1.25)
        self.assertEqual(effective.output_dir, Path("/tmp/voice-output"))
        self.assertTrue(effective.save_text)
        self.assertEqual(base, Settings())

    def test_interactive_change_does_not_persist_other_cli_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "settings.json"
            base = Settings(take_count=4, style_id=1)
            app = TuiApp(
                adapter=Mock(),
                settings=Settings(take_count=8, style_id=1),
                persisted_settings=base,
                config_path=config_path,
            )

            app._change_settings(save_text=True)

            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["take_count"], 4)
            self.assertTrue(persisted["save_text"])
            self.assertEqual(app.settings.take_count, 8)

    def test_text_editor_keeps_basic_cursor_and_backspace_controls(self):
        adapter = Mock()
        adapter.voiceger_root = Path("/nonexistent/voiceger")
        app = TuiApp(adapter=adapter, settings=Settings(), source_text="unused")
        app._screen = FakeScreen(
            [
                curses.KEY_LEFT,
                "X",
                curses.KEY_BACKSPACE,
                curses.KEY_END,
                "!",
                "\n",
            ]
        )

        value = app._read_line("Text", "ab")

        self.assertEqual(value, "ab!")

    def test_japanese_editor_marker_helpers_toggle_at_the_cursor(self):
        cases = (
            ("アメ", ["a", "\n"], "アメ'"),
            ("アメ'", ["a", "\n"], "アメ"),
            ("アメ", ["p", "\n"], "アメ/"),
            ("アメ/", ["p", "\n"], "アメ"),
        )
        for initial, keys, expected in cases:
            with self.subTest(initial=initial, keys=keys):
                app = self.make_app()
                app._screen = FakeScreen(keys)
                self.assertEqual(
                    app._read_line("JA pronunciation", initial, editor_type="japanese"),
                    expected,
                )

    def test_japanese_editor_accepts_literal_accent_and_phrase_markers(self):
        app = self.make_app()
        app._screen = FakeScreen(["'", "ア", "/", "メ", "\n"])

        value = app._read_line("JA pronunciation", "", editor_type="japanese")

        self.assertEqual(value, "'ア/メ")

    def test_japanese_marker_helpers_are_only_active_in_japanese_editor(self):
        for editor_type in ("text", "english"):
            with self.subTest(editor_type=editor_type):
                app = self.make_app()
                app._screen = FakeScreen(["a", "p", "\n"])
                self.assertEqual(
                    app._read_line("Editor", "", editor_type=editor_type),
                    "ap",
                )

    def test_japanese_editor_shows_a_separate_labeled_editor_region(self):
        app = self.make_app()
        screen = FakeScreen(["a", "\x1b"])
        app._screen = screen

        self.assertIsNone(
            app._read_line("JA example pronunciation", "アメ", editor_type="japanese")
        )

        rows = {row: text for row, _column, text, _attr in screen.drawn}
        self.assertIn("Editor: JA example pronunciation", rows[17])
        self.assertIn("a Accent (')", rows[18])
        self.assertIn("p Phrase (/)", rows[18])
        self.assertIn("' / direct input", rows[19])
        self.assertIn("Enter Save", rows[19])
        self.assertIn("Esc Cancel", rows[19])
        self.assertTrue(rows[20].startswith("> "))
        self.assertTrue(rows[21].startswith("Status:"))
        self.assertIn("cursor", rows[22])
        self.assertEqual(rows[23], "? Help   q Quit")

    def test_source_focus_enter_opens_source_editor(self):
        app = self.make_app()
        app._focus = "source"
        app._edit_source_text = Mock()

        app._handle_key("\n")

        app._edit_source_text.assert_called_once_with()

    def test_tab_focus_order_includes_generate_and_only_available_takes(self):
        app = self.make_app()
        app._focus = "source"
        expected_without_candidates = ["pronunciation", "generate", "source"]
        actual_without_candidates = []
        for _ in expected_without_candidates:
            app._handle_key("\t")
            actual_without_candidates.append(app._focus)
        self.assertEqual(actual_without_candidates, expected_without_candidates)

        app = self.make_app(candidates=(candidate(1),))
        app._focus = "source"
        expected_with_candidates = ["pronunciation", "generate", "takes", "source"]
        actual_with_candidates = []
        for _ in expected_with_candidates:
            app._handle_key("\t")
            actual_with_candidates.append(app._focus)
        self.assertEqual(actual_with_candidates, expected_with_candidates)

    def test_generate_focus_enter_routes_to_initial_generation(self):
        app = self.make_app()
        app._focus = "generate"
        app._start_generation = Mock()

        app._handle_key("\n")

        app._start_generation.assert_called_once_with()

    def test_generate_focus_enter_routes_to_regenerate_all_for_an_active_batch(self):
        app = self.make_app(candidates=(candidate(1),))
        app._focus = "generate"
        app._start_regenerate_all = Mock()

        app._handle_key("\n")

        app._start_regenerate_all.assert_called_once_with()

    def test_question_mark_opens_help_overlay(self):
        app = self.make_app()

        app._handle_key("?")

        self.assertTrue(app._help_open)

    def test_help_overlay_contains_the_full_shortcut_reference(self):
        app = self.make_app()
        app._help_open = True
        app._screen = FakeScreen()

        app._render()

        rendered = "\n".join(text for _row, _column, text, _attr in app._screen.drawn)
        for expected in (
            "Tab: next area",
            "Enter: edit / activate / accept according to focus",
            "Up/Down: pronunciation or take navigation according to focus",
            "Left/Right: English primary stress movement",
            "Shift+Tab: select another English primary-stress marker",
            "F5 / Ctrl+G: generate",
            "Space: replay take",
            "1-8: select take",
            "r: regenerate current take",
            "R (Shift+R): regenerate all takes",
            "t: edit text",
            "s: style",
            "v: speed",
            "n: take count",
            "o: output directory",
            "x: toggle text sidecar",
            "?: help",
            "q: quit",
        ):
            self.assertIn(expected, rendered)

    def test_help_overlay_closes_with_question_escape_or_enter(self):
        for key in ("?", "\x1b", "\n"):
            with self.subTest(key=key):
                app = self.make_app()
                app._handle_key("?")
                app._handle_key(key)
                self.assertFalse(app._help_open)

    def test_q_still_quits_from_help_overlay(self):
        app = self.make_app()
        app._handle_key("?")

        app._handle_key("q")

        self.assertTrue(app._exit_requested)
        self.assertTrue(app._help_open)

    def test_help_ignores_navigation_and_editing_keys(self):
        app = self.make_app()
        app._focus = "generate"
        app._handle_key("?")
        app._start_generation = Mock()
        original_save_text = app.settings.save_text

        for key in ("\t", "x", "t", curses.KEY_F5, "\x07", curses.KEY_DOWN):
            app._handle_key(key)

        self.assertEqual(app._focus, "generate")
        self.assertEqual(app.settings.save_text, original_save_text)
        app._start_generation.assert_not_called()

    def test_render_keeps_text_state_visible_separate_from_long_output_path(self):
        app = self.make_app()
        app.settings = Settings(save_text=True, output_dir=Path("/" + "long-directory/" * 30))
        app._screen = FakeScreen()

        app._render()

        rows = {row: text for row, _column, text, _attr in app._screen.drawn}
        self.assertIn("TXT ON", rows[1])
        self.assertNotIn("long-directory", rows[1])
        self.assertTrue(rows[2].startswith("Output:"))

    def test_render_shows_discoverable_text_and_generate_actions(self):
        app = self.make_app()
        app._focus = "generate"
        app._screen = FakeScreen()

        app._render()

        rows = {row: text for row, _column, text, _attr in app._screen.drawn}
        self.assertIn("Text", rows[4])
        self.assertIn("[Enter: Edit]", "".join(text for _row, _column, text, _attr in app._screen.drawn))
        self.assertIn("[ Generate 4 takes ]", "".join(rows.values()))
        self.assertIn("▶", rows[8])

    def test_render_shows_regenerate_all_action_for_an_active_batch(self):
        app = self.make_app(candidates=(candidate(1),))
        app._screen = FakeScreen()

        app._render()

        self.assertIn(
            "[ Regenerate all 4 takes ]",
            "".join(text for _row, _column, text, _attr in app._screen.drawn),
        )

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
            app._run_in_worker(lambda: values(), "Generating", operation="initial")
            app._worker.join(timeout=2)

        self.assertFalse(app._worker.is_alive())
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(app._events.get_nowait()[0], "candidate")

    def test_worker_exception_reaches_error_event_and_remains_visible(self):
        app = self.make_app()
        error = RuntimeError("synthesis worker failed")

        def failing_values():
            print("discard this output")
            raise error
            yield candidate(1)

        app._run_in_worker(
            lambda: failing_values(),
            "Generating",
            operation="initial",
        )
        app._worker.join(timeout=2)
        events = [app._events.get_nowait(), app._events.get_nowait()]

        self.assertEqual([kind for kind, _value in events], ["error", "done"])
        self.assertIs(events[0][1], error)
        app._worker_operation = "initial"
        for event in events:
            app._events.put(event)
        app._consume_events()
        self.assertTrue(app._status.startswith("Error:"))
        self.assertIn("synthesis worker failed", app._status)

    def test_move_toward_another_primary_marker_is_a_noop(self):
        query = english_query(["AA1", "IY1", "ER2"])
        app = self.make_app(query=query)
        app._selected_primary[0] = 0

        app._move_selected_stress(1)

        self.assertEqual(app.session.replace_query_calls, [])
        self.assertEqual(
            app.session.query.voicegerSegments[0].phonemes,
            ["AA1", "IY1", "ER2"],
        )
        self.assertIn("already has primary stress", app._status)

    def test_shift_tab_cycles_selected_primary_markers(self):
        app = self.make_app(query=english_query(["AA1", "IY1", "ER2"]))
        app._focus = "pronunciation"

        app._handle_key(curses.KEY_BTAB)
        self.assertEqual(app._selected_primary[0], 1)
        app._handle_key(curses.KEY_BTAB)
        self.assertEqual(app._selected_primary[0], 0)

    def test_left_right_moves_only_the_selected_primary_marker(self):
        app = self.make_app(query=english_query(["AA1", "IY0", "ER1", "AH2"]))
        app._selected_primary[0] = 2

        app._move_selected_stress(-1)

        state = app.session.query.voicegerSegments[0].phonemes
        self.assertEqual(state, ["AA1", "IY1", "ER0", "AH2"])
        self.assertEqual(app._selected_primary[0], 1)

    def test_phoneme_edit_refreshes_selected_marker_to_a_valid_primary(self):
        app = self.make_app(query=english_query(["AA1", "IY0", "ER1"]))
        app._selected_primary[0] = 7
        app._read_line = Mock(return_value="IY ER")

        app._edit_selected_segment()

        state = app.session.query.voicegerSegments[0].phonemes
        self.assertEqual(state, ["IY1", "ER0"])
        self.assertEqual(app._selected_primary[0], 0)

    def test_first_initial_candidate_is_selected_and_played_once(self):
        first, second, third = candidate(1), candidate(2), candidate(3)
        app = self.make_app(candidates=(first,))
        app._worker_operation = "initial"
        app._busy = True
        app._play_take = Mock()

        app._events.put(("candidate", first))
        app._consume_events()
        self.assertEqual(app._current_take, 1)
        app._play_take.assert_called_once_with(1)

        app.session.candidates = (first, second, third)
        app._events.put(("candidate", second))
        app._events.put(("candidate", third))
        app._consume_events()

        self.assertEqual(app._current_take, 1)
        app._play_take.assert_called_once_with(1)

    def test_manual_selection_during_initial_generation_is_retained(self):
        first, second, third = candidate(1), candidate(2), candidate(3)
        app = self.make_app(candidates=(first,))
        app._worker_operation = "initial"
        app._busy = True
        app._focus = "takes"
        app._play_take = Mock()

        app._events.put(("candidate", first))
        app._consume_events()
        app.session.candidates = (first, second)
        app._handle_take_key("2")
        app.session.candidates = (first, second, third)
        app._events.put(("candidate", third))
        app._consume_events()

        self.assertEqual(app._current_take, 2)
        app._play_take.assert_has_calls([call(1), call(2)])
        self.assertEqual(app._play_take.call_count, 2)

    def test_initial_generation_failure_discards_partial_batch_and_returns_to_editing(self):
        first = candidate(1)
        app = self.make_app(candidates=(first,))
        app._worker_operation = "initial"
        app._busy = True
        app._focus = "takes"
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
        self.assertEqual(app._focus, "pronunciation")
        self.assertIn("second synthesis failed", app._status)
        app._stop_playback.assert_called_once_with()

    def test_single_regeneration_selects_and_plays_replacement(self):
        replacement = candidate(2)
        app = self.make_app(candidates=(candidate(1), replacement))
        app._worker_operation = "regenerate_one"
        app._worker_target = 2
        app._current_take = 1
        app._busy = True
        app._play_take = Mock()

        app._events.put(("candidate", replacement))
        app._consume_events()

        self.assertEqual(app._current_take, 2)
        app._play_take.assert_called_once_with(2)

    def test_regenerate_all_keeps_selection_and_plays_only_its_replacement(self):
        one, two, three = candidate(1), candidate(2), candidate(3)
        app = self.make_app(candidates=(one, two, three))
        app._worker_operation = "regenerate_all"
        app._current_take = 2
        app._busy = True
        app._play_take = Mock()

        app._events.put(("candidate", one))
        app._consume_events()
        self.assertEqual(app._current_take, 2)
        app._events.put(("candidate", three))
        app._consume_events()
        self.assertEqual(app._current_take, 2)
        app._play_take.assert_not_called()
        app._events.put(("candidate", two))
        app._consume_events()

        self.assertEqual(app._current_take, 2)
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
        app._selected_primary[0] = 0
        events = []
        app._stop_playback = Mock(side_effect=lambda: events.append("stop"))
        app.session.replace_query = Mock(side_effect=lambda query: events.append("query"))

        app._move_selected_stress(1)

        self.assertEqual(events, ["stop", "query"])

    def test_playback_stops_before_settings_invalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app()
            app.config_path = Path(directory) / "config.json"
            events = []
            app._stop_playback = Mock(side_effect=lambda: events.append("stop"))
            app.session.replace_settings = Mock(
                side_effect=lambda settings: events.append("settings")
            )

            app._change_settings(take_count=2)

        self.assertEqual(events, ["stop", "settings"])

    def test_playback_stops_before_replacing_source_session(self):
        app = self.make_app()
        events = []
        app.session.close = Mock(side_effect=lambda: events.append("close"))
        app._read_line = Mock(return_value="new source")
        replacement_session = FakeSession()
        app._stop_playback = Mock(side_effect=lambda: events.append("stop"))
        with patch(
            "voiceger_accent_adapter.tui.UtteranceSession.from_text",
            return_value=replacement_session,
        ):
            app._edit_source_text()

        self.assertEqual(events, ["stop", "close"])
        self.assertIs(app.session, replacement_session)

    def test_stop_playback_terminates_and_reaps_child(self):
        app = self.make_app()
        child = Mock()
        child.poll.return_value = None
        app._player = child

        app._stop_playback()

        child.terminate.assert_called_once_with()
        child.wait.assert_called_once_with(timeout=0.25)
        self.assertIsNone(app._player)

    def test_stop_playback_kills_and_reaps_child_after_timeout(self):
        app = self.make_app()
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = [
            subprocess.TimeoutExpired("afplay", 0.25),
            0,
        ]
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
            [
                "/usr/bin/ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "error",
                "/tmp/take-1.wav",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def test_run_busy_shutdown_tolerates_input_timeout_and_cleans_up_after_worker(self):
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

        class TimeoutDuringDrainScreen(FakeScreen):
            reads = 0

            def get_wch(self):
                self.reads += 1
                if self.reads == 1:
                    return "q"
                timeout_read.set()
                if not worker_finished.wait(timeout=2):
                    raise AssertionError("worker did not finish during busy drain")
                raise curses.error("screen input timed out")

        def stop_playback():
            self.assertFalse(worker.is_alive())
            cleanup_order.append("playback-stopped")

        def close_session():
            self.assertFalse(worker.is_alive())
            cleanup_order.append("session-closed")

        app._stop_playback = Mock(side_effect=stop_playback)
        app.session.close = Mock(side_effect=close_session)
        screen = TimeoutDuringDrainScreen()
        worker.start()

        app.run(screen)

        self.assertEqual(screen.reads, 2)
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

        with self.assertRaisesRegex(RuntimeError, "render failed"):
            app.run(FakeScreen())

        self.assertEqual(
            cleanup_order,
            ["worker-finished", "playback-stopped", "session-closed"],
        )


if __name__ == "__main__":
    unittest.main()
