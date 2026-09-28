import curses
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from voiceger_accent_adapter.english_stress import english_phonemes_to_editor_state
from voiceger_accent_adapter.settings import Settings
from voiceger_accent_adapter.tui_editors import (
    EnglishGroupingCache,
    EnglishWordGroup,
    PronunciationRow,
)
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
        self.source_text = "明日はhello everyoneまた明日"
        self.query = AudioQuery(
            accent_phrases=[
                AccentPhrase(
                    moras=[
                        Mora(text=mora, vowel="a", vowel_length=0.1, pitch=0.0)
                        for mora in ("ア", "シ", "タ", "ワ")
                    ],
                    accent=4,
                ),
                AccentPhrase(
                    moras=[
                        Mora(text=mora, vowel="i", vowel_length=0.1, pitch=0.0)
                        for mora in ("イ", "イ", "テ", "ン", "キ")
                    ],
                    accent=3,
                ),
                AccentPhrase(
                    moras=[
                        Mora(text=mora, vowel="a", vowel_length=0.1, pitch=0.0)
                        for mora in ("マ", "タ", "ア", "シ", "タ")
                    ],
                    accent=3,
                ),
            ],
            voicegerSegments=[
                VoicegerSegment(
                    language="ja",
                    text="明日は",
                    accentPhraseStart=0,
                    accentPhraseCount=2,
                ),
                VoicegerSegment(
                    language="en",
                    text="hello everyone",
                    phonemes=[
                        "HH", "AH1", "L", "OW0", "EH1", "V", "R", "IY0",
                        "W", "AH0", "N",
                    ],
                ),
                VoicegerSegment(
                    language="ja",
                    text="また明日",
                    accentPhraseStart=2,
                    accentPhraseCount=1,
                ),
            ],
        )
        self.pronunciation_needs_rebuild = False
        self.candidates = tuple(candidates)
        self.has_active_batch = bool(candidates)


def candidate(number):
    return SimpleNamespace(number=number, audio=[0.0] * 320, sampling_rate=32000)


def rows_for(session=None):
    grouping = EnglishGroupingCache(
        "hello everyone",
        (
            EnglishWordGroup("hello", ("HH", "AH1", "L", "OW0"), True),
            EnglishWordGroup("everyone", ("EH1", "V", "R", "IY0", "W", "AH0", "N"), True),
        ),
    )
    return (
        PronunciationRow(
            "ja", "明日は", 0, 0, True, phrase_index=0,
            phrase_index_in_segment=0, moras=("ア", "シ", "タ", "ワ"), accent=4,
        ),
        PronunciationRow(
            "ja", "明日は", 0, 0, False, phrase_index=1,
            phrase_index_in_segment=1, moras=("イ", "イ", "テ", "ン", "キ"), accent=3,
        ),
        PronunciationRow(
            "en", "hello everyone", 1, 1, True, group_index=0,
            word="hello", phonemes=grouping.groups[0].phonemes,
            word_column_width=8, grouping=grouping,
        ),
        PronunciationRow(
            "en", "hello everyone", 1, 1, False, group_index=1,
            word="everyone", phonemes=grouping.groups[1].phonemes,
            vowel_offset=2, word_column_width=8, grouping=grouping,
        ),
        PronunciationRow(
            "ja", "また明日", 2, 2, True, phrase_index=2,
            phrase_index_in_segment=0, moras=("マ", "タ", "ア", "シ", "タ"), accent=3,
        ),
    )


