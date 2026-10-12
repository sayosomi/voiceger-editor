"""Issue #275: multi-peak Japanese Dictionary TUI controller and editor regressions."""

import curses

from voiceger_editor.pronunciation import PitchEvent, parse_pronunciation
from voiceger_editor.tui_dictionary_pitch import format_dictionary_pitch
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
        self.assertEqual(visible, MULTI)
        self.assertNotIn("/", visible)

    def test_initial_high_and_final_high_render_as_bracketed_spans(self):
        initial_high = parse_pronunciation("[シ]コク[メ]タン").phrases[0]
        last_high = parse_pronunciation("[シ]コク[メタン]").phrases[0]
        self.assertEqual(
            format_dictionary_pitch(
                initial_high.morae, initial_high.accent,
                initial_high.pitch_events or (),
            ),
            "[シ]コク[メ]タン",
        )
        self.assertEqual(
            format_dictionary_pitch(
                last_high.morae, last_high.accent,
                last_high.pitch_events or (),
            ),
            "[シ]コク[メタン]",
        )

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

    def test_multi_peak_detail_text_edit_preview_apply(self):
        entry = self._open_quick()
        entry.selection = "pronunciation"
        self.key("\n")
        detail = self.controller.editor
        self.assertEqual(detail.kind, "dictionary_japanese_pronunciation")
        self.assertEqual(detail.input_value, MULTI)

        changed = "ス[タ]ッ[クチャ]ン"
        detail.input_value = changed
        self.key("\n")  # Finish typing; no change to the parent until Apply.
        detail.selection = "preview"
        (preview,) = self.key("\n")
        self.assertIsInstance(preview, PreviewIntent)
        self.assertEqual(
            [(e.afterMora, e.symbol)
             for e in preview.query.pronunciationPitchEvents[0].events],
            [(1, "["), (2, "]"), (3, "["), (5, "]")],
        )
        detail.selection = "apply"
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_entry")
        self.assertEqual(
            self.controller.editor.payload["pitch_events"],
            parse_pronunciation(changed).phrases[0].pitch_events,
        )
        self.assertEqual(
            self.controller.editor.payload["pronunciation"], "スタックチャン",
        )

    def test_invalid_detail_apply_keeps_draft_and_back_discards(self):
        entry = self._open_quick()
        entry.selection = "pronunciation"
        self.key("\n")
        detail = self.controller.editor
        detail.input_value = "ス[タ]/ック[チャ]ン"
        self.key("\n")
        detail.selection = "apply"
        self.assertEqual(self.key("\n"), ())
        self.assertIs(self.controller.editor, detail)
        self.assertEqual(detail.error.kind, StatusKind.ERROR)
        self.assertEqual(detail.input_value, "ス[タ]/ック[チャ]ン")
        detail.selection = "reset"
        self.key("\n")
        self.assertEqual(detail.input_value, MULTI)
        self.key("\x1b")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_entry")
        self.assertEqual(self.controller.editor.payload["pitch_events"], EVENTS)

    def test_single_accent_uses_legacy_notation_in_detail(self):
        entry = self._open_quick("ズン'ダモン", surface="ずんだもん")
        entry.selection = "pronunciation"
        self.key("\n")
        detail = self.controller.editor
        self.assertEqual(detail.input_value, "ズン'ダモン")
        self.key("\n")
        detail.selection = "apply"
        self.key("\n")
        self.assertEqual(self.controller.editor.payload["accent"], 2)
        self.assertEqual(self.controller.editor.payload["pitch_events"], ())

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

    def test_list_multi_peak_has_no_inline_left_right_editing(self):
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
        self.key(curses.KEY_LEFT)
        self.assertEqual(editor.payload["entries"][0][1].accent_type, 2)
        self.assertEqual(editor.payload["pitch_events"]["first"], EVENTS)
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
