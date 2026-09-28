"""Keyboard-first terminal interface for local Voiceger synthesis."""

from __future__ import annotations

import argparse
import curses
from dataclasses import replace
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Sequence

from .english_stress import (
    EnglishPhonemeEditorState,
    editor_state_to_english_phonemes,
    english_phonemes_to_editor_state,
    move_primary_stress,
    replace_editor_base_phonemes,
)
from .query_editing import (
    japanese_pronunciation,
    replace_english_phoneme_groups,
    replace_japanese_pronunciation,
)
from .session import UtteranceSession
from .settings import Settings, SettingsError, load_settings, save_settings
from .styles import available_styles
from .tui_display import (
    _adjustable_value,
    _display_width,
    _english_display_tokens,
    _move_wrapped_cursor,
    _phoneme_state_tokens,
    _phonemes_as_ui_tokens,
    _truncate_display,
    _wrap_active_input,
    _wrap_labeled_tokens,
    _wrap_text,
    _wrapped_ranges,
    format_english_phonemes,
)
from .tui_rendering import (
    TuiRenderer,
    TuiRenderState,
    _HELP_ITEMS,
    _active_input_prefix,
)
from .tui_editors import (
    AdjustmentPressedIntent,
    ApplySettingsIntent,
    ClearAdjustmentFeedbackIntent,
    CloseEditorIntent,
    EditorIntent,
    EditorState as _Editor,
    EnglishGroupingCache as _EnglishGroupingCache,
    EnglishWordGroup as _EnglishWordGroup,
    QueryApplicationResult,
    ReplaceQueryIntent,
    ReplaceSourceTextIntent,
    SettingsApplicationResult,
    SourceTextApplicationResult,
    TuiEditorController,
    UpdateStatusIntent,
)
from .tui_operations import (
    DiscardInitialBatchEffect,
    FocusEffect,
    OperationEffect,
    PlayTakeEffect,
    StopPlaybackEffect,
    TuiOperations,
    UpdateStatusEffect,
)
from .tui_navigation import (
    AcceptCandidate,
    ClearAdjustmentFeedback,
    EditPronunciationSegment,
    NavigationAction,
    NavigationContext,
    OpenHelp,
    OpenSettingsEditor,
    OpenTextEditor,
    PlayCandidate,
    Quit,
    RebuildPronunciation,
    RegenerateAll,
    RegenerateCandidate,
    StartGeneration,
    TuiNavigation,
    UpdateNavigationStatus,
)
from .voiceger_adapter import VoicegerAdapter


_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voiceger-accent-adapter",
        description="Keyboard-first local pronunciation editing and take review.",
    )
    parser.add_argument("text", nargs="?", help="one utterance to edit and synthesize")
    parser.add_argument("--voiceger-root", type=Path, help="Voiceger installation path")
    parser.add_argument("--config", type=Path, help="settings file path")
    parser.add_argument("--output-dir", type=Path, help="override output directory")
    parser.add_argument("--take-count", type=int, help="override take count (1–8)")
    parser.add_argument("--style", type=int, help="override reference style ID")
    parser.add_argument("--speed", type=float, help="override speech speed")
    save_group = parser.add_mutually_exclusive_group()
    save_group.add_argument(
        "--save-text", dest="save_text", action="store_true",
        help="save an exact source-text sidecar",
    )
    save_group.add_argument(
        "--no-save-text", dest="save_text", action="store_false",
        help="disable source-text sidecars",
    )
    parser.set_defaults(save_text=None)
    return parser


