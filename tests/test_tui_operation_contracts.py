"""Operation-contract re-export and immutable progress snapshot coverage."""

import unittest
from dataclasses import FrozenInstanceError

from voiceger_editor.tui_operation_contracts import (
    BackgroundOperationProgress,
    BatchGenerationProgressEvent,
    UpdateStatusEffect,
)
from voiceger_editor.tui_operations import (
    BackgroundOperationProgress as PublicProgress,
    UpdateStatusEffect as PublicStatus,
)
from voiceger_editor.tui_status import info_status


class TuiOperationContractsTests(unittest.TestCase):
    def test_facade_keeps_existing_effect_and_progress_class_identity(self):
        self.assertIs(BackgroundOperationProgress, PublicProgress)
        self.assertIs(UpdateStatusEffect, PublicStatus)
        self.assertEqual(UpdateStatusEffect("Working").status, info_status("Working"))

    def test_progress_snapshot_and_event_are_frozen(self):
        progress = BackgroundOperationProgress(1, "initial", "item-1", 0, 2)
        with self.assertRaises(FrozenInstanceError):
            progress.completed = 1
        event = BatchGenerationProgressEvent("item-1", 1, 1, 1, 2, 0, 2)
        with self.assertRaises(FrozenInstanceError):
            event.overall_completed = 1


if __name__ == "__main__":
    unittest.main()
