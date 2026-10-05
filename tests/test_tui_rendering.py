import curses
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch

from voiceger_editor import __version__
from voiceger_editor.caption_batch import CaptionBatch
from voiceger_editor.project_info import DOCUMENTATION_URL
from voiceger_editor.settings import Settings
from voiceger_editor.tui_editors import (
    EnglishGroupingCache,
    EnglishWordGroup,
    PronunciationRow,
)
from voiceger_editor.tui_display import _display_width
from voiceger_editor.tui_rendering import (
    _HELP_ITEMS,
    _positioned_title,
    TuiRenderer,
    TuiRenderState,
)
from voiceger_editor.tui_status import (
    EMPTY_STATUS,
    error_status,
    info_status,
    warning_status,
)
from voiceger_editor.voicevox_api_models import (
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
    status=EMPTY_STATUS,
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
    accepted_take_number=None,
    batch_item_position=None,
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
        accepted_take_number=accepted_take_number,
        batch_item_position=batch_item_position,
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

    def test_semantic_colors_use_terminal_default_background(self):
        renderer = TuiRenderer()
        with patch(
            "voiceger_editor.tui_rendering.curses.has_colors",
            return_value=True,
        ), patch(
            "voiceger_editor.tui_rendering.curses.start_color"
        ), patch(
            "voiceger_editor.tui_rendering.curses.use_default_colors"
        ) as use_default_colors, patch(
            "voiceger_editor.tui_rendering.curses.init_pair"
        ) as init_pair, patch(
            "voiceger_editor.tui_rendering.curses.color_pair",
            side_effect=lambda pair: {1: 101, 2: 202, 3: 303}[pair],
        ):
            renderer.initialize_colors()

        use_default_colors.assert_called_once_with()
        self.assertEqual(
            init_pair.call_args_list,
            [
                call(1, curses.COLOR_CYAN, -1),
                call(2, curses.COLOR_RED, -1),
                call(3, curses.COLOR_MAGENTA, -1),
            ],
        )
        self.assertEqual(renderer._color_attr, 101)
        self.assertEqual(renderer._error_color_attr, 202)
        self.assertEqual(renderer._warning_color_attr, 303)
        self.assertEqual(
            renderer._status_attribute(error_status("failed")),
            curses.A_BOLD | 202,
        )
        self.assertEqual(
            renderer._status_attribute(warning_status("failed")),
            curses.A_BOLD | 303,
        )

    def test_semantic_status_colors_fall_back_to_reverse_without_color(self):
        renderer = TuiRenderer()
        with patch(
            "voiceger_editor.tui_rendering.curses.has_colors",
            return_value=False,
        ):
            renderer.initialize_colors()

        self.assertEqual(
            renderer._status_attribute(error_status("failed")),
            curses.A_BOLD | curses.A_REVERSE,
        )
        self.assertEqual(
            renderer._status_attribute(warning_status("failed")),
            curses.A_BOLD | curses.A_REVERSE,
        )

    def test_batch_item_header_uses_current_product_name_or_explicit_item_title(self):
        screen = FakeScreen()
        with patch("voiceger_editor.tui_rendering.available_styles", return_value=()):
            self.renderer.render_navigation(
                screen, render_state(), screen.rows, screen.columns
            )
        header = next(text for row, _column, text, _attr in screen.drawn if row == 0)
        self.assertEqual(header, "Voiceger Editor")
        self.assertNotIn("Voiceger Accent Adapter", header)

        screen.drawn.clear()
        with patch("voiceger_editor.tui_rendering.available_styles", return_value=()):
            self.renderer.render_navigation(
                screen,
                render_state(
                    focus_key=("batch_item", None),
                    batch_item_position=(2, 4),
                ),
                screen.rows,
                screen.columns,
                title="BATCH ITEM",
            )
        header_row = next(item for item in screen.drawn if item[0] == 0)
        header = header_row[2]
        self.assertTrue(header.startswith("BATCH ITEM"))
        self.assertTrue(header.endswith("< 2 / 4 >"))
        self.assertTrue(header_row[3] & curses.A_REVERSE)

    def test_batch_list_header_summarizes_selection_requested_takes_and_actions(self):
        batch = CaptionBatch(default_take_count=4)
        batch.add_captions_from_text(
            "first caption\nsecond caption",
            session_factory=lambda caption: SimpleNamespace(
                caption=caption, candidates=()
            ),
        )
        batch.toggle_included(batch.items[1].item_id)
        batch.items[0].session.candidates = (SimpleNamespace(number=1),)
        batch.mark_accepted(batch.items[1].item_id, 2)

        lines = self.renderer.batch_list_document(batch, ("caption", 0), 80)
        labels = [line.text for line in lines]
        self.assertIn("  Takes < 4 >", labels)
        self.assertIn("▶ [x] 1  [25%] first caption", labels)
        self.assertIn("  [ ] 2  [✓] second caption", labels)

        batch.items[0].session.candidates = tuple(
            SimpleNamespace(number=number) for number in range(1, 5)
        )
        labels = [
            line.text
            for line in self.renderer.batch_list_document(
                batch, ("caption", 0), 80
            )
        ]
        self.assertIn("▶ [x] 1  [!] first caption", labels)
        self.assertFalse(any(label.startswith("Selected:") for label in labels))
        self.assertFalse(any(label.startswith("Requested:") for label in labels))
        for action in (
            "[A] Add captions",
            "[G] Generate selected",
            "[S] Settings",
            "[D] Dictionary",
            "[?] Help",
            "[Q] Quit",
        ):
            self.assertTrue(any(action in label for label in labels))

        screen = FakeScreen()
        self.renderer.render_batch_list(
            screen, batch, ("caption", 0), EMPTY_STATUS, screen.rows, screen.columns
        )
        header = next(text for row, _column, text, _attr in screen.drawn if row == 0)
        self.assertEqual(
            header,
            "BATCH LIST · 1/2 selected · 4 takes · Accepted 1/2",
        )

        single = CaptionBatch(default_take_count=1)
        single.add_caption(
            "only caption",
            session_factory=lambda caption: SimpleNamespace(
                caption=caption, candidates=()
            ),
        )
        screen.drawn.clear()
        self.renderer.render_batch_list(
            screen, single, ("caption", 0), EMPTY_STATUS, screen.rows, screen.columns
        )
        header = next(text for row, _column, text, _attr in screen.drawn if row == 0)
        self.assertEqual(
            header,
            "BATCH LIST · 1/1 selected · 1 take · Accepted 0/1",
        )

    def test_batch_delete_confirmation_shows_target_and_explicit_actions(self):
        batch = CaptionBatch(default_take_count=4)
        batch.add_captions_from_text(
            "first caption\nsecond caption",
            session_factory=lambda caption: SimpleNamespace(
                caption=caption, candidates=()
            ),
        )
        screen = FakeScreen()

        self.renderer.render_batch_list(
            screen,
            batch,
            ("caption", 1),
            info_status("Delete confirmation active."),
            screen.rows,
            screen.columns,
            delete_confirmation_caption="second caption",
            delete_confirmation_selection="delete",
        )

        visible = self.rendered(screen)
        self.assertIn("DELETE CAPTION?", visible)
        self.assertIn("second caption", visible)
        self.assertIn("[D] Delete caption", visible)
        self.assertIn("[Esc] Cancel", visible)
        self.assertNotIn("BATCH LIST", visible)
        header = next(item for item in screen.drawn if item[0] == 0)
        self.assertTrue(header[3] & curses.A_REVERSE)
        self.assertTrue(header[3] & curses.A_BOLD)
        delete = next(item for item in screen.drawn if "[D] Delete caption" in item[2])
        self.assertTrue(delete[3] & curses.A_REVERSE)
        footer = next(
            text
            for row, _column, text, _attr in screen.drawn
            if row == screen.rows - 1
        )
        self.assertEqual(footer, "Status: Delete confirmation active.")

        screen.drawn.clear()
        self.renderer.render_batch_list(
            screen,
            batch,
            ("caption", 1),
            EMPTY_STATUS,
            screen.rows,
            screen.columns,
            delete_confirmation_caption="second caption",
            delete_confirmation_selection="cancel",
        )
        cancel = next(item for item in screen.drawn if "[Esc] Cancel" in item[2])
        self.assertTrue(cancel[2].startswith("▶ "))
        self.assertTrue(cancel[3] & curses.A_REVERSE)

    def test_acceptance_busy_state_keeps_generate_label_as_generate_action(self):
        lines = self.renderer.navigation_document(
            render_state(
                session=FakeSession(),
                focus_key=("generate", None),
                busy=True,
                worker_operation="accept",
                worker_target=2,
                operation_total=1,
            ),
            80,
        )

        label = next(line.text for line in lines if line.key == ("generate", None))
        self.assertIn("Generate < 4 > takes", label)
        self.assertNotIn("Generating", label)

    def test_main_japanese_phrases_use_fixed_separator_and_compound_mora_tokens(self):
        state = render_state(session=FakeSession(), focus_key=("pronunciation", 0))
        lines = self.renderer.navigation_document(state, 80)
        selectable = [line for line in lines if line.key and line.key[0] == "pronunciation"]

        labels = [line.text for line in lines]
        caption_index = next(index for index, value in enumerate(labels) if "Caption :" in value)
        build_index = labels.index("  [P] Build pronunciation")
        add_index = labels.index("  [A] Add section")
        generate_index = next(index for index, value in enumerate(labels) if value.startswith("  [G] Generate"))
        pronunciation_index = next(
            index for index, line in enumerate(lines)
            if line.key and line.key[0] == "pronunciation"
        )
        self.assertEqual(build_index, caption_index + 1)
        self.assertTrue(labels[caption_index].endswith("[E] Caption : 明日はhello everyoneまた明日"))
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

    def test_japanese_punctuation_renders_inline_in_phrase_order(self):
        rows = (
            PronunciationRow(
                "ja", "source", 0, 0, True,
                phrase_index=0,
                phrase_index_in_segment=0,
                moras=("ソ", "ウ"),
                accent=2,
                punctuation_suffix="、",
            ),
            PronunciationRow(
                "ja", "source", 0, 0, False,
                phrase_index=1,
                phrase_index_in_segment=1,
                moras=("ナ", "ノ", "ダ"),
                accent=3,
                punctuation_suffix="……",
            ),
            PronunciationRow(
                "ja", "source", 0, 0, False,
                phrase_index=2,
                phrase_index_in_segment=2,
                moras=("デ", "モ"),
                accent=1,
                punctuation_suffix="！？",
            ),
        )
        lines = self.renderer.navigation_document(
            render_state(
                session=FakeSession(),
                focus_key=("pronunciation", 0),
                pronunciation_rows=rows,
                segments=(("ja", "source", 0),),
            ),
            80,
        )
        selectable = [
            line for line in lines
            if line.key and line.key[0] == "pronunciation"
        ]

        self.assertEqual(len(selectable), 3)
        self.assertTrue(selectable[0].text.endswith("[ウ]、"))
        self.assertTrue(selectable[1].text.endswith("[ダ]……"))
        self.assertTrue(selectable[2].text.endswith("モ！？"))

    def test_japanese_punctuation_stays_attached_when_phrase_wraps(self):
        row = PronunciationRow(
            "ja", "source", 0, 0, True,
            phrase_index=0,
            phrase_index_in_segment=0,
            moras=("ア", "メ"),
            accent=2,
            punctuation_suffix="！？",
        )
        lines = self.renderer.navigation_document(
            render_state(
                session=FakeSession(),
                focus_key=("pronunciation", 0),
                pronunciation_rows=(row,),
                segments=(("ja", "source", 0),),
            ),
            18,
        )
        owned_lines = [
            line for line in lines
            if line.focus_owner == ("pronunciation", 0)
        ]

        self.assertGreater(len(owned_lines), 1)
        self.assertEqual(
            sum(line.key == ("pronunciation", 0) for line in owned_lines),
            1,
        )
        self.assertTrue(owned_lines[-1].text.endswith("[メ]！？"))
        self.assertNotIn("[メ] ！？", "\n".join(line.text for line in owned_lines))

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
        with patch("voiceger_editor.tui_rendering.available_styles", return_value=()):
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
        with patch("voiceger_editor.tui_rendering.available_styles", return_value=()):
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

    def test_help_describes_batch_hierarchy_and_has_no_direct_item_settings_jumps(self):
        screen = FakeScreen(rows=80, columns=120)
        self.renderer.render_help(screen, screen.columns)
        visible = self.rendered(screen)
        self.assertIn(f"Voiceger Editor {__version__}", visible)
        self.assertIn(f"Docs: {DOCUMENTATION_URL}", visible)
        for text in (
            "Up/Down",
            "Batch List Takes",
            "open a Batch List Caption",
            "toggle Batch List inclusion",
            "delete current Batch Item Caption through confirmation",
            "one level back",
            "E / P / A / G",
            "Caption / Build pronunciation / Add section / Generate or regenerate all",
            "1-9",
            "clear candidates through confirmation",
            "Batch List Add captions / Generate selected",
            "Menu mode: editor/modal action letters are active.",
            "Editing: Enter finishes; printable shortcut letters insert text.",
            "Add captions: Ctrl+N inserts a new line; Enter finishes editing.",
        ):
            self.assertIn(text, visible)
        for removed in (
            "open Settings at speed",
            "open Settings at takes",
            "open Settings at output",
            "open Settings at TXT",
            "open Settings at LAB",
            "Voiceger Accent Adapter",
        ):
            self.assertNotIn(removed, visible)
        self.assertNotIn("F5", visible)
        self.assertNotIn("Ctrl+G", visible)
        back = next(item for item in screen.drawn if item[2] == "▶ [Esc] Back")
        self.assertEqual(back[0], screen.rows - 2)
        self.assertTrue(back[3] & curses.A_REVERSE)

    def test_help_renders_shared_status_footer(self):
        screen = FakeScreen(rows=12, columns=80)

        self.renderer.render_help(
            screen,
            screen.columns,
            status=info_status("Help notice."),
        )

        footer = next(
            text
            for row, _column, text, _attr in screen.drawn
            if row == screen.rows - 1
        )
        back = next(item for item in screen.drawn if item[2] == "▶ [Esc] Back")
        self.assertEqual(footer, "Status: Help notice.")
        self.assertEqual(back[0], screen.rows - 2)

    def test_help_back_stays_visible_when_help_content_exceeds_short_terminal(self):
        for height in (24, 8, 4, 2):
            with self.subTest(height=height):
                screen = FakeScreen(rows=height, columns=80)
                self.renderer.render_help(screen, screen.columns)
                back = next(item for item in screen.drawn if item[2] == "▶ [Esc] Back")
                self.assertEqual(back[0], height - 2)
                self.assertTrue(back[3] & curses.A_REVERSE)
                self.assertFalse(
                    any(row >= height for row, _column, _text, _attr in screen.drawn)
                )

    def test_help_scrolls_body_and_clamps_offset(self):
        screen = FakeScreen(rows=12, columns=80)
        max_scroll = self.renderer.help_max_scroll(screen.rows, screen.columns)
        self.assertGreater(max_scroll, 0)

        top = self.renderer.render_help(screen, screen.columns, scroll=-100)
        self.assertEqual(top, 0)
        top_visible = self.rendered(screen)
        self.assertIn(f"Voiceger Editor {__version__}", top_visible)
        self.assertIn(f"Docs: {DOCUMENTATION_URL}", top_visible)

        screen.drawn.clear()
        bottom = self.renderer.render_help(screen, screen.columns, scroll=10_000)
        self.assertEqual(bottom, max_scroll)
        bottom_visible = self.rendered(screen)
        self.assertIn(": Quit", bottom_visible)
        self.assertNotIn(f"Docs: {DOCUMENTATION_URL}", bottom_visible)
        back = next(item for item in screen.drawn if item[2] == "▶ [Esc] Back")
        self.assertEqual(back[0], screen.rows - 2)
        self.assertTrue(back[3] & curses.A_REVERSE)

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
            labels[-4:], ["  [A] Apply", "  [C] Clear", "  [R] Reset", "  [Esc] Back"]
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
            "style_id": "3",
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
                    "voiceger_editor.tui_rendering.available_styles",
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

    def test_add_captions_editor_status_hint_explains_multiline_controls(self):
        editor = SimpleNamespace(
            kind="caption", title="ADD CAPTIONS", selection="draft",
            payload={"draft": "first\nsecond", "multiline": True},
            active_field="draft", input_value="first\nsecond", input_cursor=12,
            error="", scroll=0,
        )
        screen = FakeScreen(rows=10, columns=80)

        self.renderer.render_editor(
            screen, render_state(editor=editor), screen.rows, screen.columns
        )

        status = [
            text
            for row, _column, text, _attr in screen.drawn
            if row == screen.rows - 1
        ]
        self.assertEqual(
            status,
            ["Ctrl+N: New line   Enter: Finish editing   Esc: Back"],
        )

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
            error=error_status("invalid Caption"), scroll=0,
        )
        error_screen = FakeScreen(rows=10, columns=80)
        self.renderer.render_editor(
            error_screen,
            render_state(editor=editor, status=info_status("Saved output.wav.")),
            error_screen.rows,
            error_screen.columns,
        )
        error_lines = [
            text
            for row, _column, text, _attr in error_screen.drawn
            if row == error_screen.rows - 1
        ]
        self.assertEqual(error_lines, ["Error: invalid Caption"])

        editor.error = EMPTY_STATUS
        status_screen = FakeScreen(rows=10, columns=80)
        self.renderer.render_editor(
            status_screen,
            render_state(editor=editor, status=info_status("Saved output.wav.")),
            status_screen.rows,
            status_screen.columns,
        )
        existing_status = [
            text
            for row, _column, text, _attr in status_screen.drawn
            if row == status_screen.rows - 1
        ]
        self.assertEqual(existing_status, ["Status: Saved output.wav."])

    def test_editor_confirmation_uses_shared_status_footer(self):
        editor = SimpleNamespace(
            kind="clear_candidates_confirmation",
            title="CLEAR CANDIDATES?",
            selection="clear",
            payload={"warning": "Candidates will be removed."},
            active_field=None,
            input_value="",
            input_cursor=0,
            error=EMPTY_STATUS,
            scroll=0,
        )
        screen = FakeScreen(rows=10, columns=80)

        self.renderer.render_editor(
            screen,
            render_state(
                editor=editor,
                status=warning_status("Operation warning."),
            ),
            screen.rows,
            screen.columns,
        )

        footer = next(
            text
            for row, _column, text, _attr in screen.drawn
            if row == screen.rows - 1
        )
        self.assertEqual(footer, "Warning: Operation warning.")

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
        self.assertEqual(labels[-2:], ["▶ [R] Rebuild", "  [Esc] Cancel"])
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
            [line for line, _key in document[-8:]],
            [
                "  [P] Preview",
                "  [A] Apply",
                "  [S] Save to dictionary",
                "  [D] Dictionary menu",
                "  [E] Edit text",
                "  [C] Clear",
                "  [R] Reset",
                "  [Esc] Back",
            ],
        )

    def test_dictionary_entry_action_groups_match_add_and_edit_layout(self):
        cases = (
            (
                "dictionary_japanese_entry",
                {
                    "surface": "ずんだもん",
                    "moras": ("ズ", "ン", "ダ", "モ", "ン"),
                    "accent": 3,
                    "word_type": SimpleNamespace(value="PROPER_NOUN"),
                    "priority": 5,
                    "entry_index": 0,
                    "entry_total": 4,
                    "can_delete": True,
                },
                [
                    "surface",
                    "generate_pronunciation",
                    "pronunciation",
                    "word_type",
                    "priority",
                    "preview",
                    "save",
                    "delete",
                    "dictionary",
                    "back",
                ],
                True,
            ),
            (
                "dictionary_english_entry",
                {
                    "surface": "Voiceger",
                    "phonemes": ("V", "OY1", "AH0", "JH", "ER0"),
                    "entry_index": 0,
                    "entry_total": 4,
                    "can_delete": True,
                },
                [
                    "surface",
                    "generate_pronunciation",
                    "phonemes",
                    "preview",
                    "save",
                    "delete",
                    "dictionary",
                    "back",
                ],
                True,
            ),
            (
                "dictionary_japanese_entry",
                {
                    "surface": "",
                    "moras": (),
                    "accent": 1,
                    "word_type": SimpleNamespace(value="PROPER_NOUN"),
                    "priority": 5,
                    "entry_index": None,
                    "entry_total": None,
                    "can_delete": False,
                },
                [
                    "surface",
                    "generate_pronunciation",
                    "pronunciation",
                    "word_type",
                    "priority",
                    "preview",
                    "save",
                    "dictionary",
                    "back",
                ],
                False,
            ),
            (
                "dictionary_english_entry",
                {
                    "surface": "",
                    "phonemes": (),
                    "entry_index": None,
                    "entry_total": None,
                    "can_delete": False,
                },
                [
                    "surface",
                    "generate_pronunciation",
                    "phonemes",
                    "preview",
                    "save",
                    "dictionary",
                    "back",
                ],
                False,
            ),
        )
        for kind, payload, expected_keys, can_delete in cases:
            with self.subTest(kind=kind, can_delete=can_delete):
                editor = SimpleNamespace(
                    kind=kind,
                    title=(
                        "EDIT DICTIONARY WORD"
                        if can_delete
                        else "ADD DICTIONARY WORD"
                    ),
                    selection="surface",
                    payload=payload,
                    active_field=None,
                    input_value="",
                    input_cursor=0,
                    error="",
                    scroll=0,
                )
                document, _cursor_line, _cursor_column = self.renderer.editor_document(
                    render_state(editor=editor), 80
                )
                keyed = [
                    (index, key)
                    for index, (_text, key) in enumerate(document)
                    if key and key != "entry_navigator"
                ]
                positions = {key: index for index, key in keyed}

                self.assertEqual([key for _index, key in keyed], expected_keys)
                self.assertEqual(
                    positions["generate_pronunciation"],
                    positions["surface"] + 1,
                )
                pronunciation_key = (
                    "pronunciation"
                    if kind == "dictionary_japanese_entry"
                    else "phonemes"
                )
                self.assertEqual(
                    positions[pronunciation_key],
                    positions["generate_pronunciation"] + 2,
                )
                last_persisted = (
                    "priority"
                    if kind == "dictionary_japanese_entry"
                    else pronunciation_key
                )
                self.assertEqual(positions["preview"], positions[last_persisted] + 2)
                self.assertEqual(positions["save"], positions["preview"] + 1)
                if can_delete:
                    self.assertEqual(positions["delete"], positions["save"] + 2)
                    self.assertEqual(
                        positions["dictionary"],
                        positions["delete"] + 2,
                    )
                else:
                    self.assertEqual(
                        positions["dictionary"],
                        positions["save"] + 2,
                    )
                self.assertEqual(positions["back"], positions["dictionary"] + 1)

    def test_dictionary_existing_entry_titles_have_right_aligned_navigator(self):
        cases = (
            SimpleNamespace(
                kind="dictionary_japanese_entry",
                title="EDIT JAPANESE DICTIONARY WORD",
                selection="entry_navigator",
                payload={
                    "surface": "あめ",
                    "moras": ("ア", "メ"),
                    "accent": 1,
                    "word_type": SimpleNamespace(value="PROPER_NOUN"),
                    "priority": 5,
                    "entry_index": 1,
                    "entry_total": 4,
                },
                active_field=None,
                input_value="",
                input_cursor=0,
                error="",
                scroll=0,
            ),
            SimpleNamespace(
                kind="dictionary_english_entry",
                title="EDIT ENGLISH DICTIONARY WORD",
                selection="entry_navigator",
                payload={
                    "surface": "hello",
                    "phonemes": ("HH", "AH0", "L", "OW1"),
                    "entry_index": 1,
                    "entry_total": 4,
                },
                active_field=None,
                input_value="",
                input_cursor=0,
                error="",
                scroll=0,
            ),
        )
        for editor in cases:
            with self.subTest(kind=editor.kind):
                document, _cursor_line, _cursor_column = self.renderer.editor_document(
                    render_state(editor=editor), 50
                )

                self.assertEqual(document[0][1], "entry_navigator")
                self.assertTrue(document[0][0].startswith(editor.title))
                self.assertTrue(document[0][0].endswith("< 2 / 4 >"))
                self.assertLessEqual(_display_width(document[0][0]), 49)

                screen = FakeScreen(rows=24, columns=50)
                self.renderer.render_editor(
                    screen,
                    render_state(editor=editor),
                    screen.rows,
                    screen.columns,
                )
                header = next(item for item in screen.drawn if item[0] == 0)
                self.assertTrue(header[2].endswith("< 2 / 4 >"))
                self.assertTrue(header[3] & curses.A_REVERSE)

                editor.selection = "surface"
                screen = FakeScreen(rows=24, columns=50)
                self.renderer.render_editor(
                    screen,
                    render_state(editor=editor),
                    screen.rows,
                    screen.columns,
                )
                header = next(item for item in screen.drawn if item[0] == 0)
                self.assertFalse(header[3] & curses.A_REVERSE)

    def test_dictionary_add_entry_title_has_no_navigator(self):
        editor = SimpleNamespace(
            kind="dictionary_english_entry",
            title="ADD ENGLISH DICTIONARY WORD",
            selection="surface",
            payload={
                "surface": "",
                "phonemes": (),
                "entry_index": None,
                "entry_total": None,
            },
            active_field="surface",
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 50
        )

        self.assertEqual(document[0], ("ADD ENGLISH DICTIONARY WORD", None))
        self.assertNotIn("<", document[0][0])

    def test_dictionary_menu_renders_language_shortcuts(self):
        editor = SimpleNamespace(
            kind="dictionary_menu",
            title="DICTIONARY",
            selection="japanese",
            payload={"japanese_count": 2, "english_count": 1},
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )

        self.assertIn(("▶ [J] Japanese      2 words", "japanese"), document)
        self.assertIn(("  [E] English       1 words", "english"), document)
        self.assertIn(("  [Esc] Back", "back"), document)

    def test_dictionary_delete_confirmation_matches_common_modal(self):
        cases = (
            (
                "ja",
                {
                    "language": "ja",
                    "surface": "ずんだもん",
                    "moras": ("ズ", "ン", "ダ", "モ", "ン"),
                    "accent": 3,
                },
                "ズ ン [ダ] モ ン",
            ),
            (
                "en",
                {
                    "language": "en",
                    "surface": "Voiceger",
                    "phonemes": ("V", "OY1", "AH0", "JH", "ER0"),
                },
                "V OY1 AH0 JH ER0",
            ),
        )
        for language, payload, pronunciation in cases:
            with self.subTest(language=language):
                editor = SimpleNamespace(
                    kind="dictionary_delete_confirmation",
                    title="DELETE DICTIONARY WORD?",
                    selection="delete",
                    payload={
                        **payload,
                        "warning": "This dictionary word will be removed.",
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

                self.assertEqual(labels[0], "DELETE DICTIONARY WORD?")
                self.assertIn("Surface", labels)
                self.assertIn(f"  {payload['surface']}", labels)
                self.assertIn("Pronunciation", labels)
                self.assertIn(f"  {pronunciation}", labels)
                self.assertIn("This dictionary word will be removed.", labels)
                self.assertEqual(labels[-2:], ["▶ [D] Delete", "  [Esc] Cancel"])

                editor.selection = "cancel"
                document, _cursor_line, _cursor_column = self.renderer.editor_document(
                    render_state(editor=editor), 80
                )
                labels = [line for line, _key in document]
                self.assertEqual(labels[-2:], ["  [D] Delete", "▶ [Esc] Cancel"])

    def test_empty_dictionary_list_renders_add_and_back(self):
        editor = SimpleNamespace(
            kind="dictionary_japanese_list",
            title="JAPANESE DICTIONARY",
            selection="add",
            payload={
                "entries": (),
                "sort_mode": "surface_asc",
                "text_filter": "",
                "filter_enabled": False,
                "word_type_filter": "ALL",
                "visible_count": 0,
                "total_count": 0,
                "can_delete": False,
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

        self.assertTrue(
            any("No Japanese dictionary words." in line for line, _key in document)
        )
        self.assertIn(("▶ [A] Add", "add"), document)
        self.assertTrue(any("[S] Sort" in line for line, _key in document))
        filter_line = next(line for line, key in document if key == "filter")
        self.assertIn("[F] Filter", filter_line)
        self.assertIn("Not set", filter_line)
        self.assertNotIn("<", filter_line)
        self.assertNotIn(">", filter_line)
        self.assertIn(("  [Esc] Back", "back"), document)
        self.assertFalse(any("[X] Delete" in line for line, _key in document))

    def test_filtered_dictionary_no_match_keeps_actions_and_shown_total_count(self):
        editor = SimpleNamespace(
            kind="dictionary_english_list",
            title="ENGLISH DICTIONARY",
            selection="filter",
            payload={
                "entries": (),
                "sort_mode": "added_desc",
                "text_filter": "missing",
                "filter_enabled": True,
                "word_type_filter": None,
                "visible_count": 0,
                "total_count": 3,
                "can_delete": False,
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
        visible = "\n".join(line for line, _key in document)

        self.assertIn("Showing 0 / 3 words", visible)
        self.assertIn("No matching English dictionary words.", visible)
        self.assertIn("[S] Sort", visible)
        self.assertIn("Added ↓", visible)
        self.assertIn("[F] Filter", visible)
        self.assertIn("On: missing", visible)
        self.assertIn("[A] Add", visible)
        self.assertNotIn("[X] Delete", visible)

    def test_configured_disabled_filter_keeps_angle_bracket_off_state(self):
        editor = SimpleNamespace(
            kind="dictionary_english_list",
            title="ENGLISH DICTIONARY",
            selection="filter",
            payload={
                "entries": (),
                "sort_mode": "surface_asc",
                "text_filter": "record",
                "filter_enabled": False,
                "word_type_filter": None,
                "visible_count": 0,
                "total_count": 0,
                "can_delete": False,
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
        filter_line = next(line for line, key in document if key == "filter")
        self.assertIn("< Off >", filter_line)

    def test_dictionary_sort_chooser_renders_all_modes_without_angle_brackets(self):
        editor = SimpleNamespace(
            kind="dictionary_sort",
            title="SORT JAPANESE DICTIONARY",
            selection=("sort", 1),
            payload={
                "language": "ja",
                "modes": (
                    "surface_asc",
                    "surface_desc",
                    "word_type",
                    "priority_asc",
                    "priority_desc",
                    "added_asc",
                    "added_desc",
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
        visible = "\n".join(line for line, _key in document)
        self.assertIn("Surface ↑", visible)
        self.assertIn("▶ Surface ↓", visible)
        self.assertIn("Word type", visible)
        self.assertIn("Priority ↓", visible)
        self.assertIn("Added ↓", visible)
        self.assertNotIn("< Surface", visible)
        self.assertIn("[Esc] Back", visible)

    def test_dictionary_filter_editors_render_focused_fields_and_actions(self):
        cases = (
            SimpleNamespace(
                kind="dictionary_japanese_filter",
                title="FILTER JAPANESE DICTIONARY",
                selection="word_type",
                payload={
                    "language": "ja",
                    "text_query": "アメ",
                    "word_type_filter": "PROPER_NOUN",
                },
                active_field=None,
                input_value="",
                input_cursor=0,
                error="",
                scroll=0,
            ),
            SimpleNamespace(
                kind="dictionary_english_filter",
                title="FILTER ENGLISH DICTIONARY",
                selection="text_query",
                payload={"language": "en", "text_query": "ER0 D"},
                active_field=None,
                input_value="",
                input_cursor=0,
                error="",
                scroll=0,
            ),
        )
        for editor in cases:
            with self.subTest(kind=editor.kind):
                document, _cursor_line, _cursor_column = self.renderer.editor_document(
                    render_state(editor=editor), 80
                )
                visible = "\n".join(line for line, _key in document)
                self.assertIn("[A] Apply", visible)
                self.assertIn("[C] Clear filter", visible)
                self.assertIn("[Esc] Back", visible)
                if editor.kind == "dictionary_japanese_filter":
                    self.assertIn("Surface / Pronunciation", visible)
                    self.assertIn("PROPER_NOUN", visible)
                else:
                    self.assertIn("Surface / ARPAbet", visible)
                    self.assertIn("ER0 D", visible)

    def test_japanese_dictionary_list_uses_main_mora_accent_display(self):
        word = SimpleNamespace(
            surface="ずんだもん",
            pronunciation="ズンダモン",
            accent_type=3,
        )
        editor = SimpleNamespace(
            kind="dictionary_japanese_list",
            title="JAPANESE DICTIONARY",
            selection=("entry", 0),
            payload={
                "entries": (("uuid", word),),
                "sort_mode": "priority_desc",
                "text_filter": "ずん",
                "filter_enabled": True,
                "word_type_filter": "PROPER_NOUN",
                "visible_count": 1,
                "total_count": 4,
                "can_delete": True,
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

        entry = next(
            line for line, key in document if key == ("entry", 0)
        )
        self.assertIn("ずんだもん", entry)
        self.assertIn("ズ ン [ダ] モ ン", entry)
        visible = "\n".join(line for line, _key in document)
        self.assertNotIn("accent_type", visible)
        self.assertNotIn("Enter Edit", visible)
        self.assertIn("Showing 1 / 4 words", visible)
        self.assertTrue(any("[S] Sort" in line and "Priority ↓" in line for line, _key in document))
        self.assertTrue(any("[F] Filter" in line and "On: ずん" in line for line, _key in document))
        self.assertIn(("  [A] Add", "add"), document)
        self.assertIn(("  [X] Delete", "delete"), document)
        self.assertIn(("  [Esc] Back", "back"), document)

    def test_english_dictionary_list_renders_selectable_actions(self):
        entry = SimpleNamespace(
            surface="hello",
            phonemes=("HH", "AH0", "L", "OW1"),
        )
        editor = SimpleNamespace(
            kind="dictionary_english_list",
            title="ENGLISH DICTIONARY",
            selection="add",
            payload={
                "entries": (entry,),
                "entry_index": 0,
                "sort_mode": "surface_asc",
                "text_filter": "",
                "filter_enabled": False,
                "word_type_filter": None,
                "visible_count": 1,
                "total_count": 1,
                "can_delete": True,
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
        visible = "\n".join(line for line, _key in document)

        self.assertIn(("▶ [A] Add", "add"), document)
        self.assertTrue(any("[S] Sort" in line and "Surface ↑" in line for line, _key in document))
        filter_line = next(line for line, key in document if key == "filter")
        self.assertIn("[F] Filter", filter_line)
        self.assertIn("Not set", filter_line)
        self.assertNotIn("<", filter_line)
        self.assertNotIn(">", filter_line)
        self.assertIn(("  [X] Delete", "delete"), document)
        self.assertIn(("  [Esc] Back", "back"), document)
        self.assertNotIn("Enter Edit", visible)

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
            [line for line, _key in document[-8:]],
            [
                "  [P] Preview",
                "  [A] Apply",
                "  [S] Save to dictionary",
                "  [D] Dictionary menu",
                "  [E] Edit text",
                "  [C] Clear",
                "  [R] Reset",
                "  [Esc] Back",
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
                "  [Esc] Back",
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
            ["  [A] Add", "  [C] Clear", "  [R] Reset", "  [Esc] Back"],
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
        self.assertEqual(labels[-2:], ["▶ [D] Delete", "  [Esc] Cancel"])

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
        self.assertEqual(labels[-2:], ["▶ [C] Clear candidates", "  [Esc] Cancel"])

    def test_settings_use_sections_shortcuts_and_candidate_clearing_markers(self):
        editor = SimpleNamespace(
            kind="settings", title="EDIT SETTINGS", selection="speed",
            payload={"draft_settings": {
                "style_id": "3", "speed": "1.00", "take_count": "4",
                "output_dir": "/tmp/output", "save_text": True,
            }},
            active_field=None, input_value="", input_cursor=0, error="", scroll=0,
        )
        with patch(
            "voiceger_editor.tui_rendering.available_styles",
            return_value=(SimpleNamespace(id=3, name="Neutral"),),
        ):
            document, _, _ = self.renderer.editor_document(render_state(editor=editor), 80)
        visible = "\n".join(line for line, _key in document)

        for heading in ("Voice", "Generation", "Output", "Sampling", "Actions"):
            self.assertIn(heading, visible)
        for marked in (
            "[S] Style *", "[V] Speed *", "[K] Top K *",
            "[P] Top P *", "[T] Temperature *",
        ):
            self.assertIn(marked, visible)
        for unmarked in ("[N] Takes", "[O] Output", "[X] TXT", "[L] LAB"):
            self.assertIn(unmarked, visible)
        self.assertIn("[D] Reset sampling to Voiceger defaults", visible)
        self.assertIn("[A] Apply and save", visible)
        self.assertIn("[R] Reset", visible)
        self.assertIn("[Esc] Back", visible)
        self.assertIn(
            "* Applying this setting clears existing candidates.",
            visible,
        )
        self.assertEqual(
            [key for _line, key in document if key is not None],
            [
                "style_id", "speed", "take_count", "output_dir", "save_text", "save_lab",
                "top_k", "top_p", "temperature", "reset_sampling",
                "apply", "reset", "back",
            ],
        )
        self.assertNotIn("input:", visible)

        editor.active_field = "speed"
        editor.input_value = "1.25"
        editor.input_cursor = 4
        with patch(
            "voiceger_editor.tui_rendering.available_styles",
            return_value=(SimpleNamespace(id=3, name="Neutral"),),
        ):
            active, _, _ = self.renderer.editor_document(render_state(editor=editor), 80)
        speed_lines = [line for line, key in active if key == "speed"]
        self.assertTrue(any(line.startswith("▶ Speed *") and "1.25" in line for line in speed_lines))

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
            "voiceger_editor.tui_rendering.available_styles",
            return_value=(),
        ):
            document, _, _ = self.renderer.editor_document(
                render_state(editor=editor), 80
            )
        self.assertIn("▶ [S] Style *", "\n".join(line for line, _key in document))

        with patch(
            "voiceger_editor.tui_rendering.available_styles",
            side_effect=RuntimeError("styles unavailable"),
        ):
            value = self.renderer.setting_display("style_id", "19", Path("/missing"))
        self.assertEqual(value, "19")

    def test_no_per_page_footer_and_status_only_when_present(self):
        session = FakeSession(candidates=(candidate(1),))
        state = render_state(
            session=session,
            status=info_status("Saved output.wav."),
        )
        screen = FakeScreen()
        with patch("voiceger_editor.tui_rendering.available_styles", return_value=()):
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

    def test_long_warning_wraps_at_bottom_without_overlapping_navigation(self):
        session = FakeSession(candidates=(candidate(1),))
        warning = warning_status(
            "Saved saved.wav. LAB generation failed: "
            "mixed-language timing provenance is unavailable: "
            "mixed LAB timing capture failed: detailed runtime reason"
        )
        screen = FakeScreen(rows=14, columns=42)
        with patch(
            "voiceger_editor.tui_rendering.available_styles",
            return_value=(),
        ):
            self.renderer.render_navigation(
                screen,
                render_state(
                    session=session,
                    focus_key=("generate", None),
                    status=warning,
                ),
                screen.rows,
                screen.columns,
            )

        first_status = next(
            row
            for row, _column, text, _attr in screen.drawn
            if text.startswith("Warning:")
        )
        status_rows = [
            (row, text, attr)
            for row, column, text, attr in screen.drawn
            if row >= first_status and column == 0
        ]
        self.assertGreater(len(status_rows), 1)
        self.assertEqual(status_rows[-1][0], screen.rows - 1)
        self.assertTrue(
            all(attr & curses.A_BOLD for _row, _text, attr in status_rows)
        )
        self.assertTrue(
            all(attr & curses.A_REVERSE for _row, _text, attr in status_rows)
        )
        self.assertIn("detailed runtime reason", " ".join(
            text for _row, text, _attr in status_rows
        ))
        navigation_rows = [
            row
            for row, column, text, _attr in screen.drawn
            if 4 <= row < first_status and column == 0 and text
        ]
        self.assertTrue(navigation_rows)
        self.assertLess(max(navigation_rows), first_status)
        self.assertFalse(
            any(row >= screen.rows for row, _column, _text, _attr in screen.drawn)
        )

    def test_angle_bracket_controls_show_transient_arrow_feedback(self):
        batch = CaptionBatch(default_take_count=4)
        batch_lines = self.renderer.batch_list_document(
            batch,
            ("takes", None),
            80,
            ("batch_list", "takes", 1),
        )
        self.assertIn(
            "▶ Takes < 4>>",
            [line.text for line in batch_lines],
        )

        dictionary_editor = SimpleNamespace(
            kind="dictionary_english_list",
            title="ENGLISH DICTIONARY",
            selection="sort",
            payload={
                "entries": (),
                "sort_mode": "surface_asc",
                "text_filter": "",
                "filter_enabled": False,
                "word_type_filter": None,
                "visible_count": 0,
                "total_count": 0,
                "can_delete": False,
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )
        dictionary_document, _, _ = self.renderer.editor_document(
            render_state(
                editor=dictionary_editor,
                pressed_adjustment=("dictionary", "sort", -1),
            ),
            80,
        )
        sort_line = next(
            line for line, key in dictionary_document if key == "sort"
        )
        self.assertIn("<<Surface ↑ >", sort_line)

        add_section_editor = SimpleNamespace(
            kind="add_section",
            title="ADD SECTION",
            selection="language",
            payload={
                "language": "ja",
                "draft": "",
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )
        add_section_document, _, _ = self.renderer.editor_document(
            render_state(
                editor=add_section_editor,
                pressed_adjustment=("editor", "language", 1),
            ),
            80,
        )
        language_line = next(
            line for line, key in add_section_document if key == "language"
        )
        self.assertIn("< Japanese>>", language_line)

        self.assertTrue(
            _positioned_title(
                "BATCH ITEM",
                (2, 3),
                80,
                1,
            ).endswith("< 2 / 3>>")
        )

    def test_main_action_and_candidate_rows_show_visible_shortcuts(self):
        state = render_state(
            session=FakeSession(candidates=(candidate(1), candidate(2))),
            settings=Settings(take_count=6),
            focus_key=("generate", None),
            pressed_adjustment=("navigation", "generate", -1),
            accepted_take_number=2,
        )
        lines = self.renderer.navigation_document(state, 100)
        labels = {line.key: line.text for line in lines if line.key is not None}
        self.assertEqual(labels[("build_pronunciation", None)], "  [P] Build pronunciation")
        self.assertEqual(labels[("add_section", None)], "  [A] Add section")
        self.assertEqual(labels[("generate", None)], "▶ [G] Regenerate all <<6 > takes")
        self.assertEqual(labels[("candidate", 1)], "  [1] Take 1  0.01s")
        self.assertEqual(labels[("candidate", 2)], "  [2] ✓ Take 2  0.01s")
        self.assertEqual(labels[("clear_candidates", None)], "  [C] Clear candidates")
        self.assertEqual(labels[("delete_caption", None)], "  [X] Delete caption")
        keyed = [line.key for line in lines if line.key is not None]
        self.assertLess(keyed.index(("candidate", 2)), keyed.index(("generate", None)))
        self.assertLess(keyed.index(("generate", None)), keyed.index(("clear_candidates", None)))
        candidate_index = next(
            index for index, line in enumerate(lines)
            if line.key == ("candidate", 2)
        )
        generate_index = next(
            index for index, line in enumerate(lines)
            if line.key == ("generate", None)
        )
        clear_index = next(
            index for index, line in enumerate(lines)
            if line.key == ("clear_candidates", None)
        )
        delete_index = next(
            index for index, line in enumerate(lines)
            if line.key == ("delete_caption", None)
        )
        self.assertEqual(lines[candidate_index + 1].text, "")
        self.assertEqual(generate_index, candidate_index + 2)
        self.assertEqual(clear_index, generate_index + 1)
        self.assertEqual(lines[clear_index + 1].text, "")
        self.assertEqual(delete_index, clear_index + 2)
        self.assertEqual(lines[delete_index + 1].text, "")
        self.assertEqual(labels[("settings", None)], "  [S] Settings")
        self.assertEqual(labels[("dictionary", None)], "  [D] Dictionary")
        self.assertEqual(labels[("help", None)], "  [?] Help")
        self.assertEqual(labels[("quit", None)], "  [Q] Quit")
        caption = labels[("caption", None)]
        self.assertIn("[E] Caption : ", caption)
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
