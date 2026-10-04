import curses
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from voiceger_editor.settings import Settings
from voiceger_editor.tui_batch import BatchActionBindings, TuiBatchController
from voiceger_editor.tui_batch_item import (
    BatchItemBindings,
    TuiBatchItemController,
)
from voiceger_editor.tui_navigation import AcceptCandidate, TuiNavigation
from voiceger_editor.tui_operations import UpdateStatusEffect


class FakeSession:
    def __init__(self, caption, *, candidates=(), active=True):
        self.caption = caption
        self.candidates = list(candidates)
        self.has_active_batch = active
        self.query = SimpleNamespace(voicegerSegments=None)
        self.pure_japanese_utterance_text = caption
        self.utterance_manually_edited = False


class TuiBatchItemControllerTests(unittest.TestCase):
    def make_subject(self):
        batch = TuiBatchController(default_take_count=4)
        batch.add_captions(
            "first\nsecond",
            session_factory=lambda caption: FakeSession(caption),
        )
        navigation = TuiNavigation()
        operations = Mock()
        operations.busy = False
        operations.worker_operation = None
        operations.current_take = None
        editor = SimpleNamespace(
            clear_groupings=Mock(),
            grouping_error="",
            pronunciation_rows=Mock(return_value=()),
            adjust_pronunciation=Mock(return_value=()),
            open_clear_candidates_confirmation=Mock(return_value=()),
            open_add_section=Mock(return_value=()),
            open_build_confirmation=Mock(return_value=()),
            open_pronunciation_item=Mock(return_value=()),
        )
        dictionary = SimpleNamespace(open_menu=Mock(return_value=()))
        state = {
            "session": batch.open_item(0),
            "status": "",
            "settings": Settings(take_count=4),
        }
        set_session = Mock(
            side_effect=lambda session: state.__setitem__("session", session)
        )
        set_status = Mock(
            side_effect=lambda status: state.__setitem__("status", status)
        )
        actions = BatchActionBindings(
            operations=operations,
            navigation=navigation,
            editor_controller=editor,
            dictionary_controller=dictionary,
            set_session=set_session,
            set_status=set_status,
            open_caption_editor=Mock(),
            change_settings=Mock(),
            open_settings_editor=Mock(),
            dispatch_editor_intents=Mock(),
            dispatch_operation_effects=Mock(),
            open_help=Mock(),
            activate_quit=Mock(),
        )
        bindings = BatchItemBindings(
            actions=actions,
            get_session=lambda: state["session"],
            get_settings=lambda: state["settings"],
            get_status=lambda: state["status"],
            clear_adjustment_feedback=Mock(),
            mark_adjustment_pressed=Mock(),
        )
        return (
            TuiBatchItemController(batch),
            batch,
            bindings,
            state,
        )

    def test_escape_closes_item_and_cleans_transient_state(self):
        subject, batch, bindings, state = self.make_subject()

        subject.handle_key("\x1b", bindings)

        self.assertFalse(batch.in_item)
        self.assertIsNone(state["session"])
        bindings.actions.operations.stop_playback.assert_called_once_with()
        bindings.actions.operations.clear_current_take.assert_called_once_with()
        bindings.actions.editor_controller.clear_groupings.assert_called_once_with()
        self.assertEqual(state["status"], "")

    def test_title_navigation_and_shortcuts_move_without_wrapping(self):
        subject, batch, bindings, state = self.make_subject()
        bindings.actions.navigation.focus_key = ("batch_item", None)

        subject.handle_key(curses.KEY_RIGHT, bindings)

        self.assertEqual(batch.item_position, (2, 2))
        self.assertIs(state["session"], batch.batch.items[1].session)
        self.assertEqual(
            bindings.actions.navigation.focus_key,
            ("batch_item", None),
        )

        bindings.actions.set_status.reset_mock()
        subject.handle_key("]", bindings)
        self.assertEqual(batch.item_position, (2, 2))
        bindings.actions.set_status.assert_called_once_with("Last Caption.")

        subject.handle_key("[", bindings)
        self.assertEqual(batch.item_position, (1, 2))

    def test_caption_movement_is_blocked_while_synthesis_is_busy(self):
        subject, batch, bindings, state = self.make_subject()
        bindings.actions.operations.busy = True

        subject.move_open_item(1, bindings)

        self.assertEqual(batch.item_position, (1, 2))
        self.assertIs(state["session"], batch.batch.items[0].session)
        bindings.actions.set_status.assert_called_once_with(
            "Wait for the current synthesis operation to finish."
        )

    def test_acceptance_starts_operation_for_stable_item_without_marking_early(self):
        subject, batch, bindings, _state = self.make_subject()
        target = batch.batch.items[0]
        effects = (UpdateStatusEffect("Saving Take 2…"),)
        bindings.actions.operations.accept_take.return_value = effects

        subject.dispatch_navigation_actions(
            (AcceptCandidate(2),),
            bindings,
        )

        bindings.actions.operations.accept_take.assert_called_once_with(
            target.session,
            2,
            item_id=target.item_id,
            busy=False,
            pronunciation_index=0,
        )
        bindings.actions.dispatch_operation_effects.assert_called_once_with(effects)
        self.assertFalse(target.is_accepted)
        self.assertIsNone(target.accepted_take_number)

    def test_generate_take_count_adjustment_uses_existing_settings_owner(self):
        subject, _batch, bindings, _state = self.make_subject()
        bindings.actions.navigation.focus_key = ("generate", None)

        subject.handle_key(curses.KEY_RIGHT, bindings)

        bindings.mark_adjustment_pressed.assert_called_once_with(
            "navigation",
            "generate",
            1,
        )
        bindings.actions.change_settings.assert_called_once_with(
            take_count=5,
            report_success=False,
        )
        self.assertEqual(
            bindings.actions.navigation.focus_key,
            ("generate", None),
        )

    def test_navigation_context_uses_pronunciation_rows_from_editor_owner(self):
        subject, _batch, bindings, _state = self.make_subject()
        row = SimpleNamespace(language="ja")
        bindings.actions.editor_controller.pronunciation_rows.return_value = (row,)

        context = subject.navigation_context(bindings)

        self.assertTrue(context.has_session)
        self.assertEqual(context.pronunciation_count, 1)
        self.assertTrue(context.has_item_navigator)
        bindings.actions.editor_controller.pronunciation_rows.assert_called_once()


if __name__ == "__main__":
    unittest.main()
