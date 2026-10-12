"""Issue #275: multi-peak Japanese Dictionary TUI controller and editor regressions."""

import curses

from voiceger_editor.pronunciation import PitchEvent, parse_pronunciation
from voiceger_editor.tui_dictionary_pitch import (
    append_pitch_peak, format_dictionary_pitch, move_pitch_marker, remove_pitch_peak,
)
from voiceger_editor.tui_editors import PreviewIntent
from voiceger_editor.tui_status import StatusKind
from tests.tui_dictionary_test_support import DictionaryControllerTestCase, ja_word


MULTI = "ス[タ]ック[チャ]ン"
EVENTS = parse_pronunciation(MULTI).phrases[0].pitch_events


class JapaneseDictionaryMultiPeakTests(DictionaryControllerTestCase):
    def _open_quick(self, text=MULTI, surface="スタックチャン"):
        self.controller.open_quick_save_japanese(
            surface=surface, pronunciation=text
        )
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_entry")
        return self.controller.editor

    def test_format_has_two_peaks_without_phrase_boundary(self):
        phrase = parse_pronunciation(MULTI).phrases[0]
        visible = format_dictionary_pitch(phrase.morae, phrase.accent, EVENTS)
        self.assertEqual(visible.count("["), 2)
        self.assertEqual(visible.count("]"), 2)
        self.assertIn("(2 peaks, one phrase)", visible)
        self.assertNotIn("/", visible)

    def test_quick_save_roundtrip_preserves_extra_events_and_default_priority(self):
        editor = self._open_quick()
        self.assertEqual(editor.payload["pitch_events"], EVENTS)
        self.assertEqual(editor.payload["priority"], 5)
        self.assertEqual(editor.payload["accent"], 2)
        editor.selection = "preview"
        (preview,) = self.key("\n")
        self.assertIsInstance(preview, PreviewIntent)
        self.assertEqual(
            [(event.afterMora, event.symbol)
             for event in preview.query.pronunciationPitchEvents[0].events],
            [(event.after_mora, event.symbol) for event in EVENTS],
        )
        self.finish_operation(self.key("s"))
        identity, word = next(iter(self.core.japanese.items()))
        self.assertEqual(word.priority, 5)
        self.assertEqual(word.accent_type, 2)
        self.assertEqual(self.core.get_japanese_pitch_events(identity), EVENTS)

        self.controller.open_menu()
        self.key("j")
        self.key("\n")
        self.assertEqual(self.controller.editor.payload["word_uuid"], identity)
        self.assertEqual(self.controller.editor.payload["pitch_events"], EVENTS)
        self.assertFalse(self.controller._entry_owner._is_dirty(self.controller.editor))

    def test_move_add_remove_marker_and_preserve_navigation_shortcuts(self):
        editor = self._open_quick()
        editor.selection = "pronunciation"
        self.assertEqual(editor.payload["pitch_cursor"], 1)
        self.key("m")
        self.assertEqual(editor.payload["pitch_cursor"], 2)
        self.key(curses.KEY_LEFT)
        # This rise cannot collide with the existing fall.
        self.assertEqual(editor.payload["pitch_events"], EVENTS)
        self.key(curses.KEY_RIGHT)
        self.assertEqual(editor.payload["pitch_events"][2], PitchEvent(5, "["))
        self.key(curses.KEY_LEFT)
        self.assertEqual(editor.payload["pitch_events"], EVENTS)
        self.assertEqual(self.key("["), ())  # Existing word navigator is not a peak key.
        self.assertEqual(editor.payload["pitch_events"], EVENTS)
        self.key("-")
        self.assertEqual(editor.payload["pitch_events"], ())
        self.assertEqual(editor.payload["accent"], 2)
        self.key("+")
        self.assertEqual(len(editor.payload["pitch_events"]), 4)
        self.assertEqual(editor.payload["pitch_events"][0], PitchEvent(1, "["))
        self.assertEqual(editor.payload["pitch_events"][1], PitchEvent(2, "]"))
        self.key(curses.KEY_LEFT)
        self.assertEqual(editor.payload["accent"], 2)

    def test_edit_field_shows_all_peaks_and_failed_validation_retains_draft(self):
        editor = self._open_quick()
        editor.selection = "pronunciation"
        self.key("\n")
        self.assertEqual(editor.input_value, MULTI)
        editor.input_value = "ス[タ]/ック[チャ]ン"
        self.key("\n")
        self.assertIsNotNone(editor.active_field)
        self.assertEqual(editor.payload["pitch_events"], EVENTS)
        self.assertEqual(editor.error.kind, StatusKind.ERROR)
        editor.input_value = MULTI
        self.key("\n")
        self.assertIsNone(editor.active_field)
        self.assertEqual(editor.payload["pitch_events"], EVENTS)

    def test_existing_multi_peak_is_not_lost_on_plain_open_save_or_failed_save(self):
        self.core.japanese["existing"] = ja_word("スタックチャン", "スタックチャン", 2)
        self.core.pitch_events["existing"] = EVENTS
        self.controller.open_menu()
        self.key("j")
        self.key("\n")
        editor = self.controller.editor
        self.assertEqual(editor.payload["pitch_events"], EVENTS)
        self.assertFalse(self.controller._entry_owner._is_dirty(editor))
        self.assertEqual(self.key("m"), ())
        self.assertFalse(self.controller._entry_owner._is_dirty(editor))
        intents = self.key("s")
        op = self.operation(intents)
        self.controller.complete_operation(op.request, error=RuntimeError("disk error"))
        self.assertIs(self.controller.editor, editor)
        self.assertEqual(editor.payload["pitch_events"], EVENTS)
        self.assertEqual(self.core.pitch_events["existing"], EVENTS)
        self.finish_operation(self.key("s"))
        self.assertEqual(self.core.pitch_events["existing"], EVENTS)

    def test_duplicate_surface_picker_keeps_specific_uuid_and_all_events(self):
        self.core.japanese["first"] = ja_word("ABC", "エービーシー", 2)
        self.core.japanese["second"] = ja_word("ＡＢＣ", "スタックチャン", 2)
        self.core.pitch_events["second"] = EVENTS
        self.controller.open_quick_save_japanese(
            surface="ABC", pronunciation=MULTI,
        )
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_duplicates")
        self.key(curses.KEY_DOWN)
        self.key("\n")
        editor = self.controller.editor
        self.assertEqual(editor.payload["word_uuid"], "second")
        self.assertEqual(editor.payload["pitch_events"], EVENTS)
        self.finish_operation(self.key("s"))
        self.assertEqual(self.core.get_japanese_pitch_events("second"), EVENTS)
        self.assertNotIn("first", self.core.pitch_events)

    def test_list_preview_uses_events_and_pending_first_fall(self):
        self.core.japanese["first"] = ja_word("スタックチャン", "スタックチャン", 2)
        self.core.pitch_events["first"] = EVENTS
        self.controller.open_menu()
        self.key("j")
        editor = self.controller.editor
        self.assertEqual(editor.payload["pitch_events"]["first"], EVENTS)
        (preview,) = self.key("p")
        self.assertIsInstance(preview, PreviewIntent)
        self.assertEqual(len(preview.query.pronunciationPitchEvents[0].events), 4)
        self.key(curses.KEY_RIGHT)
        # Moving first fall to a collision is not allowed.
        self.assertEqual(editor.payload["entries"][0][1].accent_type, 2)
        self.assertFalse(self.controller.has_unsaved_list_accents)

    def test_legacy_single_accent_has_no_extra_events(self):
        editor = self._open_quick("ズン'ダモン", surface="ずんだもん")
        editor.selection = "pronunciation"
        self.key(curses.KEY_RIGHT)
        self.assertEqual(editor.payload["accent"], 3)
        self.assertEqual(editor.payload["pitch_events"], ())
        editor.selection = "preview"
        (preview,) = self.key("\n")
        self.assertIsNone(preview.query.pronunciationPitchEvents)
        self.finish_operation(self.key("s"))
        self.assertEqual(next(iter(self.core.japanese.values())).accent_type, 3)


if __name__ == "__main__":
    import unittest
    unittest.main()
