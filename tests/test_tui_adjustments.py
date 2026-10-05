import unittest
from decimal import Decimal

from voiceger_editor.tui_adjustments import (
    StepResult,
    step_bounded,
    step_cyclic,
)


class TuiAdjustmentTests(unittest.TestCase):
    def test_bounded_step_moves_and_stops_at_endpoints(self):
        self.assertEqual(
            step_bounded(
                4,
                direction=1,
                step=1,
                minimum=1,
                maximum=5,
            ),
            StepResult(5, True),
        )
        self.assertEqual(
            step_bounded(
                5,
                direction=1,
                step=1,
                minimum=1,
                maximum=5,
            ),
            StepResult(5, False),
        )
        self.assertEqual(
            step_bounded(
                1,
                direction=-1,
                step=1,
                minimum=1,
                maximum=5,
            ),
            StepResult(1, False),
        )

    def test_bounded_step_keeps_feature_owned_decimal_step_and_single_bound(self):
        self.assertEqual(
            step_bounded(
                Decimal("0.95"),
                direction=1,
                step=Decimal("0.05"),
                minimum=Decimal("0.00"),
                maximum=Decimal("1.00"),
            ),
            StepResult(Decimal("1.00"), True),
        )
        self.assertEqual(
            step_bounded(
                Decimal("0.01"),
                direction=-1,
                step=Decimal("0.01"),
                minimum=Decimal("0.01"),
            ),
            StepResult(Decimal("0.01"), False),
        )

    def test_bounded_step_normalizes_direction_and_rejects_inverted_bounds(self):
        self.assertEqual(
            step_bounded(
                5,
                direction=7,
                step=2,
                minimum=1,
                maximum=10,
            ),
            StepResult(7, True),
        )
        self.assertEqual(
            step_bounded(
                5,
                direction=-3,
                step=2,
                minimum=1,
                maximum=10,
            ),
            StepResult(3, True),
        )
        self.assertEqual(
            step_bounded(
                5,
                direction=0,
                step=2,
                minimum=1,
                maximum=10,
            ),
            StepResult(5, False),
        )
        with self.assertRaises(ValueError):
            step_bounded(
                5,
                direction=1,
                step=1,
                minimum=10,
                maximum=1,
            )

    def test_cyclic_step_wraps_in_both_directions(self):
        choices = ("first", "second", "third")
        self.assertEqual(
            step_cyclic("third", choices, direction=1),
            StepResult("first", True),
        )
        self.assertEqual(
            step_cyclic("first", choices, direction=-1),
            StepResult("third", True),
        )

    def test_cyclic_step_reports_unchanged_for_single_choice_and_zero_direction(self):
        self.assertEqual(
            step_cyclic("only", ("only",), direction=1),
            StepResult("only", False),
        )
        self.assertEqual(
            step_cyclic("first", ("first", "second"), direction=0),
            StepResult("first", False),
        )

    def test_cyclic_step_rejects_empty_choices_and_missing_current_value(self):
        with self.assertRaises(ValueError):
            step_cyclic("missing", (), direction=1)
        with self.assertRaises(ValueError):
            step_cyclic("missing", ("first", "second"), direction=1)


if __name__ == "__main__":
    unittest.main()
