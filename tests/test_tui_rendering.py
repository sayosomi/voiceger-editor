import curses
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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
        self.caption = "明日はhello everyoneまた明日"
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
        self.candidates = tuple(candidates)
        self.has_active_batch = bool(candidates)


def candidate(number):
    return SimpleNamespace(number=number, frame_count=320, sampling_rate=32000)


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

    def assert_inactive_draft_wrapping(self, editor, draft, width, marker):
        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), width
        )
        draft_lines = [(line, key) for line, key in document if key == "draft"]

        self.assertGreater(len(draft_lines), 1)
        self.assertTrue(draft_lines[0][0].startswith(marker))
        self.assertEqual(
            "".join(line[len(marker):] for line, _key in draft_lines),
            draft,
        )
        self.assertTrue(all(key == "draft" for _line, key in draft_lines))
        self.assertTrue(
            all(
                line.startswith(" " * _display_width(marker))
                for line, _key in draft_lines[1:]
            )
        )
        self.assertTrue(
            all(_display_width(line) <= width - 1 for line, _key in draft_lines)
        )
        self.assertEqual(editor.payload["draft"], draft)
        return [line for line, _key in draft_lines]

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

        labels = [line.text for line in lines]
        caption_index = next(index for index, value in enumerate(labels) if "Caption :" in value)
        build_index = labels.index("  [B] Build pronunciation")
        add_index = labels.index("  [A] Add section")
        generate_index = next(index for index, value in enumerate(labels) if value.startswith("  [G] Generate"))
        pronunciation_index = next(
            index for index, line in enumerate(lines)
            if line.key and line.key[0] == "pronunciation"
        )
        self.assertEqual(build_index, caption_index + 1)
        self.assertTrue(labels[caption_index].endswith("Caption : 明日はhello everyoneまた明日"))
        self.assertLess(build_index, pronunciation_index)
        self.assertLess(pronunciation_index, add_index)
        self.assertLess(add_index, generate_index)
        self.assertNotIn("Pronunciation", labels)
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
        self.assertEqual(english[0].text, "  EN | hello      HH [AH1] L OW0")
        self.assertIn("HH [AH1] L OW0", english[0].text)
        self.assertEqual(
            english[1].text,
            "     | everyone   [EH1] V R IY0 W AH0 N",
        )
        self.assertIn("[EH1] V R IY0 W AH0 N", english[1].text)
        self.assertEqual(english[0].key, ("pronunciation", 2))
        self.assertEqual(english[1].key, ("pronunciation", 3))
        self.assertTrue(selectable[-1].text.startswith("  JA |"))
        self.assertNotIn("JA1", "\n".join(self.labels(lines)))
        self.assertNotIn("EN1", "\n".join(self.labels(lines)))

    def test_main_english_rows_show_all_stress_digits_and_primary_markers(self):
        cases = (
            (
                "record",
                ("HH", "AH0", "L", "OW1", "ER2"),
                "HH AH0 L [OW1] ER2",
            ),
            (
                "unusual",
                ("Z", "UW1", "N", "D", "AA1", "M", "OW0", "N"),
                "Z [UW1] N D [AA1] M OW0 N",
            ),
        )
        for word, phones, expected in cases:
            with self.subTest(word=word):
                grouping = EnglishGroupingCache(
                    word, (EnglishWordGroup(word, phones, True),)
                )
                item = PronunciationRow(
                    "en", word, 0, 0, True, group_index=0, word=word,
                    phonemes=phones, word_column_width=len(word), grouping=grouping,
                )
                lines = self.renderer.navigation_document(
                    render_state(
                        session=FakeSession(),
                        focus_key=("pronunciation", 0),
                        pronunciation_rows=(item,),
                        segments=(("en", word, 0),),
                    ),
                    80,
                )
                rendered = next(
                    line.text for line in lines
                    if line.key == ("pronunciation", 0)
                )
                self.assertIn(expected, rendered)

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
        phones = tuple(["UW1", "AA0", "OW2", "HH"] * 7)
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
        wrapped = " ".join(line.text for line in child_lines)
        self.assertIn("[UW1]", wrapped)
        self.assertIn("AA0", wrapped)
        self.assertIn("OW2", wrapped)

    def test_help_contains_pronunciation_controls_and_separate_settings_shortcuts(self):
        screen = FakeScreen()
        self.renderer.render_help(screen, screen.columns)
        visible = self.rendered(screen)
        for text in (
            "Up/Down", "on JA: accent by one mora",
            "on EN: primary stress by one vowel",
            "on JA: edit segment pronunciation",
            "on EN: edit word phonemes",
            "b / a / g",
            "Build pronunciation / Add section / Generate or regenerate all",
            "initial/regenerate-all",
            "cooperatively",
            "1-9",
            "clear candidates through confirmation",
            "Menu mode: editor/modal action letters are active.",
            "Editing: Enter finishes; printable shortcut letters insert text.",
        ):
            self.assertIn(text, visible)
        self.assertNotIn("F5", visible)
        self.assertNotIn("Ctrl+G", visible)
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
        back = next(item for item in screen.drawn if item[2] == "▶ [B] Back")
        self.assertEqual(back[0], screen.rows - 1)
        self.assertTrue(back[3] & curses.A_REVERSE)

    def test_help_back_stays_visible_when_help_content_exceeds_short_terminal(self):
        for height in (24, 8, 4, 2):
            with self.subTest(height=height):
                screen = FakeScreen(rows=height, columns=80)
                self.renderer.render_help(screen, screen.columns)
                back = next(item for item in screen.drawn if item[2] == "▶ [B] Back")
                self.assertEqual(back[0], height - 1)
                self.assertTrue(back[3] & curses.A_REVERSE)
                self.assertFalse(
                    any(row >= height for row, _column, _text, _attr in screen.drawn)
                )

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

    def test_caption_editor_has_explicit_actions_after_draft(self):
        editor = SimpleNamespace(
            kind="caption", title="EDIT CAPTION TEXT", selection="draft", payload={"draft": "hello"},
            active_field="draft", input_value="hello", input_cursor=3, error="", scroll=0,
        )
        screen = FakeScreen()
        self.renderer.render_editor(screen, render_state(editor=editor), screen.rows, screen.columns)
        visible = self.rendered(screen)
        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), screen.columns
        )
        labels = [line for line, _key in document]
        self.assertEqual(document[0][0], "EDIT CAPTION TEXT")
        self.assertEqual(
            labels[-4:], ["  [A] Apply", "  [C] Clear", "  [R] Reset", "  [B] Back"]
        )
        self.assertEqual(labels.index(""), 1)
        self.assertEqual(labels.index("", 2), labels.index("▶ hello") + 1)
        self.assertIn("▶ hello", visible)
        for removed in ("Draft source", "Input:", "[Enter: Edit]", "Enter applies", "compatible pronunciation"):
            self.assertNotIn(removed, visible)
        self.assertNotIn("Esc Cancel", visible)
        self.assertIsNotNone(screen.cursor)

    def test_long_inactive_caption_wraps_and_keeps_logical_focus_on_every_line(self):
        draft = "このずんだ餅はvery sweetなのだ。さらに長い文章がここまで続いていても全部表示されるのだ。"
        editor = SimpleNamespace(
            kind="caption",
            title="EDIT CAPTION TEXT",
            selection="draft",
            payload={"draft": draft},
            active_field=None,
            input_value=draft,
            input_cursor=len(draft),
            error="",
            scroll=0,
        )
        width = 19
        draft_lines = self.assert_inactive_draft_wrapping(
            editor, draft, width, "▶ "
        )

        screen = FakeScreen(rows=24, columns=width)
        self.renderer.render_editor(
            screen, render_state(editor=editor), screen.rows, screen.columns
        )
        rendered_draft = [
            item for item in screen.drawn if item[2] in draft_lines
        ]
        self.assertEqual([item[2] for item in rendered_draft], draft_lines)
        self.assertTrue(all(item[3] & curses.A_REVERSE for item in rendered_draft))

    def test_long_inactive_section_text_wraps_without_selection_marker(self):
        draft = "このセクションの文章も長くなって、表示幅を超えて最後まで続くのだ。"
        editor = SimpleNamespace(
            kind="section_text",
            title="EDIT SECTION TEXT",
            selection="preview",
            payload={"language": "ja", "draft": draft, "can_delete": False},
            active_field=None,
            input_value=draft,
            input_cursor=len(draft),
            error="",
            scroll=0,
        )

        self.assert_inactive_draft_wrapping(editor, draft, 17, "  ")

    def test_long_inactive_add_section_text_wraps(self):
        draft = "追加する文章も画面幅に収まらない長さになって最後まで表示されるのだ。"
        editor = SimpleNamespace(
            kind="add_section",
            title="ADD SECTION",
            selection="draft",
            payload={"language": "ja", "draft": draft},
            active_field=None,
            input_value=draft,
            input_cursor=len(draft),
            error="",
            scroll=0,
        )

        self.assert_inactive_draft_wrapping(editor, draft, 17, "▶ ")

    def test_wrapped_caption_keeps_actions_reachable_in_short_viewport(self):
        editor = SimpleNamespace(
            kind="caption",
            title="EDIT CAPTION TEXT",
            selection="apply",
            payload={"draft": "A long caption that spans many physical terminal lines."},
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )
        screen = FakeScreen(rows=7, columns=16)

        self.renderer.render_editor(
            screen, render_state(editor=editor), screen.rows, screen.columns
        )

        apply_line = next(
            item for item in screen.drawn if item[2] == "▶ [A] Apply"
        )
        self.assertLess(apply_line[0], screen.rows - 1)
        self.assertTrue(apply_line[3] & curses.A_REVERSE)

    def test_editor_status_shows_hint_for_each_active_text_entry_mode(self):
        settings = {
            "style_id": "1",
            "speed": "1.00",
            "take_count": "4",
            "output_dir": "/tmp/output",
            "save_text": True,
        }
        editors = (
            SimpleNamespace(
                kind="caption", title="EDIT CAPTION TEXT", selection="draft",
                payload={"draft": "caption"}, active_field="draft",
                input_value="caption", input_cursor=7, error="", scroll=0,
            ),
            SimpleNamespace(
                kind="japanese", title="EDIT PRONUNCIATION", selection="pronunciation",
                payload={"source_text": "今日は"}, active_field="pronunciation",
                input_value="キョウワ", input_cursor=4, error="", scroll=0,
            ),
            SimpleNamespace(
                kind="english_word", title="EDIT PRONUNCIATION", selection="phonemes",
                payload={"label": "hello"}, active_field="phonemes",
                input_value="HH AH1", input_cursor=6, error="", scroll=0,
            ),
            SimpleNamespace(
                kind="section_text", title="EDIT SECTION TEXT", selection="draft",
                payload={"language": "ja", "draft": "section", "can_delete": False},
                active_field="draft", input_value="section", input_cursor=7,
                error="", scroll=0,
            ),
            SimpleNamespace(
                kind="add_section", title="ADD SECTION", selection="draft",
                payload={"language": "ja", "draft": "new section"},
                active_field="draft", input_value="new section", input_cursor=11,
                error="", scroll=0,
            ),
            SimpleNamespace(
                kind="settings", title="EDIT SETTINGS", selection="output_dir",
                payload={"draft_settings": settings}, active_field="output_dir",
                input_value="/tmp/output", input_cursor=11, error="", scroll=0,
            ),
        )

        for editor in editors:
            with self.subTest(kind=editor.kind, active_field=editor.active_field):
                screen = FakeScreen(rows=10, columns=80)
                with patch(
                    "voiceger_accent_adapter.tui_rendering.available_styles",
                    return_value=(),
                ):
                    self.renderer.render_editor(
                        screen,
                        render_state(editor=editor),
                        screen.rows,
                        screen.columns,
                    )
                status = [
                    text
                    for row, _column, text, _attr in screen.drawn
                    if row == screen.rows - 1
                ]
                self.assertEqual(status, ["Enter: Finish editing   Esc: Back"])

    def test_editor_status_hint_disappears_after_editing_finishes(self):
        editor = SimpleNamespace(
            kind="caption", title="EDIT CAPTION TEXT", selection="draft",
            payload={"draft": "caption"}, active_field=None,
            input_value="caption", input_cursor=7, error="", scroll=0,
        )
        screen = FakeScreen(rows=10, columns=80)

        self.renderer.render_editor(
            screen, render_state(editor=editor), screen.rows, screen.columns
        )

        self.assertFalse(
            any(row == screen.rows - 1 for row, _column, _text, _attr in screen.drawn)
        )

    def test_editor_error_and_existing_status_override_editing_hint(self):
        editor = SimpleNamespace(
            kind="caption", title="EDIT CAPTION TEXT", selection="draft",
            payload={"draft": "caption"}, active_field="draft",
            input_value="caption", input_cursor=7,
            error="Error: invalid Caption", scroll=0,
        )
        error_screen = FakeScreen(rows=10, columns=80)
        self.renderer.render_editor(
            error_screen,
            render_state(editor=editor, status="Saved output.wav."),
            error_screen.rows,
            error_screen.columns,
        )
        error_status = [
            text
            for row, _column, text, _attr in error_screen.drawn
            if row == error_screen.rows - 1
        ]
        self.assertEqual(error_status, ["Error: invalid Caption"])

        editor.error = ""
        status_screen = FakeScreen(rows=10, columns=80)
        self.renderer.render_editor(
            status_screen,
            render_state(editor=editor, status="Saved output.wav."),
            status_screen.rows,
            status_screen.columns,
        )
        existing_status = [
            text
            for row, _column, text, _attr in status_screen.drawn
            if row == status_screen.rows - 1
        ]
        self.assertEqual(existing_status, ["Saved output.wav."])

    def test_build_confirmation_document_warns_and_orders_actions(self):
        editor = SimpleNamespace(
            kind="build_confirmation",
            title="REBUILD PRONUNCIATION?",
            selection="rebuild",
            payload={"warning": "Manual pronunciation or utterance edits will be replaced."},
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )
        document, cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        labels = [line for line, _key in document]
        self.assertEqual(document[0][0], "REBUILD PRONUNCIATION?")
        self.assertIn("Manual pronunciation or utterance edits will be replaced.", labels)
        self.assertEqual(labels[-2:], ["▶ [R] Rebuild", "  [B] Cancel"])
        self.assertIsNone(cursor_line)

    def test_japanese_editor_shows_wrapped_source_and_active_direct_notation(self):
        editor = SimpleNamespace(
            kind="japanese", title="EDIT PRONUNCIATION",
            selection="pronunciation",
            payload={"source_text": "今日は明日なのだ。"},
            active_field="pronunciation", input_value="ナ' ノダ'。",
            input_cursor=2, error="", scroll=0,
        )
        document, cursor_line, cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        visible = "\n".join(line for line, _key in document)
        self.assertEqual(document[0][0], "EDIT PRONUNCIATION")
        self.assertIn("\nSource\n", f"\n{visible}\n")
        self.assertIn("  今日は明日なのだ。", visible)
        self.assertIn("▶ ナ' ノダ'。", visible)
        self.assertEqual(cursor_line, 5)
        self.assertEqual(cursor_column, 5)
        self.assertNotIn("\nPronunciation\n", f"\n{visible}\n")
        self.assertNotIn("/", visible)
        self.assertIn("'", visible)
        self.assertNotIn("[Enter: Edit]", visible)
        self.assertEqual(
            [line for line, _key in document[-6:]],
            [
                "  [P] Preview",
                "  [A] Apply",
                "  [E] Edit text",
                "  [C] Clear",
                "  [R] Reset",
                "  [B] Back",
            ],
        )

    def test_english_word_editor_opens_on_full_stressed_phoneme_input(self):
        editor = SimpleNamespace(
            kind="english_word", title="EDIT PRONUNCIATION",
            selection="phonemes",
            payload={"label": "hello"},
            active_field="phonemes", input_value="HH AH1 L OW2",
            input_cursor=12, error="", scroll=0,
        )
        document, cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        visible = "\n".join(line for line, _key in document)
        self.assertIn("EDIT PRONUNCIATION", visible)
        self.assertIn("Word", visible)
        self.assertIn("hello", visible)
        self.assertIn("▶ HH AH1 L OW2", visible)
        self.assertIsNotNone(cursor_line)
        self.assertNotIn("Phonemes", visible)
        self.assertNotIn("Primary stress", visible)
        self.assertNotIn("Done", visible)
        self.assertEqual(
            [line for line, _key in document[-6:]],
            [
                "  [P] Preview",
                "  [A] Apply",
                "  [E] Edit text",
                "  [C] Clear",
                "  [R] Reset",
                "  [B] Back",
            ],
        )

    def test_section_text_editor_document_has_language_and_local_actions(self):
        editor = SimpleNamespace(
            kind="section_text",
            title="EDIT SECTION TEXT",
            selection="draft",
            payload={
                "language": "ja",
                "draft": "明日はいい天気",
                "can_delete": True,
            },
            active_field="draft",
            input_value="明日はいい天気",
            input_cursor=4,
            error="",
            scroll=0,
        )
        document, cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        labels = [line for line, _key in document]
        self.assertEqual(labels[0], "EDIT SECTION TEXT")
        self.assertEqual(labels[2:4], ["Language", "  Japanese"])
        self.assertIn("▶ 明日はいい天気", labels)
        self.assertEqual(
            labels[-5:],
            [
                "  [P] Preview",
                "  [A] Apply",
                "  [R] Reset",
                "  [D] Delete section",
                "  [B] Back",
            ],
        )
        self.assertIsNotNone(cursor_line)

    def test_add_section_document_shows_two_language_choices_and_ordered_actions(self):
        editor = SimpleNamespace(
            kind="add_section",
            title="ADD SECTION",
            selection="draft",
            payload={"language": "ja", "draft": ""},
            active_field="draft",
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )
        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        labels = [line for line, _key in document]
        self.assertEqual(labels[0], "ADD SECTION")
        self.assertIn("  Language    < Japanese >", labels)
        self.assertIn("▶ ", labels)
        self.assertEqual(
            labels[-4:],
            ["  [A] Add", "  [C] Clear", "  [R] Reset", "  [B] Back"],
        )

    def test_delete_confirmation_document_uses_required_warning_and_choices(self):
        editor = SimpleNamespace(
            kind="delete_confirmation",
            title="DELETE SECTION?",
            selection="delete",
            payload={"warning": "This section will be removed from the synthesized utterance."},
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )
        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        labels = [line for line, _key in document]
        self.assertEqual(labels[0], "DELETE SECTION?")
        self.assertIn("This section will be removed from the synthesized utterance.", labels)
        self.assertEqual(labels[-2:], ["▶ [D] Delete", "  [B] Cancel"])

    def test_clear_candidates_confirmation_names_discarded_wav_files(self):
        editor = SimpleNamespace(
            kind="clear_candidates_confirmation",
            title="CLEAR CANDIDATES?",
            selection="clear",
            payload={
                "warning": "All generated candidate WAV files will be discarded."
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
        labels = [line for line, _key in document]
        self.assertEqual(labels[0], "CLEAR CANDIDATES?")
        self.assertIn("All generated candidate WAV files will be discarded.", labels)
        self.assertEqual(labels[-2:], ["▶ [C] Clear candidates", "  [B] Cancel"])

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
        self.assertIn("▶ [V] Speed       < 1.00 >", visible)
        self.assertIn("Style       < Neutral >", visible)
        self.assertIn("Takes       < 4 >", visible)
        self.assertIn("Output      /tmp/output", visible)
        self.assertIn("TXT         < ON >", visible)
        self.assertIn("Sampling", visible)
        self.assertIn("Top K           < 20 >", visible)
        self.assertIn("Top P           < 1.00 >", visible)
        self.assertIn("Temperature     < 1.00 >", visible)
        self.assertIn("Reset sampling", visible)
        self.assertIn("[A] Apply and save", visible)
        self.assertIn("[R] Reset", visible)
        self.assertIn("[B] Back", visible)
        self.assertEqual(
            [key for _line, key in document if key is not None],
            [
                "style_id", "speed", "take_count", "output_dir", "save_text",
                "top_k", "top_p", "temperature", "reset_sampling",
                "apply", "reset", "back",
            ],
        )
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

    def test_settings_style_display_falls_back_to_id_when_unresolved(self):
        editor = SimpleNamespace(
            kind="settings", title="EDIT SETTINGS", selection="style_id",
            payload={"draft_settings": {
                "style_id": "19", "speed": "1.00", "take_count": "4",
                "output_dir": "/tmp/output", "save_text": False,
            }},
            active_field=None, input_value="", input_cursor=0, error="", scroll=0,
        )
        with patch(
            "voiceger_accent_adapter.tui_rendering.available_styles",
            return_value=(),
        ):
            document, _, _ = self.renderer.editor_document(
                render_state(editor=editor), 80
            )
        self.assertIn("▶ [S] Style       < 19 >", "\n".join(line for line, _key in document))

        with patch(
            "voiceger_accent_adapter.tui_rendering.available_styles",
            side_effect=RuntimeError("styles unavailable"),
        ):
            value = self.renderer.setting_display("style_id", "19", Path("/missing"))
        self.assertEqual(value, "19")

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

    def test_main_action_and_candidate_rows_show_visible_shortcuts(self):
        state = render_state(
            session=FakeSession(candidates=(candidate(1), candidate(2))),
            settings=Settings(take_count=6),
            focus_key=("generate", None),
            pressed_adjustment=("navigation", "generate", -1),
        )
        lines = self.renderer.navigation_document(state, 100)
        labels = {line.key: line.text for line in lines if line.key is not None}
        self.assertEqual(labels[("build_pronunciation", None)], "  [B] Build pronunciation")
        self.assertEqual(labels[("add_section", None)], "  [A] Add section")
        self.assertEqual(labels[("generate", None)], "▶ [G] Regenerate all 2 takes")
        self.assertEqual(labels[("candidate", 1)], "  [1] Take 1  0.01s")
        self.assertEqual(labels[("candidate", 2)], "  [2] Take 2  0.01s")
        self.assertEqual(labels[("clear_candidates", None)], "  [C] Clear candidates")
        self.assertEqual(labels[("settings", None)], "  [S] Settings")
        self.assertEqual(labels[("help", None)], "  [?] Help")
        self.assertEqual(labels[("quit", None)], "  [Q] Quit")
        caption = labels[("caption", None)]
        self.assertIn("Caption : ", caption)
        self.assertNotIn("[T]", caption)

    def test_candidates_above_nine_have_no_direct_numeric_shortcut_label(self):
        state = render_state(
            session=FakeSession(candidates=(candidate(9), candidate(10))),
            settings=Settings(take_count=100),
        )
        labels = {
            line.key: line.text
            for line in self.renderer.navigation_document(state, 100)
            if line.key is not None
        }

        self.assertEqual(labels[("candidate", 9)], "  [9] Take 9  0.01s")
        self.assertEqual(labels[("candidate", 10)], "  Take 10  0.01s")

    def test_unavailable_status_and_terminal_write_safety_remain(self):
        screen = FakeScreen()
        self.renderer._safe_add(screen, -1, 0, "hidden", 80)
        self.renderer._safe_add(screen, 0, 80, "hidden", 80)
        self.assertEqual(screen.drawn, [])
        screen.addnstr = lambda *_args, **_kwargs: (_ for _ in ()).throw(curses.error("write failed"))
        self.renderer._safe_add(screen, 0, 0, "safe", 80)


if __name__ == "__main__":
    unittest.main()
