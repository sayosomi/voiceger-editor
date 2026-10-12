"""BATCH ITEM multi-peak row and detailed editor regressions (#276)."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from voiceger_editor.pronunciation import parse_pronunciation
from voiceger_editor.query_editing import japanese_pronunciation
from voiceger_editor.tui_editor_common import (
    PreviewIntent, ReplaceQueryIntent, SaveToDictionaryIntent,
)
from voiceger_editor.tui_rendering_navigation import navigation_document
from voiceger_editor.voicevox_api_models import (
    AudioQuery, JapanesePitchEvent, PronunciationPitchEvents, VoicegerSegment,
)
from tests.tui_editor_test_support import EditorControllerTestCase, _phrase
from tests.tui_rendering_test_support import FakeSession, render_state


def query_for(notation, *, segments=None):
    """Use core parsing as the test oracle, not the TUI's display projection."""
    parsed = parse_pronunciation(notation)
    records = [
        PronunciationPitchEvents(
            accentPhraseIndex=index,
            events=[
                JapanesePitchEvent(afterMora=event.after_mora, symbol=event.symbol)
                for event in phrase.pitch_events
            ],
        )
        for index, phrase in enumerate(parsed.phrases)
        if phrase.pitch_events is not None
    ]
    return AudioQuery(
        accent_phrases=[_phrase(phrase.morae, phrase.accent)
                        for phrase in parsed.phrases],
        pronunciationPitchEvents=records or None,
        voicegerSegments=segments,
    )


