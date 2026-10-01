"""Terminal document construction and curses rendering for the TUI."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, Sequence

from .pronunciation import parse_pronunciation
from .session import UtteranceSession
from .settings import (
    Settings,
    VOICEGER_DEFAULT_TEMPERATURE,
    VOICEGER_DEFAULT_TOP_K,
    VOICEGER_DEFAULT_TOP_P,
)
from .styles import available_styles
from .tui_display import (
    _adjustable_value,
    _display_width,
    _english_display_tokens,
    _japanese_mora_tokens,
    _truncate_display,
    _wrap_active_input,
    _wrap_tokens_with_prefixes,
    _wrap_text,
)
from .tui_editors import PronunciationRow
from .tui_shortcuts import main_shortcut, menu_item


_HELP_ITEMS = (
    ("Up/Down", ": move one selectable item"),
    (
        "Left/Right",
        ": on Generate/Regenerate: Takes; on JA: accent by one mora; on EN: primary stress by one vowel",
    ),
    (
        "Enter",
        ": on JA: edit segment pronunciation; on EN: edit word phonemes",
    ),
    ("Space", ": replay a focused candidate"),
    (
        "Esc",
        ": initial/regenerate-all cancels cooperatively; otherwise back/editor",
    ),
    ("Tab / Shift+Tab", ": next / previous major section/action"),
    (
        " / ".join(
            main_shortcut(name).shortcut
            for name in ("build_pronunciation", "add_section", "generate")
        ),
        ": Build pronunciation / Add section / Generate or regenerate all",
    ),
    ("1-9", ": focus and play an available candidate"),
    (main_shortcut("clear_candidates").shortcut, ": clear candidates through confirmation"),
    ("r", ": regenerate the focused candidate"),
    ("t", ": edit Caption"),
    (main_shortcut("settings").shortcut, ": open Settings at style"),
    (main_shortcut("dictionary").shortcut, ": open Dictionary"),
    ("v", ": open Settings at speed"),
    ("n", ": open Settings at takes"),
    ("o", ": open Settings at output"),
    ("x", ": open Settings at TXT"),
    ("l", ": open Settings at LAB"),
    (None, "Menu mode: editor/modal action letters are active."),
    (None, "Editing: Enter finishes; printable shortcut letters insert text."),
    (main_shortcut("help").shortcut, ": open or close Help"),
    (main_shortcut("quit").shortcut, ": Quit"),
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


@dataclass(frozen=True)
class TuiRenderState:
    """Read-only snapshot of the application values needed to render a frame."""

    voiceger_root: Any
    settings: Settings
    session: UtteranceSession | None
    focus_key: tuple[str, int | None]
    status: str
    segments: Sequence[tuple[str, str, int | None]]
    pronunciation_rows: Sequence[PronunciationRow]
    busy: bool
    worker_operation: str | None
    worker_target: int | None
    operation_completed: int
    operation_total: int
    pressed_adjustment: tuple[str, str, int] | None
    editor: EditorRenderState | None


@dataclass(frozen=True)
class NavigationLine:
    text: str
    key: tuple[str, int | None] | None
    focus_owner: tuple[str, int | None] | None = None
    bold_spans: tuple[tuple[int, int], ...] = ()


def _active_input_prefix(editor: EditorRenderState) -> str:
    if editor.kind == "caption":
        return "▶ "
    if editor.kind == "japanese":
        return "▶ "
    if editor.kind == "english_word":
        return "▶ "
    if editor.kind in {"section_text", "add_section"}:
        return "▶ "
    if editor.kind in {"dictionary_japanese_entry", "dictionary_english_entry"}:
        label = "Surface" if editor.active_field == "surface" else "Pronunciation"
        return f"▶ {label:<15}"
    if editor.kind == "settings":
        labels = {
            "style_id": "Style",
            "speed": "Speed",
            "take_count": "Takes",
            "output_dir": "Output",
            "save_text": "TXT",
            "save_lab": "LAB",
            "top_k": "Top K",
            "top_p": "Top P",
            "temperature": "Temperature",
        }
        label = labels.get(editor.active_field or "", "Setting")
        return f"▶ {label:<12}"
    return "▶ Input: "


def _duration_seconds(frame_count: int, sampling_rate: int) -> float:
    try:
        return frame_count / float(sampling_rate)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


class TuiRenderer:
    """Own display documents, terminal layout, and curses drawing."""

    def __init__(self) -> None:
        self._color_attr = 0
        self._error_color_attr = 0
        self._warning_color_attr = 0

    def initialize_colors(self) -> None:
        """Use semantic foreground colors on the terminal's own background."""

        self._color_attr = 0
        self._error_color_attr = 0
        self._warning_color_attr = 0
        try:
            if not curses.has_colors():
                return
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_RED, -1)
            curses.init_pair(3, curses.COLOR_MAGENTA, -1)
            self._color_attr = curses.color_pair(1)
            self._error_color_attr = curses.color_pair(2)
            self._warning_color_attr = curses.color_pair(3)
        except (AttributeError, curses.error):
            self._color_attr = 0
            self._error_color_attr = 0
            self._warning_color_attr = 0

    @staticmethod
    def _attribute(name: str) -> int:
        return int(getattr(curses, name, 0))

    def _focus_attribute(self) -> int:
        return self._attribute("A_REVERSE") | self._color_attr

    def _status_attribute(self, status: str) -> int:
        attr = self._attribute("A_BOLD")
        if status.startswith("Error:"):
            return attr | (
                self._error_color_attr or self._attribute("A_REVERSE")
            )
        if status.startswith("Warning:"):
            return attr | (
                self._warning_color_attr or self._attribute("A_REVERSE")
            )
        return attr

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
        height = screen.getmaxyx()[0]
        back_row = max(0, height - 1)
        if back_row > 0:
            safe_add(screen, 0, 0, "HELP", width, self._attribute("A_BOLD"))
        row = 1
        column = 1
        available = max(1, width - column - 1)
        bold = self._attribute("A_BOLD")
        for shortcut, suffix in _HELP_ITEMS:
            if row >= back_row:
                break
            if shortcut is None:
                pieces = _wrap_text(suffix, available) or [""]
                for piece in pieces:
                    if row >= back_row:
                        break
                    safe_add(screen, row, column, piece, width)
                    row += 1
                continue

            key_width = _display_width(shortcut)
            if key_width >= available:
                key_pieces = _wrap_text(shortcut, available) or [""]
                for piece in key_pieces:
                    if row >= back_row:
                        break
                    safe_add(screen, row, column, piece, width, bold)
                    row += 1
                explanation_pieces = _wrap_text(suffix, available)
                for piece in explanation_pieces:
                    if row >= back_row:
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
                if row >= back_row:
                    break
                safe_add(screen, row, column + key_width, piece, width)
                row += 1
        safe_add(
            screen,
            back_row,
            0,
            f"▶ {menu_item('help', 'back').display_label}",
            width,
            self._focus_attribute(),
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
            "Voiceger Accent Adapter",
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
        status = state.status
        if status and not status.startswith(("Error:", "Warning:")):
            status = f"Status: {status}"
        status_lines = (
            _wrap_text(status, max(1, width - 1))
            if status
            else []
        )
        status_height = max(1, len(status_lines))
        status_start = max(0, height - status_height)
        viewport_height = max(0, status_start - 4)
        focused_index = next(
            (
                index
                for index, line in enumerate(lines)
                if line.focus_owner == state.focus_key
            ),
            0,
        )
        start = max(0, focused_index - viewport_height // 3)
        if start + viewport_height > len(lines):
            start = max(0, len(lines) - viewport_height)
        for offset, line in enumerate(lines[start : start + viewport_height]):
            row = 4 + offset
            focused = line.focus_owner == state.focus_key
            attr = self._focus_attribute() if focused else 0
            safe_add(screen, row, 0, line.text, width, attr)
            for column, span_width in line.bold_spans:
                word_attr = self._attribute("A_BOLD")
                if focused:
                    word_attr |= self._attribute("A_REVERSE")
                safe_add(
                    screen,
                    row,
                    column,
                    line.text[column : column + span_width],
                    width,
                    word_attr,
                )

        if status_lines:
            status_attr = self._status_attribute(status)
            for offset, line in enumerate(status_lines):
                safe_add(
                    screen,
                    status_start + offset,
                    0,
                    line,
                    width,
                    status_attr,
                )

    def navigation_document(
        self,
        state: TuiRenderState,
        width: int,
    ) -> list[NavigationLine]:
        lines: list[NavigationLine] = []
        row_limit = max(1, width - 1)

        def plain(value: str = "") -> None:
            lines.append(NavigationLine(value, None))

        def action(key: tuple[str, int | None], label: str) -> None:
            marker = "▶ " if key == state.focus_key else "  "
            lines.append(NavigationLine(marker + label, key, key))

        def caption_action(key: tuple[str, int | None], value: str) -> None:
            marker = "▶ " if key == state.focus_key else "  "
            prefix = f"{marker}Caption : "
            available = max(1, width - 1 - _display_width(prefix))
            pieces = _wrap_text(value, available) or [""]
            lines.append(NavigationLine(prefix + pieces[0], key, key))
            continuation = " " * _display_width(prefix)
            lines.extend(
                NavigationLine(continuation + piece, None, key)
                for piece in pieces[1:]
            )

        def pronunciation_action(index: int, item: PronunciationRow) -> None:
            key = ("pronunciation", index)
            marker = "▶ " if key == state.focus_key else "  "
            language_prefix = (
                f"{item.language.upper()} | "
                if item.first_in_segment
                else "   | "
            )
            first_prefix = marker + language_prefix
            continuation_prefix = "     | "

            if item.language == "ja":
                tokens = _japanese_mora_tokens(item.moras, item.accent or 1)
                physical, _cursor = _wrap_tokens_with_prefixes(
                    first_prefix,
                    continuation_prefix,
                    tokens,
                    row_limit,
                )
                for physical_index, value in enumerate(physical):
                    lines.append(
                        NavigationLine(
                            value,
                            key if physical_index == 0 else None,
                            key,
                        )
                    )
                return

            if item.language == "en" and item.word is not None:
                word_width = item.word_column_width or _display_width(item.word)
                word_field = item.word + " " * max(
                    3, word_width - _display_width(item.word) + 3
                )
                tokens = _english_display_tokens(item.phonemes) or ["(none)"]
                widest_phone = max((_display_width(token) for token in tokens), default=1)
                source_column = _display_width(first_prefix)
                source_span = _display_width(item.word)
                if source_column + _display_width(word_field) + widest_phone > row_limit:
                    physical = [first_prefix + item.word]
                    wrapped, _cursor = _wrap_tokens_with_prefixes(
                        continuation_prefix,
                        continuation_prefix,
                        tokens,
                        row_limit,
                    )
                    physical.extend(wrapped)
                    bold_spans = ((source_column, source_span),)
                else:
                    phone_prefix = first_prefix + word_field
                    wrapped, _cursor = _wrap_tokens_with_prefixes(
                        phone_prefix,
                        continuation_prefix + " " * (word_width + 3),
                        tokens,
                        row_limit,
                    )
                    physical = wrapped
                    bold_spans = ((source_column, source_span),)
                for physical_index, value in enumerate(physical):
                    lines.append(
                        NavigationLine(
                            value,
                            key if physical_index == 0 else None,
                            key,
                            bold_spans if physical_index == 0 else (),
                        )
                    )
                return

            label = item.source_text or "Unavailable"
            value_prefix = first_prefix
            pieces = _wrap_text(label, max(1, row_limit - _display_width(value_prefix)))
            physical = [value_prefix + (pieces[0] if pieces else "Unavailable")]
            physical.extend(continuation_prefix + piece for piece in pieces[1:])
            for physical_index, value in enumerate(physical):
                lines.append(
                    NavigationLine(
                        value,
                        key if physical_index == 0 else None,
                        key,
                    )
                )

        session = state.session
        caption_action(("caption", None), session.caption if session else "")
        if session is not None:
            action(
                ("build_pronunciation", None),
                main_shortcut("build_pronunciation").display_label,
            )
            plain()
            for index, item in enumerate(state.pronunciation_rows):
                pronunciation_action(index, item)
            plain()
            action(
                ("add_section", None),
                main_shortcut("add_section").display_label,
            )
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
            plain()
            if not session.candidates:
                plain("Candidates   No candidates yet.")
            else:
                plain("Candidates")
            for candidate in session.candidates:
                duration = _duration_seconds(
                    candidate.frame_count,
                    candidate.sampling_rate,
                )
                label = (
                    f"[{candidate.number}] Take {candidate.number}  {duration:.2f}s"
                    if candidate.number <= 9
                    else f"Take {candidate.number}  {duration:.2f}s"
                )
                action(
                    ("candidate", candidate.number),
                    label,
                )
            if session.candidates:
                plain()
            action(
                ("generate", None),
                main_shortcut("generate").display_with_label(generate_label),
            )
            if session.candidates:
                action(
                    ("clear_candidates", None),
                    main_shortcut("clear_candidates").display_label,
                )
            plain()

        action(("settings", None), main_shortcut("settings").display_label)
        action(("dictionary", None), main_shortcut("dictionary").display_label)
        action(("help", None), main_shortcut("help").display_label)
        action(("quit", None), main_shortcut("quit").display_label)
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

        def wrap(prefix: str, value: str, key=None) -> None:
            available = max(1, width - 1 - _display_width(prefix))
            pieces = _wrap_text(value, available)
            lines.append((prefix + (pieces[0] if pieces else ""), key))
            for piece in pieces[1:]:
                lines.append((" " * _display_width(prefix) + piece, key))

        def selectable(key: str) -> None:
            marker = "▶ " if editor.selection == key else "  "
            item = menu_item(editor.kind, key, editor.payload)
            lines.append((marker + item.display_label, key))

        def wrapped_selectable_text(
            key: str | tuple[str, int | None],
            value: str,
        ) -> None:
            marker = "▶ " if editor.selection == key else "  "
            marker_width = _display_width(marker)
            available = max(1, width - 1 - marker_width)
            pieces = _wrap_text(value, available) or [""]
            lines.append((marker + pieces[0], key))
            continuation = " " * marker_width
            lines.extend((continuation + piece, key) for piece in pieces[1:])

        def input_field(name: str, prefix: str | None = None) -> None:
            nonlocal cursor_line, cursor_column
            prefix = prefix if prefix is not None else _active_input_prefix(editor)
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
            if editor.active_field == name:
                cursor_line = first_line + cursor_row
                cursor_column = prefix_width + cursor_cells

        plain(editor.title)
        if editor.kind == "caption":
            plain()
            if editor.active_field == "draft":
                input_field("draft", "▶ ")
            else:
                wrapped_selectable_text("draft", editor.payload["draft"])
            plain()
            selectable("apply")
            selectable("clear")
            selectable("reset")
            selectable("back")
        elif editor.kind == "build_confirmation":
            plain()
            wrap("", editor.payload["warning"])
            plain()
            selectable("rebuild")
            selectable("cancel")
        elif editor.kind == "japanese":
            plain()
            plain("Source")
            wrap("  ", editor.payload["source_text"])
            plain()
            input_field(
                "pronunciation",
                "▶ " if editor.selection == "pronunciation" else "  ",
            )
            plain()
            selectable("preview")
            selectable("apply")
            selectable("save_dictionary")
            selectable("dictionary")
            selectable("edit_text")
            selectable("clear")
            selectable("reset")
            selectable("back")
        elif editor.kind == "settings":
            draft = editor.payload["draft_settings"]
            values = (
                (
                    "style_id",
                    self.setting_display("style_id", draft["style_id"], state.voiceger_root),
                ),
                (
                    "speed",
                    self.setting_display("speed", draft["speed"], state.voiceger_root),
                ),
                ("take_count", str(draft["take_count"])),
                ("output_dir", str(draft["output_dir"])),
                ("save_text", "ON" if draft["save_text"] else "OFF"),
                ("save_lab", "ON" if draft.get("save_lab", False) else "OFF"),
                ("top_k", str(draft.get("top_k", VOICEGER_DEFAULT_TOP_K))),
                (
                    "top_p",
                    f"{float(draft.get('top_p', VOICEGER_DEFAULT_TOP_P)):.2f}",
                ),
                (
                    "temperature",
                    f"{float(draft.get('temperature', VOICEGER_DEFAULT_TEMPERATURE)):.2f}",
                ),
            )
            section_headers = {
                "style_id": "Voice",
                "take_count": "Generation",
                "output_dir": "Output",
                "top_k": "Sampling",
            }
            candidate_clearing = {
                "style_id", "speed", "top_k", "top_p", "temperature"
            }
            for key, value in values:
                heading = section_headers.get(key)
                if heading is not None:
                    plain(heading)
                item = menu_item(editor.kind, key, editor.payload)
                label = item.label + (" *" if key in candidate_clearing else "")
                if editor.active_field == key:
                    input_field(key, f"▶ {label:<16}")
                else:
                    if key in {
                        "style_id", "speed", "take_count", "save_text", "save_lab",
                        "top_k", "top_p", "temperature",
                    }:
                        value = _adjustable_value(
                            value,
                            self._adjustment_press_direction(state, "settings", key),
                        )
                    marker = "▶ " if editor.selection == key else "  "
                    visible_label = (
                        f"[{item.shortcut.upper()}] {label}"
                        if item.shortcut is not None
                        else label
                    )
                    lines.append((f"{marker}{visible_label:<20}{value}", key))
            selectable("reset_sampling")
            plain("Actions")
            selectable("apply")
            selectable("reset")
            selectable("back")
            plain("* Applying this setting clears existing candidates.")
        elif editor.kind == "english_word":
            plain()
            plain("Word")
            plain(f"  {editor.payload['label']}")
            plain()
            input_field(
                "phonemes",
                "▶ " if editor.selection == "phonemes" else "  ",
            )
            plain()
            selectable("preview")
            selectable("apply")
            selectable("save_dictionary")
            selectable("dictionary")
            selectable("edit_text")
            selectable("clear")
            selectable("reset")
            selectable("back")
        elif editor.kind == "dictionary_menu":
            plain()
            for key, count_name in (
                ("japanese", "japanese_count"),
                ("english", "english_count"),
            ):
                marker = "▶ " if editor.selection == key else "  "
                item = menu_item(editor.kind, key, editor.payload)
                count = editor.payload[count_name]
                lines.append((f"{marker}{item.display_label:<18}{count} words", key))
            plain()
            selectable("back")
        elif editor.kind == "dictionary_japanese_list":
            plain()
            entries = editor.payload["entries"]
            if not entries:
                plain("  No Japanese dictionary words.")
            for index, (_word_uuid, word) in enumerate(entries):
                parsed = parse_pronunciation(word.pronunciation + "'")
                display = " ".join(
                    _japanese_mora_tokens(
                        parsed.phrases[0].morae,
                        word.accent_type or len(parsed.phrases[0].morae),
                    )
                )
                key = ("entry", index)
                wrapped_selectable_text(
                    key,
                    f"{word.surface}      {display}",
                )
            plain()
            selectable("add")
            if entries:
                selectable("delete")
            selectable("back")
        elif editor.kind == "dictionary_english_list":
            plain()
            entries = editor.payload["entries"]
            if not entries:
                plain("  No English dictionary words.")
            for index, entry in enumerate(entries):
                key = ("entry", index)
                wrapped_selectable_text(
                    key,
                    f"{entry.surface}      {' '.join(entry.phonemes)}",
                )
            plain()
            selectable("add")
            if entries:
                selectable("delete")
            selectable("back")
        elif editor.kind == "dictionary_japanese_duplicates":
            plain()
            plain("Multiple existing words have this Surface. Choose one to update.")
            plain()
            for index, (_word_uuid, word) in enumerate(editor.payload["matches"]):
                parsed = parse_pronunciation(word.pronunciation + "'")
                display = " ".join(
                    _japanese_mora_tokens(
                        parsed.phrases[0].morae,
                        word.accent_type or len(parsed.phrases[0].morae),
                    )
                )
                key = ("entry", index)
                wrapped_selectable_text(key, f"{word.surface}      {display}")
            plain()
            plain("Enter Open")
            plain(menu_item(editor.kind, "back", editor.payload).display_label)
        elif editor.kind == "dictionary_japanese_entry":
            plain()
            if editor.active_field == "surface":
                input_field("surface", "▶ Surface        ")
            else:
                marker = "▶ " if editor.selection == "surface" else "  "
                wrap(marker + "Surface        ", editor.payload["surface"], "surface")
            if editor.active_field == "pronunciation":
                input_field("pronunciation", "▶ Pronunciation  ")
            else:
                display = " ".join(
                    _japanese_mora_tokens(
                        editor.payload["moras"],
                        editor.payload["accent"] or len(editor.payload["moras"]),
                    )
                )
                marker = "▶ " if editor.selection == "pronunciation" else "  "
                lines.append((f"{marker}Pronunciation  {display}", "pronunciation"))
            marker = "▶ " if editor.selection == "word_type" else "  "
            lines.append(
                (
                    f"{marker}Word type      < {editor.payload['word_type'].value} >",
                    "word_type",
                )
            )
            marker = "▶ " if editor.selection == "priority" else "  "
            lines.append(
                (
                    f"{marker}Priority       < {editor.payload['priority']} >",
                    "priority",
                )
            )
            plain()
            selectable("generate_pronunciation")
            selectable("preview")
            selectable("save")
            selectable("dictionary")
            selectable("back")
        elif editor.kind == "dictionary_english_entry":
            plain()
            if editor.active_field == "surface":
                input_field("surface", "▶ Surface        ")
            else:
                marker = "▶ " if editor.selection == "surface" else "  "
                wrap(marker + "Surface        ", editor.payload["surface"], "surface")
            if editor.active_field == "phonemes":
                input_field("phonemes", "▶ Pronunciation  ")
            else:
                marker = "▶ " if editor.selection == "phonemes" else "  "
                wrap(
                    marker + "Pronunciation  ",
                    " ".join(editor.payload["phonemes"]),
                    "phonemes",
                )
            plain()
            selectable("generate_pronunciation")
            selectable("preview")
            selectable("save")
            selectable("dictionary")
            selectable("back")
        elif editor.kind == "dictionary_delete_confirmation":
            plain()
            plain(editor.payload["surface"])
            if editor.payload["language"] == "ja":
                display = " ".join(
                    _japanese_mora_tokens(
                        editor.payload["moras"],
                        editor.payload["accent"] or len(editor.payload["moras"]),
                    )
                )
            else:
                display = " ".join(editor.payload["phonemes"])
            wrap("  ", display)
            plain()
            selectable("delete")
            selectable("cancel")
        elif editor.kind == "dictionary_discard_confirmation":
            plain()
            wrap("", "Unsaved dictionary changes will be discarded.")
            plain()
            selectable("discard")
            selectable("cancel")
        elif editor.kind == "section_text":
            language = "Japanese" if editor.payload["language"] == "ja" else "English"
            plain()
            plain("Language")
            plain(f"  {language}")
            plain()
            if editor.active_field == "draft":
                input_field("draft", "▶ " if editor.selection == "draft" else "  ")
            else:
                wrapped_selectable_text("draft", editor.payload["draft"])
            plain()
            selectable("preview")
            selectable("apply")
            selectable("reset")
            if editor.payload["can_delete"]:
                selectable("delete_section")
            selectable("back")
        elif editor.kind == "add_section":
            language = "Japanese" if editor.payload["language"] == "ja" else "English"
            marker = "▶ " if editor.selection == "language" else "  "
            plain()
            language_item = menu_item(editor.kind, "language", editor.payload)
            lines.append(
                (f"{marker}{language_item.label:<12}< {language} >", "language")
            )
            if editor.active_field == "draft":
                input_field("draft", "▶ " if editor.selection == "draft" else "  ")
            else:
                wrapped_selectable_text("draft", editor.payload["draft"])
            plain()
            selectable("add")
            selectable("clear")
            selectable("reset")
            selectable("back")
        elif editor.kind == "delete_confirmation":
            plain()
            wrap("", editor.payload["warning"])
            plain()
            selectable("delete")
            selectable("cancel")
        elif editor.kind == "clear_candidates_confirmation":
            plain()
            wrap("", editor.payload["warning"])
            plain()
            selectable("clear")
            selectable("cancel")
        return lines, cursor_line, cursor_column

    @staticmethod
    def setting_display(name: str, value: Any, voiceger_root: Any) -> str:
        if name == "style_id":
            try:
                style_id = int(value)
            except (TypeError, ValueError):
                return str(value)
            try:
                style = next(
                    (
                        item
                        for item in available_styles(voiceger_root)
                        if item.id == style_id
                    ),
                    None,
                )
                style_name = str(style.name) if style is not None else ""
            except Exception:
                return str(style_id)
            return style_name or str(style_id)
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
        status_row = max(0, height - 1)
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
        if not status and editor.active_field is not None:
            status = "Enter: Finish editing   Esc: Back"
        if status:
            safe_add(
                screen,
                status_row,
                0,
                status,
                width,
                self._status_attribute(status),
            )
        if cursor_line is not None and start <= cursor_line < start + viewport_height:
            try:
                screen.move(
                    cursor_line - start + 1,
                    min(width - 1, cursor_column),
                )
            except curses.error:
                pass
