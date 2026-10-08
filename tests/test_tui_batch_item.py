import curses
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from voiceger_editor.settings import Settings
from voiceger_editor.tui_batch import BatchActionBindings, TuiBatchController
from voiceger_editor.tui_editors import (
    AdjustmentPressedIntent,
    ClearAdjustmentFeedbackIntent,
)
from voiceger_editor.tui_batch_item import (
    BatchItemBindings,
    TuiBatchItemController,
)
from voiceger_editor.tui_navigation import (
    AcceptCandidate,
    DeleteCaption,
    OpenCaptionEditor,
    OpenClearCandidatesConfirmation,
    TuiNavigation,
)
from voiceger_editor.tui_operations import UpdateStatusEffect
from voiceger_editor.tui_output_path import BeginOutputPathEditIntent
from voiceger_editor.tui_status import error_status, warning_status


class FakeSession:
    def __init__(
        self,
        caption,
        *,
        candidates=(),
        active=True,
        prepared=True,
    ):
        self.caption = caption
        self.is_prepared = prepared
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
        operations.start_session_preparation.return_value = ()
        operations.item_mutation_conflict_status.return_value = None
        operations.owns_item.return_value = False
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
            open_batch_read=Mock(),
            open_batch_write=Mock(),
            dispatch_editor_intents=Mock(),
            dispatch_operation_effects=Mock(),
            open_help=Mock(),
            activate_quit=Mock(),
            initialize_open_item=Mock(),
        )
        bindings = BatchItemBindings(
            actions=actions,
            get_session=lambda: state["session"],
            get_settings=lambda: state["settings"],
            get_status=lambda: state["status"],
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
        bindings.actions.dispatch_editor_intents.assert_called_once_with(
            (
                AdjustmentPressedIntent("navigation", "batch_item", 1),
            )
        )

        bindings.actions.set_status.reset_mock()
        bindings.actions.dispatch_editor_intents.reset_mock()
        subject.handle_key("]", bindings)
        self.assertEqual(batch.item_position, (2, 2))
        bindings.actions.set_status.assert_called_once_with("Last Caption.")
        bindings.actions.dispatch_editor_intents.assert_called_once_with(
            (ClearAdjustmentFeedbackIntent(),)
        )

        bindings.actions.dispatch_editor_intents.reset_mock()
        subject.handle_key("[", bindings)
        self.assertEqual(batch.item_position, (1, 2))
        bindings.actions.dispatch_editor_intents.assert_called_once_with(
            (ClearAdjustmentFeedbackIntent(),)
        )

    def test_file_shortcut_starts_inline_shared_output_edit(self):
        subject, _batch, bindings, _state = self.make_subject()

        subject.handle_key("f", bindings)

        bindings.actions.dispatch_editor_intents.assert_called_once_with(
            (BeginOutputPathEditIntent("batch_item"),)
        )
        bindings.actions.open_settings_editor.assert_not_called()

    def test_open_item_focus_prefers_accepted_then_first_candidate(self):
        subject, batch, bindings, state = self.make_subject()
        state["session"].candidates = [
            SimpleNamespace(number=1),
            SimpleNamespace(number=2),
        ]
        bindings.actions.operations.play_take.return_value = ()
        item = batch.batch.items[0]
        batch.batch.mark_accepted(item.item_id, 2)

        subject.initialize_open_item_focus(bindings)

        self.assertEqual(bindings.actions.navigation.focus_key, ("candidate", 2))
        self.assertEqual(bindings.actions.operations.current_take, 2)
        bindings.actions.operations.play_take.assert_called_once_with(
            state["session"],
            2,
        )

        bindings.actions.operations.play_take.reset_mock()
        batch.batch.clear_acceptance(item.item_id)
        bindings.actions.navigation.focus_key = ("caption", None)

        subject.initialize_open_item_focus(bindings)

        self.assertEqual(bindings.actions.navigation.focus_key, ("candidate", 1))
        self.assertEqual(bindings.actions.operations.current_take, 1)
        bindings.actions.operations.play_take.assert_called_once_with(
            state["session"],
            1,
        )

    def test_open_item_focus_uses_pronunciation_then_caption_when_no_candidates(self):
        subject, _batch, bindings, state = self.make_subject()
        bindings.actions.editor_controller.pronunciation_rows.return_value = (
            SimpleNamespace(),
        )

        subject.initialize_open_item_focus(bindings)

        self.assertEqual(bindings.actions.navigation.focus_key, ("pronunciation", 0))
        bindings.actions.operations.play_take.assert_not_called()

        state["session"].is_prepared = False
        bindings.actions.navigation.focus_key = ("pronunciation", 0)

        subject.initialize_open_item_focus(bindings)

        self.assertEqual(bindings.actions.navigation.focus_key, ("caption", None))

    def test_caption_and_fixed_action_focus_survive_item_switches(self):
        subject, batch, bindings, _state = self.make_subject()

        bindings.actions.navigation.focus_key = ("caption", None)
        subject.move_open_item(1, bindings)
        self.assertEqual(batch.item_position, (2, 2))
        self.assertEqual(bindings.actions.navigation.focus_key, ("caption", None))

        bindings.actions.navigation.focus_key = ("output", None)
        subject.move_open_item(-1, bindings)
        self.assertEqual(batch.item_position, (1, 2))
        self.assertEqual(bindings.actions.navigation.focus_key, ("output", None))

    def test_candidate_focus_keeps_same_take_or_falls_back_to_target_priority(self):
        subject, batch, bindings, state = self.make_subject()
        first, second = batch.batch.items
        first.session.candidates = [
            SimpleNamespace(number=1),
            SimpleNamespace(number=2),
        ]
        second.session.candidates = [
            SimpleNamespace(number=1),
            SimpleNamespace(number=2),
        ]
        bindings.actions.operations.play_take.return_value = ()
        bindings.actions.navigation.focus_key = ("candidate", 2)

        subject.move_open_item(1, bindings)

        self.assertIs(state["session"], second.session)
        self.assertEqual(bindings.actions.navigation.focus_key, ("candidate", 2))
        self.assertEqual(bindings.actions.operations.current_take, 2)
        bindings.actions.operations.play_take.assert_called_with(second.session, 2)

        bindings.actions.operations.play_take.reset_mock()
        second.session.candidates = [SimpleNamespace(number=1)]
        batch.batch.mark_accepted(first.item_id, 2)
        bindings.actions.navigation.focus_key = ("candidate", 1)
        subject.move_open_item(-1, bindings)
        self.assertEqual(bindings.actions.navigation.focus_key, ("candidate", 1))

        first.session.candidates = [
            SimpleNamespace(number=2),
            SimpleNamespace(number=3),
        ]
        bindings.actions.navigation.focus_key = ("candidate", 1)
        subject.move_open_item(1, bindings)
        second.session.candidates = [SimpleNamespace(number=1)]
        subject.move_open_item(-1, bindings)

        self.assertEqual(bindings.actions.navigation.focus_key, ("candidate", 2))
        self.assertEqual(bindings.actions.operations.current_take, 2)
        bindings.actions.operations.play_take.assert_called_with(first.session, 2)

    def test_pronunciation_focus_keeps_index_or_falls_back_to_first_row(self):
        subject, batch, bindings, state = self.make_subject()
        first, second = batch.batch.items
        bindings.actions.editor_controller.pronunciation_rows.side_effect = (
            lambda _query, _segments: (
                (SimpleNamespace(), SimpleNamespace(), SimpleNamespace())
                if state["session"] is first.session
                else (SimpleNamespace(), SimpleNamespace())
            )
        )
        bindings.actions.navigation.focus_key = ("pronunciation", 1)

        subject.move_open_item(1, bindings)
        self.assertEqual(
            bindings.actions.navigation.focus_key,
            ("pronunciation", 1),
        )

        bindings.actions.navigation.focus_key = ("pronunciation", 2)
        subject.move_open_item(-1, bindings)
        subject.move_open_item(1, bindings)
        self.assertEqual(
            bindings.actions.navigation.focus_key,
            ("pronunciation", 0),
        )

    def test_unprepared_item_restores_preserved_focus_after_prepare(self):
        subject, batch, bindings, state = self.make_subject()
        target = batch.batch.items[1].session
        target.is_prepared = False
        bindings.actions.navigation.focus_key = ("caption", None)

        subject.move_open_item(1, bindings)

        self.assertEqual(bindings.actions.navigation.focus_key, ("caption", None))
        bindings.actions.operations.start_session_preparation.assert_called_once_with(
            target,
            rebuild=False,
            item_id=batch.batch.items[1].item_id,
        )

        target.is_prepared = True
        bindings.actions.editor_controller.pronunciation_rows.return_value = (
            SimpleNamespace(),
        )
        subject.complete_preparation(
            target,
            rebuild=False,
            error=None,
            bindings=bindings,
        )

        self.assertEqual(bindings.actions.navigation.focus_key, ("caption", None))

    def test_caption_movement_remains_available_while_another_item_generates(self):
        subject, batch, bindings, state = self.make_subject()
        bindings.actions.operations.busy = True

        subject.move_open_item(1, bindings)

        self.assertEqual(batch.item_position, (2, 2))
        self.assertIs(state["session"], batch.batch.items[1].session)

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
            pronunciation_index=0,
        )
        bindings.actions.dispatch_operation_effects.assert_called_once_with(effects)
        self.assertFalse(target.is_accepted)
        self.assertIsNone(target.accepted_take_number)

    def test_escape_keeps_batch_item_open_while_take_is_saving(self):
        subject, batch, bindings, state = self.make_subject()
        bindings.actions.operations.busy = True
        bindings.actions.operations.worker_operation = "accept"

        subject.handle_key("\x1b", bindings)

        self.assertTrue(batch.in_item)
        self.assertIs(state["session"], batch.batch.items[0].session)
        bindings.actions.set_status.assert_not_called()

    def test_escape_keeps_batch_item_open_while_pronunciation_is_preparing(self):
        subject, batch, bindings, state = self.make_subject()
        bindings.actions.operations.busy = True
        bindings.actions.operations.worker_operation = "prepare"

        subject.handle_key("\x1b", bindings)

        self.assertTrue(batch.in_item)
        self.assertIs(state["session"], batch.batch.items[0].session)
        bindings.actions.set_status.assert_not_called()

    def test_explicit_build_pronunciation_uses_deferred_preparation_operation(self):
        subject, _batch, bindings, state = self.make_subject()
        effects = (UpdateStatusEffect("Rebuilding pronunciation…"),)
        bindings.actions.operations.start_session_preparation.return_value = effects

        subject.request_build_pronunciation(bindings)

        bindings.actions.operations.start_session_preparation.assert_called_once_with(
            state["session"],
            rebuild=True,
            item_id=subject.batch.open_item_id,
        )
        bindings.actions.dispatch_operation_effects.assert_called_once_with(effects)

    def test_unprepared_item_hides_query_dependent_pronunciation_rows(self):
        subject, _batch, bindings, state = self.make_subject()
        state["session"].is_prepared = False

        self.assertEqual(subject.pronunciation_rows(bindings), ())
        bindings.actions.editor_controller.pronunciation_rows.assert_not_called()

    def test_preparation_failure_is_visible_and_explicit_build_can_retry(self):
        subject, _batch, bindings, state = self.make_subject()
        state["session"].is_prepared = False

        subject.complete_preparation(
            state["session"],
            rebuild=False,
            error=RuntimeError("g2p failed"),
            bindings=bindings,
        )

        self.assertEqual(
            state["status"],
            error_status("Pronunciation was not prepared: g2p failed"),
        )

        effects = (UpdateStatusEffect("Rebuilding pronunciation…"),)
        bindings.actions.operations.start_session_preparation.return_value = effects
        subject.request_build_pronunciation(bindings)
        bindings.actions.operations.start_session_preparation.assert_called_once_with(
            state["session"],
            rebuild=True,
            item_id=subject.batch.open_item_id,
        )

    def test_owned_caption_mutations_report_operation_conflict(self):
        subject, _batch, bindings, _state = self.make_subject()
        conflict = warning_status(
            "Caption 1 is currently generating; editing Caption is unavailable "
            "until generation finishes."
        )
        bindings.actions.operations.item_mutation_conflict_status.return_value = conflict

        subject.dispatch_navigation_actions((OpenCaptionEditor(),), bindings)

        bindings.actions.open_caption_editor.assert_not_called()
        bindings.actions.set_status.assert_called_once_with(conflict)

    def test_owned_caption_delete_and_clear_report_operation_conflict(self):
        subject, batch, bindings, state = self.make_subject()
        state["session"].candidates = [SimpleNamespace(number=1)]
        conflict = warning_status(
            "Caption 1 is currently generating; deleting Caption is unavailable "
            "until generation finishes."
        )
        bindings.actions.operations.item_mutation_conflict_status.return_value = conflict

        subject.dispatch_navigation_actions((DeleteCaption(),), bindings)

        self.assertFalse(batch.delete_confirmation_active)
        bindings.actions.set_status.assert_called_once_with(conflict)

        bindings.actions.set_status.reset_mock()
        bindings.actions.operations.item_mutation_conflict_status.return_value = (
            warning_status(
                "Caption 1 is currently generating; clearing candidates is unavailable "
                "until generation finishes."
            )
        )
        subject.dispatch_navigation_actions(
            (OpenClearCandidatesConfirmation(),),
            bindings,
        )
        bindings.actions.editor_controller.open_clear_candidates_confirmation.assert_not_called()
        bindings.actions.set_status.assert_called_once()

    def test_direct_take_numbers_one_through_nine_focus_and_play(self):
        subject, _batch, bindings, state = self.make_subject()
        state["session"].candidates = [
            SimpleNamespace(number=number) for number in range(1, 10)
        ]
        bindings.actions.operations.play_take.return_value = ()

        for number in range(1, 10):
            with self.subTest(number=number):
                bindings.actions.navigation.focus_key = ("caption", None)
                bindings.actions.operations.current_take = None
                bindings.actions.operations.play_take.reset_mock()

                subject.handle_key(str(number), bindings)

                self.assertEqual(
                    bindings.actions.navigation.focus_key,
                    ("candidate", number),
                )
                self.assertEqual(bindings.actions.operations.current_take, number)
                bindings.actions.operations.play_take.assert_called_once_with(
                    state["session"],
                    number,
                )

    def test_multi_digit_take_jump_focuses_and_plays_without_accepting(self):
        subject, _batch, bindings, state = self.make_subject()
        state["session"].candidates = [
            SimpleNamespace(number=number) for number in range(1, 13)
        ]
        bindings.actions.operations.play_take.return_value = ()

        subject.handle_key("0", bindings)
        subject.handle_key("1", bindings)
        subject.handle_key("2", bindings)
        subject.handle_key("\n", bindings)

        self.assertFalse(subject.number_jump_active)
        self.assertEqual(bindings.actions.navigation.focus_key, ("candidate", 12))
        self.assertEqual(bindings.actions.operations.current_take, 12)
        bindings.actions.operations.play_take.assert_called_once_with(
            state["session"],
            12,
        )
        bindings.actions.operations.accept_take.assert_not_called()

    def test_take_jump_escape_cancels_without_changing_focus(self):
        subject, _batch, bindings, state = self.make_subject()
        state["session"].candidates = [
            SimpleNamespace(number=number) for number in range(1, 13)
        ]
        bindings.actions.navigation.focus_key = ("candidate", 2)

        subject.handle_key("0", bindings)
        subject.handle_key("1", bindings)
        subject.handle_key("\x1b", bindings)

        self.assertFalse(subject.number_jump_active)
        self.assertEqual(bindings.actions.navigation.focus_key, ("candidate", 2))
        bindings.actions.operations.play_take.assert_not_called()

    def test_invalid_take_jump_warns_stays_active_and_swallows_shortcuts(self):
        subject, _batch, bindings, state = self.make_subject()
        state["session"].candidates = [
            SimpleNamespace(number=number) for number in range(1, 13)
        ]

        subject.handle_key("0", bindings)
        subject.handle_key("1", bindings)
        subject.handle_key("3", bindings)
        subject.handle_key("\n", bindings)

        self.assertTrue(subject.number_jump_active)
        self.assertEqual(subject.number_jump_value, "13")
        self.assertEqual(
            state["status"],
            warning_status("Enter a number from 1 to 12."),
        )

        subject.handle_key("r", bindings)
        self.assertTrue(subject.number_jump_active)
        bindings.actions.operations.start_regeneration.assert_not_called()

    def test_normal_enter_accepts_after_take_jump_completes(self):
        subject, _batch, bindings, state = self.make_subject()
        state["session"].candidates = [
            SimpleNamespace(number=number) for number in range(1, 13)
        ]
        bindings.actions.operations.play_take.return_value = ()
        bindings.actions.operations.accept_take.return_value = ()

        subject.handle_key("0", bindings)
        subject.handle_key("1", bindings)
        subject.handle_key("2", bindings)
        subject.handle_key("\n", bindings)
        bindings.actions.operations.accept_take.assert_not_called()

        subject.handle_key("\n", bindings)

        bindings.actions.operations.accept_take.assert_called_once()
        self.assertEqual(bindings.actions.operations.accept_take.call_args.args[1], 12)

    def test_generate_take_count_adjustment_uses_existing_settings_owner(self):
        subject, _batch, bindings, _state = self.make_subject()
        bindings.actions.operations.busy = True
        bindings.actions.navigation.focus_key = ("generate", None)

        subject.handle_key(curses.KEY_RIGHT, bindings)

        bindings.actions.dispatch_editor_intents.assert_called_once_with(
            (
                AdjustmentPressedIntent("navigation", "generate", 1),
            )
        )
        bindings.actions.change_settings.assert_called_once_with(
            take_count=5,
            report_success=False,
        )
        self.assertEqual(
            bindings.actions.navigation.focus_key,
            ("generate", None),
        )

    def test_generate_take_count_endpoint_clears_feedback_without_saving(self):
        subject, _batch, bindings, state = self.make_subject()
        bindings.actions.navigation.focus_key = ("generate", None)
        state["settings"] = Settings(take_count=100)

        subject.handle_key(curses.KEY_RIGHT, bindings)

        bindings.actions.dispatch_editor_intents.assert_called_once_with(
            (ClearAdjustmentFeedbackIntent(),)
        )
        bindings.actions.change_settings.assert_not_called()

    def test_navigation_context_uses_pronunciation_rows_from_editor_owner(self):
        subject, _batch, bindings, _state = self.make_subject()
        row = SimpleNamespace(language="ja")
        bindings.actions.editor_controller.pronunciation_rows.return_value = (row,)

        context = subject.navigation_context(bindings)

        self.assertTrue(context.has_session)
        self.assertEqual(context.pronunciation_count, 1)
        self.assertTrue(context.has_item_navigator)
        bindings.actions.editor_controller.pronunciation_rows.assert_called_once()