class BatchItemMultiPeakTests(EditorControllerTestCase):
    def rendered_rows(self, query, sources, *, width=80):
        controller, _ = self.make_controller(
            {"hello": (("hello", ("HH", "AH1")),)}
        )
        rows = controller.pronunciation_rows(query, sources)
        document = navigation_document(
            render_state(
                session=FakeSession(),
                focus_key=("pronunciation", 0),
                pronunciation_rows=rows,
                segments=sources,
            ), width,
        )
        return controller, rows, document

    def test_approved_mora_spaced_high_spans_and_legacy(self):
        cases = (
            ("[シ]コク[メ]タン", "[シ] コ ク [メ] タ ン"),
            ("[シ]コク[メタン]", "[シ] コ ク [メ タ ン]"),
            ("ス[タ]ック[チャ]ン", "ス [タ] ッ ク [チャ] ン"),
            ("シ'コクメタン", "[シ] コ ク メ タ ン"),
        )
        for notation, expected in cases:
            with self.subTest(notation=notation):
                query = query_for(notation)
                _controller, rows, document = self.rendered_rows(
                    query, (("ja", "四国めたん", None),),
                )
                self.assertEqual(len(rows), 1)
                label = next(
                    line.text for line in document
                    if line.key == ("pronunciation", 0)
                )
                self.assertEqual(label, "▶ JA | " + expected)
                self.assertEqual(
                    rows[0].pitch_events is not None,
                    query.pronunciationPitchEvents is not None,
                )
                self.assertEqual(japanese_pronunciation(query), notation)

    def test_later_phrase_uses_global_index_without_extra_boundaries(self):
        query = query_for("ア'メ/[シ]コク[メタン]")
        self.assertEqual(query.pronunciationPitchEvents[0].accentPhraseIndex, 1)
        _controller, rows, document = self.rendered_rows(
            query, (("ja", "雨と四国めたん", None),),
        )
        self.assertIsNone(rows[0].pitch_events)
        self.assertEqual(rows[1].phrase_index, 1)
        self.assertIsNotNone(rows[1].pitch_events)
        selected = [line.text for line in document
                    if line.key and line.key[0] == "pronunciation"]
        self.assertEqual(selected, [
            "▶ JA | [ア] メ",
            "     | [シ] コ ク [メ タ ン]",
        ])
        self.assertEqual(japanese_pronunciation(query),
                         "ア'メ/[シ]コク[メタン]")

    def test_mixed_japanese_english_rows_use_global_phrase_indices(self):
        segments = [
            VoicegerSegment(language="ja", text="雨",
                            accentPhraseStart=0, accentPhraseCount=1),
            VoicegerSegment(language="en", text="hello",
                            phonemes=["HH", "AH1"]),
            VoicegerSegment(language="ja", text="四国めたん",
                            accentPhraseStart=1, accentPhraseCount=1),
        ]
        query = query_for("ア'メ/[シ]コク[メ]タン", segments=segments)
        source = (
            ("ja", "雨", 0), ("en", "hello", 1), ("ja", "四国めたん", 2),
        )
        controller, rows, document = self.rendered_rows(query, source)
        self.assertEqual([r.language for r in rows], ["ja", "en", "ja"])
        self.assertEqual([r.phrase_index for r in rows], [0, None, 1])
        self.assertIsNotNone(rows[2].pitch_events)
        labels = [line.text for line in document
                  if line.key and line.key[0] == "pronunciation"]
        self.assertEqual(labels[0], "▶ JA | [ア] メ")
        self.assertIn("EN | hello", labels[1])
        self.assertEqual(labels[2], "  JA | [シ] コ ク [メ] タ ン")
        self.assertEqual(japanese_pronunciation(query, segment_index=2),
                         "[シ]コク[メ]タン")
        controller.open_pronunciation_item(
            query, rows, 2, origin=("pronunciation", 2), busy=False,
        )
        self.assertEqual(controller.editor.input_value, "[シ]コク[メ]タン")

    def test_wrapping_keeps_brackets_with_mora_and_single_focus_owner(self):
        query = query_for("[シ]コク[メタン]")
        _, rows, document = self.rendered_rows(
            query, (("ja", "四国めたん", None),), width=16,
        )
        self.assertEqual(len(rows), 1)
        owned = [line for line in document
                 if line.focus_owner == ("pronunciation", 0)]
        self.assertGreater(len(owned), 1)
        self.assertEqual(sum(line.key == ("pronunciation", 0)
                             for line in owned), 1)
        self.assertIn("[シ]", " ".join(line.text for line in owned))
        self.assertIn("[メ", " ".join(line.text for line in owned))
        self.assertIn("ン]", " ".join(line.text for line in owned))
        self.assertTrue(all(line.text.startswith("     | ")
                            for line in owned[1:]))

    def test_direct_editor_preview_apply_and_quick_save_keep_events(self):
        query = query_for("[シ]コク[メ]タン")
        controller, rows, _ = self.rendered_rows(
            query, (("ja", "四国めたん", None),),
        )
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False,
        )
        self.assertEqual(controller.editor.input_value, "[シ]コク[メ]タン")
        changed = "[シ]コク[メタン]"
        controller.editor.input_value = changed
        controller.editor.active_field = None
        controller.editor.selection = "save_dictionary"
        saved = controller.activate_selection(query)
        self.assertEqual(len(saved), 1)
        self.assertIsInstance(saved[0], SaveToDictionaryIntent)
        self.assertEqual(saved[0].pronunciation, changed)

        sounds = {
            "シ": ["sh", "i"], "コ": ["k", "o"], "ク": ["k", "u"],
            "メ": ["m", "e"], "タ": ["t", "a"], "ン": ["N"],
        }
        def g2p(mora, *, kana, join):
            return sounds[mora]
        with patch.dict(sys.modules, {"pyopenjtalk": SimpleNamespace(g2p=g2p)}):
            preview = controller.preview(query)
            self.assertEqual(len(preview), 1)
            self.assertIsInstance(preview[0], PreviewIntent)
            self.assertEqual(japanese_pronunciation(preview[0].query), changed)
            self.assertEqual(japanese_pronunciation(query), "[シ]コク[メ]タン")
            applied = controller.apply_pronunciation(query)
        replacement = next(item for item in applied
                           if isinstance(item, ReplaceQueryIntent))
        self.assertEqual(japanese_pronunciation(replacement.query), changed)
        self.assertEqual(
            [(e.afterMora, e.symbol)
             for e in replacement.query.pronunciationPitchEvents[0].events],
            [(1, "]"), (3, "[")],
        )
        self.assertIn("old takes cleared", replacement.success_status)

    def test_inline_single_accent_movement_cannot_discard_multi_peaks(self):
        query = query_for("[シ]コク[メ]タン")
        controller, rows, _ = self.rendered_rows(
            query, (("ja", "四国めたん", None),),
        )
        for direction in (-1, 1):
            with self.subTest(direction=direction):
                result = controller.adjust_pronunciation(query, rows[0], direction)
                self.assertFalse(any(isinstance(item, ReplaceQueryIntent)
                                     for item in result))
                self.assertEqual(japanese_pronunciation(query),
                                 "[シ]コク[メ]タン")


if __name__ == "__main__":
    unittest.main()
