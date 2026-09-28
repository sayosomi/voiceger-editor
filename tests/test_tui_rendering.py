import curses
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from voiceger_accent_adapter.english_stress import english_phonemes_to_editor_state
from voiceger_accent_adapter.settings import Settings
from voiceger_accent_adapter.tui_display import (
    _display_width,
    format_english_phonemes,
)
from voiceger_accent_adapter.tui_rendering import (
    _HELP_ITEMS,
    TuiRenderer,
    TuiRenderState,
)
from voiceger_accent_adapter.voicevox_api_models import (
    AccentPhrase,
    AudioQuery,
    Mora,
    VoicegerSegment,
)


class FakeScreen:
    def __init__(self, rows=24, columns=80):
        self.rows = rows
        self.columns = columns
        self.drawn = []
        self.cursor = None

    def getmaxyx(self):
        return self.rows, self.columns

    def addnstr(self, row, column, value, count, attr=0):
        self.drawn.append((row, column, value[:count], attr))

    def move(self, row, column):
        self.cursor = (row, column)


class FakeSession:
    def __init__(self, candidates=()):
        self.source_text = "今日はhello"
        self.query = AudioQuery(
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
                VoicegerSegment(language="en", text="hello", phonemes=["HH", "AH1"]),
            ],
        )
        self.pronunciation_needs_rebuild = False
        self.candidates = tuple(candidates)
        self.has_active_batch = bool(candidates)


def candidate(number):
    return SimpleNamespace(
        number=number,
        audio=[0.0] * 320,
        sampling_rate=32000,
    )


def render_state(
    *,
    session=None,
    settings=None,
    focus_key=("settings_summary", None),
    status="",
    segments=(("ja", "雨", 0), ("en", "hello", 1)),
    busy=False,
    worker_operation=None,
    worker_target=None,
    operation_completed=0,
    operation_total=0,
    pressed_adjustment=None,
    editor=None,
):
    return TuiRenderState(
        voiceger_root=Path("/nonexistent/voiceger"),
        settings=settings or Settings(),
        session=session,
        focus_key=focus_key,
        status=status,
        segments=segments if session is not None else (),
        busy=busy,
        worker_operation=worker_operation,
        worker_target=worker_target,
        operation_completed=operation_completed,
        operation_total=operation_total,
        pressed_adjustment=pressed_adjustment,
        editor=editor,
    )