from unittest.mock import call
from tests.tui_app_test_support import TuiAppTestCase, FakeScreen, candidate, focus_candidate, mixed_query, set_navigation_focus

class TuiBatchItemIntegrationTests(TuiAppTestCase):
    def test_candidate_regeneration_uses_only_focused_candidate(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        app._operations.current_take = 1
        app._operations.start_regeneration = Mock(return_value=())
        set_navigation_focus(app, ("generate", None))
        app._handle_key("r")
        app._operations.start_regeneration.assert_not_called()
        self.assertEqual(app._status, "Select a candidate before regenerating it.")

        app.session.candidates = (candidate(1), candidate(2))
        app._operations.play_take = Mock(return_value=())
        focus_candidate(app, 2)
        navigation_revision = app._navigation.revision
        app._handle_key("r")
        app._operations.start_regeneration.assert_called_once_with(
            app.session,
            2,
            take_count=app.settings.take_count,
            navigation_revision=navigation_revision,
            item_id=app._batch.open_item_id,
        )

    def test_busy_candidate_remains_playable_without_inline_unavailable_cues(self):
        app = self.make_app(candidates=(candidate(1), candidate(2)))
        app._operations.play_take = Mock(return_value=())
        app._operations.busy = True
        focus_candidate(app, 1)
        app._handle_key(curses.KEY_DOWN)
        self.assertEqual(app._navigation.focus_key, ("candidate", 2))
        app._handle_key(" ")
        self.assertEqual(
            app._operations.play_take.call_args_list,
            [call(app.session, 1), call(app.session, 2), call(app.session, 2)],
        )

        screen = FakeScreen()
        app._screen = screen
        app._render()
        rendered = self.rendered(screen)
        self.assertIn("Take 2", rendered)
        self.assertNotIn("unavailable while generating", rendered)
        self.assertNotIn("Enter unavailable", rendered)
        self.assertNotIn("Enter accepts and saves", rendered)
        self.assertNotIn("↑↓ Move/play", rendered)
        self.assertNotIn("↑/↓ Move", rendered)
        self.assertNotIn("? Help", rendered)
        self.assertNotIn(23, [row for row, _column, _text, _attr in screen.drawn])

    def test_enter_on_candidate_accepts_and_saves_when_not_busy(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        session = app.session
        item = app._batch.batch.items[0]
        app._operations.play_take = Mock(return_value=())
        focus_candidate(app, 1)

        app._handle_key("\n")

        self.assertEqual(session.accept_calls, [])
        self.assertFalse(item.is_accepted)
        self.assertIn("Saving Take 1…", app._status)

        app._operations.start_pending_worker()
        app._operations.join_worker()
        app._consume_events()

        self.assertEqual(session.accept_calls, [1])
        self.assertTrue(item.is_accepted)
        self.assertEqual(item.accepted_take_number, 1)
        self.assertEqual([item.number for item in session.candidates], [1])
        self.assertTrue(app._batch.in_item)
        self.assertIs(app.session, session)
        self.assertEqual(app._navigation.focus_key, ("candidate", 1))

    def test_primary_batch_item_shortcuts_activate_settled_visible_actions(self):
        caption = self.make_app(query=mixed_query())
        caption._handle_key("e")
        self.assertEqual(caption._editor_controller.editor.kind, "caption")

        build = self.make_app(query=mixed_query())
        build._batch_item_controller.request_build_pronunciation = Mock()
        build._handle_key("p")
        build._batch_item_controller.request_build_pronunciation.assert_called_once_with(
            build._batch_item_bindings
        )

        add = self.make_app(query=mixed_query())
        add._handle_key("a")
        self.assertEqual(add._editor_controller.editor.kind, "add_section")

        generate = self.make_app(query=mixed_query())
        generate._operations.start_generation = Mock(return_value=())
        generate._handle_key("g")
        generate._operations.start_generation.assert_called_once_with(
            generate.session,
            take_count=generate.settings.take_count,
            navigation_revision=generate._navigation.revision,
            item_id=generate._batch.open_item_id,
        )

        regenerate = self.make_app(
            query=mixed_query(), candidates=(candidate(1),)
        )
        regenerate._operations.start_regenerate_all = Mock(return_value=())
        regenerate._handle_key("g")
        regenerate._operations.start_regenerate_all.assert_called_once_with(
            regenerate.session,
            take_count=regenerate.settings.take_count,
            navigation_revision=regenerate._navigation.revision,
            item_id=regenerate._batch.open_item_id,
        )

        output = self.make_app(query=mixed_query())
        output._handle_key("f")
        self.assertIsNone(output._editor_controller.editor)
        self.assertTrue(output._output_path_controller.active)
        self.assertEqual(output._output_path_controller.state.owner, "batch_item")

        for removed in (
            curses.KEY_F5, "\x07", "R", "b", "t", "v", "n", "x", "l"
        ):
            with self.subTest(removed=removed):
                legacy = self.make_app(query=mixed_query())
                legacy._operations.start_generation = Mock(return_value=())
                legacy._operations.start_regenerate_all = Mock(return_value=())
                legacy._handle_key(removed)
                legacy._operations.start_generation.assert_not_called()
                legacy._operations.start_regenerate_all.assert_not_called()
                self.assertIsNone(legacy._editor_controller.editor)

    def test_batch_item_shortcuts_open_shared_actions_and_candidate_regeneration(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        app._handle_key("e")
        self.assertEqual(app._editor_controller.editor.kind, "caption")
        app._handle_key("\x1b")
        app._handle_key("s")
        self.assertEqual(app._editor_controller.editor.kind, "settings")
        self.assertEqual(app._editor_controller.editor.selection, "style_id")
        app._handle_key("\x1b")
        app._operations.play_take = Mock(return_value=())
        focus_candidate(app, 1)
        navigation_revision = app._navigation.revision
        app._operations.start_regeneration = Mock(return_value=())
        app._handle_key("r")
        app._operations.start_regeneration.assert_called_once_with(
            app.session,
            1,
            take_count=app.settings.take_count,
            navigation_revision=navigation_revision,
            item_id=app._batch.open_item_id,
        )

        help_shortcut = self.make_app(query=mixed_query())
        help_shortcut._handle_key("?")
        self.assertTrue(help_shortcut._help_open)

        quit_shortcut = self.make_app(query=mixed_query())
        quit_shortcut._handle_key("q")
        self.assertTrue(quit_shortcut._exit_requested)


if __name__ == "__main__":
    unittest.main()
