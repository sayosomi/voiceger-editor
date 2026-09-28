import curses
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from voiceger_accent_adapter.english_stress import english_phonemes_to_editor_state
from voiceger_accent_adapter.settings import Settings
from voiceger_accent_adapter.tui_display import _display_width
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
        self.assertEqual(footer[0], screen.rows - 2)
        self.assertTrue(footer[3] & curses.A_BOLD)

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
