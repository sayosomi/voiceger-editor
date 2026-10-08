from voiceger_editor.settings import Settings
from voiceger_editor.tui_status import EMPTY_STATUS
from voiceger_editor.tui_status import warning_status
from tests.tui_app_test_support import TuiAppTestCase, FakeScreen as TuiAppFakeScreen, mixed_query
from tests.tui_rendering_test_support import RenderingTestCase, FakeScreen

from types import SimpleNamespace
import unittest

from voiceger_editor.caption_batch import CaptionBatch
from voiceger_editor.tui_rendering_batch import batch_list_document


class BatchRenderingDocumentTests(RenderingTestCase):
    def test_batch_list_owner_builds_numbered_rows_and_actions(self):
        batch = CaptionBatch(default_take_count=2)
        batch.add_captions_from_text(
            "first caption\nsecond caption",
            session_factory=lambda caption: SimpleNamespace(
                caption=caption,
                candidates=(),
            ),
        )

        labels = [
            line.text
            for line in batch_list_document(batch, ("caption", 0), 80)
        ]

        self.assertIn("▶ [x] [1]  first caption", labels)
        self.assertIn("  [x] [2]  second caption", labels)
        self.assertIn("  [A] Add captions", labels)
        self.assertIn("  [G] Generate selected", labels)

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
        batch.set_generation_outcome(batch.items[0].item_id, "completed")
        batch.mark_accepted(batch.items[1].item_id, 2)

        lines = self.renderer.batch_list_document(batch, ("caption", 0), 80)
        labels = [line.text for line in lines]
        self.assertIn("  Takes < 4 >", labels)
        self.assertIn("▶ [x] [1]  [!] first caption", labels)
        self.assertIn("  [ ] [2]  [✓] second caption", labels)
        self.assertFalse(any("[25%]" in label for label in labels))

        batch.default_take_count = 9
        labels = [
            line.text
            for line in self.renderer.batch_list_document(
                batch, ("caption", 0), 80
            )
        ]
        self.assertIn("  Takes < 9 >", labels)
        self.assertIn("▶ [x] [1]  [!] first caption", labels)

        batch.set_generation_outcome(batch.items[0].item_id, "cancelled")
        labels = [
            line.text
            for line in self.renderer.batch_list_document(
                batch, ("caption", 0), 80
            )
        ]
        self.assertIn("▶ [x] [1]  [⚠] first caption", labels)

        batch.set_generation_outcome(batch.items[0].item_id, "failed")
        labels = [
            line.text
            for line in self.renderer.batch_list_document(
                batch, ("caption", 0), 80
            )
        ]
        self.assertIn("▶ [x] [1]  [⚠] first caption", labels)

        batch.set_generation_outcome(batch.items[0].item_id, "completed")
        batch.default_take_count = 4
        labels = [
            line.text
            for line in self.renderer.batch_list_document(
                batch, ("caption", 0), 80
            )
        ]
        self.assertIn("▶ [x] [1]  [!] first caption", labels)
        self.assertFalse(any(label.startswith("Selected:") for label in labels))
        self.assertFalse(any(label.startswith("Requested:") for label in labels))
        for action in (
            "[A] Add captions",
            "[G] Generate selected",
            "[R] Read batch",
            "[W] Write batch",
            "[S] Settings",
            "[D] Dictionary",
            "[?] Help",
            "[Q] Quit",
        ):
            self.assertTrue(any(action in label for label in labels))

        action_start = labels.index("  [A] Add captions")
        self.assertEqual(
            labels[action_start : action_start + 11],
            [
                "  [A] Add captions",
                "  [G] Generate selected",
                "",
                "  [R] Read batch",
                "  [W] Write batch",
                "",
                "  [S] Settings",
                "  [D] Dictionary",
                "",
                "  [?] Help",
                "  [Q] Quit",
            ],
        )

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

    def test_batch_list_marks_current_selected_generation_item(self):
        batch = CaptionBatch(default_take_count=4)
        batch.add_captions_from_text(
            "first caption\nsecond caption",
            session_factory=lambda caption: SimpleNamespace(
                caption=caption, candidates=()
            ),
        )

        lines = self.renderer.batch_list_document(
            batch,
            ("caption", 0),
            80,
            active_generation=(batch.items[1].item_id, 1, 4),
            generation_busy=True,
        )
        labels = [line.text for line in lines]

        self.assertIn("  [x] [2]  [25%] second caption", labels)
        self.assertNotIn("[25%]", next(
            line for line in labels if "first caption" in line
        ))

    def test_batch_list_number_jump_row_only_appears_for_ten_or_more_captions(self):
        def make_batch(count):
            batch = CaptionBatch(default_take_count=4)
            batch.add_captions_from_text(
                "\n".join(f"caption {number}" for number in range(1, count + 1)),
                session_factory=lambda caption: SimpleNamespace(
                    caption=caption,
                    candidates=(),
                ),
            )
            return batch

        nine = make_batch(9)
        screen = FakeScreen()
        self.renderer.render_batch_list(
            screen,
            nine,
            ("caption", 0),
            EMPTY_STATUS,
            screen.rows,
            screen.columns,
        )
        self.assertFalse(
            any("[0] Jump to Caption" in text for _row, _col, text, _attr in screen.drawn)
        )

        ten = make_batch(10)
        screen = FakeScreen()
        self.renderer.render_batch_list(
            screen,
            ten,
            ("caption", 0),
            EMPTY_STATUS,
            screen.rows,
            screen.columns,
        )
        jump_row = next(item for item in screen.drawn if item[0] == 1)
        self.assertEqual(jump_row[2], "  [0] Jump to Caption")

    def test_batch_list_number_jump_row_stays_pinned_when_scrolled_deep(self):
        batch = CaptionBatch(default_take_count=4)
        batch.add_captions_from_text(
            "\n".join(f"caption {number}" for number in range(1, 26)),
            session_factory=lambda caption: SimpleNamespace(
                caption=caption,
                candidates=(),
            ),
        )
        screen = FakeScreen(rows=12, columns=80)

        self.renderer.render_batch_list(
            screen,
            batch,
            ("caption", 19),
            EMPTY_STATUS,
            screen.rows,
            screen.columns,
        )

        self.assertEqual(
            next(text for row, _col, text, _attr in screen.drawn if row == 1),
            "  [0] Jump to Caption",
        )
        self.assertTrue(
            any(
                row >= 3 and "20  caption 20" in text
                for row, _col, text, _attr in screen.drawn
            )
        )

    def test_active_batch_number_jump_replaces_pinned_row_without_owning_status(self):
        batch = CaptionBatch(default_take_count=4)
        batch.add_captions_from_text(
            "\n".join(f"caption {number}" for number in range(1, 13)),
            session_factory=lambda caption: SimpleNamespace(
                caption=caption,
                candidates=(),
            ),
        )
        screen = FakeScreen(rows=14, columns=80)

        self.renderer.render_batch_list(
            screen,
            batch,
            ("caption", 10),
            warning_status("Requested Caption is unavailable."),
            screen.rows,
            screen.columns,
            background_status="Generating Caption 3: 1/4",
            number_jump_active=True,
            number_jump_value="11",
        )

        self.assertEqual(
            next(text for row, _col, text, _attr in screen.drawn if row == 1),
            "▶ Jump to Caption: 11_ / 12",
        )
        self.assertEqual(
            next(text for row, _col, text, _attr in screen.drawn if row == 2),
            "  [Enter] Open   [Esc] Cancel",
        )
        visible = self.rendered(screen)
        self.assertIn("Generating Caption 3: 1/4", visible)
        self.assertIn("Warning: Requested Caption is unavailable.", visible)

    def test_batch_list_number_tokens_mark_direct_shortcuts_and_align_content(self):
        batch = CaptionBatch(default_take_count=4)
        batch.add_captions_from_text(
            "\n".join(f"caption {number}" for number in range(1, 13)),
            session_factory=lambda caption: SimpleNamespace(
                caption=caption,
                candidates=(),
            ),
        )

        lines = self.renderer.batch_list_document(
            batch,
            ("caption", 11),
            80,
        )
        rows = {
            line.key[1] + 1: line.text
            for line in lines
            if line.key is not None and line.key[0] == "caption"
        }

        self.assertIn("[x] [1]  caption 1", rows[1])
        self.assertIn("[x] [9]  caption 9", rows[9])
        self.assertIn("[x]  10  caption 10", rows[10])
        self.assertIn("[x]  12  caption 12", rows[12])
        caption_columns = {
            rows[number].index(f"caption {number}")
            for number in (1, 9, 10, 12)
        }
        self.assertEqual(caption_columns, {11})


class BatchRenderingIntegrationTests(TuiAppTestCase):
    def test_batch_list_shows_active_item_generation_percentage(self):
        for completed, expected in ((0, "[0%]"), (2, "[50%]")):
            with self.subTest(completed=completed):
                app = self.make_app(query=mixed_query())
                item_id = app._batch.open_item_id
                app._operations.busy = True
                app._operations.worker_operation = "initial"
                app._operations._worker_item_id = item_id
                app._operations._active_operation_id = 1
                app._operations.operation_completed = completed
                app._operations.operation_total = 4

                app._handle_key("\x1b")
                app._screen = TuiAppFakeScreen(rows=24, columns=100)
                app._render()

                self.assertIn(expected, self.rendered(app._screen))

if __name__ == "__main__":
    unittest.main()
