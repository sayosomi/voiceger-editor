import curses
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from voiceger_editor.settings import Settings
from voiceger_editor.tui_editors import EnglishGroupingCache
from voiceger_editor.tui_editors import EnglishWordGroup
from voiceger_editor.tui_editors import PronunciationRow
from voiceger_editor.tui_display import _display_width
from tests.tui_app_test_support import TuiAppTestCase, FakeScreen as TuiAppFakeScreen, mixed_query
from tests.tui_rendering_test_support import RenderingTestCase, FakeScreen, FakeSession, candidate, render_state

import unittest

from voiceger_editor.tui_rendering_navigation import navigation_document



class NavigationRenderingDocumentTests(RenderingTestCase):
    def test_navigation_owner_builds_top_level_actions_without_session(self):
        labels = [
            line.text
            for line in navigation_document(
                render_state(focus_key=("settings", None)),
                80,
            )
        ]

        self.assertEqual(
            labels[-4:],
            ["▶ [S] Settings", "  [D] Dictionary", "  [?] Help", "  [Q] Quit"],
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

    def test_batch_item_output_row_is_a_visible_f_shortcut(self):
        screen = FakeScreen()
        settings = Settings(output_dir=Path("/tmp/voiceger-output"))
        with patch("voiceger_editor.tui_rendering.available_styles", return_value=()):
            self.renderer.render_navigation(
                screen,
                render_state(
                    settings=settings,
                    focus_key=("output", None),
                    batch_item_position=(1, 1),
                ),
                screen.rows,
                screen.columns,
                title="BATCH ITEM",
            )

        output_row = next(item for item in screen.drawn if item[0] == 2)
        self.assertIn("▶ [F] Output: /tmp/voiceger-output", output_row[2])
        self.assertTrue(output_row[3] & curses.A_REVERSE)

    def test_batch_item_output_edit_renders_in_place(self):
        screen = FakeScreen()
        settings = Settings(output_dir=Path("/tmp/voiceger-output"))
        edit = SimpleNamespace(
            owner="batch_item",
            value="/tmp/new-output",
            cursor=len("/tmp/new-output"),
        )
        with patch("voiceger_editor.tui_rendering.available_styles", return_value=()):
            self.renderer.render_navigation(
                screen,
                render_state(
                    settings=settings,
                    focus_key=("output", None),
                    batch_item_position=(1, 1),
                    output_path_edit=edit,
                ),
                screen.rows,
                screen.columns,
                title="BATCH ITEM",
            )

        output_row = next(item for item in screen.drawn if item[0] == 2)
        self.assertIn("▶ [F] Output: /tmp/new-output", output_row[2])

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
        self.assertEqual(labels[("candidate", 1)], "  [1]  Take 1  0.01s")
        self.assertEqual(labels[("candidate", 2)], "  [2]  Take 2  0.01s ✓")
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

    def test_candidate_number_tokens_bracket_one_through_nine_and_align_ten(self):
        state = render_state(
            session=FakeSession(
                candidates=tuple(candidate(number) for number in range(1, 11))
            ),
            settings=Settings(take_count=100),
        )
        labels = {
            line.key: line.text
            for line in self.renderer.navigation_document(state, 100)
            if line.key is not None
        }

        for number in range(1, 10):
            with self.subTest(number=number):
                self.assertEqual(
                    labels[("candidate", number)],
                    f"  [{number}]  Take {number}  0.01s",
                )
        self.assertEqual(labels[("candidate", 10)], "   10  Take 10  0.01s")

    def test_take_number_jump_row_only_appears_for_ten_or_more_candidates(self):
        nine = render_state(
            session=FakeSession(
                candidates=tuple(candidate(number) for number in range(1, 10))
            )
        )
        nine_labels = self.labels(self.renderer.navigation_document(nine, 100))
        self.assertNotIn("  [0] Jump to Take", nine_labels)

        twelve = render_state(
            session=FakeSession(
                candidates=tuple(candidate(number) for number in range(1, 13))
            )
        )
        twelve_labels = self.labels(self.renderer.navigation_document(twelve, 100))
        candidates_index = twelve_labels.index("Candidates")
        self.assertEqual(twelve_labels[candidates_index + 1], "  [0] Jump to Take")
        self.assertEqual(twelve_labels[candidates_index + 2], "")
        self.assertEqual(twelve_labels[candidates_index + 3], "  [1]  Take 1  0.01s")
        self.assertEqual(twelve_labels[candidates_index + 12], "   10  Take 10  0.01s")

    def test_active_take_number_jump_replaces_entry_row_with_explicit_input(self):
        state = render_state(
            session=FakeSession(
                candidates=tuple(candidate(number) for number in range(1, 13))
            ),
            batch_item_number_jump_active=True,
            batch_item_number_jump_value="12",
        )
        labels = self.labels(self.renderer.navigation_document(state, 100))
        candidates_index = labels.index("Candidates")

        self.assertEqual(labels[candidates_index + 1], "▶ Jump to Take: 12_ / 12")
        self.assertEqual(labels[candidates_index + 2], "  [Enter] Play   [Esc] Cancel")
        self.assertNotIn("  [0] Jump to Take", labels)


class NavigationRenderingIntegrationTests(TuiAppTestCase):
    def test_active_generation_renders_ctrl_c_cancel_hint(self):
        app = self.make_app(query=mixed_query())
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._active_operation_id = 1
        app._screen = TuiAppFakeScreen(rows=24, columns=100)

        app._render()

        self.assertIn("[Ctrl+C] Cancel generation", self.rendered(app._screen))

if __name__ == "__main__":
    unittest.main()