def render_state(
    *,
    session=None,
    settings=None,
    focus_key=("settings_summary", None),
    status="",
    segments=(
        ("ja", "明日は", 0),
        ("en", "hello everyone", 1),
        ("ja", "また明日", 2),
    ),
    pronunciation_rows=None,
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
        pronunciation_rows=(
            pronunciation_rows if pronunciation_rows is not None
            else rows_for(session) if session is not None else ()
        ),
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

    @staticmethod
    def labels(rows):
        return [line.text for line in rows]

    def test_main_header_shows_product_title_without_navigation_label(self):
        screen = FakeScreen()
        with patch("voiceger_accent_adapter.tui_rendering.available_styles", return_value=()):
            self.renderer.render_navigation(screen, render_state(), screen.rows, screen.columns)

        header = next(text for row, _column, text, _attr in screen.drawn if row == 0)
        self.assertEqual(header, "Voiceger Accent Adapter")
        self.assertNotIn("NAVIGATION", header)

    def test_main_japanese_phrases_use_fixed_separator_and_compound_mora_tokens(self):
        state = render_state(session=FakeSession(), focus_key=("pronunciation", 0))
        lines = self.renderer.navigation_document(state, 80)
        selectable = [line for line in lines if line.key and line.key[0] == "pronunciation"]

        self.assertIn("Pronunciation", [line.text for line in lines])
        self.assertEqual(selectable[0].text, "▶ JA | ア シ タ [ワ]")
        self.assertEqual(selectable[1].text, "     | イ イ [テ] ン キ")
        self.assertNotIn("キ ョ", "\n".join(self.labels(lines)))
        self.assertEqual(selectable[0].key, ("pronunciation", 0))
        self.assertEqual(selectable[1].key, ("pronunciation", 1))

    def test_compound_mora_is_one_main_display_token(self):
        item = PronunciationRow(
            "ja", "今日", 0, 0, True,
            phrase_index=0,
            phrase_index_in_segment=0,
            moras=("キョ", "ウ"),
            accent=1,
        )
        lines = self.renderer.navigation_document(
            render_state(
                session=FakeSession(),
                focus_key=("pronunciation", 0),
                pronunciation_rows=(item,),
                segments=(("ja", "今日", 0),),
            ),
            80,
        )
        row = next(line.text for line in lines if line.key == ("pronunciation", 0))
        self.assertEqual(row, "▶ JA | [キョ] ウ")
        self.assertNotIn("キ ョ", row)

    def test_english_words_are_individual_rows_grouped_under_one_language_label(self):
        lines = self.renderer.navigation_document(
            render_state(session=FakeSession(), focus_key=("pronunciation", 0)), 80
        )
        selectable = [line for line in lines if line.key and line.key[0] == "pronunciation"]
        english = [line for line in selectable if "hello" in line.text or "everyone" in line.text]

        self.assertEqual(len(english), 2)
        self.assertEqual(english[0].text, "  EN | hello      HH [AH] L OW")
        self.assertIn("HH [AH] L OW", english[0].text)
        self.assertEqual(
            english[1].text,
            "     | everyone   [EH] V R IY W AH N",
        )
        self.assertIn("[EH] V R IY W AH N", english[1].text)
        self.assertEqual(english[0].key, ("pronunciation", 2))
        self.assertEqual(english[1].key, ("pronunciation", 3))
        self.assertTrue(selectable[-1].text.startswith("  JA |"))
        self.assertNotIn("JA1", "\n".join(self.labels(lines)))
        self.assertNotIn("EN1", "\n".join(self.labels(lines)))

    def test_focused_english_source_is_bold_and_phonemes_are_reverse_only(self):
        state = render_state(
            session=FakeSession(), focus_key=("pronunciation", 2)
        )
        screen = FakeScreen()
        with patch("voiceger_accent_adapter.tui_rendering.available_styles", return_value=()):
            self.renderer.render_navigation(screen, state, screen.rows, screen.columns)

        base = next(
            item for item in screen.drawn
            if item[2].startswith("▶ EN | hello") and item[1] == 0
        )
        source = next(
            item for item in screen.drawn
            if item[2] == "hello" and item[1] == 7
        )
        self.assertTrue(base[3] & curses.A_REVERSE)
        self.assertFalse(base[3] & curses.A_BOLD)
        self.assertTrue(source[3] & curses.A_REVERSE)
        self.assertTrue(source[3] & curses.A_BOLD)

        idle_screen = FakeScreen()
        idle_state = render_state(session=FakeSession(), focus_key=("pronunciation", 0))
        with patch("voiceger_accent_adapter.tui_rendering.available_styles", return_value=()):
            self.renderer.render_navigation(idle_screen, idle_state, idle_screen.rows, idle_screen.columns)
        idle_source = next(item for item in idle_screen.drawn if item[2] == "hello")
        self.assertTrue(idle_source[3] & curses.A_BOLD)
        self.assertFalse(idle_source[3] & curses.A_REVERSE)

    def test_wrapped_physical_rows_keep_tokens_and_do_not_gain_focus_keys(self):
        phones = tuple(["HH", "AH1", "L", "OW0"] * 7)
        grouping = EnglishGroupingCache(
            "hello",
            (EnglishWordGroup("hello", phones, True),),
        )
        row = PronunciationRow(
            "en", "hello", 0, 0, True, group_index=0, word="hello",
            phonemes=phones, word_column_width=5, grouping=grouping,
        )
        lines = self.renderer.navigation_document(
            render_state(
                session=FakeSession(),
                focus_key=("pronunciation", 0),
                pronunciation_rows=(row,),
                segments=(("en", "hello", 0),),
            ),
            24,
        )
        child_lines = [line for line in lines if line.focus_owner == ("pronunciation", 0)]
        self.assertGreater(len(child_lines), 1)
        self.assertEqual(sum(line.key == ("pronunciation", 0) for line in child_lines), 1)
        self.assertTrue(all(_display_width(line.text) <= 23 for line in child_lines))
        self.assertTrue(all("AH1" not in line.text for line in child_lines))

    def test_help_contains_pronunciation_controls_and_separate_settings_shortcuts(self):
        screen = FakeScreen()
        self.renderer.render_help(screen, screen.columns)
        visible = self.rendered(screen)
        for text in (
            "Up/Down", "on JA: accent by one mora",
            "on EN: primary stress by one vowel",
            "on JA: edit segment pronunciation",
            "on EN: edit word phonemes",
        ):
            self.assertIn(text, visible)
        settings_shortcuts = (("s", "style"), ("v", "speed"), ("n", "takes"), ("o", "output"), ("x", "TXT"))
        rows = []
        for shortcut, label in settings_shortcuts:
            found = next(item for item in screen.drawn if item[2] == shortcut and item[3] & curses.A_BOLD)
            rows.append(found[0])
            self.assertIn(label, next(text for row, _column, text, _attr in screen.drawn if row == found[0] and text.startswith(": open Settings")))
        self.assertEqual(rows, list(range(rows[0], rows[0] + 5)))
        self.assertNotIn("Return to Navigation", visible)
        self.assertNotIn("| q Quit", visible)
        self.assertIn("q", [text for _row, _column, text, _attr in screen.drawn])

    def test_help_shortcut_emphasis_does_not_bold_explanations(self):
        screen = FakeScreen(rows=30, columns=60)
        self.renderer.render_help(screen, screen.columns)
        for shortcut, suffix in _HELP_ITEMS:
            if shortcut is None:
                continue
            draws = [item for item in screen.drawn if item[2] == shortcut]
            if draws:
                self.assertTrue(any(item[3] & curses.A_BOLD for item in draws))
        self.assertFalse(any("Return to Navigation" in text for _row, _column, text, _attr in screen.drawn))

    def test_text_editor_is_one_active_input_row_without_persistent_instructions(self):
        editor = SimpleNamespace(
            kind="text", title="EDIT TEXT", selection="draft", payload={"draft": "hello"},
            active_field="draft", input_value="hello", input_cursor=3, error="", scroll=0,
        )
        screen = FakeScreen()
        self.renderer.render_editor(screen, render_state(editor=editor), screen.rows, screen.columns)
        visible = self.rendered(screen)
        self.assertIn("▶ hello", visible)
        for removed in ("Draft source", "Input:", "[Enter: Edit]", "Enter applies", "compatible pronunciation"):
            self.assertNotIn(removed, visible)
        self.assertNotIn("Esc Cancel", visible)
        self.assertIsNotNone(screen.cursor)

    def test_japanese_editor_shows_wrapped_source_and_active_direct_notation(self):
        editor = SimpleNamespace(
            kind="japanese", title="EDIT JAPANESE PRONUNCIATION",
            selection="pronunciation",
            payload={"source_text": "今日は明日なのだ。"},
            active_field="pronunciation", input_value="ナ' ノダ'。",
            input_cursor=2, error="", scroll=0,
        )
        document, cursor_line, cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        visible = "\n".join(line for line, _key in document)
        self.assertEqual(document[0][0], "EDIT JAPANESE PRONUNCIATION")
        self.assertIn("\nSource\n", f"\n{visible}\n")
        self.assertIn("  今日は明日なのだ。", visible)
        self.assertIn("▶ ナ' ノダ'。", visible)
        self.assertEqual(cursor_line, 5)
        self.assertEqual(cursor_column, 5)
        self.assertNotIn("\nPronunciation\n", f"\n{visible}\n")
        self.assertNotIn("/", visible)
        self.assertIn("'", visible)
        self.assertNotIn("[Enter: Edit]", visible)

    def test_english_word_editor_only_shows_stress_free_phoneme_sequence(self):
        editor = SimpleNamespace(
            kind="english_word", title="EDIT WORD PRONUNCIATION",
            selection="phonemes",
            payload={
                "label": "hello",
                "draft_state": english_phonemes_to_editor_state(
                    ["HH", "AH1", "L", "OW2"]
                ),
            },
            active_field=None, input_value="", input_cursor=0, error="", scroll=0,
        )
        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        visible = "\n".join(line for line, _key in document)
        self.assertIn("EDIT WORD PRONUNCIATION", visible)
        self.assertIn("Word", visible)
        self.assertIn("hello", visible)
        self.assertIn("Phonemes  HH AH L OW", visible)
        self.assertNotIn("Primary stress", visible)
        self.assertNotIn("AH1", visible)
        self.assertNotIn("OW2", visible)
        self.assertNotIn("Done", visible)

    def test_settings_use_compact_rows_and_edit_the_current_field_in_place(self):
        editor = SimpleNamespace(
            kind="settings", title="EDIT SETTINGS", selection="speed",
            payload={"draft_settings": {
                "style_id": "1", "speed": "1.00", "take_count": "4",
                "output_dir": "/tmp/output", "save_text": True,
            }},
            active_field=None, input_value="", input_cursor=0, error="", scroll=0,
        )
        with patch(
            "voiceger_accent_adapter.tui_rendering.available_styles",
            return_value=(SimpleNamespace(id=1, name="Neutral"),),
        ):
            document, _, _ = self.renderer.editor_document(render_state(editor=editor), 80)
        visible = "\n".join(line for line, _key in document)
        self.assertIn("▶ Speed       < 1.00 >", visible)
        self.assertIn("Style       < 1 Neutral >", visible)
        self.assertIn("Takes       < 4 >", visible)
        self.assertIn("Output      /tmp/output", visible)
        self.assertIn("TXT         < ON >", visible)
        self.assertIn("[ Apply and save ]", visible)
        self.assertNotIn("input:", visible)

        editor.active_field = "speed"
        editor.input_value = "1.25"
        editor.input_cursor = 4
        with patch(
            "voiceger_accent_adapter.tui_rendering.available_styles",
            return_value=(SimpleNamespace(id=1, name="Neutral"),),
        ):
            active, _, _ = self.renderer.editor_document(render_state(editor=editor), 80)
        self.assertIn(("▶ Speed       1.25", "speed"), active)

    def test_no_per_page_footer_and_status_only_when_present(self):
        session = FakeSession(candidates=(candidate(1),))
        state = render_state(session=session, status="Saved output.wav.")
        screen = FakeScreen()
        with patch("voiceger_accent_adapter.tui_rendering.available_styles", return_value=()):
            self.renderer.render_navigation(screen, state, screen.rows, screen.columns)
        visible = self.rendered(screen)
        self.assertIn("Status: Saved output.wav.", visible)
        self.assertNotIn("↑/↓ Move", visible)
        self.assertNotIn("Enter accepts", visible)
        self.assertNotIn("Esc / Enter", visible)

        screen.drawn.clear()
        self.renderer.render_navigation(
            screen, render_state(session=session), screen.rows, screen.columns
        )
        self.assertFalse(any(text.startswith("Status:") for _row, _col, text, _attr in screen.drawn))

    def test_generate_and_candidate_rows_keep_existing_main_actions(self):
        state = render_state(
            session=FakeSession(candidates=(candidate(1), candidate(2))),
            settings=Settings(take_count=6),
            focus_key=("generate", None),
            pressed_adjustment=("navigation", "generate", -1),
        )
        lines = self.renderer.navigation_document(state, 100)
        labels = {line.key: line.text for line in lines if line.key is not None}
        self.assertIn("Regenerate all <<6 > takes", labels[("generate", None)])
        self.assertIn("Take 1  0.01s", labels[("candidate", 1)])
        self.assertIn("Take 2  0.01s", labels[("candidate", 2)])

    def test_unavailable_status_and_terminal_write_safety_remain(self):
        screen = FakeScreen()
        self.renderer._safe_add(screen, -1, 0, "hidden", 80)
        self.renderer._safe_add(screen, 0, 80, "hidden", 80)
        self.assertEqual(screen.drawn, [])
        screen.addnstr = lambda *_args, **_kwargs: (_ for _ in ()).throw(curses.error("write failed"))
        self.renderer._safe_add(screen, 0, 0, "safe", 80)


if __name__ == "__main__":
    unittest.main()
