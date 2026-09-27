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
import unicodedata
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
from .voiceger_adapter import VoicegerAdapter


_VOWELS = frozenset(
    {
        "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY",
        "IH", "IY", "OW", "OY", "UH", "UW",
    }
)
_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"
_HELP_ITEMS = (
    "Up/Down: move through every action in order",
    "Enter: edit, open, generate, regenerate, or accept the focused action",
    "Left/Right on Generate: decrease/increase take count",
    "Left/Right in Settings: adjust the selected value",
    "Space: replay a focused candidate",
    "Esc: return from candidate review; cancel editor draft",
    "Tab: move down one action",
    "F5 / Ctrl+G: activate Generate / Regenerate all",
    "1-8: focus and play an available candidate",
    "r: regenerate the focused candidate",
    "R: activate Generate / Regenerate all",
    "t: edit Text",
    "s / v / n / o / x: open Settings at style / speed / takes / output / TXT",
    "Rebuild pronunciation: rerun automatic pronunciation from current Text",
    "?: open Help",
    "q: Quit",
)


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


def format_english_phonemes(
    phonemes: Sequence[str],
    *,
    selected_primary: int | None = None,
) -> str:
    """Render stress-free ARPAbet, marking primary-stress anchors visually."""

    state = english_phonemes_to_editor_state(phonemes)
    result: list[str] = []
    vowel_position = 0
    for token in state.base_phonemes:
        if token in _VOWELS:
            stress = state.vowel_stresses[vowel_position]
            selected = vowel_position == selected_primary
            if selected:
                rendered = f"▶[{token}]"
            elif stress == 1:
                rendered = f"[{token}]"
            else:
                rendered = token
            result.append(rendered)
            vowel_position += 1
        else:
            result.append(token)
    return " ".join(result)


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
        self._color_attr = 0

    def run(self, screen: Any) -> None:
        self._screen = screen
        try:
            screen.keypad(True)
            curses.set_escdelay(25)
            screen.timeout(100)
            self._initialize_colors()
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

    def _initialize_colors(self) -> None:
        """Set up optional theme-default colors; attributes remain the main cue."""

        self._color_attr = 0
        try:
            if not curses.has_colors():
                return
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            self._color_attr = curses.color_pair(1)
        except (AttributeError, curses.error):
            self._color_attr = 0

    @staticmethod
    def _attribute(name: str) -> int:
        return int(getattr(curses, name, 0))

    def _focus_attribute(self) -> int:
        return (
            self._attribute("A_REVERSE")
            | self._attribute("A_BOLD")
            | self._color_attr
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
            self._move_navigation(1)
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
        items.extend((("help", None), ("quit", None)))
        return items

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
            self._status = "Wait for the current synthesis operation to finish."
            return
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

    def _active_input_prefix(self, editor: _Editor) -> str:
        if editor.kind == "text":
            return "▶ Input: "
        if editor.kind == "japanese":
            return "▶ Pronunciation input: "
        if editor.kind == "english_word":
            return "▶ Phonemes input: "
        if editor.kind == "settings":
            labels = {
                "style_id": "Style",
                "speed": "Speed",
                "take_count": "Take count",
                "output_dir": "Output directory",
            }
            label = labels.get(editor.active_field or "", "Setting")
            return f"▶ {label} input: "
        return "▶ Input: "

    def _active_input_width(self, editor: _Editor) -> int:
        screen_width = self._screen.getmaxyx()[1] if self._screen else 80
        return max(
            1,
            screen_width - 1 - _display_width(self._active_input_prefix(editor)),
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

    def _render_help(self, width: int) -> None:
        self._safe_add(0, 0, "HELP", width, self._attribute("A_BOLD"))
        self._safe_add(1, 0, "Navigation and action shortcuts", width)
        for index, item in enumerate(_HELP_ITEMS):
            self._safe_add(2 + index, 1, item, width)
        self._safe_add(
            max(0, self._screen.getmaxyx()[0] - 2),
            0,
            "Esc / Enter / ? Return to Navigation  |  q Quit",
            width,
            self._attribute("A_BOLD"),
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
            self._render_editor(height, width)
        elif self._help_open:
            self._render_help(width)
        else:
            self._render_navigation(height, width)
        screen.refresh()

    def _render_navigation(self, height: int, width: int) -> None:
        self._set_focus_key(self._focus_key)
        self._safe_add(
            0,
            0,
            "NAVIGATION  Voiceger Accent Adapter",
            width,
            self._attribute("A_BOLD"),
        )
        settings = self.settings
        style_name = next(
            (
                style.name
                for style in available_styles(self.adapter.voiceger_root)
                if style.id == settings.style_id
            ),
            "unavailable",
        )
        text_state = "TXT ON" if settings.save_text else "TXT OFF"
        suffix = f" | {text_state}"
        prefix = (
            f"Style {settings.style_id} {style_name} | Speed {settings.speed:.2f} | "
            f"Takes {settings.take_count}"
        )
        marker = "▶ " if self._focus_key == ("settings_summary", None) else "  "
        prefix_width = max(
            0,
            width - 1 - _display_width(marker) - _display_width(suffix),
        )
        summary = marker + _truncate_display(prefix, prefix_width) + suffix
        summary_attr = (
            self._focus_attribute()
            if self._focus_key == ("settings_summary", None)
            else 0
        )
        output_marker = "▶ " if self._focus_key == ("output", None) else "  "
        output_attr = (
            self._focus_attribute()
            if self._focus_key == ("output", None)
            else 0
        )
        self._safe_add(1, 0, summary, width, summary_attr)
        self._safe_add(
            2,
            0,
            f"{output_marker}Output: {settings.output_dir}",
            width,
            output_attr,
        )

        lines = self._navigation_document(width)
        status_row = max(0, height - 2)
        viewport_height = max(1, status_row - 4)
        focused_index = next(
            (index for index, (_text, key) in enumerate(lines) if key == self._focus_key),
            0,
        )
        start = max(0, focused_index - viewport_height // 3)
        if start + viewport_height > len(lines):
            start = max(0, len(lines) - viewport_height)
        for offset, (line, key) in enumerate(lines[start : start + viewport_height]):
            row = 4 + offset
            attr = self._focus_attribute() if key == self._focus_key else 0
            self._safe_add(row, 0, line, width, attr)

        status = self._status
        if status and not status.startswith("Error:"):
            status = f"Status: {status}"
        status_attr = self._attribute("A_BOLD")
        if status.startswith("Error:"):
            status_attr |= self._attribute("A_REVERSE")
        self._safe_add(status_row, 0, status, width, status_attr)

    def _navigation_document(self, width: int) -> list[tuple[str, tuple[str, int | None] | None]]:
        lines: list[tuple[str, tuple[str, int | None] | None]] = []

        def plain(value: str = "") -> None:
            lines.append((value, None))

        def action(key: tuple[str, int | None], label: str) -> None:
            marker = "▶ " if key == self._focus_key else "  "
            lines.append((marker + label, key))

        def text_action(key: tuple[str, int | None], value: str) -> None:
            marker = "▶ " if key == self._focus_key else "  "
            prefix = f"{marker}Text : "
            available = max(1, width - 1 - _display_width(prefix))
            pieces = _wrap_text(value, available) or [""]
            lines.append((prefix + pieces[0], key))
            continuation = " " * _display_width(prefix)
            lines.extend((continuation + piece, None) for piece in pieces[1:])

        def segment_action(
            key: tuple[str, int | None],
            language: str,
            source: str,
            pronunciation: str,
            *,
            pronunciation_tokens: Sequence[str] | None = None,
        ) -> None:
            marker = "▶ " if key == self._focus_key else "  "
            prefix = f"{marker}{language.upper()} | "
            separator = " | "
            row_limit = max(1, width - 1)
            compact = f"{prefix}{source}{separator}{pronunciation}"
            if _display_width(compact) <= row_limit:
                lines.append((compact, key))
                return

            minimum_token_width = max(
                (_display_width(token) for token in (pronunciation_tokens or ())),
                default=1,
            )
            field_width = (
                row_limit
                - _display_width(prefix)
                - _display_width(separator)
            )
            if field_width < minimum_token_width + 1:
                # Preserve the action on narrow terminals, then show its
                # content on display-only continuation rows.
                continuation_prefix = " " * _display_width(prefix)
                action_source_width = row_limit - _display_width(prefix)
                if action_source_width >= 1:
                    action_source_lines = _wrap_text(source, action_source_width) or [""]
                    lines.append((f"{prefix}{action_source_lines[0]}", key))
                    remaining_source = "".join(action_source_lines[1:])
                else:
                    source_width = max(
                        1, row_limit - _display_width(continuation_prefix)
                    )
                    source_lines = _wrap_text(source, source_width) or [""]
                    lines.append((f"{prefix}{source_lines[0]}", key))
                    remaining_source = "".join(source_lines[1:])
                source_width = max(
                    1, row_limit - _display_width(continuation_prefix)
                )
                source_lines = _wrap_text(remaining_source, source_width)
                lines.extend(
                    (continuation_prefix + piece, None) for piece in source_lines
                )
                pronunciation_prefix = continuation_prefix + " | "
                if pronunciation_tokens is not None:
                    widest_token = max(
                        (_display_width(token) for token in pronunciation_tokens),
                        default=1,
                    )
                    if widest_token > row_limit - _display_width(pronunciation_prefix):
                        pronunciation_prefix = "|"
                pronunciation_width = max(
                    1, row_limit - _display_width(pronunciation_prefix)
                )
                if pronunciation_tokens is None:
                    pronunciation_lines = _wrap_text(
                        pronunciation, pronunciation_width
                    )
                else:
                    pronunciation_lines = _wrap_labeled_tokens(
                        "", pronunciation_tokens, pronunciation_width
                    )
                lines.extend(
                    (pronunciation_prefix + piece, None)
                    for piece in pronunciation_lines
                )
                return

            source_width = min(
                max(1, _display_width(source)),
                max(1, field_width // 2),
                field_width - minimum_token_width,
            )
            pronunciation_width = field_width - source_width
            source_lines = _wrap_text(source, source_width) or [""]
            if pronunciation_tokens is None:
                pronunciation_lines = _wrap_text(
                    pronunciation, pronunciation_width
                )
            else:
                pronunciation_lines = _wrap_labeled_tokens(
                    "", pronunciation_tokens, pronunciation_width
                )

            continuation_prefix = " " * _display_width(prefix)
            line_count = max(len(source_lines), len(pronunciation_lines), 1)
            for index in range(line_count):
                row_prefix = prefix if index == 0 else continuation_prefix
                source_piece = source_lines[index] if index < len(source_lines) else ""
                pronunciation_piece = (
                    pronunciation_lines[index]
                    if index < len(pronunciation_lines)
                    else ""
                )
                padding = " " * max(
                    0, source_width - _display_width(source_piece)
                )
                line = (
                    row_prefix
                    + source_piece
                    + padding
                    + separator
                    + pronunciation_piece
                )
                lines.append((line, key if index == 0 else None))

        text_action(("text", None), self.session.source_text if self.session else "")
        if self.session is not None:
            plain()
            if self.session.pronunciation_needs_rebuild:
                plain("Pronunciation   Rebuild required")
            else:
                plain("Pronunciation")
                for index, (language, source, model_index) in enumerate(self._segments()):
                    if language == "ja":
                        try:
                            query = self.session.query
                            pronunciation = japanese_pronunciation(
                                query,
                                segment_index=(model_index if query.voicegerSegments is not None else None),
                            )
                        except Exception as exc:
                            pronunciation = f"<{exc}>"
                        segment_action(
                            ("segment", index), language, source, pronunciation
                        )
                    elif language == "en" and model_index is not None:
                        try:
                            segment = self.session.query.voicegerSegments[model_index]
                            tokens = _english_display_tokens(segment.phonemes or ())
                        except Exception as exc:
                            tokens = [f"<{exc}>"]
                        segment_action(
                            ("segment", index),
                            language,
                            source,
                            " ".join(tokens),
                            pronunciation_tokens=tokens or ["(none)"],
                        )
                    else:
                        segment_action(
                            ("segment", index), language, source, "Unavailable"
                        )
            action(("rebuild", None), "[ Rebuild pronunciation ]")
            plain()
            has_batch = self.session.has_active_batch
            if self._busy:
                if self._worker_operation == "regenerate_one":
                    generate_label = f"Regenerating take {self._worker_target}"
                else:
                    current = min(
                        self._operation_completed + 1,
                        max(1, self._operation_total),
                    )
                    verb = "Regenerating" if self._worker_operation == "regenerate_all" else "Generating"
                    generate_label = f"{verb} {current}/{self._operation_total}"
            else:
                generate_label = (
                    f"Regenerate all {self.settings.take_count} takes"
                    if has_batch
                    else f"Generate {self.settings.take_count} takes"
                )
            action(("generate", None), f"[ {generate_label} ]")
            plain()
            if not self.session.candidates:
                plain("Candidates   No candidates yet.")
            else:
                plain("Candidates")
            for candidate in self.session.candidates:
                duration = _duration_seconds(candidate.audio, candidate.sampling_rate)
                action(("candidate", candidate.number), f"Take {candidate.number}  {duration:.2f}s")
            plain()

        action(("help", None), "Help")
        action(("quit", None), "Quit")
        return lines

    def _editor_document(
        self,
        width: int,
    ) -> tuple[list[tuple[str, str | tuple[str, int | None] | None]], int | None, int]:
        editor = self._editor
        assert editor is not None
        lines: list[tuple[str, str | tuple[str, int | None] | None]] = []
        cursor_line: int | None = None
        cursor_column = 0

        def plain(value: str = "") -> None:
            lines.append((value, None))

        def wrap(label: str, value: str) -> None:
            prefix = f"{label}"
            available = max(1, width - 1 - _display_width(prefix))
            pieces = _wrap_text(value, available)
            plain(prefix + (pieces[0] if pieces else ""))
            for piece in pieces[1:]:
                plain(" " * _display_width(prefix) + piece)

        def selectable(key: str | tuple[str, int | None], label: str) -> None:
            marker = "▶ " if editor.selection == key else "  "
            lines.append((marker + label, key))

        def token_lines(label: str, tokens: Sequence[str]) -> None:
            for line in _wrap_labeled_tokens(label, tokens, width - 1):
                plain(line)

        def input_field(name: str) -> None:
            nonlocal cursor_line, cursor_column
            prefix = self._active_input_prefix(editor)
            prefix_width = _display_width(prefix)
            input_width = max(1, width - 1 - prefix_width)
            wrapped, cursor_row, cursor_cells = _wrap_active_input(
                editor.input_value,
                editor.input_cursor,
                input_width,
            )
            first_line = len(lines)
            lines.append((prefix + wrapped[0], name))
            continuation = " " * prefix_width
            lines.extend((continuation + value, name) for value in wrapped[1:])
            cursor_line = first_line + cursor_row
            cursor_column = prefix_width + cursor_cells

        plain(editor.title)
        if editor.kind in {"text", "japanese"}:
            plain("Enter applies the draft; Esc cancels this editor.")
        elif editor.kind == "settings":
            plain("Changes stay in this draft until Apply; Esc cancels all settings.")
        elif editor.kind == "english_word":
            plain("Phoneme and stress changes stay here until Done.")
        else:
            plain("Changes stay in this draft until Apply.")
        if editor.kind == "text":
            plain("Context: edit Text; compatible pronunciation is preserved.")
            plain("Rebuild pronunciation is an explicit Navigation action.")
            draft = editor.input_value if editor.active_field == "draft" else editor.payload["draft"]
            wrap("Draft source: ", draft)
            if editor.active_field == "draft":
                input_field("draft")
            else:
                selectable("draft", "Source text field  [Enter: Edit]")
        elif editor.kind == "japanese":
            wrap("Source: ", editor.payload["source_text"])
            draft = editor.input_value if editor.active_field == "draft" else editor.payload["draft"]
            wrap("Draft pronunciation: ", draft)
            if editor.active_field == "draft":
                input_field("draft")
            else:
                selectable("draft", "Pronunciation field  [Enter: Edit]")
            plain("Type ' and / directly; the stored notation is literal.")
        elif editor.kind == "settings":
            plain("Context: current run and persisted output settings.")
            draft = editor.payload["draft_settings"]
            values = (
                ("style_id", "Style", self._setting_display("style_id", draft["style_id"])),
                ("speed", "Speed", str(draft["speed"])),
                ("take_count", "Take count", str(draft["take_count"])),
                ("output_dir", "Output directory", str(draft["output_dir"])),
                ("save_text", "TXT sidecar", "ON" if draft["save_text"] else "OFF"),
            )
            for key, label, value in values:
                if editor.active_field == key:
                    input_field(key)
                else:
                    selectable(key, f"{label}: {value}")
            plain()
            selectable("apply", "Apply and save settings")
        elif editor.kind == "english_segment":
            wrap("Source: ", editor.payload["source_text"])
            plain("Draft word pronunciations:")
            groups: tuple[_EnglishWordGroup, ...] = editor.payload["groups"]
            for index, group in enumerate(groups):
                if not group.editable:
                    tokens = list(group.phonemes) or ["(no phonemes)"]
                    for line in _wrap_labeled_tokens(
                        f"  Fixed context {group.label!r}: ", tokens, width - 1
                    ):
                        plain(line)
                    continue
                key = ("word", index)
                selectable(key, f"Word {group.label!r}  [Enter: Edit]")
                token_lines("    Pronunciation: ", _phonemes_as_ui_tokens(group.phonemes))
            plain()
            selectable("apply", "Apply changes to English segment")
            selectable("cancel", "Cancel and discard segment draft")
        elif editor.kind == "english_word":
            wrap("Source: ", editor.payload["source_text"])
            wrap("Token: ", editor.payload["label"])
            state: EnglishPhonemeEditorState = editor.payload["draft_state"]
            token_lines("Draft pronunciation: ", _phoneme_state_tokens(state))
            if editor.active_field == "phonemes":
                input_field("phonemes")
            else:
                selectable("phonemes", "Phonemes  [Enter: Edit]")
            positions = state.primary_stress_vowel_positions
            vowels = [token for token in state.base_phonemes if token in _VOWELS]
            moving = bool(editor.payload.get("moving_primary"))
            for ordinal, position in enumerate(positions):
                key = ("primary", ordinal)
                label = f"Primary marker {ordinal + 1}: vowel {position + 1} [{vowels[position]}]"
                if moving and editor.selection == key:
                    destination = editor.payload["stress_destination"]
                    label += f" → proposed vowel {destination + 1} [{vowels[destination]}]"
                selectable(key, label)
            if not positions:
                plain("  No primary-stress markers in this word.")
            plain("Secondary stress is retained where the vowel position permits.")
            plain()
            selectable("done", "Done with word changes")
            selectable("cancel", "Cancel word changes")

        if editor.error:
            plain()
            plain(editor.error)
        return lines, cursor_line, cursor_column

    def _setting_display(self, name: str, value: Any) -> str:
        if name == "style_id":
            try:
                style_id = int(value)
            except (TypeError, ValueError):
                return str(value)
            style = next(
                (item for item in available_styles(self.adapter.voiceger_root) if item.id == style_id),
                None,
            )
            return f"{value} {style.name}" if style is not None else str(value)
        return str(value)

    def _adjust_settings_draft(self, direction: int) -> None:
        editor = self._editor
        if editor is None or editor.kind != "settings" or editor.active_field is not None:
            return
        draft = editor.payload["draft_settings"]
        selected = editor.selection
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

    def _render_editor(self, height: int, width: int) -> None:
        editor = self._editor
        assert editor is not None
        document, cursor_line, cursor_column = self._editor_document(width)
        self._safe_add(
            0,
            0,
            editor.title,
            width,
            self._attribute("A_REVERSE") | self._attribute("A_BOLD"),
        )
        document = document[1:]
        if cursor_line is not None:
            cursor_line -= 1
        status_row = max(0, height - 3)
        viewport_height = max(1, status_row - 1)
        focused_line = next(
            (index for index, (_line, key) in enumerate(document) if key == editor.selection),
            0,
        )
        if cursor_line is not None:
            focused_line = cursor_line
        start = max(0, focused_line - viewport_height // 3)
        if start + viewport_height > len(document):
            start = max(0, len(document) - viewport_height)
        editor.scroll = start
        for offset, (line, key) in enumerate(document[start : start + viewport_height]):
            attr = self._focus_attribute() if key == editor.selection else 0
            self._safe_add(offset + 1, 0, line, width, attr)
        status = editor.error or self._status
        if status and not status.startswith("Error:"):
            status = f"Draft: {status}"
        status_attr = self._attribute("A_BOLD")
        if status.startswith("Error:"):
            status_attr |= self._attribute("A_REVERSE")
        self._safe_add(status_row, 0, status, width, status_attr)
        if editor.active_field is not None and editor.kind in {"text", "japanese"}:
            footer = "Type / IME  ←/→ Cursor  ↑/↓ Wrapped line  Enter Apply  Esc Cancel"
            if editor.kind == "japanese":
                footer += "  ' and / direct"
        elif editor.active_field is not None and editor.kind == "settings":
            footer = "Type / IME  ←/→ Cursor  Enter Finish field  Esc Cancel Settings"
        elif editor.active_field is not None and editor.kind == "english_word":
            footer = "Type phonemes  ←/→ Cursor  Enter Commit phonemes  Esc Cancel word editor"
        elif editor.kind == "japanese":
            footer = "Enter Edit  ' and / direct  Esc Cancel pronunciation"
        elif editor.kind == "english_word" and editor.payload.get("moving_primary"):
            footer = "←/→ Choose vowel  Enter Commit marker  Esc Cancel marker move"
        elif editor.kind == "english_word":
            footer = "↑/↓ Select  Enter Edit/Done  Esc Cancel word changes"
        elif editor.kind == "english_segment":
            footer = "↑/↓ Select word  Enter Edit/Apply  Esc Cancel segment draft"
        elif editor.kind == "settings":
            footer = ""
        else:
            footer = "↑/↓ Select field/action  Enter Edit/Apply  Esc Cancel draft"
        if not (editor.kind == "settings" and editor.active_field is None):
            self._safe_add(status_row + 1, 0, footer, width, self._attribute("A_BOLD"))
        if cursor_line is not None and start <= cursor_line < start + viewport_height:
            try:
                self._screen.move(
                    cursor_line - start + 1,
                    min(width - 1, cursor_column),
                )
            except curses.error:
                pass

    def _safe_add(
        self,
        row: int,
        column: int,
        value: str,
        width: int,
        attr: int = 0,
    ) -> None:
        if self._screen is None or row < 0 or column < 0 or width <= column:
            return
        try:
            arguments = (row, column, value, max(0, width - column - 1))
            if attr:
                self._screen.addnstr(*arguments, attr)
            else:
                self._screen.addnstr(*arguments)
        except curses.error:
            pass

def _duration_seconds(audio: Any, sampling_rate: int) -> float:
    try:
        return len(audio) / float(sampling_rate)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _display_width(value: str) -> int:
    return sum(
        0
        if unicodedata.combining(character) or character == "\u200d"
        else 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1
        for character in value
    )


def _wrap_text(value: str, width: int) -> list[str]:
    """Wrap visible text at character boundaries without changing stored text."""

    if not value:
        return []
    width = max(1, width)
    lines: list[str] = []
    current: list[str] = []
    used = 0
    for character in value:
        cell_width = _display_width(character)
        if current and used + cell_width > width:
            lines.append("".join(current))
            current = []
            used = 0
        current.append(character)
        used += cell_width
    if current:
        lines.append("".join(current))
    return lines


def _truncate_display(value: str, width: int) -> str:
    """Trim a display-only value at a complete character boundary."""

    width = max(0, width)
    result: list[str] = []
    used = 0
    for character in value:
        cells = _display_width(character)
        if used + cells > width:
            break
        result.append(character)
        used += cells
    return "".join(result)


def _wrap_labeled_tokens(
    label: str,
    tokens: Sequence[str],
    width: int,
) -> list[str]:
    """Wrap a phoneme sequence only between complete display tokens."""

    width = max(1, width)
    continuation = " " * _display_width(label)
    lines: list[str] = []
    current = label
    used = _display_width(label)
    values = list(tokens) or ["(none)"]
    first_line = True
    line_has_tokens = False
    for token in values:
        separator = (
            1
            if line_has_tokens or (first_line and label and not label[-1].isspace())
            else 0
        )
        token_width = _display_width(token)
        if used + separator + token_width > width and line_has_tokens:
            lines.append(current)
            current = continuation
            used = _display_width(continuation)
            first_line = False
            line_has_tokens = False
            separator = 0
        if separator:
            current += " "
            used += 1
        current += token
        used += token_width
        line_has_tokens = True
    lines.append(current)
    return lines


def _phoneme_state_tokens(state: EnglishPhonemeEditorState) -> list[str]:
    result: list[str] = []
    vowel_index = 0
    for token in state.base_phonemes:
        if token in _VOWELS:
            if state.vowel_stresses[vowel_index] == 1:
                result.append(f"[{token}]")
            else:
                result.append(token)
            vowel_index += 1
        else:
            result.append(token)
    return result


def _phonemes_as_ui_tokens(phonemes: Sequence[str]) -> list[str]:
    return _phoneme_state_tokens(english_phonemes_to_editor_state(phonemes))


def _english_display_tokens(phonemes: Sequence[str]) -> list[str]:
    return _phonemes_as_ui_tokens(phonemes)


def _wrapped_ranges(value: str, width: int) -> list[tuple[int, int]]:
    width = max(1, width)
    if not value:
        return [(0, 0)]
    rows: list[tuple[int, int]] = []
    start = 0
    used = 0
    for index, character in enumerate(value):
        cell_width = _display_width(character)
        if index > start and used + cell_width > width:
            rows.append((start, index))
            start = index
            used = 0
        used += cell_width
    rows.append((start, len(value)))
    return rows


def _wrap_active_input(
    value: str,
    cursor: int,
    width: int,
) -> tuple[list[str], int, int]:
    """Wrap an active input line and locate its cursor in terminal cells."""

    ranges = _wrapped_ranges(value, width)
    cursor = min(max(cursor, 0), len(value))
    cursor_row = len(ranges) - 1
    for index, (start, end) in enumerate(ranges):
        if start <= cursor < end:
            cursor_row = index
            break
        if cursor == start:
            cursor_row = index
            break
        if cursor == end and index == len(ranges) - 1:
            cursor_row = index
            break
    start, _end = ranges[cursor_row]
    return (
        [value[row_start:row_end] for row_start, row_end in ranges],
        cursor_row,
        _display_width(value[start:cursor]),
    )


def _move_wrapped_cursor(value: str, cursor: int, delta: int, width: int) -> int:
    """Move a code-point cursor between wrapped visual lines when possible."""

    rows = _wrapped_ranges(value, width)
    cursor = min(max(cursor, 0), len(value))
    _wrapped, current_row, current_column = _wrap_active_input(
        value, cursor, width
    )
    target_row = min(max(current_row + delta, 0), len(rows) - 1)
    if target_row == current_row:
        return cursor
    row_start, row_end = rows[target_row]
    target = row_start
    used = 0
    for index in range(row_start, row_end):
        cell_width = _display_width(value[index])
        if used + cell_width > current_column:
            break
        used += cell_width
        target = index + 1
    return target


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