class TuiRenderingTests(unittest.TestCase):
    def setUp(self):
        self.renderer = TuiRenderer()

    @staticmethod
    def rendered(screen):
        return "\n".join(text for _row, _column, text, _attr in screen.drawn)

    def test_help_bolds_shortcut_spans_and_wraps_explanations(self):
        screen = FakeScreen(rows=30, columns=60)
        self.renderer.render_help(screen, screen.columns)

        shortcut, suffix = _HELP_ITEMS[1]
        shortcut_draw = next(
            item
            for item in screen.drawn
            if item[2] == shortcut and item[3] & curses.A_BOLD
        )
        explanation_draws = [
            item
            for item in screen.drawn
            if shortcut_draw[0] <= item[0] < shortcut_draw[0] + 4
            and item[1] == 1 + _display_width(shortcut)
        ]
        self.assertTrue(shortcut_draw[3] & curses.A_BOLD)
        self.assertGreaterEqual(len(explanation_draws), 2)
        self.assertTrue(all(not (item[3] & curses.A_BOLD) for item in explanation_draws))
        self.assertTrue(any(suffix.lstrip()[:5] in item[2] for item in explanation_draws))
        footer = next(item for item in screen.drawn if "Return to Navigation" in item[2])
        self.assertEqual(footer[0], screen.rows - 1)
        self.assertTrue(footer[3] & curses.A_BOLD)

    def test_help_settings_shortcuts_are_independent_80x24_rows(self):
        screen = FakeScreen(rows=24, columns=80)
        self.renderer.render_help(screen, screen.columns)

        expected_settings = (
            ("s", ": open Settings at style"),
            ("v", ": open Settings at speed"),
            ("n", ": open Settings at takes"),
            ("o", ": open Settings at output"),
            ("x", ": open Settings at TXT"),
        )

        settings_rows = []
        for shortcut, suffix in expected_settings:
            shortcut_draw = next(
                item
                for item in screen.drawn
                if item[2] == shortcut and item[3] & curses.A_BOLD
            )
            suffix_draw = next(
                item
                for item in screen.drawn
                if item[0] == shortcut_draw[0]
                and item[1] == 1 + _display_width(shortcut)
                and item[2] == suffix
            )
            self.assertFalse(suffix_draw[3] & curses.A_BOLD)
            settings_rows.append(shortcut_draw[0])

        self.assertEqual(
            settings_rows,
            list(range(settings_rows[0], settings_rows[0] + 5)),
        )

        rebuild_draw = next(
            item
            for item in screen.drawn
            if "Rebuild pronunciation: rerun automatic pronunciation from current Text"
            in item[2]
        )
        self.assertEqual(rebuild_draw[0], settings_rows[-1] + 1)
        self.assertFalse(rebuild_draw[3] & curses.A_BOLD)

        footer = next(
            item for item in screen.drawn if "Return to Navigation" in item[2]
        )
        self.assertEqual(footer[0], screen.rows - 1)
        self.assertLess(rebuild_draw[0], footer[0])

    def test_navigation_document_formats_mixed_language_state_and_narrow_rows(self):
        session = FakeSession()
        session.query.voicegerSegments[1].text = "verylongenglishword"
        state = render_state(
            session=session,
            focus_key=("segment", 1),
            segments=(("ja", "雨", 0), ("en", "verylongenglishword", 1)),
        )
        rows = self.renderer.navigation_document(state, 80)
        action_rows = [line for line, key in rows if key is not None]
        self.assertTrue(any("JA | 雨" in line for line in action_rows))
        english = next(line for line in action_rows if "EN | very" in line)
        self.assertIn("HH [AH]", english)
        self.assertIn(("segment", 1), [key for _line, key in rows])

        narrow_rows = self.renderer.navigation_document(state, 24)
        english_index = next(
            index
            for index, (_line, key) in enumerate(narrow_rows)
            if key == ("segment", 1)
        )
        narrow_segment_rows = [narrow_rows[english_index][0]]
        for line, key in narrow_rows[english_index + 1 :]:
            if key is not None:
                break
            narrow_segment_rows.append(line)
        self.assertGreaterEqual(len(narrow_segment_rows), 2)
        self.assertTrue(
            all(_display_width(line) <= 23 for line in narrow_segment_rows)
        )

    def test_navigation_action_labels_expose_settings_help_and_quit_shortcuts(self):
        rows = self.renderer.navigation_document(
            render_state(session=FakeSession()), 80
        )
        labels = {key: line for line, key in rows if key is not None}
        self.assertIn("[s]", labels[("settings", None)])
        self.assertIn("[?]", labels[("help", None)])
        self.assertIn("[q]", labels[("quit", None)])

    def test_idle_generate_and_settings_rows_advertise_adjustable_values(self):
        session = FakeSession()
        settings = Settings(take_count=6)
        idle_state = render_state(
            session=session,
            settings=settings,
            focus_key=("generate", None),
        )
        idle_generate = next(
            line
            for line, key in self.renderer.navigation_document(idle_state, 100)
            if key == ("generate", None)
        )
        self.assertIn("[ Generate < 6 > takes ]", idle_generate)

        session.candidates = (candidate(1),)
        session.has_active_batch = True
        regenerate = next(
            line
            for line, key in self.renderer.navigation_document(idle_state, 100)
            if key == ("generate", None)
        )
        self.assertIn("[ Regenerate all < 6 > takes ]", regenerate)

        busy_state = render_state(
            session=session,
            settings=settings,
            focus_key=("generate", None),
            busy=True,
            worker_operation="initial",
            operation_completed=1,
            operation_total=6,
        )
        busy_generate = next(
            line
            for line, key in self.renderer.navigation_document(busy_state, 100)
            if key == ("generate", None)
        )
        self.assertIn("[ Generating 2/6 ]", busy_generate)
        self.assertNotIn("<", busy_generate)
        self.assertNotIn(">", busy_generate)

        busy_regenerate_state = render_state(
            session=session,
            settings=settings,
            focus_key=("generate", None),
            busy=True,
            worker_operation="regenerate_all",
            operation_completed=1,
            operation_total=6,
        )
        busy_regenerate = next(
            line
            for line, key in self.renderer.navigation_document(
                busy_regenerate_state, 100
            )
            if key == ("generate", None)
        )
        self.assertIn("[ Regenerating 2/6 ]", busy_regenerate)
        self.assertNotIn("<", busy_regenerate)
        self.assertNotIn(">", busy_regenerate)

        settings_editor = SimpleNamespace(
            kind="settings",
            title="SETTINGS",
            selection="style_id",
            payload={
                "draft_settings": {
                    "style_id": "1",
                    "speed": "1.0",
                    "take_count": "4",
                    "output_dir": "/tmp/voiceger-output",
                    "save_text": True,
                }
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )
        full_settings = Settings(
            style_id=1,
            speed=1.0,
            take_count=4,
            output_dir=Path("/tmp/voiceger-output"),
            save_text=True,
        )
        styles = (SimpleNamespace(id=1, name="Neutral"),)
        settings_state = render_state(
            settings=full_settings,
            editor=settings_editor,
        )
        with patch(
            "voiceger_accent_adapter.tui_rendering.available_styles",
            return_value=styles,
        ):
            document, _cursor_line, _cursor_column = self.renderer.editor_document(
                settings_state, 100
            )
        setting_rows = {
            key: line for line, key in document if isinstance(key, str)
        }
        self.assertIn("Style: < 1 Neutral >", setting_rows["style_id"])
        self.assertIn("Speed: < 1.00 >", setting_rows["speed"])
        self.assertIn("Take count: < 4 >", setting_rows["take_count"])
        self.assertIn("TXT sidecar: < ON >", setting_rows["save_text"])
        self.assertIn("Output directory: /tmp/voiceger-output", setting_rows["output_dir"])
        self.assertNotIn("<", setting_rows["output_dir"])
        self.assertNotIn(">", setting_rows["output_dir"])

        summary_screen = FakeScreen(columns=100)
        summary_state = render_state(
            settings=full_settings,
            focus_key=("settings_summary", None),
        )
        with patch(
            "voiceger_accent_adapter.tui_rendering.available_styles",
            return_value=styles,
        ):
            self.renderer.render_navigation(
                summary_screen,
                summary_state,
                summary_screen.rows,
                summary_screen.columns,
            )
        summary = next(
            text for row, _column, text, _attr in summary_screen.drawn if row == 1
        )
        output = next(
            text for row, _column, text, _attr in summary_screen.drawn if row == 2
        )
        self.assertNotIn("<", summary)
        self.assertNotIn(">", summary)
        self.assertNotIn("<", output)
        self.assertNotIn(">", output)

    def test_help_updates_tab_guidance_and_bolds_only_key_spans(self):
        screen = FakeScreen(columns=100)
        self.renderer.render_help(screen, screen.columns)

        drawn = {(row, column, text): attr for row, column, text, attr in screen.drawn}
        for index, (shortcut, suffix) in enumerate(_HELP_ITEMS):
            if shortcut is None:
                normal_attr = drawn[(2 + index, 1, suffix)]
                self.assertFalse(normal_attr & curses.A_BOLD)
                continue
            shortcut_attr = drawn[(2 + index, 1, shortcut)]
            self.assertTrue(shortcut_attr & curses.A_BOLD)
            suffix_attr = drawn[(2 + index, 1 + len(shortcut), suffix)]
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
        self.assertIn(
            "Up/Down: move one selectable Navigation item at a time", rendered
        )
        self.assertIn("Tab: move to the next major section/action", rendered)
        self.assertIn(
            "Shift+Tab: move to the previous major section/action", rendered
        )
        self.assertNotIn("Tab: move down one action", rendered)
        footer = next(
            (row, text, attr)
            for row, _column, text, attr in screen.drawn
            if "Return to Navigation" in text
        )
        self.assertEqual(footer[0], screen.rows - 1)
        self.assertEqual(
            footer[1], "Esc / Enter / ? Return to Navigation  |  q Quit"
        )
        self.assertTrue(footer[2] & curses.A_BOLD)

    def test_help_explanations_wrap_without_reaching_the_footer(self):
        screen = FakeScreen(rows=60, columns=40)
        self.renderer.render_help(screen, screen.columns)

        first_item = [item for item in screen.drawn if item[0] in (2, 3)]
        self.assertIn((2, 1, "Up/Down", curses.A_BOLD), first_item)
        self.assertTrue(
            any(row == 2 and column > 1 for row, column, _text, _attr in first_item)
        )
        explanation = "".join(
            text
            for row, column, text, _attr in first_item
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
                row < screen.rows - 1
                for row, _column, text, _attr in screen.drawn
                if row >= 2 and "Return to Navigation" not in text
            )
        )

    def test_pronunciation_rows_are_compact_selectable_actions(self):
        state = render_state(
            session=FakeSession(),
            focus_key=("segment", 0),
            segments=(("ja", "雨", 0), ("en", "hello", 1)),
        )
        rows = self.renderer.navigation_document(state, 80)
        labels = {key: line for line, key in rows if key is not None}

        self.assertEqual(labels[("segment", 0)], "▶ JA | 雨 | ア'")
        self.assertEqual(labels[("segment", 1)], "  EN | hello | HH [AH]")
        self.assertNotIn("segment 1", "\n".join(line for line, _key in rows))
        self.assertNotIn("segment 2", "\n".join(line for line, _key in rows))
        self.assertNotIn("[Enter: Edit]", labels[("segment", 0)])
        self.assertNotIn("[Enter: Edit]", labels[("segment", 1)])

    def test_text_is_one_selectable_wrapped_row_without_source_or_edit_metadata(self):
        source = "今日はhelloと言うよ。" * 8
        session = FakeSession()
        session.source_text = source
        rows = self.renderer.navigation_document(
            render_state(session=session, focus_key=("text", None)), 24
        )
        text_rows = [(line, key) for line, key in rows if key == ("text", None)]
        text_index = next(
            index for index, (_line, key) in enumerate(rows) if key == ("text", None)
        )
        continuations = []
        for line, key in rows[text_index + 1 :]:
            if key is not None:
                break
            if line.startswith(" " * len("▶ Text : ")):
                continuations.append(line.strip())
            else:
                break

        self.assertEqual(len(text_rows), 1)
        self.assertTrue(text_rows[0][0].startswith("▶ Text : "))
        self.assertEqual(
            "".join(
                [text_rows[0][0].removeprefix("▶ Text : ").strip(), *continuations]
            ),
            source,
        )
        visible = "\n".join(line for line, _key in rows)
        self.assertNotIn("Source:", visible)
        self.assertNotIn("[Enter: Edit]", visible)

    def test_no_candidates_are_rendered_on_one_compact_line(self):
        rows = self.renderer.navigation_document(
            render_state(session=FakeSession()), 80
        )
        self.assertIn(("Candidates   No candidates yet.", None), rows)
        self.assertEqual(sum("No candidates yet." in line for line, _ in rows), 1)

    def test_navigation_render_has_no_footer_and_leaves_final_row_unused(self):
        session = FakeSession(candidates=(candidate(1),))
        state = render_state(session=session, status="Saved output.wav.")
        screen = FakeScreen(rows=24)
        self.renderer.render_navigation(screen, state, screen.rows, screen.columns)

        rendered = self.rendered(screen)
        self.assertNotIn("↑/↓ Move", rendered)
        self.assertNotIn("? Help", rendered)
        self.assertIn("Status: Saved output.wav.", rendered)
        self.assertIn(22, [row for row, _column, _text, _attr in screen.drawn])
        self.assertNotIn(23, [row for row, _column, _text, _attr in screen.drawn])

        screen.drawn.clear()
        candidate_state = render_state(
            session=session,
            focus_key=("candidate", 1),
            status="Saved output.wav.",
        )
        self.renderer.render_navigation(
            screen, candidate_state, screen.rows, screen.columns
        )
        candidate_rendered = self.rendered(screen)
        self.assertNotIn("↑/↓ Move", candidate_rendered)
        self.assertNotIn("↑↓ Move/play", candidate_rendered)
        self.assertNotIn("Enter accepts and saves", candidate_rendered)
        self.assertNotIn("? Help", candidate_rendered)
        self.assertNotIn(23, [row for row, _column, _text, _attr in screen.drawn])

    def test_empty_and_error_status_render_in_the_status_row(self):
        screen = FakeScreen(rows=24)
        state = render_state(session=FakeSession())
        self.renderer.render_navigation(screen, state, screen.rows, screen.columns)
        self.assertFalse(
            any(text.startswith("Status:") for text in self.rendered(screen).splitlines())
        )
        self.assertTrue(
            any(row == 22 and text == "" for row, _column, text, _attr in screen.drawn)
        )

        screen.drawn.clear()
        error_state = render_state(
            session=FakeSession(), status="Error: Voiceger runtime failed."
        )
        self.renderer.render_navigation(
            screen, error_state, screen.rows, screen.columns
        )
        self.assertIn("Error: Voiceger runtime failed.", self.rendered(screen))
        status_rows = [
            row
            for row, _column, text, _attr in screen.drawn
            if "runtime failed" in text
        ]
        self.assertEqual(status_rows, [22])

    def test_only_focused_navigation_action_gets_focus_attribute(self):
        screen = FakeScreen()
        state = render_state(
            session=FakeSession(), focus_key=("segment", 1)
        )
        self.renderer.render_navigation(screen, state, screen.rows, screen.columns)
        focused = [
            row
            for row, _column, _text, attr in screen.drawn
            if attr & curses.A_REVERSE
        ]
        self.assertEqual(len(focused), 1)

    def test_candidate_rows_have_no_current_suffix_or_visible_selected_regenerate_action(self):
        session = FakeSession(candidates=(candidate(1), candidate(2)))
        rows = self.renderer.navigation_document(
            render_state(session=session, focus_key=("candidate", 2)), 80
        )
        labels = [line for line, _key in rows]
        self.assertIn("  Take 1  0.01s", labels)
        self.assertIn("▶ Take 2  0.01s", labels)
        visible = "\n".join(labels)
        self.assertNotIn("(current)", visible)
        self.assertNotIn("Regenerate selected", visible)
        self.assertNotIn("regenerate_selected", [key for _line, key in rows])

    def test_busy_navigation_uses_compact_rows_without_unavailable_suffixes(self):
        session = FakeSession(candidates=(candidate(1),))
        state = render_state(
            session=session,
            focus_key=("candidate", 1),
            busy=True,
            worker_operation="initial",
            operation_total=4,
        )
        rows = self.renderer.navigation_document(state, 80)
        labels = {key: line for line, key in rows if key is not None}

        self.assertIn("[ Generating 1/4 ]", labels[("generate", None)])
        self.assertNotIn("unavailable while generating", "\n".join(labels.values()))
        self.assertNotIn("Space replay", "\n".join(labels.values()))
        self.assertNotIn("(current)", "\n".join(labels.values()))

    def test_long_english_navigation_wraps_only_between_complete_tokens_at_80_columns(self):
        phones = [
            "HH", "AY1", "DH", "EH1", "R", "!", "AY1", "M", "Z", "AH1",
            "N", "D", "AH0", "M", "AA1", "N", "N", "AW1", "N", "OW1", "D", "AH0", "!",
        ]
        text = "Hi There! I'm Zundamon now noda!"
        query = AudioQuery(
            accent_phrases=[],
            voicegerSegments=[
                VoicegerSegment(language="en", text=text, phonemes=phones)
            ],
        )
        session = FakeSession()
        session.query = query
        session.source_text = text
        rows = self.renderer.navigation_document(
            render_state(
                session=session,
                focus_key=("segment", 0),
                segments=(("en", text, 0),),
            ),
            80,
        )
        segment_position = next(
            index for index, (_text, key) in enumerate(rows) if key == ("segment", 0)
        )
        segment_lines = [rows[segment_position][0]]
        for text_line, key in rows[segment_position + 1 :]:
            if key is not None or text_line == "":
                break
            if text_line.startswith(" "):
                segment_lines.append(text_line)

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
        self.assertNotIn("segment 1", "\n".join(line for line, _key in rows))
        self.assertNotIn(
            "[Enter: Edit]",
            next(text for text, key in rows if key == ("segment", 0)),
        )

    def test_english_segment_editor_has_word_rows_wrapping_and_fixed_punctuation(self):
        word_phones = (
            "HH", "AA1", "K", "IY0", "N", "G", "W", "ER1", "D", "S",
            "HH", "AA0", "R", "T", "P", "AA1", "T", "ER0", "N",
        )
        phones = list(word_phones * 4) + ["!"]
        editor = SimpleNamespace(
            kind="english_segment",
            title="EDIT ENGLISH SEGMENT",
            selection=("word", 0),
            payload={
                "source_text": "Hi! There",
                "groups": (
                    SimpleNamespace(
                        label="LongWord", phonemes=tuple(phones[:-1]), editable=True
                    ),
                    SimpleNamespace(label="!", phonemes=("!",), editable=False),
                ),
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )
        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        drawn_lines = [line for line, _key in document]
        rendered = "\n".join(drawn_lines)
        self.assertIn("EDIT ENGLISH SEGMENT", rendered)
        self.assertIn("Word 'LongWord'", rendered)
        self.assertIn("Fixed context '!'", rendered)
        self.assertIn("[AA]", rendered)
        self.assertIn("ER", rendered)
        pronunciation_start = next(
            index
            for index, line in enumerate(drawn_lines)
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

    def test_active_field_footers_describe_settings_and_english_escape_scope(self):
        cases = (
            (
                SimpleNamespace(
                    kind="settings",
                    title="SETTINGS",
                    selection="speed",
                    payload={
                        "draft_settings": {
                            "style_id": "1",
                            "speed": "1.00",
                            "take_count": "4",
                            "output_dir": "/tmp/output",
                            "save_text": True,
                        }
                    },
                    active_field="speed",
                    input_value="1.00",
                    input_cursor=4,
                    error="",
                    scroll=0,
                ),
                "Enter Finish field",
                "Esc Cancel Settings",
                "[Enter: Edit]",
            ),
            (
                SimpleNamespace(
                    kind="english_word",
                    title="EDIT ENGLISH WORD",
                    selection="phonemes",
                    payload={
                        "source_text": "Hi",
                        "label": "Hi",
                        "draft_state": english_phonemes_to_editor_state(
                            ["HH", "AY1"]
                        ),
                        "moving_primary": False,
                    },
                    active_field="phonemes",
                    input_value="HH AY1",
                    input_cursor=6,
                    error="",
                    scroll=0,
                ),
                "Enter Commit phonemes",
                "Esc Cancel word editor",
                None,
            ),
            (
                SimpleNamespace(
                    kind="japanese",
                    title="EDIT JAPANESE PRONUNCIATION",
                    selection="draft",
                    payload={"source_text": "雨", "draft": "あめ"},
                    active_field="draft",
                    input_value="あめ",
                    input_cursor=2,
                    error="",
                    scroll=0,
                ),
                "Enter Apply",
                "Esc Cancel",
                "Apply pronunciation changes",
            ),
        )
        for editor, expected_enter, expected_escape, unexpected in cases:
            with self.subTest(kind=editor.kind):
                screen = FakeScreen()
                state = render_state(editor=editor)
                self.renderer.render_editor(screen, state, screen.rows, screen.columns)
                rendered = self.rendered(screen)
                self.assertIn(expected_enter, rendered)
                self.assertIn(expected_escape, rendered)
                if unexpected is not None:
                    self.assertNotIn(unexpected, rendered)
        japanese_screen = FakeScreen()
        japanese_editor = cases[-1][0]
        self.renderer.render_editor(
            japanese_screen,
            render_state(editor=japanese_editor),
            japanese_screen.rows,
            japanese_screen.columns,
        )
        japanese_footer = self.rendered(japanese_screen)
        self.assertNotIn("Cancel and discard pronunciation draft", japanese_footer)

    def test_navigation_render_shows_generate_adjustment_and_candidate_rows(self):
        screen = FakeScreen(columns=100)
        state = render_state(
            session=FakeSession(),
            settings=Settings(take_count=6),
            focus_key=("generate", None),
            pressed_adjustment=("navigation", "generate", -1),
        )
        with patch("voiceger_accent_adapter.tui_rendering.available_styles", return_value=()):
            self.renderer.render_navigation(screen, state, screen.rows, screen.columns)
        self.assertTrue(
            any("[ Generate <<6 > takes ]" in text for _row, _column, text, _attr in screen.drawn)
        )

        candidate_screen = FakeScreen(columns=100)
        candidate_state = render_state(
            session=FakeSession(candidates=(candidate(1), candidate(2))),
            focus_key=("candidate", 2),
        )
        with patch("voiceger_accent_adapter.tui_rendering.available_styles", return_value=()):
            self.renderer.render_navigation(
                candidate_screen,
                candidate_state,
                candidate_screen.rows,
                candidate_screen.columns,
            )
        candidate_text = "\n".join(text for _row, _column, text, _attr in candidate_screen.drawn)
        self.assertIn("Take 1  0.01s", candidate_text)
        self.assertIn("Take 2  0.01s", candidate_text)
        self.assertIn("Regenerate all < 4 > takes", candidate_text)

    def test_editor_documents_cover_text_japanese_english_and_settings_modes(self):
        text_editor = SimpleNamespace(
            kind="text",
            title="EDIT TEXT",
            selection="draft",
            payload={"draft": "今日はhello"},
            active_field="draft",
            input_value="今日はhello",
            input_cursor=3,
            error="",
            scroll=0,
        )
        text_state = render_state(editor=text_editor)
        text_document, cursor_line, cursor_column = self.renderer.editor_document(
            text_state, 22
        )
        self.assertTrue(any("Draft source:" in line for line, _key in text_document))
        self.assertIsNotNone(cursor_line)
        self.assertGreater(cursor_column, 0)
        self.assertGreaterEqual(
            max(_display_width(line) for line, _key in text_document), 10
        )

        japanese_editor = SimpleNamespace(
            kind="japanese",
            title="EDIT JAPANESE PRONUNCIATION",
            selection="draft",
            payload={"source_text": "雨", "draft": "あめ"},
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )
        japanese_document, _, _ = self.renderer.editor_document(
            render_state(editor=japanese_editor), 80
        )
        self.assertTrue(any("Draft pronunciation: あめ" in line for line, _key in japanese_document))

        settings_editor = SimpleNamespace(
            kind="settings",
            title="SETTINGS",
            selection="style_id",
            payload={
                "draft_settings": {
                    "style_id": "1",
                    "speed": "1.0",
                    "take_count": "4",
                    "output_dir": "/tmp/output",
                    "save_text": True,
                }
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )
        with patch(
            "voiceger_accent_adapter.tui_rendering.available_styles",
            return_value=(SimpleNamespace(id=1, name="Neutral"),),
        ):
            settings_document, _, _ = self.renderer.editor_document(
                render_state(editor=settings_editor), 80
            )
        self.assertTrue(any("Style: < 1 Neutral >" in line for line, _key in settings_document))

        english_segment_editor = SimpleNamespace(
            kind="english_segment",
            title="EDIT ENGLISH SEGMENT",
            selection=("word", 0),
            payload={
                "source_text": "hello",
                "groups": (SimpleNamespace(label="hello", phonemes=("HH", "AH1"), editable=True),),
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )
        segment_document, _, _ = self.renderer.editor_document(
            render_state(editor=english_segment_editor), 40
        )
        self.assertTrue(any("Word 'hello'" in line for line, _key in segment_document))
        self.assertTrue(any("HH [AH]" in line for line, _key in segment_document))

        english_word_editor = SimpleNamespace(
            kind="english_word",
            title="EDIT ENGLISH WORD",
            selection="phonemes",
            payload={
                "source_text": "hello",
                "label": "hello",
                "draft_state": english_phonemes_to_editor_state(["HH", "AH1"]),
                "moving_primary": False,
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )
        word_document, _, _ = self.renderer.editor_document(
            render_state(editor=english_word_editor), 60
        )
        self.assertTrue(any("Draft pronunciation: HH [AH]" in line for line, _key in word_document))

    def test_safe_terminal_write_ignores_invalid_coordinates_and_curses_errors(self):
        screen = FakeScreen(columns=20)
        self.renderer._safe_add(screen, -1, 0, "hidden", 20)
        self.renderer._safe_add(screen, 0, 20, "hidden", 20)
        self.assertEqual(screen.drawn, [])

        screen.addnstr = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            curses.error("write failed")
        )
        self.renderer._safe_add(screen, 0, 0, "safe", 20)


if __name__ == "__main__":
    unittest.main()
