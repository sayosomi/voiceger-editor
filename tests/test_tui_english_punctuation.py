"""English punctuation rendering, editing, and query authority regressions (#293)."""

import unittest

from voiceger_editor.mixed_language import build_mixed_synthesis_plan
from voiceger_editor.tui_editor_english import is_english_punctuation_group
from voiceger_editor.tui_editors import (
    PreviewIntent,
    QueryApplicationResult,
    ReplaceQueryIntent,
)
from voiceger_editor.tui_rendering_navigation import navigation_document
from voiceger_editor.voicevox_api_models import AudioQuery, VoicegerSegment
from tests.tui_editor_test_support import EditorControllerTestCase, segments
from tests.tui_rendering_test_support import FakeSession, render_state


WAIT = ("W", "EY1", "T")
WHAT = ("W", "AH1", "T")
HELLO = ("HH", "AH0", "L", "OW1")
WORLD = ("W", "ER1", "L", "D")

CASES = {
    "Hello world": (("Hello", HELLO), ("world", WORLD)),
    "Hello world.": (("Hello", HELLO), ("world", WORLD), (".", (".",))),
    "Hello world!": (("Hello", HELLO), ("world", WORLD), ("!", ("!",))),
    "Hello world?": (("Hello", HELLO), ("world", WORLD), ("?", ("?",))),
    "Hello, world!": (
        ("Hello", HELLO), (",", (",",)), ("world", WORLD), ("!", ("!",)),
    ),
    "Wait. What?": (
        ("Wait", WAIT), (".", (".",)), ("What", WHAT), ("?", ("?",)),
    ),
    "Wait, what?": (
        ("Wait", WAIT), (",", (",",)), ("what", WHAT), ("?", ("?",)),
    ),
    "!Hello": (("!", ("!",)), ("Hello", HELLO)),
}


def english_query(source, groups):
    return AudioQuery(
        accent_phrases=[],
        voicegerSegments=[
            VoicegerSegment(
                language="en",
                text=source,
                phonemes=[phone for _word, group in groups for phone in group],
            ),
        ],
    )


