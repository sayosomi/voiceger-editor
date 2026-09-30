"""Keyboard-first terminal interface for local Voiceger synthesis."""

from __future__ import annotations

import curses
from dataclasses import replace
import os
import sys
from typing import Any, Sequence

from .session import UtteranceSession
from .settings import Settings, SettingsError, load_settings, save_settings
from .styles import available_styles
from .takes import cleanup_stale_take_directories
from .tui_cli import build_argument_parser, settings_for_invocation
from .tui_display import _adjustable_value, format_english_phonemes
from .tui_dictionary import TuiDictionaryController
from .tui_rendering import (
    TuiRenderer,
    TuiRenderState,
    _HELP_ITEMS,
    _active_input_prefix,
)
from .tui_editors import (
    AdjustmentPressedIntent,
    ApplyCaptionIntent,
    ApplySettingsIntent,
    BuildPronunciationIntent,
    BuildPronunciationResult,
    CaptionApplicationResult,
    ClearAdjustmentFeedbackIntent,
    ClearCandidatesIntent,
    CloseEditorIntent,
    EditorIntent,
    OpenHelpIntent,
    OpenDictionaryIntent,
    SaveToDictionaryIntent,
    QuitIntent,
    PreviewIntent,
    QueryApplicationResult,
    PronunciationRow,
    ReplaceQueryIntent,
    SettingsApplicationResult,
    TuiEditorController,
    UpdateStatusIntent,
)
from .tui_operations import (
    DiscardInitialBatchEffect,
    FocusEffect,
    OperationEffect,
    PlayPreviewEffect,
    PlayTakeEffect,
    StopPlaybackEffect,
    TuiOperations,
    UpdateStatusEffect,
)
from .tui_shortcuts import resolve_main_shortcut, resolve_shortcut
from .tui_navigation import (
    AcceptCandidate,
    AddSectionEditor,
    BuildPronunciation,
    ClearAdjustmentFeedback,
    EditPronunciationItem,
    NavigationAction,
    NavigationContext,
    OpenClearCandidatesConfirmation,
    OpenHelp,
    OpenDictionary,
    OpenSettingsEditor,
    OpenCaptionEditor,
    PlayCandidate,
    Quit,
    RegenerateAll,
    RegenerateCandidate,
    StartGeneration,
    TuiNavigation,
    UpdateNavigationStatus,
)
from .voiceger_adapter import VoicegerAdapter


