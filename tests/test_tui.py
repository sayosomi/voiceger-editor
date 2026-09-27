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
    TuiApp,
    _take_key_action,
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

    def getmaxyx(self):
        return self.rows, self.columns

    def keypad(self, enabled):
        return None

    def timeout(self, milliseconds):
        return None

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

    def test_take_review_key_helper_keeps_nonwrapping_candidate_edges(self):
        numbers = [1, 2, 4]
        self.assertEqual(
            _take_key_action(curses.KEY_DOWN, candidate_numbers=numbers, current_number=2),
            ("select", 4),
        )
        self.assertEqual(
            _take_key_action(curses.KEY_UP, candidate_numbers=numbers, current_number=4),
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
                ("text", None),
                ("segment", 0),
                ("segment", 1),
                ("generate", None),
                ("candidate", 1),
                ("candidate", 2),
                ("regenerate_selected", 2),
                ("settings", None),
                ("help", None),
                ("quit", None),
            ],
        )

    def test_navigation_is_nonwrapping_at_both_ends(self):
        app = self.make_app(query=mixed_query())
        app._set_focus_key(("text", None))
        app._handle_key(curses.KEY_UP)
        self.assertEqual(app._focus_key, ("text", None))
        app._set_focus_key(("quit", None))
        app._handle_key(curses.KEY_DOWN)
        self.assertEqual(app._focus_key, ("quit", None))

    def test_text_and_generate_are_reachable_with_only_vertical_arrows(self):
        app = self.make_app(query=mixed_query())
        app._set_focus_key(("text", None))
        app._handle_key(curses.KEY_UP)
        self.assertEqual(app._focus_key, ("text", None))
        while app._focus_key != ("generate", None):
            app._handle_key(curses.KEY_DOWN)
        app._start_generation = Mock()
        app._handle_key("\n")
        app._start_generation.assert_called_once_with()

    def test_help_and_quit_actions_activate_from_the_continuous_list(self):
        app = self.make_app(query=mixed_query())
        app._set_focus_key(("help", None))
        app._handle_key("\n")
        self.assertTrue(app._help_open)
        app._handle_key("\x1b")
        app._set_focus_key(("quit", None))
        app._handle_key("\n")
        self.assertTrue(app._exit_requested)

        shortcut = self.make_app(query=mixed_query())
        shortcut._handle_key("?")
        shortcut._handle_key("q")
        self.assertTrue(shortcut._exit_requested)

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
        self.assertIn("Cancel and discard text draft", rendered)
        self.assertIn("Esc Discard field", rendered)

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
        app._open_text_editor(original)
        app._handle_editor_key("!")
        app._handle_editor_key("\n")
        app._handle_editor_key(curses.KEY_DOWN)
        app._handle_editor_key(curses.KEY_DOWN)
        app._handle_editor_key("\n")
        self.assertIsNone(app._editor)
        self.assertEqual(app.session.source_text, original)
        self.assertEqual(app.session.replace_query_calls, [])

    def test_text_editor_apply_rebuilds_source_only_after_apply(self):
        app = self.make_app(query=mixed_query())
        replacement = FakeSession(query=mixed_query(), candidates=())
        app._open_text_editor("new source")
        app._editor.payload["draft"] = "new source"
        app._editor.active_field = None
        with patch(
            "voiceger_accent_adapter.tui.UtteranceSession.from_text",
            return_value=replacement,
        ):
            app._editor.selection = "apply"
            app._apply_editor()
        self.assertIs(app.session, replacement)
        self.assertEqual(replacement.close_calls, 0)
        self.assertEqual(app._english_groupings, {})

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

    def test_japanese_validation_failure_keeps_the_modal_draft_open(self):
        app = self.make_app(query=mixed_query())
        original = app.session.query.model_dump()
        app._edit_selected_segment(0)
        editor = app._editor
        editor.payload["draft"] = "not a pronunciation"
        editor.active_field = None
        editor.selection = "apply"
        app._apply_editor()
        self.assertIs(app._editor, editor)
        self.assertIn("Error:", editor.error)
        self.assertEqual(app.session.query.model_dump(), original)

    def test_settings_are_reachable_and_editable_without_shortcuts(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query())
            app.config_path = Path(directory) / "config.json"
            for _ in range(4):
                app._handle_key(curses.KEY_DOWN)
            self.assertEqual(app._focus_key, ("settings", None))
            app._handle_key("\n")
            self.assertEqual(app._editor.kind, "settings")
            app._editor.selection = "take_count"
            app._handle_key("\n")
            app._handle_key(curses.KEY_BACKSPACE)
            app._handle_key("2")
            app._handle_key("\n")
            for _ in range(3):
                app._handle_key(curses.KEY_DOWN)
            app._handle_key("\n")
            self.assertIsNone(app._editor)
            self.assertEqual(app.settings.take_count, 2)
            self.assertEqual(json.loads(app.config_path.read_text())["take_count"], 2)

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
            ("settings", None),
        ):
            app._set_focus_key(key)
            app._handle_key("\n")
            self.assertIsNone(app._editor)

        app._focus_candidate(1)
        app._handle_key("\n")
        self.assertEqual(app.session.accept_calls, [])
        app._set_focus_key(("regenerate_selected", 1))
        app._handle_key("\n")
        app._start_generation.assert_not_called()
        app._start_regenerate_all.assert_not_called()
        app._start_regeneration.assert_not_called()
        app._set_focus_key(("candidate", 1))
        app._handle_key(" ")
        app._play_take.assert_called_with(1)

    def test_query_replacement_clears_stale_selected_take_and_r_cannot_regenerate_it(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        app._current_take = 1
        app._set_focus_key(("candidate", 1))
        replacement = app.session.query.model_copy(deep=True)
        replacement.voicegerSegments[1].phonemes = ["HH", "EH1"]
        app._apply_session_query(replacement)

        self.assertEqual(app.session.candidates, ())
        self.assertIsNone(app._current_take)
        self.assertNotIn(("regenerate_selected", 1), app._navigation_items())
        app._start_regeneration = Mock()
        app._handle_key("r")
        app._start_regeneration.assert_not_called()
        self.assertEqual(app._status, "Select a candidate before regenerating it.")

        app.session.candidates = (candidate(2),)
        app._play_take = Mock()
        app._focus_candidate(2)
        self.assertIn(("regenerate_selected", 2), app._navigation_items())

    def test_busy_navigation_marks_every_unavailable_action_without_reordering(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        app._current_take = 1
        app._busy = True

        items = app._navigation_items()
        rows = app._navigation_document(80)
        labels = {key: line for line, key in rows if key is not None}

        self.assertEqual([key for _line, key in rows if key is not None], items)
        self.assertIn("(unavailable while generating)", labels[("text", None)])
        for index in (0, 1):
            self.assertIn(
                "(unavailable while generating)",
                labels[("segment", index)],
            )
        self.assertIn("busy; unavailable while generating", labels[("generate", None)])
        self.assertIn(
            "Space replay; Enter unavailable while generating",
            labels[("candidate", 1)],
        )
        self.assertIn(
            "(unavailable while generating)",
            labels[("regenerate_selected", 1)],
        )
        self.assertIn("(unavailable while generating)", labels[("settings", None)])

    def test_busy_candidate_remains_playable_and_footer_does_not_claim_acceptance(self):
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
        self.assertIn("Space replay; Enter unavailable while generating", rendered)
        self.assertIn("Enter unavailable while generating", rendered)
        self.assertNotIn("Enter accepts and saves", rendered)
        footer = screen.drawn[-1][2]
        self.assertTrue(footer.endswith("q Quit"))
        self.assertLessEqual(len(footer), 79)

    def test_candidate_footer_says_enter_accepts_and_saves(self):
        app = self.make_app(candidates=(candidate(1),))
        app._play_take = Mock()
        app._focus_candidate(1)
        screen = FakeScreen()
        app._screen = screen
        app._render()
        self.assertIn("Enter accepts and saves", self.rendered(screen))

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
        for token in {"HH", "[AY]", "DH", "[EH]", "R", "AH", "N", "[OW]", "D"}:
            self.assertIn(token, rendered)
        self.assertNotIn("AY1", rendered)
        pronunciation_lines = [
            text
            for _row, _column, text, _attr in screen.drawn
            if text.startswith("Pronunciation:")
            or (text.startswith(" " * len("Pronunciation: ")) and text.strip())
        ]
        self.assertGreaterEqual(len(pronunciation_lines), 2)
        for _row, _column, text, _attr in screen.drawn:
            self.assertLessEqual(len(text), 79)

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
        moved._set_focus_key(("settings", None), moved=True)
        moved._events.put(("candidate", second))
        moved._consume_events()
        self.assertEqual(moved._focus_key, ("settings", None))
        moved._play_take.assert_called_once_with(1)

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
        app._set_focus_key(("regenerate_selected", 2))
        app._busy = True
        app._play_take = Mock()
        app._events.put(("candidate", replacement))
        app._consume_events()
        self.assertEqual(app._current_take, 2)
        self.assertEqual(app._focus_key, ("regenerate_selected", 2))
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

    def test_source_rebuild_stops_playback_before_closing_old_session(self):
        app = self.make_app(query=mixed_query())
        app._english_grouping(1)
        events = []
        old = app.session
        old.close = Mock(side_effect=lambda: events.append("close"))
        app._stop_playback = Mock(side_effect=lambda: events.append("stop"))
        replacement = FakeSession(query=mixed_query())
        app._open_text_editor("new source")
        app._editor.payload["draft"] = "new source"
        app._editor.active_field = None
        with patch(
            "voiceger_accent_adapter.tui.UtteranceSession.from_text",
            return_value=replacement,
        ):
            app._apply_editor()
        self.assertEqual(events, ["stop", "close"])
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
