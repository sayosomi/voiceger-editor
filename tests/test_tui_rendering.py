import unittest
import curses
from types import SimpleNamespace
from unittest.mock import call
from unittest.mock import patch
from voiceger_editor.caption_batch import CaptionBatch
from voiceger_editor.tui_operations import BackgroundOperationProgress
from voiceger_editor.tui_rendering import _positioned_title
from voiceger_editor.tui_rendering import format_background_operation_progress
from voiceger_editor.tui_rendering import TuiRenderer
from voiceger_editor.tui_status import EMPTY_STATUS
from voiceger_editor.tui_status import error_status
from voiceger_editor.tui_status import info_status
from voiceger_editor.tui_status import warning_status
from tests.tui_rendering_test_support import RenderingTestCase, FakeScreen, FakeSession, candidate, render_state

class TuiRenderingTests(RenderingTestCase):
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

    def test_background_operation_progress_uses_stable_item_identity(self):
        batch = CaptionBatch(default_take_count=4)
        batch.add_captions_from_text(
            "first caption\nsecond caption",
            session_factory=lambda caption: SimpleNamespace(
                caption=caption, candidates=()
            ),
        )
        progress = BackgroundOperationProgress(
            operation_id=7,
            operation="batch_generate",
            item_id=batch.items[1].item_id,
            completed=3,
            total=8,
            take_number=2,
            take_completed=1,
            take_total=4,
            caption_number=1,
            caption_total=2,
        )

        self.assertEqual(
            format_background_operation_progress(progress, batch, True),
            "Generating selected · Caption 2 · Take 2/4 · Overall 3/8 · "
            "[Ctrl+C] Cancel generation",
        )
        self.assertEqual(
            format_background_operation_progress(None, batch, True),
            "",
        )

    def test_footer_wrap_keeps_cancel_generation_hint_together(self):
        layout = self.renderer._status_footer_layout(
            EMPTY_STATUS,
            height=24,
            width=80,
            background_status=(
                "Generating selected · Caption 2 · Take 6/10 · Overall 15/20 · "
                "[Ctrl+C] Cancel generation"
            ),
        )

        self.assertEqual(
            layout.lines,
            (
                "Generating selected · Caption 2 · Take 6/10 · Overall 15/20",
                "[Ctrl+C] Cancel generation",
            ),
        )

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
                    "voiceger_editor.tui_rendering_shared.available_styles",
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

    def test_unavailable_status_and_terminal_write_safety_remain(self):
        screen = FakeScreen()
        self.renderer._safe_add(screen, -1, 0, "hidden", 80)
        self.renderer._safe_add(screen, 0, 80, "hidden", 80)
        self.assertEqual(screen.drawn, [])
        screen.addnstr = lambda *_args, **_kwargs: (_ for _ in ()).throw(curses.error("write failed"))
        self.renderer._safe_add(screen, 0, 0, "safe", 80)


if __name__ == "__main__":
    unittest.main()
