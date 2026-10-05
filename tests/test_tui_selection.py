import unittest

from voiceger_editor.tui_selection import (
    SelectionMoveResult,
    move_clamped_selection,
)


class TuiSelectionTests(unittest.TestCase):
    def test_signed_delta_moves_and_clamps_at_endpoints(self):
        items = ("first", "second", "third")

        self.assertEqual(
            move_clamped_selection("second", items, delta=1),
            SelectionMoveResult("third", 2, True),
        )
        self.assertEqual(
            move_clamped_selection("third", items, delta=1),
            SelectionMoveResult("third", 2, False),
        )
        self.assertEqual(
            move_clamped_selection("first", items, delta=-1),
            SelectionMoveResult("first", 0, False),
        )
        self.assertEqual(
            move_clamped_selection("first", items, delta=9),
            SelectionMoveResult("third", 2, True),
        )
        self.assertEqual(
            move_clamped_selection("third", items, delta=-9),
            SelectionMoveResult("first", 0, True),
        )

    def test_missing_current_resolves_from_first_index_before_moving(self):
        items = ("first", "second", "third")

        self.assertEqual(
            move_clamped_selection("missing", items, delta=1),
            SelectionMoveResult("second", 1, True),
        )
        self.assertEqual(
            move_clamped_selection("missing", items, delta=-1),
            SelectionMoveResult("first", 0, False),
        )

    def test_zero_delta_and_empty_sequence_report_no_movement(self):
        self.assertEqual(
            move_clamped_selection("second", ("first", "second"), delta=0),
            SelectionMoveResult("second", 1, False),
        )
        self.assertIsNone(move_clamped_selection("missing", (), delta=1))


if __name__ == "__main__":
    unittest.main()
