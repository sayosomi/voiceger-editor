import curses
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from voiceger_editor.caption_batch import CaptionBatch
from voiceger_editor.tui_editors import (
    AdjustmentPressedIntent,
    ClearAdjustmentFeedbackIntent,
)
from voiceger_editor.tui_batch import (
    AddCaptions,
    AdjustBatchTakeCount,
    BatchActionBindings,
    GenerateSelected,
    OpenBatchDictionary,
    OpenBatchHelp,
    OpenBatchItem,
    OpenBatchRead,
    OpenBatchSettings,
    OpenBatchWrite,
    QuitBatch,
    ReportBatchStatus,
    TuiBatchController,
)


class FakeSession:
    def __init__(self, caption, *, prepared=True):
        self.caption = caption
        self.is_prepared = prepared
        self.candidates = []
        self.closed = False
        self.close_calls = 0

    def close(self):
        self.closed = True
        self.close_calls += 1


class TuiBatchControllerTests(unittest.TestCase):
    def make_controller(self, text=""):
        controller = TuiBatchController(default_take_count=4)
        if text:
            controller.add_captions(text, session_factory=FakeSession)
        return controller

    def make_bindings(self):
        operations = Mock()
        operations.busy = False
        operations.operation_resource_busy = False
        operations.worker_operation = None
        operations.item_mutation_conflict_status.return_value = None
        operations.start_batch_generation.return_value = ()
        operations.start_session_preparation.return_value = ()
        operations.generation_conflict_status.return_value = None
        navigation = SimpleNamespace(
            focus_key=("takes", None),
            revision=7,
            mark_context_change=Mock(),
            reset_pronunciation_index=Mock(),
        )
        return BatchActionBindings(
            operations=operations,
            navigation=navigation,
            editor_controller=SimpleNamespace(clear_groupings=Mock()),
            dictionary_controller=SimpleNamespace(open_menu=Mock(return_value=())),
            set_session=Mock(),
            set_status=Mock(),
            open_caption_editor=Mock(),
            change_settings=Mock(),
            open_settings_editor=Mock(),
            open_batch_read=Mock(),
            open_batch_write=Mock(),
            dispatch_editor_intents=Mock(),
            dispatch_operation_effects=Mock(),
            open_help=Mock(),
            activate_quit=Mock(),
            initialize_open_item=Mock(),
        )

    def test_batch_list_initial_focus_matches_available_primary_work(self):
        empty = self.make_controller()
        self.assertEqual(empty.focus_key, ("add_captions", None))

        populated = self.make_controller("first\nsecond")
        self.assertEqual(populated.focus_key, ("caption", 0))

    def test_batch_list_items_keep_takes_captions_and_actions_in_vertical_order(self):
        controller = self.make_controller("first\nsecond")
        self.assertEqual(
            controller.navigation_items(),
            (
                ("takes", None),
                ("caption", 0),
                ("caption", 1),
                ("add_captions", None),
                ("generate_selected", None),
                ("read_batch", None),
                ("write_batch", None),
                ("settings", None),
                ("dictionary", None),
                ("help", None),
                ("quit", None),
            ),
        )

    def test_space_toggles_focused_caption_without_changing_focus(self):
        controller = self.make_controller("first\nsecond")
        controller.focus_key = ("caption", 1)

        self.assertTrue(controller.batch.items[1].included_for_generation)
        self.assertEqual(controller.handle_key(" "), ())
        self.assertFalse(controller.batch.items[1].included_for_generation)
        self.assertEqual(controller.focus_key, ("caption", 1))

        controller.handle_key(" ")
        self.assertTrue(controller.batch.items[1].included_for_generation)

    def test_x_requests_delete_only_for_focused_caption_and_escape_cancels(self):
        controller = self.make_controller("first\nsecond")
        target = controller.batch.items[1]
        controller.focus_key = ("takes", None)

        self.assertEqual(controller.handle_key("x"), ())
        self.assertFalse(controller.delete_confirmation_active)

        controller.focus_key = ("caption", 1)
        self.assertEqual(controller.handle_key("x"), ())
        self.assertTrue(controller.delete_confirmation_active)
        self.assertEqual(controller.delete_confirmation_caption, "second")
        self.assertTrue(target.included_for_generation)

        self.assertEqual(controller.handle_key(" "), ())
        self.assertTrue(target.included_for_generation)
        self.assertEqual(controller.handle_key("\x1b"), ())
        self.assertFalse(controller.delete_confirmation_active)
        self.assertEqual(controller.focus_key, ("caption", 1))
        self.assertEqual(
            [item.caption for item in controller.batch.items],
            ["first", "second"],
        )
        self.assertEqual(target.session.close_calls, 0)

    def test_operation_owned_caption_cannot_open_or_confirm_delete(self):
        controller = self.make_controller("first\nsecond")
        target = controller.batch.items[1]
        controller.focus_key = ("caption", 1)
        operations = Mock()
        conflict = SimpleNamespace(message="Caption 2 is currently generating")
        operations.item_mutation_conflict_status.return_value = conflict

        actions = controller.handle_key("x", operations=operations)

        self.assertFalse(controller.delete_confirmation_active)
        self.assertEqual(len(actions), 1)
        self.assertIs(actions[0].status, conflict)
        operations.item_mutation_conflict_status.assert_called_once_with(
            controller.batch,
            target.item_id,
            action="deleting Caption",
        )

        operations.item_mutation_conflict_status.return_value = None
        controller.handle_key("x", operations=operations)
        self.assertTrue(controller.delete_confirmation_active)
        operations.item_mutation_conflict_status.return_value = conflict

        actions = controller.handle_key("d", operations=operations)

        self.assertTrue(controller.delete_confirmation_active)
        self.assertEqual([item.caption for item in controller.batch.items], ["first", "second"])
        self.assertIs(actions[0].status, conflict)

    def test_open_item_delete_cancel_keeps_item_and_confirm_returns_to_list(self):
        controller = self.make_controller("first\nsecond")
        target = controller.batch.items[1]
        controller.focus_key = ("caption", 1)
        controller.open_item(1)

        controller.request_delete_open_item()
        self.assertTrue(controller.delete_confirmation_active)
        self.assertEqual(controller.delete_confirmation_caption, "second")
        controller.handle_key("\x1b")

        self.assertTrue(controller.in_item)
        self.assertEqual(controller.item_title, "BATCH ITEM")
        self.assertEqual(controller.item_position, (2, 2))
        self.assertEqual(target.session.close_calls, 0)

        controller.request_delete_open_item()
        controller.handle_key("d")

        self.assertFalse(controller.in_item)
        self.assertEqual(
            [item.caption for item in controller.batch.items],
            ["first"],
        )
        self.assertEqual(controller.focus_key, ("caption", 0))
        self.assertEqual(target.session.close_calls, 1)

    def test_delete_confirmation_uses_modal_arrow_and_enter_semantics(self):
        controller = self.make_controller("first\nsecond")
        controller.focus_key = ("caption", 1)
        controller.handle_key("x")

        self.assertEqual(controller.delete_confirmation_selection, "cancel")
        controller.handle_key(curses.KEY_DOWN)
        self.assertEqual(controller.delete_confirmation_selection, "cancel")
        controller.handle_key("\n")

        self.assertFalse(controller.delete_confirmation_active)
        self.assertEqual(
            [item.caption for item in controller.batch.items],
            ["first", "second"],
        )

        controller.handle_key("x")
        controller.handle_key(curses.KEY_UP)
        self.assertEqual(controller.delete_confirmation_selection, "delete")
        controller.handle_key("\n")

        self.assertEqual(
            [item.caption for item in controller.batch.items],
            ["first"],
        )

    def test_confirmed_delete_targets_pending_stable_id_and_closes_only_removed_session(self):
        controller = self.make_controller("first\nsecond\nthird")
        target = controller.batch.items[1]
        survivors = (controller.batch.items[0], controller.batch.items[2])
        controller.focus_key = ("caption", 1)
        controller.handle_key("x")

        controller.batch.move_item(target.item_id, 0)
        controller.handle_key("d")

        self.assertFalse(controller.delete_confirmation_active)
        self.assertEqual(
            [item.caption for item in controller.batch.items],
            ["first", "third"],
        )
        self.assertEqual(target.session.close_calls, 1)
        self.assertEqual([item.session.close_calls for item in survivors], [0, 0])
        self.assertEqual(controller.focus_key, ("caption", 0))

        controller.close_sessions()
        self.assertEqual(target.session.close_calls, 1)
        self.assertEqual([item.session.close_calls for item in survivors], [1, 1])

    def test_delete_repairs_focus_for_first_middle_last_and_final_caption(self):
        cases = (
            (0, ["second", "third"], ("caption", 0)),
            (1, ["first", "third"], ("caption", 1)),
            (2, ["first", "second"], ("caption", 1)),
        )
        for index, expected_captions, expected_focus in cases:
            with self.subTest(index=index):
                controller = self.make_controller("first\nsecond\nthird")
                controller.focus_key = ("caption", index)
                controller.handle_key("x")
                controller.handle_key("d")
                self.assertEqual(
                    [item.caption for item in controller.batch.items],
                    expected_captions,
                )
                self.assertEqual(controller.focus_key, expected_focus)

        final = self.make_controller("only")
        only_session = final.batch.items[0].session
        final.focus_key = ("caption", 0)
        final.handle_key("x")
        final.handle_key("d")
        self.assertEqual(final.batch.items, ())
        self.assertEqual(final.focus_key, ("add_captions", None))
        self.assertEqual(only_session.close_calls, 1)

    def test_open_item_identity_survives_reordering(self):
        controller = self.make_controller("first\nsecond")
        target = controller.batch.items[1]
        controller.open_item(1)

        controller.batch.move_item(target.item_id, 0)

        self.assertEqual(controller.open_item_id, target.item_id)
        self.assertEqual(controller.item_index, 0)
        self.assertEqual(controller.item_title, "BATCH ITEM")
        self.assertEqual(controller.item_position, (1, 2))

    def test_complete_acceptance_marks_stable_item_and_stays_open(self):
        controller = self.make_controller("first\nsecond\nthird")
        target = controller.batch.items[1]
        controller.open_item(1)

        controller.batch.move_item(target.item_id, 0)
        controller.complete_acceptance(target.item_id, 2)

        self.assertTrue(target.is_accepted)
        self.assertEqual(target.accepted_take_number, 2)
        self.assertTrue(controller.in_item)
        self.assertEqual(controller.open_item_id, target.item_id)
        self.assertEqual(controller.item_position, (1, 3))

    def test_enter_opens_focused_caption_by_list_position(self):
        controller = self.make_controller("first\nsecond")
        controller.focus_key = ("caption", 1)

        self.assertEqual(controller.handle_key("\n"), (OpenBatchItem(1),))
        session = controller.open_item(1)
        self.assertIs(session, controller.batch.items[1].session)
        self.assertTrue(controller.in_item)
        self.assertEqual(controller.item_title, "BATCH ITEM")
        self.assertEqual(controller.item_position, (2, 2))

        controller.close_item()
        self.assertFalse(controller.in_item)
        self.assertEqual(controller.focus_key, ("caption", 1))

    def test_left_right_adjust_only_the_focused_batch_take_count(self):
        controller = self.make_controller("first")
        controller.focus_key = ("takes", None)

        self.assertEqual(
            controller.handle_key(curses.KEY_RIGHT),
            (AdjustBatchTakeCount(1),),
        )
        controller.focus_key = ("caption", 0)
        self.assertEqual(controller.handle_key(curses.KEY_LEFT), ())

    def test_batch_list_shortcuts_emit_settled_actions(self):
        controller = self.make_controller("first")
        expected = {
            "a": AddCaptions(),
            "g": GenerateSelected(),
            "r": OpenBatchRead(),
            "w": OpenBatchWrite(),
            "s": OpenBatchSettings(),
            "d": OpenBatchDictionary(),
            "?": OpenBatchHelp(),
            "q": QuitBatch(),
            "Q": QuitBatch(),
        }
        for key, action in expected.items():
            with self.subTest(key=key):
                self.assertEqual(controller.handle_key(key), (action,))

    def test_dispatch_open_item_owns_batch_item_transition_policy(self):
        controller = self.make_controller("first\nsecond")
        bindings = self.make_bindings()

        controller.dispatch_actions((OpenBatchItem(1),), bindings)

        bindings.operations.stop_playback.assert_called_once_with()
        bindings.operations.clear_current_take.assert_called_once_with()
        bindings.navigation.mark_context_change.assert_called_once_with()
        bindings.editor_controller.clear_groupings.assert_called_once_with()
        bindings.set_session.assert_called_once_with(
            controller.batch.items[1].session
        )
        self.assertEqual(bindings.navigation.focus_key, ("caption", None))
        bindings.navigation.reset_pronunciation_index.assert_called_once_with()
        bindings.initialize_open_item.assert_called_once_with()
        bindings.set_status.assert_called_once_with("")
        self.assertEqual(controller.item_title, "BATCH ITEM")
        self.assertEqual(controller.item_position, (2, 2))

        bindings.operations.start_session_preparation.assert_not_called()

    def test_dispatch_open_unprepared_item_defers_pronunciation_preparation(self):
        controller = TuiBatchController(default_take_count=4)
        controller.add_caption(
            "slow caption",
            session_factory=lambda caption: FakeSession(
                caption,
                prepared=False,
            ),
        )
        bindings = self.make_bindings()
        effects = (SimpleNamespace(kind="prepare"),)
        bindings.operations.start_session_preparation.return_value = effects
        session = controller.batch.items[0].session

        controller.dispatch_actions((OpenBatchItem(0),), bindings)

        bindings.set_session.assert_called_once_with(session)
        bindings.set_status.assert_called_once_with("")
        bindings.operations.start_session_preparation.assert_called_once_with(
            session,
            rebuild=False,
            item_id=controller.batch.items[0].item_id,
        )
        bindings.dispatch_operation_effects.assert_called_once_with(effects)

    def test_dispatch_read_write_open_recipe_flow_only_when_idle(self):
        controller = self.make_controller("first")
        bindings = self.make_bindings()

        controller.dispatch_actions((OpenBatchRead(), OpenBatchWrite()), bindings)

        bindings.open_batch_read.assert_called_once_with()
        bindings.open_batch_write.assert_called_once_with()

        bindings.open_batch_read.reset_mock()
        bindings.open_batch_write.reset_mock()
        bindings.operations.operation_resource_busy = True

        controller.dispatch_actions((OpenBatchRead(),), bindings)
        self.assertIn("before reading a batch", str(bindings.set_status.call_args.args[0]))
        bindings.open_batch_read.assert_not_called()

        controller.dispatch_actions((OpenBatchWrite(),), bindings)
        self.assertIn("before writing a batch", str(bindings.set_status.call_args.args[0]))
        bindings.open_batch_write.assert_not_called()

    def test_replace_batch_closes_old_sessions_and_resets_list_focus(self):
        controller = self.make_controller("old first\nold second")
        previous_sessions = controller.sessions
        controller.open_item(1)
        controller.request_delete_open_item()

        replacement = CaptionBatch(default_take_count=7)
        replacement.add_captions_from_text(
            "new first\nnew second",
            session_factory=FakeSession,
        )

        controller.replace_batch(replacement)

        self.assertIs(controller.batch, replacement)
        self.assertFalse(controller.in_item)
        self.assertFalse(controller.delete_confirmation_active)
        self.assertEqual(controller.focus_key, ("caption", 0))
        self.assertTrue(all(session.closed for session in previous_sessions))
        self.assertTrue(
            all(not item.session.closed for item in replacement.items)
        )

        empty = CaptionBatch(default_take_count=3)
        replacement_sessions = tuple(item.session for item in replacement.items)
        controller.replace_batch(empty)
        self.assertEqual(controller.focus_key, ("add_captions", None))
        self.assertTrue(all(session.closed for session in replacement_sessions))

    def test_dispatch_generate_selected_uses_owned_batch_and_navigation_revision(self):
        controller = self.make_controller("first\nsecond")
        bindings = self.make_bindings()
        effects = (SimpleNamespace(kind="effect"),)
        bindings.operations.start_batch_generation.return_value = effects

        controller.dispatch_actions((GenerateSelected(),), bindings)

        bindings.operations.start_batch_generation.assert_called_once_with(
            controller.batch,
            navigation_revision=7,
        )
        bindings.dispatch_operation_effects.assert_called_once_with(effects)

    def test_dispatch_generation_preserves_acceptance_until_replacement_ready(self):
        controller = self.make_controller("first\nsecond")
        first, second = controller.batch.items
        controller.batch.mark_accepted(first.item_id, 1)
        controller.batch.mark_accepted(second.item_id, 1)
        second.included_for_generation = False
        bindings = self.make_bindings()

        def start_batch_generation(_batch, *, navigation_revision):
            bindings.operations.busy = True
            bindings.operations.worker_operation = "batch_generate"
            return ()

        bindings.operations.start_batch_generation.side_effect = start_batch_generation
        controller.dispatch_actions((GenerateSelected(),), bindings)

        self.assertTrue(first.is_accepted)
        self.assertTrue(second.is_accepted)

    def test_replacement_invalidates_only_matching_item_acceptance(self):
        controller = self.make_controller("first\nsecond")
        first, second = controller.batch.items
        controller.batch.mark_accepted(first.item_id, 2)
        controller.batch.mark_accepted(second.item_id, 1)

        controller.invalidate_acceptance_for_replacement(first.item_id, 1)

        self.assertTrue(first.is_accepted)
        self.assertTrue(second.is_accepted)

        controller.invalidate_acceptance_for_replacement(first.item_id, 2)

        self.assertFalse(first.is_accepted)
        self.assertTrue(second.is_accepted)

    def test_dispatch_take_adjustment_keeps_batch_default_as_source_of_truth(self):
        controller = self.make_controller("first")
        bindings = self.make_bindings()

        controller.dispatch_actions((AdjustBatchTakeCount(1),), bindings)

        bindings.dispatch_editor_intents.assert_called_once_with(
            (
                AdjustmentPressedIntent("batch_list", "takes", 1),
            )
        )
        bindings.change_settings.assert_called_once_with(
            take_count=5,
            report_success=False,
        )
        self.assertEqual(controller.batch.default_take_count, 4)

    def test_dispatch_take_adjustment_at_endpoint_clears_feedback(self):
        controller = TuiBatchController(default_take_count=100)
        bindings = self.make_bindings()

        controller.dispatch_actions((AdjustBatchTakeCount(1),), bindings)

        bindings.dispatch_editor_intents.assert_called_once_with(
            (ClearAdjustmentFeedbackIntent(),)
        )
        bindings.change_settings.assert_not_called()

    def test_add_captions_uses_frontend_neutral_multiline_model(self):
        controller = self.make_controller()
        controller.add_captions(
            "first\n\nsecond\nthird",
            session_factory=FakeSession,
        )
        self.assertEqual(
            [item.caption for item in controller.batch.items],
            ["first", "second", "third"],
        )
        self.assertTrue(
            all(item.included_for_generation for item in controller.batch.items)
        )

    def test_close_sessions_closes_every_owned_item_session(self):
        controller = self.make_controller("first\nsecond")
        sessions = controller.sessions
        controller.close_sessions()
        self.assertTrue(all(session.closed for session in sessions))


    def test_numeric_shortcuts_open_existing_caption_numbers_directly(self):
        controller = self.make_controller(
            "\n".join(f"caption {number}" for number in range(1, 10))
        )

        self.assertEqual(controller.handle_key("1"), (OpenBatchItem(0),))
        self.assertEqual(controller.focus_key, ("caption", 0))
        self.assertEqual(controller.handle_key("9"), (OpenBatchItem(8),))
        self.assertEqual(controller.focus_key, ("caption", 8))

    def test_unavailable_direct_digit_is_a_harmless_no_op(self):
        controller = self.make_controller("first\nsecond")
        original_focus = controller.focus_key

        self.assertEqual(controller.handle_key("9"), ())
        self.assertEqual(controller.focus_key, original_focus)
        self.assertFalse(controller.number_jump_active)

    def test_zero_enters_jump_mode_and_multi_digit_enter_opens_caption(self):
        controller = self.make_controller(
            "\n".join(f"caption {number}" for number in range(1, 13))
        )

        self.assertEqual(controller.handle_key("0"), ())
        self.assertTrue(controller.number_jump_active)
        controller.handle_key("1")
        controller.handle_key("1")
        self.assertEqual(controller.number_jump_value, "11")

        self.assertEqual(controller.handle_key("\n"), (OpenBatchItem(10),))
        self.assertFalse(controller.number_jump_active)
        self.assertEqual(controller.focus_key, ("caption", 10))

    def test_jump_escape_cancels_without_opening(self):
        controller = self.make_controller(
            "\n".join(f"caption {number}" for number in range(1, 13))
        )
        original_focus = controller.focus_key
        controller.handle_key("0")
        controller.handle_key("1")

        self.assertEqual(controller.handle_key("\x1b"), ())
        self.assertFalse(controller.number_jump_active)
        self.assertEqual(controller.focus_key, original_focus)
        self.assertFalse(controller.in_item)

    def test_invalid_jump_warns_stays_active_and_suppresses_batch_shortcuts(self):
        controller = self.make_controller(
            "\n".join(f"caption {number}" for number in range(1, 13))
        )
        controller.handle_key("0")
        controller.handle_key("1")
        controller.handle_key("3")

        actions = controller.handle_key("\n")

        self.assertEqual(len(actions), 1)
        self.assertIsInstance(actions[0], ReportBatchStatus)
        self.assertEqual(str(actions[0].status), "Enter a number from 1 to 12.")
        self.assertTrue(controller.number_jump_active)
        self.assertEqual(controller.number_jump_value, "13")
        self.assertEqual(controller.handle_key("a"), ())
        self.assertTrue(controller.number_jump_active)

    def test_existing_navigation_and_actions_resume_after_jump_cancel(self):
        controller = self.make_controller(
            "\n".join(f"caption {number}" for number in range(1, 13))
        )
        controller.handle_key("0")
        controller.handle_key("\x1b")

        controller.handle_key(curses.KEY_DOWN)
        self.assertEqual(controller.focus_key, ("caption", 1))
        included = controller.batch.items[1].included_for_generation
        controller.handle_key(" ")
        self.assertNotEqual(
            controller.batch.items[1].included_for_generation,
            included,
        )
        self.assertEqual(controller.handle_key("\n"), (OpenBatchItem(1),))
        self.assertEqual(controller.handle_key("a"), (AddCaptions(),))


