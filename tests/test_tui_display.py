import unittest

from voiceger_accent_adapter.english_stress import english_phonemes_to_editor_state
from voiceger_accent_adapter.tui_display import (
    _adjustable_value,
    _display_width,
    _english_display_tokens,
    _japanese_mora_tokens,
    _move_wrapped_cursor,
    _phoneme_state_tokens,
    _phonemes_as_ui_tokens,
    _truncate_display,
    _wrap_active_input,
    _wrap_labeled_tokens,
    _wrap_tokens_with_prefixes,
    _wrap_text,
    _wrapped_ranges,
    format_english_phonemes,
)


class TuiDisplayTests(unittest.TestCase):
    def test_japanese_phrase_display_brackets_one_complete_mora(self):
        self.assertEqual(
            _japanese_mora_tokens(("ア", "シ", "タ", "ワ"), 4),
            ["ア", "シ", "タ", "[ワ]"],
        )
        self.assertEqual(
            _japanese_mora_tokens(("キョ", "ウ"), 1),
            ["[キョ]", "ウ"],
        )

    def test_japanese_token_wrapping_keeps_compound_mora_and_fixed_separator(self):
        lines, cursor = _wrap_tokens_with_prefixes(
            "▶ JA | ", "     | ", ["ア", "[キョ]", "ウ"], 13,
            cursor_index=2,
        )
        self.assertGreaterEqual(len(lines), 2)
        self.assertTrue(all(line.startswith("     | ") for line in lines[1:]))
        self.assertTrue(any("[キョ]" in line for line in lines))
        self.assertEqual(cursor[0], 2)
        self.assertFalse(any("キ ョ" in line for line in lines))

    def test_english_phoneme_formatting_shows_digits_and_marks_primary_stress(self):
        self.assertEqual(
            format_english_phonemes(
                ["V", "OY1", "AH0", "JH", "ER2"],
                selected_primary=0,
            ),
            "V ▶[OY1] AH0 JH ER2",
        )
        self.assertEqual(
            format_english_phonemes(["HH", "AH0", "L", "OW1", "ER2"]),
            "HH AH0 L [OW1] ER2",
        )
        self.assertEqual(
            format_english_phonemes(["ER", "IH"]),
            "ER IH",
        )

    def test_terminal_width_counts_fullwidth_and_combining_characters(self):
        self.assertEqual(_display_width("A界e\u0301\u200d"), 4)

    def test_adjustable_value_preserves_one_frame_boundary_feedback(self):
        self.assertEqual(_adjustable_value("1"), "< 1 >")
        self.assertEqual(_adjustable_value("1", -1), "<<1 >")
        self.assertEqual(_adjustable_value("1", 1), "< 1>>")
        self.assertEqual(_adjustable_value("1", 0), "< 1 >")

    def test_adjustable_feedback_forms_are_fixed_width_ascii_with_stable_value_column(self):
        for value in ("6", "1.00", "1 Neutral"):
            idle = _adjustable_value(value)
            left = _adjustable_value(value, -1)
            right = _adjustable_value(value, 1)
            self.assertEqual(
                (idle, left, right),
                (f"< {value} >", f"<<{value} >", f"< {value}>>"),
            )
            self.assertEqual(len(idle), len(left))
            self.assertEqual(len(idle), len(right))
            self.assertEqual(
                (idle.index(value), left.index(value), right.index(value)),
                (2, 2, 2),
            )
            self.assertTrue(idle.isascii() and left.isascii() and right.isascii())
            self.assertEqual((idle[0], left[0], right[0]), ("<", "<", "<"))
            self.assertEqual((idle[-1], left[-1], right[-1]), (">", ">", ">"))

    def test_character_wrapping_and_truncation_preserve_whole_characters(self):
        self.assertEqual(_wrap_text("A界BC", 3), ["A界", "BC"])
        self.assertEqual(_wrap_text("界", 1), ["界"])
        self.assertEqual(_wrap_text("", 5), [])
        self.assertEqual(_truncate_display("A界BC", 3), "A界")
        self.assertEqual(_truncate_display("A界BC", 2), "A")
        self.assertEqual(_truncate_display("A", 0), "")

    def test_labeled_token_wrapping_keeps_tokens_intact(self):
        self.assertEqual(
            _wrap_labeled_tokens("Phones: ", ["HH", "AH", "L", "OW"], 12),
            ["Phones: HH", "        AH L", "        OW"],
        )
        self.assertEqual(_wrap_labeled_tokens("Phones: ", [], 20), ["Phones: (none)"])

    def test_phoneme_tokens_show_all_stress_values_and_each_primary_marker(self):
        state = english_phonemes_to_editor_state(
            ["Z", "UW1", "N", "D", "AA1", "M", "OW0", "N"]
        )
        expected = ["Z", "[UW1]", "N", "D", "[AA1]", "M", "OW0", "N"]
        self.assertEqual(_phoneme_state_tokens(state), expected)
        self.assertEqual(
            _phonemes_as_ui_tokens(["HH", "AH0", "L", "OW1", "ER2"]),
            ["HH", "AH0", "L", "[OW1]", "ER2"],
        )
        self.assertEqual(
            _english_display_tokens(["HH", "AH1"]), ["HH", "[AH1]"]
        )

    def test_wrapped_input_ranges_and_cursor_location_use_terminal_cells(self):
        self.assertEqual(_wrapped_ranges("ab界cd", 3), [(0, 2), (2, 4), (4, 5)])
        self.assertEqual(_wrapped_ranges("", 3), [(0, 0)])
        self.assertEqual(
            _wrap_active_input("ab界cd", 3, 3),
            (["ab", "界c", "d"], 1, 2),
        )
        self.assertEqual(_wrap_active_input("", 0, 3), ([""], 0, 0))

    def test_wrapped_vertical_cursor_movement_clamps_to_target_visual_line(self):
        self.assertEqual(_move_wrapped_cursor("ab界cd", 1, 1, 3), 2)
        self.assertEqual(_move_wrapped_cursor("ab界cd", 3, -1, 3), 2)
        self.assertEqual(_move_wrapped_cursor("ab", 1, -1, 3), 1)


if __name__ == "__main__":
    unittest.main()
