"""Terminal document construction and curses rendering for the TUI."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, Sequence

from .english_stress import EnglishPhonemeEditorState
from .query_editing import japanese_pronunciation
from .session import UtteranceSession
from .settings import Settings
from .styles import available_styles
from .tui_display import (
    _VOWELS,
    _adjustable_value,
    _display_width,
    _english_display_tokens,
    _phoneme_state_tokens,
    _phonemes_as_ui_tokens,
    _truncate_display,
    _wrap_active_input,
    _wrap_labeled_tokens,
    _wrap_text,
)


_HELP_ITEMS = (
    ("Up/Down", ": move one selectable Navigation item at a time"),
    ("Enter", ": edit, open, generate, regenerate, or accept the focused action"),
    ("Left/Right", " on Generate: decrease/increase take count"),
    ("Left/Right", " in Settings: adjust the selected value"),
    ("Space", ": replay a focused candidate"),
    ("Esc", ": return from candidate review; cancel editor draft"),
    ("Tab", ": move to the next major section/action"),
    ("Shift+Tab", ": move to the previous major section/action"),
    ("F5 / Ctrl+G", ": activate Generate / Regenerate all"),
    ("1-8", ": focus and play an available candidate"),
    ("r", ": regenerate the focused candidate"),
    ("R", ": activate Generate / Regenerate all"),
    ("t", ": edit Text"),
    ("s", ": open Settings at style"),
    ("v", ": open Settings at speed"),
    ("n", ": open Settings at takes"),
    ("o", ": open Settings at output"),
    ("x", ": open Settings at TXT"),
    (None, "Rebuild pronunciation: rerun automatic pronunciation from current Text"),
    ("?", ": open Help"),
    ("q", ": Quit"),
)


class EditorRenderState(Protocol):
    kind: str
    title: str
    selection: str | tuple[str, int | None]
    payload: dict[str, Any]
    active_field: str | None
    input_value: str
    input_cursor: int
    error: str


class EnglishWordGroupRenderState(Protocol):
    label: str
    phonemes: Sequence[str]
    editable: bool


@dataclass(frozen=True)
class TuiRenderState:
    """Read-only snapshot of the application values needed to render a frame."""

    voiceger_root: Any
    settings: Settings
    session: UtteranceSession | None
    focus_key: tuple[str, int | None]
    status: str
    segments: Sequence[tuple[str, str, int | None]]
    busy: bool
    worker_operation: str | None
    worker_target: int | None
    operation_completed: int
    operation_total: int
    pressed_adjustment: tuple[str, str, int] | None
    editor: EditorRenderState | None


def _active_input_prefix(editor: EditorRenderState) -> str:
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


def _duration_seconds(audio: Any, sampling_rate: int) -> float:
    try:
        return len(audio) / float(sampling_rate)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


class TuiRenderer:
    """Own display documents, terminal layout, and curses drawing."""

    def __init__(self) -> None:
        self._color_attr = 0

    def initialize_colors(self) -> None:
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

    @staticmethod
    def _adjustment_press_direction(
        state: TuiRenderState,
        area: str,
        control: str,
    ) -> int | None:
        pressed = state.pressed_adjustment
        if pressed is None or pressed[:2] != (area, control):
            return None
        return pressed[2]

    @staticmethod
    def _safe_add(
        screen: Any,
        row: int,
        column: int,
        value: str,
        width: int,
        attr: int = 0,
    ) -> None:
        if screen is None or row < 0 or column < 0 or width <= column:
            return
        try:
            arguments = (row, column, value, max(0, width - column - 1))
            if attr:
                screen.addnstr(*arguments, attr)
            else:
                screen.addnstr(*arguments)
        except curses.error:
            pass

    def render_help(self, screen: Any, width: int) -> None:
        safe_add = self._safe_add
        safe_add(screen, 0, 0, "HELP", width, self._attribute("A_BOLD"))
        safe_add(screen, 1, 0, "Navigation and action shortcuts", width)
        height = screen.getmaxyx()[0]
        footer_row = max(0, height - 1)
        row = 2
        column = 1
        available = max(1, width - column - 1)
        bold = self._attribute("A_BOLD")
        for shortcut, suffix in _HELP_ITEMS:
            if row >= footer_row:
                break
            if shortcut is None:
                pieces = _wrap_text(suffix, available) or [""]
                for piece in pieces:
                    if row >= footer_row:
                        break
                    safe_add(screen, row, column, piece, width)
                    row += 1
                continue

            key_width = _display_width(shortcut)
            if key_width >= available:
                key_pieces = _wrap_text(shortcut, available) or [""]
                for piece in key_pieces:
                    if row >= footer_row:
                        break
                    safe_add(screen, row, column, piece, width, bold)
                    row += 1
                explanation_pieces = _wrap_text(suffix, available)
                for piece in explanation_pieces:
                    if row >= footer_row:
                        break
                    safe_add(screen, row, column, piece, width)
                    row += 1
                continue

            safe_add(screen, row, column, shortcut, width, bold)
            explanation_width = available - key_width
            explanation_pieces = _wrap_text(suffix, explanation_width)
            if explanation_pieces:
                safe_add(
                    screen, row, column + key_width, explanation_pieces[0], width
                )
            row += 1
            for piece in explanation_pieces[1:]:
                if row >= footer_row:
                    break
                safe_add(screen, row, column + key_width, piece, width)
                row += 1
        safe_add(
            screen,
            max(0, screen.getmaxyx()[0] - 1),
            0,
            "Esc / Enter / ? Return to Navigation  |  q Quit",
            width,
            self._attribute("A_BOLD"),
        )

    def render_navigation(
        self,
        screen: Any,
        state: TuiRenderState,
        height: int,
        width: int,
    ) -> None:
        safe_add = self._safe_add
        safe_add(
            screen,
            0,
            0,
            "NAVIGATION  Voiceger Accent Adapter",
            width,
            self._attribute("A_BOLD"),
        )
        settings = state.settings
        style_name = next(
            (
                style.name
                for style in available_styles(state.voiceger_root)
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
        marker = "▶ " if state.focus_key == ("settings_summary", None) else "  "
        prefix_width = max(
            0,
            width - 1 - _display_width(marker) - _display_width(suffix),
        )
        summary = marker + _truncate_display(prefix, prefix_width) + suffix
        summary_attr = (
            self._focus_attribute()
            if state.focus_key == ("settings_summary", None)
            else 0
        )
        output_marker = "▶ " if state.focus_key == ("output", None) else "  "
        output_attr = (
            self._focus_attribute() if state.focus_key == ("output", None) else 0
        )
        safe_add(screen, 1, 0, summary, width, summary_attr)
        safe_add(
            screen,
            2,
            0,
            f"{output_marker}Output: {settings.output_dir}",
            width,
            output_attr,
        )

        lines = self.navigation_document(state, width)
        status_row = max(0, height - 2)
        viewport_height = max(1, status_row - 4)
        focused_index = next(
            (
                index
                for index, (_text, key) in enumerate(lines)
                if key == state.focus_key
            ),
            0,
        )
        start = max(0, focused_index - viewport_height // 3)
        if start + viewport_height > len(lines):
            start = max(0, len(lines) - viewport_height)
        for offset, (line, key) in enumerate(lines[start : start + viewport_height]):
            row = 4 + offset
            attr = self._focus_attribute() if key == state.focus_key else 0
            safe_add(screen, row, 0, line, width, attr)

        status = state.status
        if status and not status.startswith("Error:"):
            status = f"Status: {status}"
        status_attr = self._attribute("A_BOLD")
        if status.startswith("Error:"):
            status_attr |= self._attribute("A_REVERSE")
        safe_add(screen, status_row, 0, status, width, status_attr)

    def navigation_document(
        self,
        state: TuiRenderState,
        width: int,
    ) -> list[tuple[str, tuple[str, int | None] | None]]:
        lines: list[tuple[str, tuple[str, int | None] | None]] = []

        def plain(value: str = "") -> None:
            lines.append((value, None))

        def action(key: tuple[str, int | None], label: str) -> None:
            marker = "▶ " if key == state.focus_key else "  "
            lines.append((marker + label, key))

        def text_action(key: tuple[str, int | None], value: str) -> None:
            marker = "▶ " if key == state.focus_key else "  "
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
            marker = "▶ " if key == state.focus_key else "  "
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

        session = state.session
        text_action(("text", None), session.source_text if session else "")
        if session is not None:
            plain()
            if session.pronunciation_needs_rebuild:
                plain("Pronunciation   Rebuild required")
            else:
                plain("Pronunciation")
                for index, (language, source, model_index) in enumerate(state.segments):
                    if language == "ja":
                        try:
                            query = session.query
                            pronunciation = japanese_pronunciation(
                                query,
                                segment_index=(
                                    model_index if query.voicegerSegments is not None else None
                                ),
                            )
                        except Exception as exc:
                            pronunciation = f"<{exc}>"
                        segment_action(
                            ("segment", index), language, source, pronunciation
                        )
                    elif language == "en" and model_index is not None:
                        try:
                            segment = session.query.voicegerSegments[model_index]
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
            has_batch = session.has_active_batch
            if state.busy:
                if state.worker_operation == "regenerate_one":
                    generate_label = f"Regenerating take {state.worker_target}"
                else:
                    current = min(
                        state.operation_completed + 1,
                        max(1, state.operation_total),
                    )
                    verb = (
                        "Regenerating"
                        if state.worker_operation == "regenerate_all"
                        else "Generating"
                    )
                    generate_label = f"{verb} {current}/{state.operation_total}"
            else:
                adjustable_count = _adjustable_value(
                    str(state.settings.take_count),
                    self._adjustment_press_direction(state, "navigation", "generate"),
                )
                generate_label = (
                    f"Regenerate all {adjustable_count} takes"
                    if has_batch
                    else f"Generate {adjustable_count} takes"
                )
            action(("generate", None), f"[ {generate_label} ]")
            plain()
            if not session.candidates:
                plain("Candidates   No candidates yet.")
            else:
                plain("Candidates")
            for candidate in session.candidates:
                duration = _duration_seconds(candidate.audio, candidate.sampling_rate)
                action(
                    ("candidate", candidate.number),
                    f"Take {candidate.number}  {duration:.2f}s",
                )
            plain()

        action(("settings", None), "Settings  [s]")
        action(("help", None), "Help      [?]")
        action(("quit", None), "Quit      [q]")
        return lines

    def editor_document(
        self,
        state: TuiRenderState,
        width: int,
    ) -> tuple[
        list[tuple[str, str | tuple[str, int | None] | None]],
        int | None,
        int,
    ]:
        editor = state.editor
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
            prefix = _active_input_prefix(editor)
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
            draft = (
                editor.input_value
                if editor.active_field == "draft"
                else editor.payload["draft"]
            )
            wrap("Draft source: ", draft)
            if editor.active_field == "draft":
                input_field("draft")
            else:
                selectable("draft", "Source text field  [Enter: Edit]")
        elif editor.kind == "japanese":
            wrap("Source: ", editor.payload["source_text"])
            draft = (
                editor.input_value
                if editor.active_field == "draft"
                else editor.payload["draft"]
            )
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
                (
                    "style_id",
                    "Style",
                    self.setting_display("style_id", draft["style_id"], state.voiceger_root),
                ),
                (
                    "speed",
                    "Speed",
                    self.setting_display("speed", draft["speed"], state.voiceger_root),
                ),
                ("take_count", "Take count", str(draft["take_count"])),
                ("output_dir", "Output directory", str(draft["output_dir"])),
                ("save_text", "TXT sidecar", "ON" if draft["save_text"] else "OFF"),
            )
            for key, label, value in values:
                if editor.active_field == key:
                    input_field(key)
                else:
                    if key in {"style_id", "speed", "take_count", "save_text"}:
                        value = _adjustable_value(
                            value,
                            self._adjustment_press_direction(state, "settings", key),
                        )
                    selectable(key, f"{label}: {value}")
            plain()
            selectable("apply", "Apply and save settings")
        elif editor.kind == "english_segment":
            wrap("Source: ", editor.payload["source_text"])
            plain("Draft word pronunciations:")
            groups: tuple[EnglishWordGroupRenderState, ...] = editor.payload["groups"]
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
            phoneme_state: EnglishPhonemeEditorState = editor.payload["draft_state"]
            token_lines("Draft pronunciation: ", _phoneme_state_tokens(phoneme_state))
            if editor.active_field == "phonemes":
                input_field("phonemes")
            else:
                selectable("phonemes", "Phonemes  [Enter: Edit]")
            positions = phoneme_state.primary_stress_vowel_positions
            vowels = [
                token for token in phoneme_state.base_phonemes if token in _VOWELS
            ]
            moving = bool(editor.payload.get("moving_primary"))
            for ordinal, position in enumerate(positions):
                key = ("primary", ordinal)
                label = (
                    f"Primary marker {ordinal + 1}: vowel {position + 1} "
                    f"[{vowels[position]}]"
                )
                if moving and editor.selection == key:
                    destination = editor.payload["stress_destination"]
                    label += (
                        f" → proposed vowel {destination + 1} "
                        f"[{vowels[destination]}]"
                    )
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

    @staticmethod
    def setting_display(name: str, value: Any, voiceger_root: Any) -> str:
        if name == "style_id":
            try:
                style_id = int(value)
            except (TypeError, ValueError):
                return str(value)
            style = next(
                (item for item in available_styles(voiceger_root) if item.id == style_id),
                None,
            )
            return f"{value} {style.name}" if style is not None else str(value)
        if name == "speed":
            try:
                return f"{Decimal(str(value)):.2f}"
            except (InvalidOperation, ValueError):
                return str(value)
        return str(value)

    def render_editor(
        self,
        screen: Any,
        state: TuiRenderState,
        height: int,
        width: int,
    ) -> None:
        editor = state.editor
        assert editor is not None
        safe_add = self._safe_add
        document, cursor_line, cursor_column = self.editor_document(state, width)
        safe_add(
            screen,
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
            (
                index
                for index, (_line, key) in enumerate(document)
                if key == editor.selection
            ),
            0,
        )
        if cursor_line is not None:
            focused_line = cursor_line
        start = max(0, focused_line - viewport_height // 3)
        if start + viewport_height > len(document):
            start = max(0, len(document) - viewport_height)
        for offset, (line, key) in enumerate(document[start : start + viewport_height]):
            attr = self._focus_attribute() if key == editor.selection else 0
            safe_add(screen, offset + 1, 0, line, width, attr)
        status = editor.error or state.status
        if status and not status.startswith("Error:"):
            status = f"Draft: {status}"
        status_attr = self._attribute("A_BOLD")
        if status.startswith("Error:"):
            status_attr |= self._attribute("A_REVERSE")
        safe_add(screen, status_row, 0, status, width, status_attr)
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
            safe_add(
                screen,
                status_row + 1,
                0,
                footer,
                width,
                self._attribute("A_BOLD"),
            )
        if cursor_line is not None and start <= cursor_line < start + viewport_height:
            try:
                screen.move(
                    cursor_line - start + 1,
                    min(width - 1, cursor_column),
                )
            except curses.error:
                pass
