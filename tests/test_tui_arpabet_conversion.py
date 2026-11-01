"""TUI Issue #322 direct JA→EN editor conversion and Take guard regression."""

import unittest

from tests.tui_editor_test_support import (
    EditorControllerTestCase, direct_japanese_query, segments,
)
from voiceger_editor.tui_editor_common import (
    QueryApplicationResult, ReplaceQueryIntent,
)


class JapaneseArpabetTuiTests(EditorControllerTestCase):
    def _open(self, *, has_takes=False):
        query = direct_japanese_query()
        controller, provider = self.make_controller()
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False,
            has_takes=has_takes,
        )
        self.assertEqual(controller.editor.kind, "japanese")
        return controller, query, provider

    def _convert(self, controller, query):
        return controller.handle_key(
            "v", settings=self.settings(), query=query,
            current_caption="なのだ。",
        )

    def test_shortcut_is_plain_text_while_field_is_editing(self):
        controller, query, provider = self._open()
        original = controller.editor.input_value
        self.assertIsNotNone(controller.editor.active_field)
        self.assertEqual(self._convert(controller, query), ())
        self.assertEqual(controller.editor.input_value, original + "v")
        self.assertEqual(provider.calls, [])

    def test_direct_conversion_opens_existing_english_editor(self):
        controller, query, provider = self._open()
        controller.editor.input_value = "ズ'ンダモンハ カシコ'イ ノダ'！"
        controller.handle_key(
            "\n", settings=self.settings(), query=query,
            current_caption="なのだ。",
        )
        intents = self._convert(controller, query)
        replacement = next(x for x in intents if isinstance(x, ReplaceQueryIntent))
        self.assertEqual(replacement.converted_english_index, 0)
        self.assertEqual(replacement.query.voicegerSegments[0].language, "en")
        controller.complete_query_application(replacement, QueryApplicationResult())
        self.assertEqual(controller.editor.kind, "english_word")
        self.assertEqual(controller.editor.payload["label"], "ズンダモンハ")
        self.assertEqual(provider.calls, [])  # No English tokenizer on JA source.

    def test_candidate_confirmation_cancel_preserves_draft(self):
        controller, query, _provider = self._open(has_takes=True)
        controller.editor.input_value = "ズ'ンダモンハ"
        controller.handle_key(
            "\n", settings=self.settings(), query=query,
            current_caption="なのだ。",
        )
        self.assertEqual(self._convert(controller, query), ())
        self.assertEqual(controller.editor.kind, "convert_confirmation")
        self.assertEqual(controller.editor.selection, "cancel")
        result = controller.handle_key(
            "\x1b", settings=self.settings(), query=query,
            current_caption="なのだ。",
        )
        self.assertFalse(any(isinstance(x, ReplaceQueryIntent) for x in result))
        self.assertEqual(controller.editor.kind, "japanese")
        self.assertEqual(controller.editor.input_value, "ズ'ンダモンハ")
        self.assertEqual(self._convert(controller, query), ())
        confirmed = self._convert(controller, query)
        replacement = next(x for x in confirmed if isinstance(x, ReplaceQueryIntent))
        self.assertEqual(replacement.query.voicegerSegments[0].language, "en")


if __name__ == "__main__":
    unittest.main()
