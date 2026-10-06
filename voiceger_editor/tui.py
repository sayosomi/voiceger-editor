"""Keyboard-first terminal interface for local Voiceger synthesis."""

from __future__ import annotations

import curses
import os
from typing import Any, Sequence

from .session import UtteranceSession
from . import tui_batch
from .tui_batch_item import BatchItemBindings, TuiBatchItemController
from .tui_batch_recipe import TuiBatchRecipeController
from .settings import Settings, save_settings
from .tui_settings import TuiSettingsController
from .tui_status import EMPTY_STATUS, Status, error_status, info_status
from .styles import available_styles
from .tui_cli import build_argument_parser, settings_for_invocation
from .tui_display import _adjustable_value, format_english_phonemes
from .tui_dictionary import (
    DictionaryControllerIntent,
    DictionaryOperationIntent,
    TuiDictionaryController,
)
from .tui_help import HelpOutcome, TuiHelpController
from .tui_rendering import (
    TuiRenderer,
    TuiRenderState,
    _HELP_ITEMS,
    _active_input_prefix,
    format_background_operation_progress,
)
from .tui_editors import (
    AdjustmentPressedIntent, ApplyCaptionIntent, ApplySettingsIntent,
    BuildPronunciationIntent, BuildPronunciationResult, CaptionApplicationResult,
    ClearAdjustmentFeedbackIntent, ClearCandidatesIntent, CloseEditorIntent,
    OpenHelpIntent, OpenDictionaryIntent, SaveToDictionaryIntent,
    QuitIntent, PreviewIntent, QueryApplicationResult, PronunciationRow,
    ReplaceQueryIntent, SettingsApplicationResult, TuiEditorController,
    UpdateStatusIntent,
)
from .tui_operations import (
    BatchCandidateReplacedEffect,
    CandidateReplacedEffect,
    DictionaryOperationCompletedEffect,
    DiscardInitialBatchEffect,
    SessionPreparationCompletedEffect,
    FocusEffect,
    GenerationOutcomeEffect,
    OperationEffect,
    PlayPreviewEffect,
    PlayTakeEffect,
    StopPlaybackEffect,
    TakeAcceptedEffect,
    TuiOperations,
    UpdateStatusEffect,
)
from .tui_navigation import NavigationAction, NavigationContext, TuiNavigation
from .tui_output_path import BeginOutputPathEditIntent, TuiOutputPathController
from .tui_input import TuiInputReader
from .tui_interrupts import TuiInterruptController
from .voiceger_adapter import VoicegerAdapter


_ESCAPE = "\x1b"