if __name__ == "__main__":
    unittest.main()


from tests.tui_app_test_support import (
    TuiAppTestCase,
    FakeScreen,
    candidate,
    editor_document,
    english_grouping,
    english_query,
    focus_candidate,
    japanese_query,
    mixed_query,
    navigation_document,
    navigation_items,
    set_navigation_focus,
)

class TuiBatchIntegrationTests(TuiAppTestCase):
    def test_other_batch_item_shows_busy_generate_and_explains_owner(self):
        app = self.make_app(query=mixed_query())
        first_item_id = app._batch.open_item_id
        second = FakeSession(query=mixed_query())
        second.caption = "second caption"
        app._batch.batch.add_item(CaptionBatchItem(second))
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._worker_item_id = first_item_id
        app._operations.operation_completed = 2
        app._operations.operation_total = 4
        app._operations._cancellation_event = Event()

        app._handle_key("\x1b")
        app._batch.focus_key = ("caption", 1)
        app._handle_key("\n")
        app._screen = FakeScreen(rows=24, columns=100)
        app._render()

        rendered = self.rendered(app._screen)
        self.assertIn("Generate < 4 > takes [busy]", rendered)
        self.assertNotIn("Generating 3/4", rendered)

        app._handle_key("g")
        self.assertEqual(
            app._status,
            "Generate Caption 2 is unavailable while generation is active.",
        )
        self.assertIs(app._status.kind, StatusKind.WARNING)
        self.assertEqual(app._operations._worker_item_id, first_item_id)

    def test_generation_progress_does_not_overwrite_conflict_status(self):
        app = self.make_app(query=mixed_query())
        item_id = app._batch.open_item_id
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._worker_item_id = item_id
        app._operations._active_operation_id = 1
        app._operations.operation_completed = 2
        app._operations.operation_total = 4
        app._operations._cancellation_event = Event()
        app._status = warning_status(
            "Generate selected is unavailable while generation is active."
        )

        app._operations.events.put(("candidate", candidate(3)))
        app._consume_events()

        self.assertEqual(
            app._status,
            "Generate selected is unavailable while generation is active.",
        )
        self.assertIs(app._status.kind, StatusKind.WARNING)

        app._screen = FakeScreen(rows=24, columns=100)
        app._render()
        rendered = self.rendered(app._screen)
        self.assertIn(
            "Generating · Caption 1 · Take 4/4 · [Ctrl+C] Cancel generation",
            rendered,
        )
        self.assertIn(
            "Warning: Generate selected is unavailable while generation is active.",
            rendered,
        )

    def test_batch_list_generate_selected_shows_busy_and_explains_owner(self):
        app = self.make_app(query=mixed_query())
        first_item_id = app._batch.open_item_id
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._worker_item_id = first_item_id
        app._operations.operation_completed = 2
        app._operations.operation_total = 4
        app._operations._cancellation_event = Event()

        app._handle_key("\x1b")
        app._screen = FakeScreen(rows=24, columns=100)
        app._render()

        self.assertIn("[G] Generate selected [busy]", self.rendered(app._screen))

        app._handle_key("g")
        self.assertEqual(
            app._status,
            "Generate selected is unavailable while generation is active.",
        )
        self.assertIs(app._status.kind, StatusKind.WARNING)
        self.assertEqual(app._operations._worker_item_id, first_item_id)

    def test_regenerate_all_cannot_replace_an_active_generation_worker(self):
        app = self.make_app(query=mixed_query())
        item_id = app._batch.open_item_id
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._worker_item_id = item_id
        app._operations.operation_completed = 1
        app._operations.operation_total = 4
        original_worker = app._operations.worker
        app.session.regenerate_all_takes = Mock(
            side_effect=AssertionError("must not start a second synthesis")
        )

        effects = app._operations.start_regenerate_all(
            app.session,
            take_count=4,
            navigation_revision=app._navigation.revision,
            item_id=item_id,
        )

        self.assertEqual(
            str(effects[0].status),
            "Regenerate all Takes is unavailable while Take generation is active.",
        )
        self.assertIs(app._operations.worker, original_worker)
        app.session.regenerate_all_takes.assert_not_called()

    def test_clear_candidates_confirmation_cancel_and_confirmed_clear(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1), candidate(2)))
        app._operations.current_take = 2
        item = app._batch.batch.items[0]
        app._batch.batch.mark_accepted(item.item_id, 2)
        query_before = app.session.query.model_dump()
        settings_before = app.settings
        caption_before = app.session.caption
        candidates_before = app.session.candidates
        stop_playback = Mock()
        app._operations.stop_playback = stop_playback

        app._handle_key("c")
        self.assertEqual(
            app._editor_controller.editor.kind,
            "clear_candidates_confirmation",
        )
        app._handle_key("\x1b")
        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(app.session.candidates, candidates_before)
        self.assertEqual(app.session.discard_calls, 0)
        self.assertEqual(app._operations.current_take, 2)
        self.assertTrue(item.is_accepted)

        app._handle_key("c")
        app._handle_key("c")

        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(app.session.discard_calls, 1)
        self.assertEqual(app.session.candidates, ())
        self.assertIsNone(app._operations.current_take)
        self.assertFalse(item.is_accepted)
        self.assertEqual(app.session.caption, caption_before)
        self.assertEqual(app.session.query.model_dump(), query_before)
        self.assertEqual(app.settings, settings_before)
        self.assertEqual(stop_playback.call_count, 1)
        self.assertEqual(app._status, "Candidates cleared.")

    def test_clear_candidates_is_blocked_for_operation_owned_caption(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        item_id = app._batch.open_item_id
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._owned_item_ids = frozenset({item_id})

        app._handle_key("c")

        self.assertIsNone(app._editor_controller.editor)
        self.assertEqual(app.session.candidates, (candidate(1),))
        self.assertEqual(app.session.discard_calls, 0)
        self.assertIn("currently generating", app._status)
        self.assertIn("clearing candidates", app._status)
