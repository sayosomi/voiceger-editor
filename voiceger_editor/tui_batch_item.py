"""Batch Item interaction policy and routing for the TUI."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .settings import Settings
from .tui_batch import BatchActionBindings, TuiBatchController
from .tui_editors import PronunciationRow
from .tui_navigation import (
    AcceptCandidate,
    AddSectionEditor,
    BuildPronunciation,
    ClearAdjustmentFeedback,
    DeleteCaption,
    EditPronunciationItem,
    NavigationAction,
    NavigationContext,
    OpenCaptionEditor,
    OpenClearCandidatesConfirmation,
    OpenDictionary,
    OpenHelp,
    OpenSettingsEditor,
    PlayCandidate,
    Quit,
    RegenerateAll,
    RegenerateCandidate,
    StartGeneration,
    UpdateNavigationStatus,
)
from .tui_shortcuts import resolve_main_shortcut
from .tui_status import EMPTY_STATUS, Status, error_status, info_status


_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"


@dataclass(frozen=True)
class BatchItemBindings:
    """Composition hooks and live app state used by Batch Item interaction."""

    actions: BatchActionBindings
    get_session: Callable[[], Any | None]
    get_settings: Callable[[], Settings]
    get_status: Callable[[], Status]
    clear_adjustment_feedback: Callable[[], None]
    mark_adjustment_pressed: Callable[[str, str, int], None]


class TuiBatchItemController:
    """Own Batch Item key interpretation and action-routing policy."""

    def __init__(self, batch: TuiBatchController) -> None:
        self.batch = batch

    def handle_key(self, key: Any, bindings: BatchItemBindings) -> None:
        actions = bindings.actions
        if self._handle_item_navigation_key(key, bindings):
            return
        if key in ("Q", "\x03"):
            actions.activate_quit()
            return

        context = self.navigation_context(bindings)
        main_shortcut = resolve_main_shortcut(key)
        if main_shortcut is not None:
            self.dispatch_navigation_actions(
                actions.navigation.activate_item(
                    context,
                    (main_shortcut.navigation_key, None),
                ),
                bindings,
            )
            return
        if key == "\t":
            self.dispatch_navigation_actions(
                actions.navigation.move_section(context, 1),
                bindings,
            )
            return
        backtab = getattr(curses, "KEY_BTAB", None)
        if backtab is not None and key == backtab:
            self.dispatch_navigation_actions(
                actions.navigation.move_section(context, -1),
                bindings,
            )
            return
        if key in (curses.KEY_LEFT, curses.KEY_RIGHT):
            direction = -1 if key == curses.KEY_LEFT else 1
            if actions.navigation.focus_key[0] == "generate":
                self.adjust_take_count(direction, bindings)
            elif (
                actions.navigation.focus_key[0] == "pronunciation"
                and actions.navigation.focus_key[1] is not None
                and bindings.get_session() is not None
                and not actions.operations.busy
            ):
                rows = self.pronunciation_rows(bindings)
                index = actions.navigation.focus_key[1]
                if 0 <= index < len(rows):
                    session = bindings.get_session()
                    actions.dispatch_editor_intents(
                        actions.editor_controller.adjust_pronunciation(
                            session.query,
                            rows[index],
                            direction,
                        )
                    )
            return
        if isinstance(key, str) and len(key) == 1 and key in "123456789":
            self.dispatch_navigation_actions(
                actions.navigation.focus_candidate(context, int(key)),
                bindings,
            )
            return
        if key == "r":
            self.dispatch_navigation_actions(
                actions.navigation.activate_regenerate_focused(context),
                bindings,
            )
            return
        if key == curses.KEY_UP:
            self.dispatch_navigation_actions(
                actions.navigation.move(context, -1),
                bindings,
            )
        elif key == curses.KEY_DOWN:
            self.dispatch_navigation_actions(
                actions.navigation.move(context, 1),
                bindings,
            )
        elif key == " ":
            if actions.navigation.focus_key[0] == "candidate":
                actions.dispatch_operation_effects(
                    actions.operations.play_take(
                        bindings.get_session(),
                        actions.navigation.focus_key[1],
                    )
                )
        elif key in _ENTER_KEYS:
            self.dispatch_navigation_actions(
                actions.navigation.activate_focused_item(context),
                bindings,
            )

    def navigation_context(self, bindings: BatchItemBindings) -> NavigationContext:
        session = bindings.get_session()
        return NavigationContext.from_session(
            session,
            pronunciation_count=(
                len(self.pronunciation_rows(bindings))
                if session is not None
                else 0
            ),
            busy=bindings.actions.operations.busy,
            has_item_navigator=self.batch.in_item,
        )

    def dispatch_navigation_actions(
        self,
        navigation_actions: Sequence[NavigationAction],
        bindings: BatchItemBindings,
    ) -> None:
        actions = bindings.actions
        for action in navigation_actions:
            session = bindings.get_session()
            settings = bindings.get_settings()
            if isinstance(action, ClearAdjustmentFeedback):
                bindings.clear_adjustment_feedback()
            elif isinstance(action, UpdateNavigationStatus):
                actions.set_status(action.status)
            elif isinstance(action, OpenSettingsEditor):
                actions.open_settings_editor(
                    action.selected_field,
                    edit=action.edit,
                )
            elif isinstance(action, OpenCaptionEditor):
                actions.open_caption_editor()
            elif isinstance(action, DeleteCaption):
                actions.operations.stop_playback()
                self.batch.request_delete_open_item()
            elif isinstance(action, OpenClearCandidatesConfirmation):
                if actions.operations.busy:
                    actions.set_status(
                        info_status(
                            "Finish or cancel synthesis before clearing candidates."
                        )
                    )
                elif session is not None and session.candidates:
                    actions.dispatch_editor_intents(
                        actions.editor_controller.open_clear_candidates_confirmation(
                            origin=actions.navigation.focus_key
                        )
                    )
            elif isinstance(action, EditPronunciationItem):
                self.edit_selected_pronunciation(action.index, bindings)
            elif isinstance(action, AddSectionEditor):
                if session is None or not getattr(session, "is_prepared", True):
                    actions.set_status(
                        info_status(
                            "Prepare pronunciation before adding a section."
                        )
                    )
                    continue
                actions.dispatch_editor_intents(
                    actions.editor_controller.open_add_section(
                        session.query,
                        pure_japanese_utterance_text=(
                            session.pure_japanese_utterance_text
                        ),
                        origin=actions.navigation.focus_key,
                        busy=actions.operations.busy,
                    )
                )
            elif isinstance(action, StartGeneration):
                if session is not None and not getattr(session, "is_prepared", True):
                    actions.set_status(
                        info_status(
                            "Prepare pronunciation before generating Takes."
                        )
                    )
                    continue
                effects = actions.operations.start_generation(
                    session,
                    take_count=settings.take_count,
                    navigation_revision=actions.navigation.revision,
                )
                if (
                    actions.operations.busy
                    and actions.operations.worker_operation == "initial"
                ):
                    self.batch.clear_open_item_acceptance()
                actions.dispatch_operation_effects(effects)
            elif isinstance(action, RegenerateAll):
                actions.dispatch_operation_effects(
                    actions.operations.start_regenerate_all(
                        session,
                        take_count=settings.take_count,
                        navigation_revision=actions.navigation.revision,
                    )
                )
            elif isinstance(action, BuildPronunciation):
                self.request_build_pronunciation(bindings)
            elif isinstance(action, AcceptCandidate):
                self.accept_open_item(
                    action.number,
                    pronunciation_index=actions.navigation.pronunciation_index,
                    bindings=bindings,
                )
            elif isinstance(action, RegenerateCandidate):
                actions.dispatch_operation_effects(
                    actions.operations.start_regeneration(
                        session,
                        action.number,
                        take_count=settings.take_count,
                        navigation_revision=actions.navigation.revision,
                    )
                )
            elif isinstance(action, PlayCandidate):
                actions.operations.current_take = action.number
                actions.dispatch_operation_effects(
                    actions.operations.play_take(session, action.number)
                )
            elif isinstance(action, OpenDictionary):
                actions.dispatch_editor_intents(
                    actions.dictionary_controller.open_menu()
                )
            elif isinstance(action, OpenHelp):
                actions.open_help()
            elif isinstance(action, Quit):
                actions.activate_quit()

    def request_build_pronunciation(self, bindings: BatchItemBindings) -> None:
        session = bindings.get_session()
        if session is None:
            return
        actions = bindings.actions
        if session.utterance_manually_edited:
            actions.dispatch_editor_intents(
                actions.editor_controller.open_build_confirmation(
                    origin=actions.navigation.focus_key
                )
            )
            return
        self.start_pronunciation_preparation(bindings, rebuild=True)

    def build_pronunciation_from_caption(
        self,
        bindings: BatchItemBindings,
    ) -> str | None:
        """Compatibility route for confirmed explicit pronunciation rebuilds."""

        return self.start_pronunciation_preparation(bindings, rebuild=True)

    def start_pronunciation_preparation(
        self,
        bindings: BatchItemBindings,
        *,
        rebuild: bool,
    ) -> str | None:
        session = bindings.get_session()
        if session is None:
            return "there is no active session"
        actions = bindings.actions
        actions.dispatch_operation_effects(
            actions.operations.start_session_preparation(
                session,
                rebuild=rebuild,
            )
        )
        return None

    def complete_preparation(
        self,
        session: Any,
        *,
        rebuild: bool,
        error: BaseException | None,
        bindings: BatchItemBindings,
    ) -> None:
        """Apply one preparation result to the currently open Batch Item."""

        if session is not bindings.get_session():
            return
        actions = bindings.actions
        if error is not None:
            label = "rebuilt" if rebuild else "prepared"
            actions.set_status(
                error_status(f"Pronunciation was not {label}: {error}")
            )
            return

        actions.operations.stop_playback()
        actions.editor_controller.clear_groupings()
        actions.operations.clear_current_take()
        self.dispatch_navigation_actions(
            actions.navigation.reset_after_rebuild(
                self.navigation_context(bindings)
            ),
            bindings,
        )
        actions.set_status(
            info_status(
                "Pronunciation rebuilt from Caption."
                if rebuild
                else "Pronunciation prepared."
            )
        )

    def adjust_take_count(
        self,
        direction: int,
        bindings: BatchItemBindings,
    ) -> None:
        actions = bindings.actions
        if actions.operations.busy:
            bindings.clear_adjustment_feedback()
            actions.set_status(
                info_status("Wait for the current synthesis operation to finish.")
            )
            return
        count = bindings.get_settings().take_count
        updated = min(100, max(1, count + direction))
        if updated == count:
            bindings.clear_adjustment_feedback()
            return
        bindings.mark_adjustment_pressed(
            "navigation",
            "generate",
            direction,
        )
        actions.change_settings(
            take_count=updated,
            report_success=False,
        )
        self.dispatch_navigation_actions(
            actions.navigation.set_focus_key(
                self.navigation_context(bindings),
                ("generate", None),
            ),
            bindings,
        )

    def segments(self, session: Any | None) -> list[tuple[str, str, int | None]]:
        if session is None or not getattr(session, "is_prepared", True):
            return []
        query = session.query
        if query.voicegerSegments is None:
            return [
                ("ja", session.pure_japanese_utterance_text or "", None)
            ]
        return [
            (segment.language, segment.text, index)
            for index, segment in enumerate(query.voicegerSegments)
        ]

    def pronunciation_rows(
        self,
        bindings: BatchItemBindings,
    ) -> tuple[PronunciationRow, ...]:
        session = bindings.get_session()
        if session is None or not getattr(session, "is_prepared", True):
            return ()
        actions = bindings.actions
        previous_grouping_error = actions.editor_controller.grouping_error
        rows = actions.editor_controller.pronunciation_rows(
            session.query,
            self.segments(session),
        )
        grouping_error = actions.editor_controller.grouping_error
        if grouping_error:
            actions.set_status(grouping_error)
        elif (
            previous_grouping_error
            and bindings.get_status() == previous_grouping_error
        ):
            actions.set_status(EMPTY_STATUS)
        return rows

    def edit_selected_pronunciation(
        self,
        pronunciation_index: int,
        bindings: BatchItemBindings,
    ) -> None:
        session = bindings.get_session()
        actions = bindings.actions
        if (
            session is None
            or not getattr(session, "is_prepared", True)
            or actions.operations.busy
        ):
            return
        rows = self.pronunciation_rows(bindings)
        if not 0 <= pronunciation_index < len(rows):
            return
        actions.dispatch_editor_intents(
            actions.editor_controller.open_pronunciation_item(
                session.query,
                rows,
                pronunciation_index,
                origin=("pronunciation", pronunciation_index),
                busy=actions.operations.busy,
            )
        )

    def accept_open_item(
        self,
        number: int,
        *,
        pronunciation_index: int,
        bindings: BatchItemBindings,
    ) -> None:
        item_id = self.batch.open_item_id
        if item_id is None:
            return
        item = self.batch.batch.get_item(item_id)
        session = item.session
        actions = bindings.actions
        effects = actions.operations.accept_take(
            session,
            number,
            item_id=item_id,
            busy=actions.operations.busy,
            pronunciation_index=pronunciation_index,
        )
        actions.dispatch_operation_effects(effects)

    def move_open_item(
        self,
        direction: int,
        bindings: BatchItemBindings,
        *,
        show_feedback: bool = False,
    ) -> None:
        index = self.batch.item_index
        if index is None or direction == 0:
            bindings.clear_adjustment_feedback()
            return
        actions = bindings.actions
        if actions.operations.busy:
            bindings.clear_adjustment_feedback()
            actions.set_status(
                info_status("Wait for the current synthesis operation to finish.")
            )
            return
        target = index + (-1 if direction < 0 else 1)
        if target < 0:
            bindings.clear_adjustment_feedback()
            actions.set_status(info_status("First Caption."))
            return
        if target >= len(self.batch.batch):
            bindings.clear_adjustment_feedback()
            actions.set_status(info_status("Last Caption."))
            return

        if show_feedback:
            bindings.mark_adjustment_pressed(
                "navigation",
                "batch_item",
                direction,
            )
        else:
            bindings.clear_adjustment_feedback()
        actions.operations.stop_playback()
        actions.operations.clear_current_take()
        actions.editor_controller.clear_groupings()
        session = self.batch.open_item(target)
        actions.set_session(session)
        actions.navigation.focus_key = ("batch_item", None)
        actions.navigation.reset_pronunciation_index()
        actions.set_status(EMPTY_STATUS)
        if not getattr(session, "is_prepared", True):
            actions.dispatch_operation_effects(
                actions.operations.start_session_preparation(
                    session,
                    rebuild=False,
                )
            )

    def _handle_item_navigation_key(
        self,
        key: Any,
        bindings: BatchItemBindings,
    ) -> bool:
        actions = bindings.actions
        if key == _ESCAPE:
            if (
                actions.operations.busy
                and actions.operations.worker_operation in {"accept", "prepare"}
            ):
                return True
            actions.operations.stop_playback()
            actions.operations.clear_current_take()
            actions.editor_controller.clear_groupings()
            self.batch.close_item()
            actions.set_session(None)
            actions.set_status(EMPTY_STATUS)
            return True

        direction: int | None = None
        show_adjustment_feedback = False
        if key == "[":
            direction = -1
        elif key == "]":
            direction = 1
        elif actions.navigation.focus_key == ("batch_item", None):
            if key == curses.KEY_LEFT:
                direction = -1
                show_adjustment_feedback = True
            elif key == curses.KEY_RIGHT:
                direction = 1
                show_adjustment_feedback = True
        if direction is None:
            return False
        self.move_open_item(
            direction,
            bindings,
            show_feedback=show_adjustment_feedback,
        )
        return True