_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
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
        self.settings = settings
        self._persisted_settings = persisted_settings or settings
        self.config_path = config_path
        self.session: UtteranceSession | None = None
        self._initial_caption = source_text
        self._screen: Any = None
        self._operations = TuiOperations()
        self._navigation = TuiNavigation()
        self._exit_requested = False
        self._status = ""
        self._help_open = False
        self._editor_controller = TuiEditorController(
            english_word_groups=self.adapter.english_word_phoneme_groups,
            available_styles=lambda: available_styles(self.adapter.voiceger_root),
            input_prefix=_active_input_prefix,
        )
        self._dictionary_controller = TuiDictionaryController(
            self.adapter.user_dictionary,
            input_prefix=_active_input_prefix,
        )
        self._pressed_adjustment: tuple[str, str, int] | None = None
        self._renderer = TuiRenderer()

    def run(self, screen: Any) -> None:
        self._screen = screen
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
            if caption is None or not caption.strip():
                self._dispatch_navigation_actions(
                    self._navigation.set_focus_key(
                        self._navigation_context(),
                        ("caption", None),
                    )
                )
            else:
                try:
                    self.session = UtteranceSession.from_text(
                        adapter=self.adapter,
                        caption=caption,
                        settings=self.settings,
                    )
                    self._status = ""
                except Exception as exc:
                    self._status = f"Error: Unable to prepare utterance: {exc}"
                    self._open_caption_editor(caption)

            while not self._exit_requested:
                self._consume_events()
                self._render()
                key = self._read_key()
                if key is not None:
                    self._handle_key(key)

            while self._operations.busy:
                self._consume_events()
                if not self._operations.busy:
                    break
                self._render()
                self._read_key()
        finally:
            try:
                self._operations.join_worker()
            finally:
                try:
                    self._operations.stop_playback()
                finally:
                    if self.session is not None and (
                        not self._operations.worker_is_alive()
                    ):
                        self.session.close()

    def _read_key(self) -> Any:
        try:
            key = self._screen.get_wch()
        except KeyboardInterrupt:
            self._activate_quit()
            return None
        except curses.error:
            return None
        if key == -1:
            return None
        if key == _ESCAPE:
            return _ESCAPE
        return key

    def _mark_adjustment_pressed(self, area: str, control: str, direction: int) -> None:
        self._pressed_adjustment = (
            area,
            control,
            -1 if direction < 0 else 1,
        )

    def _handle_key(self, key: Any) -> None:
        if key == _ESCAPE and self._operations.can_cancel_batch:
            self._dispatch_operation_effects(self._operations.request_batch_cancellation())
            return
        if self._help_open:
            if key in ("q", "Q", "\x03"):
                self._help_open = False
                self._activate_quit()
                return
            if (
                key in {_ESCAPE, "?", *_ENTER_KEYS}
                or resolve_shortcut("help", key) is not None
            ):
                self._help_open = False
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
            )
            self._dispatch_editor_intents(intents)
            return
        if self._editor_controller.editor is not None:
            intents = self._editor_controller.handle_key(
                key,
                settings=self.settings,
                query=self.session.query if self.session is not None else None,
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

        if key == _ESCAPE:
            actions = self._navigation.escape_candidate(self._navigation_context())
            if actions is None:
                self._operations.stop_playback()
                if self._operations.playback_process is None:
                    self._status = "Playback stopped."
            else:
                self._dispatch_navigation_actions(actions)
            return
        if key in ("Q", "\x03"):
            self._activate_quit()
            return
        main_shortcut = resolve_main_shortcut(key)
        if main_shortcut is not None:
            self._dispatch_navigation_actions(
                self._navigation.activate_item(
                    self._navigation_context(),
                    (main_shortcut.navigation_key, None),
                )
            )
            return
        if key == "\t":
            self._dispatch_navigation_actions(
                self._navigation.move_section(self._navigation_context(), 1)
            )
            return
        backtab = getattr(curses, "KEY_BTAB", None)
        if backtab is not None and key == backtab:
            self._dispatch_navigation_actions(
                self._navigation.move_section(self._navigation_context(), -1)
            )
            return
        if key == "t":
            self._open_caption_editor()
            return
        setting_shortcuts = {
            "v": "speed",
            "n": "take_count",
            "o": "output_dir",
            "x": "save_text",
        }
        if key in setting_shortcuts:
            self._open_settings_editor(setting_shortcuts[key])
            return
        if key in (curses.KEY_LEFT, curses.KEY_RIGHT):
            direction = -1 if key == curses.KEY_LEFT else 1
            if self._navigation.focus_key[0] == "generate":
                self._adjust_take_count(direction)
            elif (
                self._navigation.focus_key[0] == "pronunciation"
                and self._navigation.focus_key[1] is not None
                and self.session is not None
                and not self._operations.busy
            ):
                rows = self._pronunciation_rows()
                index = self._navigation.focus_key[1]
                if 0 <= index < len(rows):
                    self._dispatch_editor_intents(
                        self._editor_controller.adjust_pronunciation(
                            self.session.query,
                            rows[index],
                            direction,
                        )
                    )
            return
        if isinstance(key, str) and len(key) == 1 and key in "123456789":
            self._dispatch_navigation_actions(
                self._navigation.focus_candidate(
                    self._navigation_context(), int(key)
                )
            )
            return
        if key == "r":
            self._dispatch_navigation_actions(
                self._navigation.activate_regenerate_focused(
                    self._navigation_context()
                )
            )
            return
        if key == curses.KEY_UP:
            self._dispatch_navigation_actions(
                self._navigation.move(self._navigation_context(), -1)
            )
        elif key == curses.KEY_DOWN:
            self._dispatch_navigation_actions(
                self._navigation.move(self._navigation_context(), 1)
            )
        elif key == " ":
            if self._navigation.focus_key[0] == "candidate":
                self._dispatch_operation_effects(
                    self._operations.play_take(
                        self.session, self._navigation.focus_key[1]
                    )
                )
        elif key in _ENTER_KEYS:
            self._dispatch_navigation_actions(
                self._navigation.activate_focused_item(self._navigation_context())
            )

    def _navigation_context(self) -> NavigationContext:
        session = self.session
        return NavigationContext(
            has_session=session is not None,
            pronunciation_count=(
                len(self._pronunciation_rows())
                if session is not None
                else 0
            ),
            candidate_numbers=(
                tuple(candidate.number for candidate in session.candidates)
                if session is not None
                else ()
            ),
            busy=self._operations.busy,
            has_active_batch=(
                session.has_active_batch if session is not None else False
            ),
        )

    def _dispatch_navigation_actions(
        self,
        actions: Sequence[NavigationAction],
    ) -> None:
        for action in actions:
            if isinstance(action, ClearAdjustmentFeedback):
                self._pressed_adjustment = None
            elif isinstance(action, UpdateNavigationStatus):
                self._status = action.status
            elif isinstance(action, OpenSettingsEditor):
                self._open_settings_editor(action.selected_field, edit=action.edit)
            elif isinstance(action, OpenCaptionEditor):
                self._open_caption_editor()
            elif isinstance(action, OpenClearCandidatesConfirmation):
                if self._operations.busy:
                    self._status = "Finish or cancel synthesis before clearing candidates."
                elif self.session is not None and self.session.candidates:
                    self._dispatch_editor_intents(
                        self._editor_controller.open_clear_candidates_confirmation(
                            origin=self._navigation.focus_key
                        )
                    )
            elif isinstance(action, EditPronunciationItem):
                self._edit_selected_pronunciation(action.index)
            elif isinstance(action, AddSectionEditor):
                self._dispatch_editor_intents(
                    self._editor_controller.open_add_section(
                        self.session.query if self.session is not None else None,
                        pure_japanese_utterance_text=(
                            self.session.pure_japanese_utterance_text
                            if self.session is not None
                            else None
                        ),
                        origin=self._navigation.focus_key,
                        busy=self._operations.busy,
                    )
                )
            elif isinstance(action, StartGeneration):
                self._dispatch_operation_effects(
                    self._operations.start_generation(
                        self.session,
                        take_count=self.settings.take_count,
                        navigation_revision=self._navigation.revision,
                    )
                )
            elif isinstance(action, RegenerateAll):
                self._dispatch_operation_effects(
                    self._operations.start_regenerate_all(
                        self.session,
                        take_count=(
                            self.session.active_candidate_count
                            if self.session is not None
                            else 0
                        ),
                        navigation_revision=self._navigation.revision,
                    )
                )
            elif isinstance(action, BuildPronunciation):
                self._request_build_pronunciation()
            elif isinstance(action, AcceptCandidate):
                self._dispatch_operation_effects(
                    self._operations.accept_take(
                        self.session,
                        action.number,
                        busy=self._operations.busy,
                        pronunciation_index=self._navigation.pronunciation_index,
                    )
                )
            elif isinstance(action, RegenerateCandidate):
                self._dispatch_operation_effects(
                    self._operations.start_regeneration(
                        self.session,
                        action.number,
                        take_count=self.settings.take_count,
                        navigation_revision=self._navigation.revision,
                    )
                )
            elif isinstance(action, PlayCandidate):
                self._operations.current_take = action.number
                self._dispatch_operation_effects(
                    self._operations.play_take(self.session, action.number)
                )
            elif isinstance(action, OpenDictionary):
                self._dispatch_editor_intents(self._dictionary_controller.open_menu())
            elif isinstance(action, OpenHelp):
                self._help_open = True
            elif isinstance(action, Quit):
                self._activate_quit()

    def _request_build_pronunciation(self) -> None:
        if self.session is None:
            return
        if self.session.utterance_manually_edited:
            self._dispatch_editor_intents(
                self._editor_controller.open_build_confirmation(
                    origin=self._navigation.focus_key
                )
            )
            return
        self._build_pronunciation_from_caption()

    def _build_pronunciation_from_caption(self) -> str | None:
        if self.session is None:
            return "there is no active session"
        try:
            self.session.build_pronunciation_from_caption()
        except Exception as exc:
            self._status = f"Error: Pronunciation was not rebuilt: {exc}"
            return str(exc)
        self._operations.stop_playback()
        self._editor_controller.clear_groupings()
        self._operations.clear_current_take()
        self._dispatch_navigation_actions(
            self._navigation.reset_after_rebuild(self._navigation_context())
        )
        self._status = "Pronunciation rebuilt from Caption."
        return None

    def _adjust_take_count(self, direction: int) -> None:
        if self._operations.busy:
            self._pressed_adjustment = None
            self._status = "Wait for the current synthesis operation to finish."
            return
        count = self.settings.take_count
        updated = min(100, max(1, count + direction))
        if updated == count:
            self._pressed_adjustment = None
            return
        self._mark_adjustment_pressed("navigation", "generate", direction)
        self._change_settings(take_count=updated, report_success=False)
        self._dispatch_navigation_actions(
            self._navigation.set_focus_key(
                self._navigation_context(), ("generate", None)
            )
        )

    def _activate_quit(self) -> None:
        self._exit_requested = True
        self._dispatch_operation_effects(self._operations.request_shutdown())

    def _segments(self) -> list[tuple[str, str, int | None]]:
        if self.session is None:
            return []
        query = self.session.query
        if query.voicegerSegments is None:
            return [
                ("ja", self.session.pure_japanese_utterance_text or "", None)
            ]
        return [
            (segment.language, segment.text, index)
            for index, segment in enumerate(query.voicegerSegments)
        ]

    def _pronunciation_rows(self) -> tuple[PronunciationRow, ...]:
        if self.session is None:
            return ()
        rows = self._editor_controller.pronunciation_rows(
            self.session.query,
            self._segments(),
        )
        if self._editor_controller.grouping_error:
            self._status = self._editor_controller.grouping_error
        elif self._status.startswith("Error: Cannot align English word pronunciation:"):
            self._status = ""
        return rows

    def _open_caption_editor(self, initial: str | None = None) -> None:
        intents = self._editor_controller.open_caption(
            initial,
            current_caption=(
                self.session.caption if self.session is not None else None
            ),
            origin=self._navigation.focus_key,
            busy=self._operations.busy,
        )
        self._dispatch_editor_intents(intents)

    def _open_settings_editor(
        self,
        selected_field: str | None = None,
        *,
        edit: bool = False,
    ) -> None:
        intents = self._editor_controller.open_settings(
            self.settings,
            origin=self._navigation.focus_key,
            busy=self._operations.busy,
            selected_field=selected_field,
            edit=edit,
        )
        self._dispatch_editor_intents(intents)

    def _edit_selected_pronunciation(self, pronunciation_index: int) -> None:
        if self.session is None or self._operations.busy:
            return
        rows = self._pronunciation_rows()
        if not 0 <= pronunciation_index < len(rows):
            return
        self._dispatch_editor_intents(
            self._editor_controller.open_pronunciation_item(
                self.session.query,
                rows,
                pronunciation_index,
                origin=("pronunciation", pronunciation_index),
                busy=self._operations.busy,
            )
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

    def _apply_caption(self, caption: str) -> CaptionApplicationResult:
        if self.session is not None and caption == self.session.caption:
            return CaptionApplicationResult(unchanged=True)
        if self.session is not None:
            try:
                self.session.replace_caption(caption)
            except Exception as exc:
                return CaptionApplicationResult(error=str(exc))
        else:
            try:
                self.session = UtteranceSession.from_text(
                    adapter=self.adapter,
                    caption=caption,
                    settings=self.settings,
                )
            except Exception as exc:
                return CaptionApplicationResult(error=str(exc))
            self._navigation.reset_pronunciation_index()
            return CaptionApplicationResult(initial_session_created=True)
        return CaptionApplicationResult()

    def _dispatch_editor_intents(self, intents: Sequence[EditorIntent]) -> None:
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
                self._help_open = True
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
            elif isinstance(intent, QuitIntent):
                self._activate_quit()
            elif isinstance(intent, ClearCandidatesIntent):
                if self._operations.busy:
                    self._status = "Finish or cancel synthesis before clearing candidates."
                else:
                    self._operations.stop_playback()
                    if self.session is not None:
                        self.session.discard_takes()
                    self._operations.clear_current_take()
            elif isinstance(intent, CloseEditorIntent):
                self._pressed_adjustment = None
                self._dispatch_navigation_actions(
                    self._navigation.set_focus_key(
                        self._navigation_context(), intent.origin
                    )
                )
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
                    self._operations.start_preview(self.session, intent.query)
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
        try:
            updated = replace(self.settings, **changes)
            synthesis_changed = any(
                getattr(updated, name) != getattr(self.settings, name)
                for name in ("style_id", "speed", "top_k", "top_p", "temperature")
            )
            if self.session is not None:
                if synthesis_changed:
                    self._operations.stop_playback()
                self.session.replace_settings(updated)
        except (SettingsError, ValueError) as exc:
            self._status = f"Error: Settings were not changed: {exc}"
            return
        self.settings = updated
        try:
            persisted = replace(self._persisted_settings, **changes)
        except SettingsError as exc:
            self._status = f"Error: Settings changed for this run but were not saved: {exc}"
            return
        self._persisted_settings = persisted
        if synthesis_changed:
            self._operations.clear_current_take()
        try:
            save_settings(persisted, self.config_path)
        except OSError as exc:
            self._status = f"Error: Settings changed for this run but could not be saved: {exc}"
        else:
            if report_success:
                self._status = (
                    "Settings saved. Existing temporary takes were cleared."
                    if synthesis_changed
                    else "Settings saved. Existing temporary takes were preserved."
                )

    def _apply_settings_target(self, target: Settings) -> SettingsApplicationResult:
        baseline = self.session.settings if self.session is not None else self.settings
        runtime_changed = target != self.settings or target != baseline
        synthesis_changed = any(
            getattr(target, name) != getattr(baseline, name)
            for name in ("style_id", "speed", "top_k", "top_p", "temperature")
        )
        if runtime_changed:
            try:
                if synthesis_changed:
                    self._operations.stop_playback()
                if self.session is not None:
                    self.session.replace_settings(target)
            except (SettingsError, ValueError) as exc:
                self._status = f"Error: Settings were not changed: {exc}"
                return SettingsApplicationResult(error_status=self._status)
            self.settings = target
            if synthesis_changed:
                self._operations.clear_current_take()

        try:
            save_settings(target, self.config_path)
        except (OSError, SettingsError) as exc:
            failure = (
                "Settings changed for this run but could not be saved"
                if runtime_changed
                else "Settings could not be saved"
            )
            self._status = f"Error: {failure}: {exc}"
            return SettingsApplicationResult(error_status=self._status)

        self._persisted_settings = target
        self._status = "Settings saved."
        return SettingsApplicationResult()

    def _consume_events(self) -> None:
        effects = self._operations.consume_pending_events(
            self.session,
            navigation_revision=self._navigation.revision,
            pronunciation_index=self._navigation.pronunciation_index,
            exit_requested=self._exit_requested,
        )
        self._dispatch_operation_effects(effects)

    def _dispatch_operation_effects(
        self,
        effects: Sequence[OperationEffect],
    ) -> None:
        for effect in effects:
            if isinstance(effect, UpdateStatusEffect):
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
                if self.session is not None:
                    self.session.discard_takes()

    def _render_state(
        self,
        *,
        segments: Sequence[tuple[str, str, int | None]] | None = None,
    ) -> TuiRenderState:
        if segments is None:
            segments = self._segments() if self.session is not None else ()
        pronunciation_rows = (
            self._pronunciation_rows()
            if self.session is not None
            else ()
        )
        return TuiRenderState(
            voiceger_root=self.adapter.voiceger_root,
            settings=self.settings,
            session=self.session,
            focus_key=self._navigation.focus_key,
            status=self._status,
            segments=segments,
            pronunciation_rows=pronunciation_rows,
            busy=self._operations.busy,
            worker_operation=self._operations.worker_operation,
            worker_target=self._operations.worker_target,
            operation_completed=self._operations.operation_completed,
            operation_total=self._operations.operation_total,
            pressed_adjustment=self._pressed_adjustment,
            editor=self._dictionary_controller.editor if self._dictionary_controller.active else self._editor_controller.editor,
        )

    def _render(self) -> None:
        if self._screen is None:
            return
        screen = self._screen
        height, width = screen.getmaxyx()
        screen.erase()
        try:
            editor = (
                self._dictionary_controller.editor
                if self._dictionary_controller.active
                else self._editor_controller.editor
            )
            curses.curs_set(
                0 if self._help_open else 1 if editor and editor.active_field else 0
            )
        except curses.error:
            pass
        if self._help_open:
            self._renderer.render_help(screen, width)
        elif (
            self._dictionary_controller.active
            or self._editor_controller.editor is not None
        ):
            self._renderer.render_editor(
                screen, self._render_state(segments=()), height, width
            )
        else:
            self._dispatch_navigation_actions(
                self._navigation.set_focus_key(
                    self._navigation_context(), self._navigation.focus_key
                )
            )
            self._renderer.render_navigation(
                screen, self._render_state(), height, width
            )
        screen.refresh()
        self._pressed_adjustment = None



def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    cleanup_stale_take_directories()
    try:
        persisted_settings = load_settings(args.config)
        settings = settings_for_invocation(args, persisted_settings)
    except (SettingsError, ValueError) as exc:
        print(f"Cannot load settings: {exc}", file=sys.stderr)
        return 2
    adapter = VoicegerAdapter(
        voiceger_root=args.voiceger_root,
        output_dir=settings.output_dir,
    )
    app = TuiApp(
        adapter=adapter,
        settings=settings,
        persisted_settings=persisted_settings,
        config_path=args.config,
        source_text=args.text,
    )
    try:
        curses.wrapper(app.run)
    except curses.error as exc:
        print(
            f"The terminal UI could not start: {exc}. Run this command in a real terminal.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
