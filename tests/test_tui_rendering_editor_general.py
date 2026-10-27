import curses
from voiceger_editor.caption_batch import CaptionBatch
from voiceger_editor.tui_status import EMPTY_STATUS
from voiceger_editor.tui_status import info_status
from tests.tui_rendering_test_support import RenderingTestCase, FakeScreen, candidate, render_state

from types import SimpleNamespace
import unittest

from voiceger_editor.tui_rendering_editor_common import EditorDocumentBuilder
from voiceger_editor.tui_rendering_editor_general import build_document


class GeneralEditorRenderingDocumentTests(RenderingTestCase):
    def test_caption_owner_builds_draft_and_actions(self):
        editor = SimpleNamespace(
            kind="caption",
            title="EDIT CAPTION",
            selection="draft",
            payload={"draft": "hello"},
            active_field=None,
            input_value="hello",
            input_cursor=5,
            error="",
        )
        builder = EditorDocumentBuilder(render_state(editor=editor), 80)

        self.assertTrue(build_document(builder))
        self.assertIn(("▶ hello", "draft"), builder.lines)
        self.assertTrue(any("[A] Apply" in line for line, _key in builder.lines))

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

    def test_pronunciation_editors_show_direct_delete_only_when_allowed(self):
        for kind, payload, field, value in (
            ("japanese", {"source_text": "なのだ。"}, "pronunciation", "ナ' ノダ'。"),
            ("english_word", {"label": "hello"}, "phonemes", "HH AH1 L OW2"),
        ):
            for can_delete in (False, True):
                with self.subTest(kind=kind, can_delete=can_delete):
                    editor = SimpleNamespace(
                        kind=kind, title="EDIT PRONUNCIATION",
                        selection=field, payload={**payload, "can_delete": can_delete},
                        active_field=field, input_value=value,
                        input_cursor=len(value), error="", scroll=0,
                    )
                    document, _, _ = self.renderer.editor_document(
                        render_state(editor=editor), 80
                    )
                    labels = [line for line, _key in document]
                    self.assertEqual(
                        "  [X] Delete section" in labels,
                        can_delete,
                    )
                    self.assertIn("  [E] Edit text", labels)

    def test_delete_section_confirmation_wraps_full_language_labeled_text(self):
        for language, title in (("ja", "Japanese"), ("en", "English")):
            with self.subTest(language=language):
                value = "Very sweet indeed! And some more words."
                editor = SimpleNamespace(
                    kind="delete_confirmation", title="DELETE SECTION?",
                    selection="cancel",
                    payload={
                        "warning": "This section will be removed from the synthesized utterance.",
                        "target_language": language,
                        "target_text": value,
                    },
                    active_field=None, input_value="", input_cursor=0,
                    error="", scroll=0,
                )
                document, _, _ = self.renderer.editor_document(
                    render_state(editor=editor), 25
                )
                labels = [line for line, _key in document]
                self.assertIn(f"{title} section", labels)
                self.assertTrue(any("Very sweet" in line for line in labels))
                self.assertTrue(any("some more words" in line for line in labels))
                self.assertIn("  [D] Delete", labels)
                self.assertIn("▶ [Esc] Cancel", labels)

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
                "  [X] Delete section",
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

if __name__ == "__main__":
    unittest.main()
