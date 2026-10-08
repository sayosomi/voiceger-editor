from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from voiceger_editor.tui_operation_acceptance import TuiTakeAcceptanceOwner
from voiceger_editor.tui_operation_conflicts import TuiOperationConflictPolicy
from voiceger_editor.tui_operation_playback import TuiPlaybackOwner
from voiceger_editor.tui_operations import (
    TakeAcceptedEffect,
    TuiOperations,
    UpdateStatusEffect,
)


class TuiOperationOwnerTests(unittest.TestCase):
    def test_playback_owner_holds_playback_state_behind_facade(self):
        operations = TuiOperations(
            platform=lambda: "linux",
            which=lambda _name: "/usr/bin/ffplay",
            popen=Mock(),
        )

        self.assertIsInstance(operations._playback, TuiPlaybackOwner)
        operations.current_take = 3
        self.assertEqual(operations._playback.current_take, 3)
        operations._playback.current_take = 4
        self.assertEqual(operations.current_take, 4)

    def test_playback_owner_executes_take_playback(self):
        process = Mock()
        popen = Mock(return_value=process)
        owner = TuiPlaybackOwner(
            platform=lambda: "linux",
            which=lambda _name: "/usr/bin/ffplay",
            popen=popen,
            update_status=UpdateStatusEffect,
        )
        session = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    number=2,
                    wav_path=Path("/tmp/take-2.wav"),
                )
            ]
        )

        effects = owner.play_take(session, 2)

        self.assertEqual(effects, (UpdateStatusEffect("Playing take 2."),))
        self.assertIs(owner.playback_process, process)
        self.assertEqual(owner.current_take, 2)

    def test_conflict_policy_is_focused_and_stateless(self):
        policy = TuiOperationConflictPolicy()

        conflict = policy.resource_conflict_status(
            "Generate Caption",
            busy=True,
            operation="dictionary",
        )

        self.assertIsNotNone(conflict)
        self.assertIn("Dictionary operation is active", str(conflict))

    def test_acceptance_owner_builds_completion_effects(self):
        owner = TuiTakeAcceptanceOwner(
            update_status=UpdateStatusEffect,
            accepted_effect=TakeAcceptedEffect,
        )
        event = SimpleNamespace(
            error=None,
            item_id="item-1",
            number=2,
            saved=SimpleNamespace(
                wav_path=Path("/tmp/saved.wav"),
                text_path=Path("/tmp/saved.txt"),
            ),
        )

        effects = owner.completion_effects(event)

        self.assertEqual(
            effects,
            (
                TakeAcceptedEffect("item-1", 2),
                UpdateStatusEffect("Saved saved.wav and saved.txt."),
            ),
        )


if __name__ == "__main__":
    unittest.main()
