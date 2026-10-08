import curses
from voiceger_editor import __version__
from voiceger_editor.project_info import DOCUMENTATION_URL
from voiceger_editor.settings import Settings
from voiceger_editor.tui_rendering import _HELP_ITEMS
from voiceger_editor.tui_status import info_status
from threading import Event
from tests.tui_app_test_support import TuiAppTestCase, FakeScreen as TuiAppFakeScreen, mixed_query
from tests.tui_rendering_test_support import RenderingTestCase, FakeScreen

import unittest

from voiceger_editor.tui_rendering import TuiRenderer
from voiceger_editor.tui_rendering_help import help_document


class HelpRenderingDocumentTests(RenderingTestCase):
    def test_renderer_compatibility_wrapper_uses_help_document_owner(self):
        self.assertEqual(help_document(48), TuiRenderer.help_document(48))
        self.assertTrue(
            any(
                "Voiceger Editor" in segment[1]
                for row in help_document(48)
                for segment in row
            )
        )

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


class HelpRenderingIntegrationTests(TuiAppTestCase):
    def test_background_generation_stays_visible_in_help_with_unrelated_status(self):
        app = self.make_app(query=mixed_query())
        item_id = app._batch.open_item_id
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._worker_item_id = item_id
        app._operations._active_operation_id = 7
        app._operations.operation_completed = 1
        app._operations.operation_total = 4
        app._operations._cancellation_event = Event()
        app._status = info_status("Caption 2 was added.")

        app._handle_key("?")
        app._screen = TuiAppFakeScreen(rows=24, columns=100)
        app._render()
        rendered = self.rendered(app._screen)

        self.assertIn(
            "Generating · Caption 1 · Take 2/4 · [Ctrl+C] Cancel generation",
            rendered,
        )
        self.assertIn("Status: Caption 2 was added.", rendered)

    def test_help_scroll_clamp_accounts_for_status_footer_height(self):
        app = self.make_app(query=mixed_query())
        app._screen = TuiAppFakeScreen(rows=8, columns=32)
        app._status = info_status(
            "This is a long shared Status message that occupies multiple footer rows."
        )
        app._open_help()
        height, width = app._screen.getmaxyx()
        max_scroll = app._renderer.help_max_scroll(
            height,
            width,
            app._status,
        )
        self.assertGreater(
            max_scroll,
            app._renderer.help_max_scroll(height, width),
        )

        app._help_scroll = 10_000
        app._handle_key(curses.KEY_DOWN)

        self.assertEqual(app._help_scroll, max_scroll)

if __name__ == "__main__":
    unittest.main()