class TuiApp:
    """Own the curses view and route edits through the reusable session core."""

    def __init__(
        self,
        *,
        adapter: VoicegerAdapter,
        settings: Settings,
        persisted_settings: Settings | None = None,
        config_path: str | os.PathLike[str] | None = None,
        source_text: str | None = None,
    ) -> None:
        self.adapter = adapter
        self.session: UtteranceSession | None = None
        self._initial_caption = source_text
        self._batch = tui_batch.TuiBatchController(
            default_take_count=settings.take_count
        )
        self._screen: Any = None
        self._operations = TuiOperations()
        self._navigation = TuiNavigation()
        self._exit_requested = False
        self._status = EMPTY_STATUS
        self._settings_controller = TuiSettingsController(
            settings=settings,
            persisted_settings=persisted_settings,
            config_path=config_path,
            operations=self._operations,
            sessions=lambda: self._batch.sessions,
            active_session=lambda: self.session,
            set_batch_take_count=lambda count: setattr(
                self._batch.batch, "default_take_count", count
            ),
            set_status=lambda status: setattr(self, "_status", status),
            save=lambda value, path: save_settings(value, path),
            clear_generation_outcomes=self._batch.clear_generation_outcomes,
        )
        self._output_path_controller = TuiOutputPathController(
            get_output_dir=lambda: self.settings.output_dir,
            save_output_dir=lambda value: self._settings_controller.change(
                output_dir=value
            ),
            set_status=lambda status: setattr(self, "_status", status),
        )
        self._help_controller = TuiHelpController()
        self._editor_controller = TuiEditorController(
            english_word_groups=self.adapter.english_word_phoneme_groups,
            available_styles=lambda: available_styles(self.adapter.voiceger_root),
            input_prefix=_active_input_prefix,
        )
        self._dictionary_controller = TuiDictionaryController(
            self.adapter.user_dictionary,
            input_prefix=_active_input_prefix,
            japanese_pronunciation=self.adapter.japanese_dictionary_pronunciation,
            english_word_groups=self.adapter.english_word_phoneme_groups,
            output_dir=lambda: self.settings.output_dir,
        )
        self._batch_recipe_controller = TuiBatchRecipeController(
            adapter=self.adapter,
            runtime_settings=lambda: self.settings,
            current_batch=lambda: self._batch.batch,
            replace_batch=self._batch.replace_batch,
            output_dir=lambda: self.settings.output_dir,
            input_prefix=_active_input_prefix,
        )
        self._pressed_adjustment: tuple[str, str, int] | None = None
        self._renderer = TuiRenderer()
        self._input = TuiInputReader()
        self._interrupt_controller = TuiInterruptController()
        self._batch_item_controller = TuiBatchItemController(self._batch)
        self._batch_action_bindings = tui_batch.BatchActionBindings(
            operations=self._operations,
            navigation=self._navigation,
            editor_controller=self._editor_controller,
            dictionary_controller=self._dictionary_controller,
            set_session=lambda session: setattr(self, "session", session),
            set_status=lambda status: setattr(self, "_status", status),
            open_caption_editor=self._open_caption_editor,
            change_settings=self._change_settings,
            open_settings_editor=self._open_settings_editor,
            open_batch_read=self._batch_recipe_controller.open_read,
            open_batch_write=self._batch_recipe_controller.open_write,
            dispatch_editor_intents=self._dispatch_editor_intents,
            dispatch_operation_effects=self._dispatch_operation_effects,
            open_help=self._open_help,
            activate_quit=self._activate_quit,
            initialize_open_item=lambda: self._batch_item_controller.initialize_open_item_focus(
                self._batch_item_bindings
            ),
        )
        self._batch_item_bindings = BatchItemBindings(
            actions=self._batch_action_bindings,
            get_session=lambda: self.session,
            get_settings=lambda: self.settings,
            get_status=lambda: self._status,
        )

    @property
    def settings(self) -> Settings:
        return self._settings_controller.settings

    @settings.setter
    def settings(self, value: Settings) -> None:
        self._settings_controller.settings = value

    @property
    def _persisted_settings(self) -> Settings:
        return self._settings_controller.persisted_settings

    @_persisted_settings.setter
    def _persisted_settings(self, value: Settings) -> None:
        self._settings_controller.persisted_settings = value

    @property
    def config_path(self) -> str | os.PathLike[str] | None:
        return self._settings_controller.config_path

    @config_path.setter
    def config_path(self, value: str | os.PathLike[str] | None) -> None:
        self._settings_controller.config_path = value

    @property
    def _help_open(self) -> bool:
        return self._help_controller.active

    @_help_open.setter
    def _help_open(self, value: bool) -> None:
        self._help_controller.active = value

    @property
    def _help_scroll(self) -> int:
        return self._help_controller.scroll

    @_help_scroll.setter
    def _help_scroll(self, value: int) -> None:
        self._help_controller.scroll = value

    def run(self, screen: Any) -> None:
        self._screen = screen
        self.session = None
        self._batch.close_item()
        try:
            screen.keypad(True)
            curses.set_escdelay(25)
            screen.timeout(100)
            self._renderer.initialize_colors()
            try:
                curses.curs_set(0)
            except curses.error:
                pass

            caption = self._initial_caption
            if caption is not None and caption.strip():
                try:
                    self._batch.add_captions(caption, session_factory=self._new_session)
                except Exception as exc:
                    self._status = error_status(
                        f"Unable to add Caption batch: {exc}"
                    )

            while not self._exit_requested:
                self._consume_events()
                self._render()
                self._operations.start_pending_worker()
                key = self._read_key()
                if key is not None:
                    self._handle_key(key)

            while self._operations.busy:
                self._consume_events()
                if not self._operations.busy:
                    break
                self._render()
                self._operations.start_pending_worker()
                self._read_key()
        finally:
            try:
                self._operations.join_worker()
            finally:
                try:
                    self._operations.stop_playback()
                finally:
                    self._batch_recipe_controller.close()
                    if not self._operations.worker_is_alive():
                        self._batch.close_sessions()

    def _read_key(self) -> Any:
        editor = self._editor_controller.editor
        key = self._input.read(
            self._screen,
            infer_paste_newlines=bool(
                editor is not None
                and editor.kind == "caption"
                and editor.active_field is not None
                and editor.payload.get("multiline", False)
            ),
        )
        if key == -1:
            return None
        if key == _ESCAPE:
            return _ESCAPE
        return key

    def _open_help(self) -> None:
        self._help_controller.open()

    def _mark_adjustment_pressed(self, area: str, control: str, direction: int) -> None:
        self._pressed_adjustment = (
            area,
            control,
            -1 if direction < 0 else 1,
        )

    def _handle_key(self, key: Any) -> None:
        interrupt = self._interrupt_controller.handle_key(key, self._operations)
        if interrupt.handled:
            self._dispatch_operation_effects(interrupt.effects)
            if interrupt.quit_requested:
                self._activate_quit()
            return
        if self._help_controller.active:
            height, width = (
                self._screen.getmaxyx()
                if self._screen is not None
                else (24, 80)
            )
            outcome = self._help_controller.handle_key(
                key,
                height=height,
                max_scroll=self._renderer.help_max_scroll(
                    height,
                    width,
                    self._status,
                ),
            )
            if outcome is HelpOutcome.QUIT:
                self._activate_quit()
            elif outcome is HelpOutcome.CLOSED:
                pass
            return
        if self._output_path_controller.active:
            self._output_path_controller.handle_key(
                key,
                screen_width=(
                    self._screen.getmaxyx()[1] if self._screen is not None else 80
                ),
            )
            return
        if self._batch_recipe_controller.active:
            intents = self._batch_recipe_controller.handle_key(
                key,
                screen_width=(
                    self._screen.getmaxyx()[1] if self._screen is not None else 80
                ),
            )
            self._dispatch_editor_intents(intents)
            return
        if self._dictionary_controller.active:
            intents = self._dictionary_controller.handle_key(
                key,
                screen_width=(
                    self._screen.getmaxyx()[1] if self._screen is not None else 80
                ),
                preview_busy=(
                    self._operations.busy
                    and self._operations.worker_operation == "preview"
                ),
                dictionary_operation_busy=(
                    self._operations.busy
                    and self._operations.worker_operation == "dictionary"
                ),
            )
            self._dispatch_editor_intents(intents)
            return
        if self._editor_controller.editor is not None:
            intents = self._editor_controller.handle_key(
                key,
                settings=self.settings,
                query=(
                    self.session.query
                    if self.session is not None and self.session.is_prepared
                    else None
                ),
                current_caption=(
                    self.session.caption if self.session is not None else None
                ),
                screen_width=(
                    self._screen.getmaxyx()[1] if self._screen is not None else 80
                ),
                preview_busy=(
                    self._operations.busy
                    and self._operations.worker_operation == "preview"
                ),
            )
            self._dispatch_editor_intents(intents)
            return

        if self._batch.delete_confirmation_active or not self._batch.in_item:
            self._batch.dispatch_actions(
                self._batch.handle_key(
                    key,
                    operations=self._operations,
                ),
                self._batch_action_bindings,
            )
            self.session = self.session if self._batch.in_item else None
            return
        self._batch_item_controller.handle_key(
            key,
            self._batch_item_bindings,
        )

    def _navigation_context(self) -> NavigationContext:
        return self._batch_item_controller.navigation_context(
            self._batch_item_bindings
        )

    def _dispatch_navigation_actions(
        self,
        actions: Sequence[NavigationAction],
    ) -> None:
        self._batch_item_controller.dispatch_navigation_actions(
            actions,
            self._batch_item_bindings,
        )

    def _build_pronunciation_from_caption(self) -> str | None:
        return self._batch_item_controller.build_pronunciation_from_caption(
            self._batch_item_bindings
        )

    def _activate_quit(self) -> None:
        self._help_controller.close()
        self._exit_requested = True
        self._dispatch_operation_effects(self._operations.request_shutdown())

    def _new_session(self, caption: str) -> UtteranceSession:
        return UtteranceSession.from_caption(
            adapter=self.adapter, caption=caption, settings=self.settings
        )

    def _segments(self) -> list[tuple[str, str, int | None]]:
        return self._batch_item_controller.segments(self.session)

    def _pronunciation_rows(self) -> tuple[PronunciationRow, ...]:
        return self._batch_item_controller.pronunciation_rows(
            self._batch_item_bindings
        )

    def _open_caption_editor(
        self,
        initial: str | None = None,
        *,
        multiline: bool = False,
    ) -> None:
        intents = self._editor_controller.open_caption(
            initial,
            current_caption=(
                self.session.caption if self.session is not None else None
            ),
            origin=self._navigation.focus_key if self._batch.in_item else self._batch.focus_key,
            busy=self._operations.owns_item(self._batch.open_item_id),
            multiline=multiline,
        )
        self._dispatch_editor_intents(intents)

    def _open_settings_editor(
        self,
        selected_field: str | None = None,
        *,
        edit: bool = False,
        origin: tuple[str, int | None] | None = None,
    ) -> None:
        intents = self._editor_controller.open_settings(
            self.settings,
            origin=(
                origin
                if origin is not None
                else self._navigation.focus_key
                if self._batch.in_item
                else self._batch.focus_key
            ),
            busy=False,
            selected_field=selected_field,
            edit=edit,
        )
        self._dispatch_editor_intents(intents)

    def _edit_selected_pronunciation(self, pronunciation_index: int) -> None:
        self._batch_item_controller.edit_selected_pronunciation(
            pronunciation_index,
            self._batch_item_bindings,
        )

    def _apply_session_query(
        self,
        query: Any,
        *,
        pure_japanese_utterance_text: str | None = None,
    ) -> None:
        if self.session is None:
            return
        self._operations.stop_playback()
        if pure_japanese_utterance_text is None:
            self.session.replace_query(query)
        else:
            self.session.replace_query(
                query,
                pure_japanese_utterance_text=pure_japanese_utterance_text,
            )
        self._operations.clear_current_take()
        self._batch.clear_open_item_generation_outcome()

    def _apply_caption(self, caption: str) -> CaptionApplicationResult:
        if not self._batch.in_item:
            before_count = len(self._batch.batch)
            try:
                self._batch.add_captions(
                    caption,
                    session_factory=self._new_session,
                )
            except Exception as exc:
                return CaptionApplicationResult(error=str(exc))
            added_count = len(self._batch.batch) - before_count
            if added_count == 0:
                return CaptionApplicationResult(error="caption must not be empty")
            return CaptionApplicationResult(added_caption_count=added_count)
        if self.session is not None and caption == self.session.caption:
            return CaptionApplicationResult(unchanged=True)
        if self.session is not None:
            try:
                self.session.replace_caption(caption)
            except Exception as exc:
                return CaptionApplicationResult(error=str(exc))
        else:
            try:
                self.session = self._new_session(caption)
            except Exception as exc:
                return CaptionApplicationResult(error=str(exc))
            self._navigation.reset_pronunciation_index()
            return CaptionApplicationResult(initial_session_created=True)
        return CaptionApplicationResult()

    def _dispatch_editor_intents(
        self,
        intents: Sequence[DictionaryControllerIntent],
    ) -> None:
        pending = list(intents)
        while pending:
            intent = pending.pop(0)
            if isinstance(intent, UpdateStatusIntent):
                self._status = intent.status
            elif isinstance(intent, ClearAdjustmentFeedbackIntent):
                self._pressed_adjustment = None
            elif isinstance(intent, AdjustmentPressedIntent):
                self._mark_adjustment_pressed(
                    intent.area, intent.control, intent.direction
                )
            elif isinstance(intent, OpenHelpIntent):
                self._open_help()
            elif isinstance(intent, OpenDictionaryIntent):
                pending[0:0] = self._dictionary_controller.open_menu()
            elif isinstance(intent, SaveToDictionaryIntent):
                if intent.language == "ja":
                    pending[0:0] = self._dictionary_controller.open_quick_save_japanese(
                        surface=intent.surface,
                        pronunciation=intent.pronunciation,
                    )
                else:
                    pending[0:0] = self._dictionary_controller.open_quick_save_english(
                        surface=intent.surface,
                        phonemes=intent.pronunciation,
                    )
            elif isinstance(intent, BeginOutputPathEditIntent):
                self._output_path_controller.begin(intent.owner)
            elif isinstance(intent, DictionaryOperationIntent):
                self._dispatch_operation_effects(
                    self._operations.start_dictionary_operation(intent)
                )
            elif isinstance(intent, QuitIntent):
                self._activate_quit()
            elif isinstance(intent, ClearCandidatesIntent):
                conflict = self._operations.item_mutation_conflict_status(
                    self._batch.batch,
                    self._batch.open_item_id,
                    action="clearing candidates",
                )
                if conflict is not None:
                    self._status = conflict
                else:
                    self._operations.stop_playback()
                    if self.session is not None:
                        self.session.discard_takes()
                    self._batch.clear_open_item_acceptance()
                    self._batch.clear_open_item_generation_outcome()
                    self._operations.clear_current_take()
            elif isinstance(intent, CloseEditorIntent):
                self._pressed_adjustment = None
                if self._batch.in_item:
                    self._dispatch_navigation_actions(
                        self._navigation.set_focus_key(
                            self._navigation_context(), intent.origin
                        )
                    )
                else:
                    self._batch.focus_key = intent.origin
                self._status = intent.status
            elif isinstance(intent, ReplaceQueryIntent):
                try:
                    self._apply_session_query(
                        intent.query,
                        pure_japanese_utterance_text=(
                            intent.pure_japanese_utterance_text
                        ),
                    )
                except Exception as exc:
                    result = QueryApplicationResult(error=str(exc))
                else:
                    result = QueryApplicationResult()
                pending[0:0] = self._editor_controller.complete_query_application(
                    intent, result
                )
            elif isinstance(intent, PreviewIntent):
                self._dispatch_operation_effects(
                    self._operations.start_preview(
                        self.session,
                        intent.query,
                        adapter=self.adapter,
                        settings=self.settings,
                    )
                )
            elif isinstance(intent, ApplyCaptionIntent):
                result = self._apply_caption(intent.caption)
                pending[0:0] = self._editor_controller.complete_caption_application(
                    result
                )
            elif isinstance(intent, BuildPronunciationIntent):
                error = self._build_pronunciation_from_caption()
                pending[0:0] = self._editor_controller.complete_build_confirmation(
                    BuildPronunciationResult(error=error)
                )
            elif isinstance(intent, ApplySettingsIntent):
                result = self._apply_settings_target(intent.settings)
                pending[0:0] = self._editor_controller.complete_settings_application(
                    result
                )

    def _change_settings(self, *, report_success: bool = True, **changes: Any) -> None:
        self._settings_controller.change(
            report_success=report_success,
            **changes,
        )

    def _apply_settings_target(self, target: Settings) -> SettingsApplicationResult:
        return self._settings_controller.apply_target(target)

    def _consume_events(self) -> None:
        effects = self._operations.consume_pending_events(
            self.session,
            navigation_revision=self._navigation.revision,
            pronunciation_index=self._navigation.pronunciation_index,
            exit_requested=self._exit_requested,
            batch=self._batch.batch,
        )
        self._dispatch_operation_effects(effects)

    def _dispatch_operation_effects(
        self,
        effects: Sequence[OperationEffect],
    ) -> None:
        for effect in effects:
            if isinstance(effect, UpdateStatusEffect):
                if effect.channel != "background":
                    self._status = effect.status
            elif isinstance(effect, FocusEffect):
                self._dispatch_navigation_actions(
                    self._navigation.set_focus_key(
                        self._navigation_context(), effect.focus_key
                    )
                )
            elif isinstance(effect, PlayTakeEffect):
                self._dispatch_operation_effects(
                    self._operations.play_take(self.session, effect.number)
                )
            elif isinstance(effect, PlayPreviewEffect):
                self._dispatch_operation_effects(
                    self._operations.play_preview(
                        effect.audio,
                        effect.sampling_rate,
                    )
                )
            elif isinstance(effect, StopPlaybackEffect):
                self._operations.stop_playback()
            elif isinstance(effect, DiscardInitialBatchEffect):
                if effect.item_id is not None:
                    self._batch.discard_item_candidates(effect.item_id)
                else:
                    if self.session is not None:
                        self.session.discard_takes()
                    self._batch.clear_open_item_acceptance()
                    self._batch.clear_open_item_generation_outcome()
            elif isinstance(effect, TakeAcceptedEffect):
                self._batch.complete_acceptance(effect.item_id, effect.number)
            elif isinstance(effect, GenerationOutcomeEffect):
                self._batch.set_item_generation_outcome(
                    effect.item_id,
                    effect.outcome,
                )
            elif isinstance(effect, DictionaryOperationCompletedEffect):
                self._dispatch_editor_intents(
                    self._dictionary_controller.complete_operation(
                        effect.request,
                        effect.value,
                        effect.error,
                    )
                )
            elif isinstance(effect, SessionPreparationCompletedEffect):
                self._batch_item_controller.complete_preparation(
                    effect.session,
                    rebuild=effect.rebuild,
                    error=effect.error,
                    bindings=self._batch_item_bindings,
                )
            elif isinstance(effect, BatchCandidateReplacedEffect):
                self._batch.invalidate_acceptance_for_replacement(
                    effect.item_id,
                    effect.number,
                )
            elif isinstance(effect, CandidateReplacedEffect):
                if effect.item_id is not None:
                    self._batch.invalidate_acceptance_for_replacement(
                        effect.item_id,
                        effect.number,
                    )
                elif self._batch.open_item_accepted_take_number == effect.number:
                    self._batch.clear_open_item_acceptance()

    def _render_state(
        self,
        *,
        segments: Sequence[tuple[str, str, int | None]] | None = None,
        status: Status | None = None,
    ) -> TuiRenderState:
        if segments is None:
            segments = self._segments() if self.session is not None else ()
        pronunciation_rows = self._pronunciation_rows() if self.session is not None else ()
        return TuiRenderState(
            voiceger_root=self.adapter.voiceger_root,
            settings=self.settings,
            session=self.session,
            focus_key=self._navigation.focus_key,
            status=self._status if status is None else status,
            segments=segments,
            pronunciation_rows=pronunciation_rows,
            busy=self._operations.busy,
            worker_operation=self._operations.worker_operation,
            worker_target=self._operations.worker_target,
            operation_completed=self._operations.operation_completed,
            operation_total=self._operations.operation_total,
            pressed_adjustment=self._pressed_adjustment,
            editor=(
                self._batch_recipe_controller.editor
                if self._batch_recipe_controller.active
                else self._dictionary_controller.editor
                if self._dictionary_controller.active
                else self._editor_controller.editor
            ),
            accepted_take_number=self._batch.open_item_accepted_take_number,
            batch_item_position=(
                self._batch.item_position if self._batch.in_item else None
            ),
            batch_item_id=self._batch.open_item_id,
            active_generation_item_id=self._operations.active_generation_item_id,
            background_status=format_background_operation_progress(
                self._operations.background_operation_progress,
                self._batch.batch,
                self._operations.can_cancel_batch,
            ),
            output_path_edit=self._output_path_controller.state,
        )

    def _render(self) -> None:
        if self._screen is None:
            return
        screen = self._screen
        height, width = screen.getmaxyx()
        render_status = self._status
        background_status = format_background_operation_progress(
            self._operations.background_operation_progress,
            self._batch.batch,
            self._operations.can_cancel_batch,
        )
        screen.erase()
        try:
            editor = (
                self._batch_recipe_controller.editor
                if self._batch_recipe_controller.active
                else self._dictionary_controller.editor
                if self._dictionary_controller.active
                else self._editor_controller.editor
            )
            curses.curs_set(
                0
                if self._help_controller.active
                else 1
                if self._output_path_controller.active
                or (editor and editor.active_field)
                else 0
            )
        except curses.error:
            pass
        if self._help_controller.active:
            self._help_controller.clamp_scroll(
                self._renderer.help_max_scroll(
                    height,
                    width,
                    render_status,
                    background_status,
                )
            )
            self._renderer.render_help(
                screen,
                width,
                self._help_controller.scroll,
                status=render_status,
                background_status=background_status,
            )
        elif (
            self._batch_recipe_controller.active
            or self._dictionary_controller.active
            or self._editor_controller.editor is not None
        ):
            self._renderer.render_editor(
                screen,
                self._render_state(segments=(), status=render_status),
                height,
                width,
            )
        elif self._batch.delete_confirmation_active or not self._batch.in_item:
            self._renderer.render_batch_list(
                screen,
                self._batch.batch,
                self._batch.focus_key,
                render_status,
                height,
                width,
                delete_confirmation_caption=self._batch.delete_confirmation_caption,
                delete_confirmation_selection=self._batch.delete_confirmation_selection,
                pressed_adjustment=self._pressed_adjustment,
                active_generation=self._operations.active_item_generation_progress,
                generation_busy=self._operations.generation_slot_busy,
                background_status=background_status,
            )
        else:
            self._dispatch_navigation_actions(
                self._navigation.set_focus_key(
                    self._navigation_context(), self._navigation.focus_key
                )
            )
            self._renderer.render_navigation(
                screen,
                self._render_state(status=render_status),
                height,
                width,
                title=self._batch.item_title,
            )
        screen.refresh()
        self._pressed_adjustment = None

def main(argv: Sequence[str] | None = None) -> int:
    from .entrypoint import main as run
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