def settings_for_invocation(args: argparse.Namespace, base: Settings) -> Settings:
    """Apply command-line overrides without writing them to persisted settings."""

    overrides = {
        name: value
        for name, value in (
            ("output_dir", args.output_dir),
            ("take_count", args.take_count),
            ("style_id", args.style),
            ("speed", args.speed),
            ("save_text", args.save_text),
        )
        if value is not None
    }
    return replace(base, **overrides)


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
        self._initial_text = source_text
        self._screen: Any = None
        self._operations = TuiOperations(
            platform=lambda: sys.platform,
            which=lambda name: shutil.which(name),
            popen=lambda *args, **kwargs: subprocess.Popen(*args, **kwargs),
        )
        self._navigation = TuiNavigation()
        self._exit_requested = False
        self._status = "Enter text, edit pronunciation, then press F5 to generate."
        self._help_open = False
        self._editor_controller = TuiEditorController(
            english_word_groups=self.adapter.english_word_phoneme_groups,
            available_styles=lambda: available_styles(self.adapter.voiceger_root),
            input_prefix=_active_input_prefix,
        )
        self._pressed_adjustment: tuple[str, str, int] | None = None
        self._renderer = TuiRenderer()

    @property
    def _editor(self) -> _Editor | None:
        return self._editor_controller.editor

    @_editor.setter
    def _editor(self, editor: _Editor | None) -> None:
        self._editor_controller.editor = editor

    @property
    def _english_groupings(self) -> dict[int, _EnglishGroupingCache]:
        return self._editor_controller.grouping_cache

    @property
    def _focus_key(self) -> tuple[str, int | None]:
        return self._navigation.focus_key

    @_focus_key.setter
    def _focus_key(self, key: tuple[str, int | None]) -> None:
        self._set_focus_key(key)

    @property
    def _segment_index(self) -> int:
        return self._navigation.segment_index

    @_segment_index.setter
    def _segment_index(self, index: int) -> None:
        self._navigation.set_segment_index(index)

    @property
    def _navigation_revision(self) -> int:
        return self._navigation.revision

    @_navigation_revision.setter
    def _navigation_revision(self, revision: int) -> None:
        self._navigation.revision = revision

    @property
    def _events(self) -> Any:
        return self._operations.events

    @_events.setter
    def _events(self, events: Any) -> None:
        self._operations.events = events

    @property
    def _worker(self) -> Any:
        return self._operations.worker

    @_worker.setter
    def _worker(self, worker: Any) -> None:
        self._operations.worker = worker

    @property
    def _worker_operation(self) -> str | None:
        return self._operations.worker_operation

    @_worker_operation.setter
    def _worker_operation(self, operation: str | None) -> None:
        self._operations.worker_operation = operation

    @property
    def _worker_target(self) -> int | None:
        return self._operations.worker_target

    @_worker_target.setter
    def _worker_target(self, target: int | None) -> None:
        self._operations.worker_target = target

    @property
    def _worker_error(self) -> BaseException | None:
        return self._operations.worker_error

    @_worker_error.setter
    def _worker_error(self, error: BaseException | None) -> None:
        self._operations.worker_error = error

    @property
    def _busy(self) -> bool:
        return self._operations.busy

    @_busy.setter
    def _busy(self, busy: bool) -> None:
        self._operations.busy = busy

    @property
    def _operation_focus_revision(self) -> int:
        return self._operations.operation_focus_revision

    @_operation_focus_revision.setter
    def _operation_focus_revision(self, revision: int) -> None:
        self._operations.operation_focus_revision = revision

    @property
    def _operation_completed(self) -> int:
        return self._operations.operation_completed

    @_operation_completed.setter
    def _operation_completed(self, completed: int) -> None:
        self._operations.operation_completed = completed

    @property
    def _operation_total(self) -> int:
        return self._operations.operation_total

    @_operation_total.setter
    def _operation_total(self, total: int) -> None:
        self._operations.operation_total = total

    @property
    def _current_take(self) -> int | None:
        return self._operations.current_take

    @_current_take.setter
    def _current_take(self, number: int | None) -> None:
        self._operations.current_take = number

    @property
    def _player(self) -> Any:
        return self._operations.playback_process

    @_player.setter
    def _player(self, process: Any) -> None:
        self._operations.playback_process = process

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

            source_text = self._initial_text
            if source_text is None:
                self._open_text_editor("")
            elif not source_text.strip():
                self._open_text_editor(source_text)
            else:
                try:
                    self.session = UtteranceSession.from_text(
                        adapter=self.adapter,
                        source_text=source_text,
                        settings=self.settings,
                    )
                    self._status = ""
                except Exception as exc:
                    self._status = f"Error: Unable to prepare utterance: {exc}"
                    self._open_text_editor(source_text)

            while not self._exit_requested:
                self._consume_events()
                self._render()
                key = self._read_key()
                if key is not None:
                    self._handle_key(key)

            while self._busy:
                self._consume_events()
                if not self._busy:
                    break
                self._render()
                self._read_key()
        finally:
            try:
                self._operations.join_worker()
            finally:
                try:
                    self._stop_playback()
                finally:
                    if self.session is not None and (
                        not self._operations.worker_is_alive()
                    ):
                        self.session.close()

    def _read_key(self) -> Any:
        try:
            key = self._screen.get_wch()
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
        if self._editor is not None:
            self._handle_editor_key(key)
            return
        if self._help_open:
            if key in ("q", "Q", "\x03"):
                self._help_open = False
                self._activate_quit()
                return
            if key in {_ESCAPE, "?", *_ENTER_KEYS}:
                self._help_open = False
            return

        if key == _ESCAPE:
            actions = self._navigation.escape_candidate(self._navigation_context())
            if actions is None:
                self._stop_playback()
                self._status = "Playback stopped." if self._player is None else self._status
            else:
                self._dispatch_navigation_actions(actions)
            return
        if key in ("q", "Q", "\x03"):
            self._activate_quit()
            return
        if key == "?":
            self._open_help()
            return
        if key == curses.KEY_F5 or key == "\x07":
            self._activate_generate()
            return
        if key == "\t":
            self._move_navigation_section(1)
            return
        backtab = getattr(curses, "KEY_BTAB", None)
        if backtab is not None and key == backtab:
            self._move_navigation_section(-1)
            return
        if key == "t":
            self._open_text_editor()
            return
        setting_shortcuts = {
            "s": "style_id",
            "v": "speed",
            "n": "take_count",
            "o": "output_dir",
            "x": "save_text",
        }
        if key in setting_shortcuts:
            self._open_settings_editor(setting_shortcuts[key])
            return
        if key in (curses.KEY_LEFT, curses.KEY_RIGHT):
            if self._focus_key[0] == "generate":
                self._adjust_take_count(-1 if key == curses.KEY_LEFT else 1)
            return
        if isinstance(key, str) and len(key) == 1 and key in "12345678":
            self._focus_candidate(int(key))
            return
        if key == "r":
            self._activate_regenerate_focused()
            return
        if key == "R":
            self._activate_generate()
            return
        if key == curses.KEY_UP:
            self._move_navigation(-1)
        elif key == curses.KEY_DOWN:
            self._move_navigation(1)
        elif key == " ":
            if self._focus_key[0] == "candidate":
                self._play_take(self._focus_key[1])
        elif key in _ENTER_KEYS:
            self._activate_focused_item()

    def _navigation_context(self) -> NavigationContext:
        session = self.session
        return NavigationContext(
            has_session=session is not None,
            pronunciation_needs_rebuild=(
                session.pronunciation_needs_rebuild if session is not None else False
            ),
            segment_count=len(self._segments()) if session is not None else 0,
            candidate_numbers=(
                tuple(candidate.number for candidate in session.candidates)
                if session is not None
                else ()
            ),
            busy=self._busy,
            has_active_batch=(
                session.has_active_batch if session is not None else False
            ),
        )

    def _navigation_items(self) -> list[tuple[str, int | None]]:
        return list(self._navigation.navigation_items(self._navigation_context()))

    def _major_navigation_stops(self) -> list[tuple[str, int | None]]:
        return list(
            self._navigation.major_navigation_stops(self._navigation_context())
        )

    def _move_navigation_section(self, delta: int) -> None:
        self._dispatch_navigation_actions(
            self._navigation.move_section(self._navigation_context(), delta)
        )

    def _set_focus_key(
        self,
        key: tuple[str, int | None],
        *,
        moved: bool = False,
    ) -> None:
        self._dispatch_navigation_actions(
            self._navigation.set_focus_key(
                self._navigation_context(),
                key,
                moved=moved,
            )
        )

    def _move_navigation(self, delta: int) -> None:
        self._dispatch_navigation_actions(
            self._navigation.move(self._navigation_context(), delta)
        )

    def _activate_focused_item(self) -> None:
        self._dispatch_navigation_actions(
            self._navigation.activate_focused_item(self._navigation_context())
        )

    def _activate_generate(self) -> None:
        self._dispatch_navigation_actions(
            self._navigation.activate_generate(self._navigation_context())
        )

    def _activate_regenerate_focused(self) -> None:
        self._dispatch_navigation_actions(
            self._navigation.activate_regenerate_focused(self._navigation_context())
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
            elif isinstance(action, OpenTextEditor):
                self._open_text_editor()
            elif isinstance(action, EditPronunciationSegment):
                self._edit_selected_segment(action.index)
            elif isinstance(action, StartGeneration):
                self._start_generation()
            elif isinstance(action, RegenerateAll):
                self._start_regenerate_all()
            elif isinstance(action, RebuildPronunciation):
                self._activate_rebuild_pronunciation()
            elif isinstance(action, AcceptCandidate):
                self._accept_take(action.number)
            elif isinstance(action, RegenerateCandidate):
                self._start_regeneration(action.number)
            elif isinstance(action, PlayCandidate):
                self._current_take = action.number
                self._play_take(action.number)
            elif isinstance(action, OpenHelp):
                self._help_open = True
            elif isinstance(action, Quit):
                self._activate_quit()

    def _activate_rebuild_pronunciation(self) -> None:
        if self.session is None:
            return
        self._stop_playback()
        try:
            self.session.rebuild_pronunciation()
        except Exception as exc:
            self._status = f"Error: Pronunciation was not rebuilt: {exc}"
            return
        self._editor_controller.clear_groupings()
        self._operations.clear_current_take()
        self._dispatch_navigation_actions(
            self._navigation.reset_after_rebuild(self._navigation_context())
        )
        self._status = "Pronunciation rebuilt from the current Text."

    def _adjust_take_count(self, direction: int) -> None:
        if self._busy:
            self._pressed_adjustment = None
            self._status = "Wait for the current synthesis operation to finish."
            return
        self._mark_adjustment_pressed("navigation", "generate", direction)
        count = self.settings.take_count
        updated = min(8, max(1, count + direction))
        if updated == count:
            return
        self._change_settings(take_count=updated, report_success=False)
        self._set_focus_key(("generate", None))

    def _activate_quit(self) -> None:
        self._exit_requested = True
        if self._busy:
            self._status = "Finishing the current sequential synthesis before cleanup…"

    def _open_help(self) -> None:
        self._dispatch_navigation_actions(
            self._navigation.open_help(self._navigation_context())
        )

    def _focus_candidate(self, number: int) -> None:
        self._dispatch_navigation_actions(
            self._navigation.focus_candidate(self._navigation_context(), number)
        )

    def _segments(self) -> list[tuple[str, str, int | None]]:
        if self.session is None or self.session.pronunciation_needs_rebuild:
            return []
        query = self.session.query
        if query.voicegerSegments is None:
            return [("ja", self.session.source_text, None)]
        return [
            (segment.language, segment.text, index)
            for index, segment in enumerate(query.voicegerSegments)
        ]

    def _open_text_editor(self, initial: str | None = None) -> None:
        intents = self._editor_controller.open_text(
            initial,
            current_source=(
                self.session.source_text if self.session is not None else None
            ),
            origin=self._focus_key,
            busy=self._busy,
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
            origin=self._focus_key,
            busy=self._busy,
            selected_field=selected_field,
            edit=edit,
        )
        self._dispatch_editor_intents(intents)

    def _edit_selected_segment(self, segment_index: int | None = None) -> None:
        if self.session is None or self._busy:
            return
        index = self._segment_index if segment_index is None else segment_index
        segments = self._segments()
        if not 0 <= index < len(segments):
            return
        self._navigation.set_segment_index(index)
        self._dispatch_editor_intents(
            self._editor_controller.open_segment(
                self.session.query,
                segments,
                index,
                origin=("segment", index),
                busy=self._busy,
            )
        )

    @staticmethod
    def _first_editable_word_key(
        groups: Sequence[_EnglishWordGroup],
    ) -> str | tuple[str, int | None]:
        return TuiEditorController.first_editable_word_key(groups)

    def _english_grouping(self, segment_index: int) -> _EnglishGroupingCache:
        if self.session is None:
            raise ValueError("English word editing requires a mixed-language segment")
        return self._editor_controller.english_grouping(
            self.session.query,
            segment_index,
        )

    def _apply_session_query(self, query: Any) -> None:
        if self.session is None:
            return
        self._stop_playback()
        self.session.replace_query(query)
        self._current_take = None
        self._editor_controller.reconcile_groupings(query)

    def _handle_editor_key(self, key: Any) -> None:
        screen_width = self._screen.getmaxyx()[1] if self._screen is not None else 80
        intents = self._editor_controller.handle_key(
            key,
            settings=self.settings,
            query=self.session.query if self.session is not None else None,
            current_source=(
                self.session.source_text if self.session is not None else None
            ),
            screen_width=screen_width,
        )
        self._dispatch_editor_intents(intents)

    def _apply_editor(self) -> None:
        self._dispatch_editor_intents(
            self._editor_controller.apply(
                self.settings,
                self.session.query if self.session is not None else None,
                self.session.source_text if self.session is not None else None,
            )
        )

    def _cancel_editor(self) -> None:
        self._dispatch_editor_intents(self._editor_controller.cancel())

    def _apply_source_text(self, source_text: str) -> SourceTextApplicationResult:
        if self.session is not None and source_text == self.session.source_text:
            return SourceTextApplicationResult(unchanged=True)
        if self.session is not None:
            self._stop_playback()
            try:
                self.session.replace_source_text(source_text)
            except Exception as exc:
                return SourceTextApplicationResult(error=str(exc))
            needs_rebuild = self.session.pronunciation_needs_rebuild
        else:
            try:
                self.session = UtteranceSession.from_text(
                    adapter=self.adapter,
                    source_text=source_text,
                    settings=self.settings,
                )
            except Exception as exc:
                return SourceTextApplicationResult(error=str(exc))
            needs_rebuild = False
        self._navigation.reset_segment_index()
        self._current_take = None
        return SourceTextApplicationResult(needs_rebuild=needs_rebuild)

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
            elif isinstance(intent, CloseEditorIntent):
                self._pressed_adjustment = None
                self._set_focus_key(intent.origin)
                self._status = intent.status
            elif isinstance(intent, ReplaceQueryIntent):
                try:
                    self._apply_session_query(intent.query)
                except Exception as exc:
                    result = QueryApplicationResult(error=str(exc))
                else:
                    result = QueryApplicationResult()
                pending[0:0] = self._editor_controller.complete_query_application(
                    intent, result
                )
            elif isinstance(intent, ReplaceSourceTextIntent):
                result = self._apply_source_text(intent.source_text)
                pending[0:0] = self._editor_controller.complete_source_text_application(
                    result
                )
            elif isinstance(intent, ApplySettingsIntent):
                self._change_settings(**intent.changes.as_dict())
                error_status = (
                    self._status if self._status.startswith("Error:") else None
                )
                pending[0:0] = self._editor_controller.complete_settings_application(
                    SettingsApplicationResult(error_status=error_status)
                )

    def _change_settings(self, *, report_success: bool = True, **changes: Any) -> None:
        try:
            updated = replace(self.settings, **changes)
            if self.session is not None:
                self._stop_playback()
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
        self._current_take = None
        try:
            save_settings(persisted, self.config_path)
        except OSError as exc:
            self._status = f"Error: Settings changed for this run but could not be saved: {exc}"
        else:
            if report_success:
                self._status = "Settings saved. Existing temporary takes were cleared."

    def _start_generation(self) -> None:
        self._dispatch_operation_effects(
            self._operations.start_generation(
                self.session,
                take_count=self.settings.take_count,
                navigation_revision=self._navigation_revision,
            )
        )

    def _start_regeneration(self, number: int) -> None:
        self._dispatch_operation_effects(
            self._operations.start_regeneration(
                self.session,
                number,
                take_count=self.settings.take_count,
                navigation_revision=self._navigation_revision,
            )
        )

    def _start_regenerate_all(self) -> None:
        self._dispatch_operation_effects(
            self._operations.start_regenerate_all(
                self.session,
                take_count=self.settings.take_count,
                navigation_revision=self._navigation_revision,
            )
        )

    def _run_in_worker(
        self,
        make_values: Any,
        status: str,
        *,
        operation: str,
        target: int | None = None,
    ) -> None:
        self._dispatch_operation_effects(
            self._operations.run_worker(
                make_values,
                status,
                operation=operation,
                target=target,
                take_count=self.settings.take_count,
                navigation_revision=self._navigation_revision,
            )
        )

    def _consume_events(self) -> None:
        effects = self._operations.consume_pending_events(
            self.session,
            navigation_revision=self._navigation_revision,
            segment_index=self._segment_index,
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
                self._set_focus_key(effect.focus_key)
            elif isinstance(effect, PlayTakeEffect):
                self._play_take(effect.number)
            elif isinstance(effect, StopPlaybackEffect):
                self._stop_playback()
            elif isinstance(effect, DiscardInitialBatchEffect):
                if self.session is not None:
                    self.session.discard_takes()

    def _play_take(self, number: int) -> None:
        self._dispatch_operation_effects(
            self._operations.play_take(self.session, number)
        )

    def _stop_playback(self) -> None:
        self._operations.stop_playback()

    def _accept_take(self, number: int) -> None:
        self._dispatch_operation_effects(
            self._operations.accept_take(
                self.session,
                number,
                busy=self._busy,
                segment_index=self._segment_index,
            )
        )

    def _render_state(
        self,
        *,
        segments: Sequence[tuple[str, str, int | None]] | None = None,
    ) -> TuiRenderState:
        if segments is None:
            segments = self._segments() if self.session is not None else ()
        return TuiRenderState(
            voiceger_root=self.adapter.voiceger_root,
            settings=self.settings,
            session=self.session,
            focus_key=self._focus_key,
            status=self._status,
            segments=segments,
            busy=self._busy,
            worker_operation=self._worker_operation,
            worker_target=self._worker_target,
            operation_completed=self._operation_completed,
            operation_total=self._operation_total,
            pressed_adjustment=self._pressed_adjustment,
            editor=self._editor,
        )

    def _render(self) -> None:
        if self._screen is None:
            return
        screen = self._screen
        height, width = screen.getmaxyx()
        screen.erase()
        try:
            curses.curs_set(1 if self._editor and self._editor.active_field else 0)
        except curses.error:
            pass
        if self._editor is not None:
            self._renderer.render_editor(
                screen, self._render_state(segments=()), height, width
            )
        elif self._help_open:
            self._renderer.render_help(screen, width)
        else:
            self._set_focus_key(self._focus_key)
            self._renderer.render_navigation(
                screen, self._render_state(), height, width
            )
        screen.refresh()
        self._pressed_adjustment = None



def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
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
