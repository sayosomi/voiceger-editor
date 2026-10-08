from types import SimpleNamespace
import unittest

from voiceger_editor.caption_batch import CaptionBatch
from voiceger_editor.tui_rendering_batch import batch_list_document


class BatchRenderingDocumentTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
