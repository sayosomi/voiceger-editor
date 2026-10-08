"""Pure generation Status policy coverage independent of lifecycle state."""

import unittest

from voiceger_editor.tui_operation_status import (
    generation_candidate_status,
    generation_done_status,
    generation_error_status,
)
from voiceger_editor.tui_status import error_status


class TuiOperationStatusTests(unittest.TestCase):
    def test_candidate_status_for_all_generation_modes(self):
        self.assertEqual(generation_candidate_status("initial", 1, 3, 1), "Generating 2/3 · 1 ready")
        self.assertEqual(generation_candidate_status("regenerate_all", 3, 3, 3), "Regenerating 3/3 · 3 ready")
        self.assertEqual(generation_candidate_status("regenerate_one", 1, 1, 7), "Take 7 replacement ready.")

    def test_error_status_keeps_preview_and_caption_identity(self):
        failure = RuntimeError("unavailable")
        self.assertEqual(generation_error_status("preview", None, failure), error_status("Preview failed: unavailable"))
        self.assertEqual(generation_error_status("initial", "Caption 2", failure), error_status("Caption 2 generation failed: unavailable"))
        self.assertEqual(generation_error_status("regenerate_one", None, failure), error_status("Generation failed: unavailable"))

    def final(self, operation, **overrides):
        args = dict(operation=operation, owner=None, batch_owner=None, completed=2,
                    total=3, worker_error=None, cancelled=False, exit_requested=False)
        args.update(overrides)
        return generation_done_status(**args)

    def test_success_status_and_exit_suppression(self):
        self.assertIsNone(self.final("preview"))
        self.assertEqual(self.final("batch_generate"), "Batch generation finished. 2/3 take(s) ready.")
        self.assertEqual(self.final("initial", owner="Caption 3"), "Caption 3 generation finished. 2 take(s) ready.")
        self.assertEqual(self.final("regenerate_one"), "Take regeneration finished.")
        self.assertEqual(self.final("initial", completed=0), "No takes were generated. Select Generate to try again.")
        self.assertIsNone(self.final("initial", completed=0, exit_requested=True))

    def test_cancellation_status_preserves_ownership_and_progress(self):
        self.assertEqual(self.final("batch_generate", cancelled=True, batch_owner="Caption 2"), "Batch generation cancelled at Caption 2. 2/3 take(s) ready.")
        self.assertEqual(self.final("initial", cancelled=True, owner="Caption 3"), "Caption 3 generation cancelled. 2 take(s) ready.")
        self.assertEqual(self.final("regenerate_all", cancelled=True), "Regeneration cancelled after 2 replacement(s).")

    def test_error_status_suppresses_batch_duplicate_and_labels_generation(self):
        failure = ValueError("bad")
        self.assertIsNone(self.final("batch_generate", worker_error=failure))
        self.assertEqual(self.final("initial", worker_error=failure, owner="Caption 5"), error_status("Caption 5 generation failed: bad"))


if __name__ == "__main__":
    unittest.main()
