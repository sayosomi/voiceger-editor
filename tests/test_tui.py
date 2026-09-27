import curses
import json
from argparse import Namespace
from pathlib import Path
import subprocess
import tempfile
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

    def getmaxyx(self):
        return self.rows, self.columns

    def addnstr(self, *args):
        return None

    def move(self, *args):
        return None

    def refresh(self):
        return None

    def erase(self):
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


if __name__ == "__main__":
    unittest.main()
