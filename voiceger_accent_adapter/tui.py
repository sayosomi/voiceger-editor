"""Keyboard-first terminal interface for local Voiceger synthesis."""

from __future__ import annotations

import argparse
import curses
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
from threading import Thread
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
from .voiceger_adapter import VoicegerAdapter


_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"


@dataclass(frozen=True)
class _EnglishWordGroup:
    """Transient word/token grouping used only by the TUI editor."""

    label: str
    phonemes: tuple[str, ...]
    editable: bool


@dataclass(frozen=True)
class _EnglishGroupingCache:
    source_text: str
    groups: tuple[_EnglishWordGroup, ...]

    @property
    def flattened(self) -> tuple[str, ...]:
        return tuple(phone for group in self.groups for phone in group.phonemes)


@dataclass
class _Editor:
    kind: str
    title: str
    origin: tuple[str, int | None]
    selection: str | tuple[str, int | None]
    payload: dict[str, Any] = field(default_factory=dict)
    active_field: str | None = None
    input_value: str = ""
    input_cursor: int = 0
    input_original: str = ""
    error: str = ""
    scroll: int = 0


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
        self._events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._worker: Thread | None = None
        self._worker_operation: str | None = None
        self._worker_target: int | None = None
        self._worker_error: BaseException | None = None
        self._busy = False
        self._exit_requested = False
        self._focus = "settings_summary"
        self._focus_key: tuple[str, int | None] = ("settings_summary", None)
        self._navigation_revision = 0
        self._operation_focus_revision = 0
        self._operation_completed = 0
        self._operation_total = 0
        self._segment_index = 0
        self._current_take: int | None = None
        self._status = "Enter text, edit pronunciation, then press F5 to generate."
        self._player: subprocess.Popen[Any] | None = None
        self._help_open = False
        self._editor: _Editor | None = None
        self._english_groupings: dict[int, _EnglishGroupingCache] = {}
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
            worker = self._worker
            try:
                if worker is not None and worker.ident is not None:
                    worker.join()
            finally:
                try:
                    self._stop_playback()
                finally:
                    if self.session is not None and (
                        worker is None or not worker.is_alive()
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
            if self._focus_key[0] == "candidate":
                self._set_focus_key(("segment", self._segment_index), moved=True)
                self._status = "Returned to the last pronunciation segment."
            else:
                self._stop_playback()
                self._status = "Playback stopped." if self._player is None else self._status
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

    def _navigation_items(self) -> list[tuple[str, int | None]]:
        items: list[tuple[str, int | None]] = [
            ("settings_summary", None),
            ("output", None),
            ("text", None),
        ]
        if self.session is not None:
            if not self.session.pronunciation_needs_rebuild:
                items.extend(
                    ("segment", index)
                    for index, _item in enumerate(self._segments())
                )
            items.append(("rebuild", None))
            items.append(("generate", None))
            items.extend(
                ("candidate", candidate.number)
                for candidate in self.session.candidates
            )
        items.extend((("settings", None), ("help", None), ("quit", None)))
        return items

    def _major_navigation_stops(self) -> list[tuple[str, int | None]]:
        """Collapse multi-row sections in the visible selectable order."""

        stops: list[tuple[str, int | None]] = []
        previous_section: str | None = None
        for key in self._navigation_items():
            name = key[0]
            if name in {"segment", "candidate"}:
                if name == previous_section:
                    continue
                previous_section = name
            else:
                previous_section = None
            stops.append(key)
        return stops

    def _move_navigation_section(self, delta: int) -> None:
        stops = self._major_navigation_stops()
        if not stops:
            return
        try:
            index = stops.index(self._focus_key)
        except ValueError:
            index = next(
                (
                    position
                    for position, key in enumerate(stops)
                    if key[0] == self._focus_key[0]
                ),
                0,
            )
        target = min(max(index + delta, 0), len(stops) - 1)
        if target == index:
            return
        key = stops[target]
        self._set_focus_key(key, moved=True)
        name, number = key
        if name == "candidate" and number is not None:
            self._current_take = number
            self._play_take(number)

    def _set_focus_key(
        self,
        key: tuple[str, int | None],
        *,
        moved: bool = False,
    ) -> None:
        items = self._navigation_items()
        if key not in items:
            segment_key = ("segment", self._segment_index)
            if segment_key in items:
                key = segment_key
            elif ("rebuild", None) in items:
                key = ("rebuild", None)
            else:
                key = ("text", None)
        if key not in items:
            key = items[0]
        changed = key != self._focus_key
        if changed:
            self._pressed_adjustment = None
        self._focus_key = key
        self._focus = key[0]
        if key[0] == "segment" and key[1] is not None:
            self._segment_index = key[1]
        if moved and changed:
            self._navigation_revision += 1

    def _move_navigation(self, delta: int) -> None:
        items = self._navigation_items()
        if not items:
            return
        try:
            index = items.index(self._focus_key)
        except ValueError:
            index = 0
        target = min(max(index + delta, 0), len(items) - 1)
        if target == index:
            return
        key = items[target]
        self._set_focus_key(key, moved=True)
        name, number = key
        if name == "candidate" and number is not None:
            self._current_take = number
            self._play_take(number)

    def _activate_focused_item(self) -> None:
        name, number = self._focus_key
        if name == "settings_summary":
            self._open_settings_editor("style_id")
        elif name == "output":
            self._open_settings_editor("output_dir", edit=True)
        elif name == "text":
            if self._busy:
                self._status = "Wait for synthesis to finish before editing text."
            else:
                self._open_text_editor()
        elif name == "segment" and number is not None:
            if self._busy:
                self._status = "Wait for synthesis to finish before editing pronunciation."
            else:
                self._edit_selected_segment(number)
        elif name == "generate":
            self._activate_generate()
        elif name == "rebuild":
            self._activate_rebuild_pronunciation()
        elif name == "candidate" and number is not None:
            if self._busy:
                self._status = "Wait for generation to finish before accepting a take."
            else:
                self._accept_take(number)
        elif name == "settings":
            self._open_settings_editor("style_id")
        elif name == "help":
            self._open_help()
        elif name == "quit":
            self._activate_quit()

    def _activate_generate(self) -> None:
        if self._busy:
            self._status = "A sequential take operation is already running."
        elif self.session is not None and self.session.has_active_batch:
            self._start_regenerate_all()
        else:
            self._start_generation()

    def _activate_regenerate_focused(self) -> None:
        if self._busy:
            self._status = "Wait for the current synthesis operation to finish."
        elif self._focus_key[0] != "candidate" or self._focus_key not in self._navigation_items():
            self._status = "Select a candidate before regenerating it."
        else:
            assert self._focus_key[1] is not None
            self._start_regeneration(self._focus_key[1])

    def _activate_rebuild_pronunciation(self) -> None:
        if self._busy:
            self._status = "Wait for the current synthesis operation to finish."
            return
        if self.session is None:
            return
        self._stop_playback()
        try:
            self.session.rebuild_pronunciation()
        except Exception as exc:
            self._status = f"Error: Pronunciation was not rebuilt: {exc}"
            return
        self._english_groupings.clear()
        self._current_take = None
        self._segment_index = 0
        if self._segments():
            self._set_focus_key(("segment", 0), moved=True)
        else:
            self._set_focus_key(("generate", None), moved=True)
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
        self._set_focus_key(("help", None), moved=True)
        self._help_open = True

    def _focus_candidate(self, number: int) -> None:
        key = ("candidate", number)
        if key not in self._navigation_items():
            self._status = f"Take {number} has not been generated yet."
            return
        self._set_focus_key(key, moved=True)
        self._current_take = number
        self._play_take(number)

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
        if self._busy:
            self._status = "Wait for synthesis to finish before editing text."
            return
        self._status = ""
        current = (
            initial
            if initial is not None
            else self.session.source_text if self.session is not None else ""
        )
        editor = _Editor(
            kind="text",
            title="EDIT TEXT",
            origin=self._focus_key,
            selection="draft",
            payload={"draft": current},
        )
        self._editor = editor
        self._begin_editor_field("draft", current)

    def _open_settings_editor(
        self,
        selected_field: str | None = None,
        *,
        edit: bool = False,
    ) -> None:
        if self._busy:
            self._status = "Wait for synthesis to finish before changing settings."
            return
        self._status = ""
        draft = {
            "style_id": str(self.settings.style_id),
            "speed": str(self.settings.speed),
            "take_count": str(self.settings.take_count),
            "output_dir": str(self.settings.output_dir),
            "save_text": self.settings.save_text,
        }
        self._editor = _Editor(
            kind="settings",
            title="EDIT SETTINGS",
            origin=self._focus_key,
            selection=selected_field or "style_id",
            payload={"draft_settings": draft},
        )
        if edit and selected_field is not None:
            self._begin_editor_field(selected_field, str(draft[selected_field]))

    def _edit_selected_segment(self, segment_index: int | None = None) -> None:
        if self.session is None or self._busy:
            return
        index = self._segment_index if segment_index is None else segment_index
        segments = self._segments()
        if not 0 <= index < len(segments):
            return
        language, segment_text, model_index = segments[index]
        self._status = ""
        self._segment_index = index
        origin = ("segment", index)
        if language == "ja":
            try:
                query = self.session.query
                segment_model_index = (
                    model_index if query.voicegerSegments is not None else None
                )
                current = japanese_pronunciation(
                    query,
                    segment_index=segment_model_index,
                )
            except Exception as exc:
                self._status = f"Error: Cannot render Japanese pronunciation: {exc}"
                return
            editor = _Editor(
                kind="japanese",
                title="EDIT JAPANESE PRONUNCIATION",
                origin=origin,
                selection="draft",
                payload={
                    "source_text": segment_text,
                    "draft": current,
                    "segment_index": segment_model_index,
                },
            )
            self._editor = editor
            self._begin_editor_field("draft", current)
            return
        if language == "en" and model_index is not None:
            try:
                grouping = self._english_grouping(model_index)
            except Exception as exc:
                self._status = f"Error: Cannot align English word pronunciation: {exc}"
                return
            self._editor = _Editor(
                kind="english_segment",
                title="EDIT ENGLISH SEGMENT",
                origin=origin,
                selection=self._first_editable_word_key(grouping.groups),
                payload={
                    "segment_index": model_index,
                    "source_text": segment_text,
                    "groups": grouping.groups,
                },
            )
            return
        self._status = f"Error: Pronunciation editing is not available for {language!r}."

    @staticmethod
    def _first_editable_word_key(
        groups: Sequence[_EnglishWordGroup],
    ) -> str | tuple[str, int | None]:
        for index, group in enumerate(groups):
            if group.editable:
                return ("word", index)
        return "apply"

    def _english_grouping(self, segment_index: int) -> _EnglishGroupingCache:
        if self.session is None or self.session.query.voicegerSegments is None:
            raise ValueError("English word editing requires a mixed-language segment")
        if not 0 <= segment_index < len(self.session.query.voicegerSegments):
            raise ValueError("English segment index is out of range")
        segment = self.session.query.voicegerSegments[segment_index]
        if segment.language != "en" or segment.phonemes is None:
            raise ValueError("selected segment is not an editable English segment")
        canonical_flat = tuple(segment.phonemes)
        cached = self._english_groupings.get(segment_index)
        if (
            cached is not None
            and cached.source_text == segment.text
            and cached.flattened == canonical_flat
        ):
            return cached
        self._english_groupings.pop(segment_index, None)

        raw_groups = self.adapter.english_word_phoneme_groups(segment.text)
        groups = tuple(
            _EnglishWordGroup(
                label=label,
                phonemes=tuple(phonemes),
                editable=any(character.isalpha() for character in label),
            )
            for label, phonemes in raw_groups
        )
        grouped_flat = tuple(phone for group in groups for phone in group.phonemes)
        if not groups or grouped_flat != canonical_flat:
            raise ValueError(
                "Voiceger word groups do not exactly match the current English segment"
            )
        cache = _EnglishGroupingCache(segment.text, groups)
        self._english_groupings[segment_index] = cache
        return cache

    def _apply_session_query(self, query: Any) -> None:
        if self.session is None:
            return
        self._stop_playback()
        self.session.replace_query(query)
        self._current_take = None
        segments = query.voicegerSegments or []
        for index, cached in tuple(self._english_groupings.items()):
            if (
                index >= len(segments)
                or segments[index].language != "en"
                or segments[index].text != cached.source_text
                or segments[index].phonemes is None
                or tuple(segments[index].phonemes) != cached.flattened
            ):
                self._english_groupings.pop(index, None)

    def _begin_editor_field(self, name: str, value: str) -> None:
        if self._editor is None:
            return
        self._pressed_adjustment = None
        self._editor.selection = name
        self._editor.active_field = name
        self._editor.input_value = value
        self._editor.input_cursor = len(value)
        self._editor.input_original = value
        self._editor.error = ""

    def _editor_selection_keys(self) -> list[str | tuple[str, int | None]]:
        editor = self._editor
        if editor is None:
            return []
        if editor.kind in {"text", "japanese"}:
            return ["draft"]
        if editor.kind == "settings":
            return [
                "style_id", "speed", "take_count", "output_dir", "save_text", "apply",
            ]
        if editor.kind == "english_segment":
            keys = [
                ("word", index)
                for index, group in enumerate(editor.payload["groups"])
                if group.editable
            ]
            return keys + ["apply", "cancel"]
        if editor.kind == "english_word":
            state: EnglishPhonemeEditorState = editor.payload["draft_state"]
            keys: list[str | tuple[str, int | None]] = ["phonemes"]
            keys.extend(("primary", index) for index, _position in enumerate(
                state.primary_stress_vowel_positions
            ))
            return keys + ["done", "cancel"]
        return []

    def _move_editor_selection(self, delta: int) -> None:
        editor = self._editor
        if editor is None:
            return
        keys = self._editor_selection_keys()
        if not keys:
            return
        try:
            index = keys.index(editor.selection)
        except ValueError:
            index = 0
        target = min(max(index + delta, 0), len(keys) - 1)
        if target != index:
            self._pressed_adjustment = None
            editor.selection = keys[target]
            editor.error = ""

    def _activate_editor_selection(self) -> None:
        editor = self._editor
        if editor is None:
            return
        selected = editor.selection
        if editor.kind in {"text", "japanese"}:
            if selected == "draft":
                self._begin_editor_field("draft", editor.payload["draft"])
        elif editor.kind == "settings":
            if selected == "save_text":
                draft = editor.payload["draft_settings"]
                draft["save_text"] = not draft["save_text"]
            elif selected == "apply":
                self._apply_editor()
            elif isinstance(selected, str):
                value = editor.payload["draft_settings"][selected]
                self._begin_editor_field(selected, str(value))
        elif editor.kind == "english_segment":
            if isinstance(selected, tuple) and selected[0] == "word":
                self._open_word_editor(selected[1])
            elif selected == "apply":
                self._apply_editor()
            elif selected == "cancel":
                self._cancel_editor()
        elif editor.kind == "english_word":
            if selected == "phonemes":
                state = editor.payload["draft_state"]
                self._begin_editor_field("phonemes", " ".join(state.base_phonemes))
            elif isinstance(selected, tuple) and selected[0] == "primary":
                state: EnglishPhonemeEditorState = editor.payload["draft_state"]
                positions = state.primary_stress_vowel_positions
                ordinal = selected[1]
                if ordinal is not None and ordinal < len(positions):
                    source = positions[ordinal]
                    editor.payload["moving_primary"] = True
                    editor.payload["stress_source"] = source
                    editor.payload["stress_destination"] = source
                    editor.error = "Choose a destination vowel with Left/Right, then Enter."
            elif selected == "done":
                self._finish_word_editor()
            elif selected == "cancel":
                self._cancel_word_editor()

    def _handle_editor_key(self, key: Any) -> None:
        editor = self._editor
        if editor is None:
            return
        if editor.active_field is not None:
            if key in _ENTER_KEYS:
                if editor.kind in {"text", "japanese"}:
                    editor.payload["draft"] = editor.input_value
                    self._apply_editor()
                else:
                    self._finish_editor_field()
            elif key == _ESCAPE:
                if editor.kind in {"text", "japanese", "settings"}:
                    self._cancel_editor()
                elif editor.kind == "english_word":
                    self._cancel_word_editor()
                else:
                    editor.input_value = editor.input_original
                    editor.input_cursor = len(editor.input_original)
                    editor.active_field = None
                    editor.error = ""
                    self._status = "Field edit canceled; the editor draft is unchanged."
            elif key == curses.KEY_LEFT:
                editor.input_cursor = max(0, editor.input_cursor - 1)
            elif key == curses.KEY_RIGHT:
                editor.input_cursor = min(len(editor.input_value), editor.input_cursor + 1)
            elif key == curses.KEY_HOME or key == "\x01":
                editor.input_cursor = 0
            elif key == curses.KEY_END or key == "\x05":
                editor.input_cursor = len(editor.input_value)
            elif key == curses.KEY_UP:
                input_width = self._active_input_width(editor)
                editor.input_cursor = _move_wrapped_cursor(
                    editor.input_value,
                    editor.input_cursor,
                    -1,
                    input_width,
                )
            elif key == curses.KEY_DOWN:
                input_width = self._active_input_width(editor)
                editor.input_cursor = _move_wrapped_cursor(
                    editor.input_value,
                    editor.input_cursor,
                    1,
                    input_width,
                )
            elif key in (curses.KEY_BACKSPACE, "\x7f", "\x08"):
                if editor.input_cursor:
                    editor.input_value = (
                        editor.input_value[: editor.input_cursor - 1]
                        + editor.input_value[editor.input_cursor :]
                    )
                    editor.input_cursor -= 1
            elif key == curses.KEY_DC:
                if editor.input_cursor < len(editor.input_value):
                    editor.input_value = (
                        editor.input_value[: editor.input_cursor]
                        + editor.input_value[editor.input_cursor + 1 :]
                    )
            elif isinstance(key, str) and key and all(char.isprintable() for char in key):
                editor.input_value = (
                    editor.input_value[: editor.input_cursor]
                    + key
                    + editor.input_value[editor.input_cursor :]
                )
                editor.input_cursor += len(key)
            return

        if editor.kind == "english_word" and editor.payload.get("moving_primary"):
            if key == curses.KEY_LEFT:
                editor.payload["stress_destination"] = max(
                    0, editor.payload["stress_destination"] - 1
                )
            elif key == curses.KEY_RIGHT:
                state: EnglishPhonemeEditorState = editor.payload["draft_state"]
                editor.payload["stress_destination"] = min(
                    len(state.vowel_stresses) - 1,
                    editor.payload["stress_destination"] + 1,
                )
            elif key in _ENTER_KEYS:
                self._commit_primary_move()
            elif key == _ESCAPE:
                editor.payload.pop("moving_primary", None)
                editor.error = ""
            return

        if editor.kind == "settings" and key in (curses.KEY_LEFT, curses.KEY_RIGHT):
            self._adjust_settings_draft(-1 if key == curses.KEY_LEFT else 1)
            return

        if key == _ESCAPE:
            if editor.kind == "english_word":
                self._cancel_word_editor()
            else:
                self._cancel_editor()
        elif key == curses.KEY_UP:
            self._move_editor_selection(-1)
        elif key == curses.KEY_DOWN:
            self._move_editor_selection(1)
        elif key in _ENTER_KEYS:
            self._activate_editor_selection()

    def _active_input_width(self, editor: _Editor) -> int:
        screen_width = self._screen.getmaxyx()[1] if self._screen else 80
        return max(
            1,
            screen_width - 1 - _display_width(_active_input_prefix(editor)),
        )

    def _finish_editor_field(self) -> None:
        editor = self._editor
        if editor is None or editor.active_field is None:
            return
        name = editor.active_field
        value = editor.input_value
        if editor.kind == "english_word" and name == "phonemes":
            try:
                current = editor.payload["draft_state"]
                updated = replace_editor_base_phonemes(current, value.split())
            except Exception as exc:
                editor.error = f"Error: {exc}"
                return
            editor.payload["draft_state"] = updated
            editor.input_value = " ".join(updated.base_phonemes)
            value = editor.input_value
        elif editor.kind == "settings":
            editor.payload["draft_settings"][name] = value
        else:
            editor.payload[name] = value
        editor.active_field = None
        editor.input_original = value
        editor.input_cursor = len(value)
        editor.error = ""
        if editor.kind == "settings":
            self._status = "Settings field updated; Apply saves the settings draft."
        elif editor.kind == "english_word":
            self._status = "Phonemes updated in the word draft; Done returns it to the segment."
        else:
            self._status = "Draft field updated."

    def _open_word_editor(self, group_index: int | None) -> None:
        parent = self._editor
        if parent is None or group_index is None:
            return
        group: _EnglishWordGroup = parent.payload["groups"][group_index]
        try:
            state = english_phonemes_to_editor_state(group.phonemes)
        except Exception as exc:
            parent.error = f"Error: Cannot edit token {group.label!r}: {exc}"
            return
        self._editor = _Editor(
            kind="english_word",
            title="EDIT ENGLISH WORD",
            origin=parent.origin,
            selection="phonemes",
            payload={
                "parent": parent,
                "group_index": group_index,
                "label": group.label,
                "source_text": parent.payload["source_text"],
                "draft_state": state,
                "moving_primary": False,
            },
        )

    def _commit_primary_move(self) -> None:
        editor = self._editor
        if editor is None:
            return
        state: EnglishPhonemeEditorState = editor.payload["draft_state"]
        source = editor.payload["stress_source"]
        destination = editor.payload["stress_destination"]
        occupied = state.primary_stress_vowel_positions
        if destination in occupied and destination != source:
            editor.error = "Error: That vowel already has primary stress. Choose another vowel."
            return
        if destination != source:
            try:
                state = move_primary_stress(state, source, destination)
            except Exception as exc:
                editor.error = f"Error: Primary stress was not changed: {exc}"
                return
            editor.payload["draft_state"] = state
        editor.payload.pop("moving_primary", None)
        positions = state.primary_stress_vowel_positions
        if destination in positions:
            editor.selection = ("primary", positions.index(destination))
        editor.error = ""
        self._status = "Word stress draft updated."

    def _finish_word_editor(self) -> None:
        editor = self._editor
        if editor is None:
            return
        parent: _Editor = editor.payload["parent"]
        index = editor.payload["group_index"]
        groups = list(parent.payload["groups"])
        old_group = groups[index]
        groups[index] = _EnglishWordGroup(
            old_group.label,
            tuple(editor_state_to_english_phonemes(editor.payload["draft_state"])),
            old_group.editable,
        )
        parent.payload["groups"] = tuple(groups)
        parent.selection = ("word", index)
        parent.error = ""
        self._editor = parent
        self._status = f"{old_group.label} draft updated; Apply changes to commit it."

    def _cancel_word_editor(self) -> None:
        editor = self._editor
        if editor is None:
            return
        parent = editor.payload.get("parent")
        if parent is not None:
            self._editor = parent
            parent.error = ""
            self._status = "Word changes canceled."

    def _apply_editor(self) -> None:
        editor = self._editor
        if editor is None:
            return
        if editor.kind == "text":
            self._apply_text_editor(editor)
        elif editor.kind == "japanese":
            try:
                updated = replace_japanese_pronunciation(
                    self.session.query,
                    editor.payload["draft"],
                    segment_index=editor.payload["segment_index"],
                )
                self._apply_session_query(updated)
            except Exception as exc:
                editor.error = f"Error: Pronunciation was not changed: {exc}"
                return
            self._close_editor("Japanese pronunciation updated; old takes cleared.")
        elif editor.kind == "english_segment":
            index = editor.payload["segment_index"]
            groups = editor.payload["groups"]
            try:
                updated = replace_english_phoneme_groups(
                    self.session.query,
                    segment_index=index,
                    phoneme_groups=tuple(group.phonemes for group in groups),
                )
                self._apply_session_query(updated)
            except Exception as exc:
                editor.error = f"Error: English changes were not applied: {exc}"
                return
            self._english_groupings[index] = _EnglishGroupingCache(
                editor.payload["source_text"], groups
            )
            self._close_editor("English pronunciation updated; old takes cleared.")
        elif editor.kind == "settings":
            self._apply_settings_editor(editor)

    def _apply_text_editor(self, editor: _Editor) -> None:
        source = editor.payload["draft"]
        if self.session is not None and source == self.session.source_text:
            self._close_editor("Source text unchanged.")
            return
        if self.session is not None:
            self._stop_playback()
            try:
                self.session.replace_source_text(source)
            except Exception as exc:
                editor.error = f"Error: Source text was not changed: {exc}"
                return
            needs_rebuild = self.session.pronunciation_needs_rebuild
        else:
            try:
                self.session = UtteranceSession.from_text(
                    adapter=self.adapter,
                    source_text=source,
                    settings=self.settings,
                )
            except Exception as exc:
                editor.error = f"Error: Source text was not changed: {exc}"
                return
            needs_rebuild = False
        self._english_groupings.clear()
        self._segment_index = 0
        self._current_take = None
        status = (
            "Source text updated; rebuild pronunciation before generating."
            if needs_rebuild
            else "Source text updated; pronunciation preserved."
        )
        self._close_editor(status)

    def _apply_settings_editor(self, editor: _Editor) -> None:
        draft = editor.payload["draft_settings"]
        try:
            updated = replace(
                self.settings,
                style_id=int(draft["style_id"]),
                speed=float(draft["speed"]),
                take_count=int(draft["take_count"]),
                output_dir=Path(draft["output_dir"]).expanduser(),
                save_text=bool(draft["save_text"]),
            )
        except (TypeError, ValueError, SettingsError) as exc:
            editor.error = f"Error: Settings were not changed: {exc}"
            return
        changes = {
            name: getattr(updated, name)
            for name in ("style_id", "speed", "take_count", "output_dir", "save_text")
            if getattr(updated, name) != getattr(self.settings, name)
        }
        if changes:
            self._change_settings(**changes)
            if self._status.startswith("Error:"):
                editor.error = self._status
                return
            self._close_editor("Settings saved. Existing temporary takes were cleared.")
        else:
            self._close_editor("Settings unchanged.")

    def _close_editor(self, status: str) -> None:
        editor = self._editor
        if editor is None:
            return
        self._pressed_adjustment = None
        self._editor = None
        self._set_focus_key(editor.origin)
        self._status = status

    def _cancel_editor(self) -> None:
        editor = self._editor
        if editor is None:
            return
        status = {
            "text": "Text draft discarded.",
            "japanese": "Japanese pronunciation draft discarded.",
            "settings": "Settings draft discarded.",
            "english_segment": "English segment draft discarded.",
        }.get(editor.kind, "Editor draft discarded.")
        self._close_editor(status)

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
        if self._busy:
            self._status = "A sequential take operation is already running."
            return
        if self.session is None:
            return
        if self.session.has_active_batch:
            self._status = "A take batch already exists; use R to regenerate all takes."
            return
        try:
            iterator = self.session.generate_takes()
        except Exception as exc:
            self._status = f"Error: Could not start take generation: {exc}"
            return
        self._current_take = None
        self._run_in_worker(
            lambda: iterator,
            f"Generating 1/{self.settings.take_count}",
            operation="initial",
        )

    def _start_regeneration(self, number: int) -> None:
        if self.session is None:
            return
        self._stop_playback()
        self._current_take = number
        self._run_in_worker(
            lambda: (self.session.regenerate_take(number),),
            f"Regenerating take {number}…",
            operation="regenerate_one",
            target=number,
        )

    def _start_regenerate_all(self) -> None:
        if self.session is None:
            return
        try:
            iterator = self.session.regenerate_all_takes()
        except Exception as exc:
            self._status = f"Error: Could not regenerate all takes: {exc}"
            return
        self._run_in_worker(
            lambda: iterator,
            f"Regenerating 1/{self.settings.take_count}",
            operation="regenerate_all",
        )

    def _run_in_worker(
        self,
        make_values: Any,
        status: str,
        *,
        operation: str,
        target: int | None = None,
    ) -> None:
        self._busy = True
        self._worker_operation = operation
        self._worker_target = target
        self._worker_error = None
        self._status = status
        self._operation_focus_revision = self._navigation_revision
        self._operation_completed = 0
        self._operation_total = 1 if operation == "regenerate_one" else self.settings.take_count

        def work() -> None:
            try:
                with open(os.devnull, "w", encoding="utf-8") as sink:
                    with redirect_stdout(sink), redirect_stderr(sink):
                        for candidate in make_values():
                            self._events.put(("candidate", candidate))
            except BaseException as exc:
                self._events.put(("error", exc))
            finally:
                self._events.put(("done", None))

        self._worker = Thread(target=work, name="voiceger-tui-synthesis", daemon=True)
        self._worker.start()

    def _consume_events(self) -> None:
        while True:
            try:
                kind, value = self._events.get_nowait()
            except queue.Empty:
                return
            if kind == "candidate":
                operation = self._worker_operation
                self._operation_completed += 1
                if operation == "initial":
                    self._status = (
                        f"Generating {min(self._operation_completed + 1, self._operation_total)}"
                        f"/{self._operation_total} · {self._operation_completed} ready"
                    )
                elif operation == "regenerate_all":
                    self._status = (
                        f"Regenerating {min(self._operation_completed + 1, self._operation_total)}"
                        f"/{self._operation_total} · {self._operation_completed} ready"
                    )
                else:
                    self._status = f"Take {value.number} replacement ready."
                if operation == "initial":
                    if (
                        self._operation_completed == 1
                        and self._navigation_revision == self._operation_focus_revision
                    ):
                        self._current_take = value.number
                        self._set_focus_key(("candidate", value.number))
                        self._play_take(value.number)
                elif operation == "regenerate_one":
                    if (
                        value.number == self._worker_target
                        and self._current_take == value.number
                    ):
                        self._play_take(value.number)
                elif operation == "regenerate_all":
                    if value.number == self._current_take:
                        self._play_take(value.number)
            elif kind == "error":
                self._worker_error = value
                self._status = f"Error: Generation failed: {value}"
                if self._worker_operation == "initial":
                    self._stop_playback()
                    if self.session is not None:
                        self.session.discard_takes()
                    self._current_take = None
                    self._set_focus_key(("segment", self._segment_index))
            elif kind == "done":
                operation = self._worker_operation
                self._busy = False
                if self._worker_error is not None:
                    self._status = f"Error: Generation failed: {self._worker_error}"
                elif operation == "initial" and self.session is not None and self.session.candidates:
                    self._status = f"{len(self.session.candidates)} take(s) ready."
                elif operation in {"regenerate_one", "regenerate_all"}:
                    self._status = "Take regeneration finished."
                elif not self._exit_requested:
                    self._status = "No takes were generated. Select Generate to try again."
                self._worker_operation = None
                self._worker_target = None

    def _play_take(self, number: int) -> None:
        if self.session is None:
            return
        candidate = next(
            (item for item in self.session.candidates if item.number == number),
            None,
        )
        if candidate is None:
            self._status = f"Take {number} is not available yet."
            return
        self._stop_playback()
        try:
            if sys.platform == "darwin":
                player = shutil.which("afplay")
                if player:
                    command = [player, str(candidate.wav_path)]
                else:
                    player = shutil.which("ffplay")
                    command = (
                        [player, "-nodisp", "-autoexit", "-loglevel", "error", str(candidate.wav_path)]
                        if player
                        else None
                    )
            else:
                player = shutil.which("ffplay")
                command = (
                    [player, "-nodisp", "-autoexit", "-loglevel", "error", str(candidate.wav_path)]
                    if player
                    else None
                )
            if command is None:
                self._status = "Error: Playback needs afplay (macOS) or ffplay (other systems)."
                return
            self._player = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._current_take = number
            self._status = f"Playing take {number}."
        except OSError as exc:
            self._status = f"Error: Could not play take {number}: {exc}"

    def _stop_playback(self) -> None:
        process = self._player
        self._player = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _accept_take(self, number: int) -> None:
        if self.session is None or self._busy:
            return
        self._stop_playback()
        try:
            saved = self.session.accept_take(number)
        except Exception as exc:
            self._status = f"Error: Could not save take {number}: {exc}"
            return
        self._current_take = None
        self._set_focus_key(("segment", self._segment_index))
        sidecar = f" and {saved.text_path.name}" if saved.text_path else ""
        self._status = f"Saved {saved.wav_path.name}{sidecar}."

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

    def _adjust_settings_draft(self, direction: int) -> None:
        editor = self._editor
        if editor is None or editor.kind != "settings" or editor.active_field is not None:
            return
        draft = editor.payload["draft_settings"]
        selected = editor.selection
        if selected in {"style_id", "speed", "take_count", "save_text"}:
            self._mark_adjustment_pressed("settings", selected, direction)
        else:
            return
        if selected == "style_id":
            styles = available_styles(self.adapter.voiceger_root)
            if not styles:
                editor.error = "Error: No available styles can be selected."
                return
            try:
                current_id = int(draft["style_id"])
            except (TypeError, ValueError):
                editor.error = "Error: Style ID must be a positive integer."
                return
            index = next(
                (i for i, style in enumerate(styles) if style.id == current_id),
                None,
            )
            if index is None:
                choices = [
                    style for style in styles
                    if (style.id > current_id if direction > 0 else style.id < current_id)
                ]
                if not choices:
                    return
                draft["style_id"] = str(choices[0 if direction > 0 else -1].id)
            else:
                target = index + direction
                if not 0 <= target < len(styles):
                    return
                draft["style_id"] = str(styles[target].id)
        elif selected == "speed":
            try:
                current = Decimal(str(draft["speed"]))
                if not current.is_finite() or current <= 0:
                    raise InvalidOperation
                current = current.quantize(Decimal("0.01"))
                updated = current + Decimal("0.01") * direction
                updated = max(Decimal("0.01"), updated)
            except (InvalidOperation, ValueError):
                editor.error = "Error: Speed must be a positive finite number."
                return
            draft["speed"] = f"{updated:.2f}"
        elif selected == "take_count":
            try:
                current = int(draft["take_count"])
            except (TypeError, ValueError):
                editor.error = "Error: Take count must be an integer from 1 through 8."
                return
            draft["take_count"] = str(min(8, max(1, current + direction)))
        elif selected == "save_text":
            draft["save_text"] = direction > 0
        else:
            return
        editor.error = ""


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