class EnglishPunctuationTests(EditorControllerTestCase):
    def setup_case(self, source):
        groups = CASES[source]
        controller, _provider = self.make_controller({source: groups})
        query = english_query(source, groups)
        rows = controller.pronunciation_rows(query, segments(query))
        return controller, query, rows

    def open_punctuation(self, source, index=1):
        controller, query, rows = self.setup_case(source)
        controller.open_pronunciation_item(
            query, rows, index, origin=("pronunciation", index), busy=False
        )
        self.assertEqual(controller.editor.kind, "english_punctuation")
        self.assertEqual(controller.editor.selection, "phonemes")
        self.assertEqual(controller.selection_keys(), [
            "phonemes", "preview", "apply", "edit_text", "reset", "back"
        ])
        return controller, query

    def finish_and_activate(self, controller, query, action):
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption=query.voicegerSegments[0].text
        )
        return controller.handle_key(
            action, settings=self.settings(), query=query,
            current_caption=query.voicegerSegments[0].text,
        )

    def test_supported_punctuation_groups_are_editable_but_words_remain_words(self):
        self.assertTrue(is_english_punctuation_group(".", (".",)))
        self.assertTrue(is_english_punctuation_group(".", (",",)))
        self.assertFalse(is_english_punctuation_group("Wait", WAIT))
        self.assertFalse(is_english_punctuation_group(".", ("HH",)))
        self.assertFalse(is_english_punctuation_group("UNK", ("UNK",)))

    def test_punctuation_rows_are_selectable_in_source_order(self):
        for source, groups in CASES.items():
            with self.subTest(source=source):
                controller, query, rows = self.setup_case(source)
                self.assertIsNone(controller.grouping_error)
                self.assertEqual([row.word for row in rows], [label for label, _ in groups])
                self.assertEqual([row.phonemes for row in rows], [phones for _, phones in groups])
                self.assertTrue(rows[0].first_in_segment)
                self.assertTrue(all(not row.first_in_segment for row in rows[1:]))
                lines = navigation_document(
                    render_state(
                        session=FakeSession(),
                        focus_key=("pronunciation", 0),
                        pronunciation_rows=rows,
                        segments=(("en", source, 0),),
                    ),
                    80,
                )
                actual = [line for line in lines if line.key and line.key[0] == "pronunciation"]
                self.assertEqual(len(actual), len(groups))
                for index, (label, phones) in enumerate(groups):
                    self.assertEqual(actual[index].key, ("pronunciation", index))
                    self.assertIn(label, actual[index].text)
                    if label in {".", ",", "!", "?"}:
                        self.assertTrue(actual[index].text.endswith(label))

    def test_punctuation_only_apply_changes_query_and_synthesis_plan_not_text(self):
        controller, query = self.open_punctuation("Wait. What?")
        original = query.model_dump()
        controller.editor.input_value = ","
        intents = self.finish_and_activate(controller, query, "a")
        replacement = next(item for item in intents if isinstance(item, ReplaceQueryIntent))
        self.assertEqual(replacement.editor_kind, "english_punctuation")
        updated = replacement.query
        self.assertEqual(updated.voicegerSegments[0].text, "Wait. What?")
        self.assertEqual(updated.voicegerSegments[0].phonemes, [
            *WAIT, ",", *WHAT, "?",
        ])
        self.assertEqual(query.model_dump(), original)
        self.assertEqual(
            build_mixed_synthesis_plan(updated).english_overrides,
            (("Wait. What?", [*WAIT, ",", *WHAT, "?"]),),
        )
        self.assertEqual(
            AudioQuery.model_validate(updated.model_dump()).voicegerSegments[0].phonemes,
            updated.voicegerSegments[0].phonemes,
        )
        controller.complete_query_application(replacement, QueryApplicationResult())
        controller.clear_groupings()
        rebuilt = controller.pronunciation_rows(updated, segments(updated))
        self.assertIsNone(controller.grouping_error)
        self.assertEqual([row.word for row in rebuilt], ["Wait", ",", "What", "?"])
        self.assertEqual(rebuilt[1].phonemes, (",",))

    def test_punctuation_preview_is_transient_and_uses_updated_tokens(self):
        controller, query = self.open_punctuation("Wait. What?", index=3)
        old = query.model_dump()
        controller.editor.input_value = "!"
        intents = self.finish_and_activate(controller, query, "p")
        preview = next(item for item in intents if isinstance(item, PreviewIntent)).query
        self.assertEqual(
            preview.voicegerSegments[0].phonemes, [*WAIT, ".", *WHAT, "!"]
        )
        self.assertEqual(preview.voicegerSegments[0].text, "Wait. What?")
        self.assertEqual(query.model_dump(), old)

    def test_unchanged_punctuation_does_not_replace_query(self):
        controller, query = self.open_punctuation("Wait. What?")
        intents = self.finish_and_activate(controller, query, "a")
        self.assertFalse(any(isinstance(item, ReplaceQueryIntent) for item in intents))
        self.assertIsNone(controller.editor)

    def test_non_punctuation_draft_cannot_replace_punctuation_slot(self):
        for invalid in ("HH", ". HH", "UNK", ""):
            with self.subTest(invalid=invalid):
                controller, query = self.open_punctuation("Wait. What?")
                controller.editor.input_value = invalid
                intents = self.finish_and_activate(controller, query, "a")
                self.assertFalse(any(isinstance(item, ReplaceQueryIntent) for item in intents))
                self.assertIn("punctuation", controller.editor.error.lower())

    def test_rebinding_does_not_hide_unrelated_word_changes(self):
        controller, query, _rows = self.setup_case("Wait. What?")
        query.voicegerSegments[0].phonemes[0] = "HH"
        controller.clear_groupings()
        rows = controller.pronunciation_rows(query, segments(query))
        self.assertEqual(rows, ())
        self.assertIn("Cannot align English", controller.grouping_error)


if __name__ == "__main__":
    unittest.main()
