"""Terminal document construction and curses rendering for the TUI."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, Sequence

from ._version import __version__
from .caption_batch import CaptionBatch
from .project_info import DOCUMENTATION_URL
from .pronunciation import parse_pronunciation
from .session import UtteranceSession
from .settings import (
    Settings,
    VOICEGER_DEFAULT_TEMPERATURE,
    VOICEGER_DEFAULT_TOP_K,
    VOICEGER_DEFAULT_TOP_P,
)
from .styles import available_styles
from .tui_confirmation import ConfirmationDetail, confirmation_lines
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
from .tui_operations import BackgroundOperationProgress
from .tui_shortcuts import (
    batch_list_shortcut,
    main_shortcut,
    menu_item,
)
from .tui_status import EMPTY_STATUS, Status, StatusKind, format_status


_CANCEL_GENERATION_HINT = "[Ctrl+C] Cancel generation"

_OUTPUT_FORMAT_LABELS = {
    "wav": "WAV",
    "flac": "FLAC",
    "mp3": "MP3",
}
_OUTPUT_ENCODING_LABELS = {
    "source": "Source",
    "pcm16": "PCM 16-bit",
    "pcm24": "PCM 24-bit",
    "float32": "Float 32-bit",
}


def status_with_cancel_generation_hint(
    status: Status,
    cancel_generation_available: bool,
) -> Status:
    """Add the generation-cancellation affordance without mutating Status."""

    if not cancel_generation_available:
        return status
    message = (
        f"{status} · {_CANCEL_GENERATION_HINT}"
        if status
        else _CANCEL_GENERATION_HINT
    )
    return Status(status.kind, message)


def background_with_cancel_generation_hint(
    message: str,
    cancel_generation_available: bool,
) -> str:
    """Add the cancellation affordance to background progress presentation."""

    if not message:
        return ""
    if not cancel_generation_available:
        return message
    return f"{message} · {_CANCEL_GENERATION_HINT}"


def _wrap_footer_text(value: str, width: int) -> tuple[str, ...]:
    """Wrap footer text without splitting the cancel-generation affordance."""

    if not value:
        return ()

    width = max(1, width)
    suffix = f" · {_CANCEL_GENERATION_HINT}"
    if not value.endswith(suffix):
        return tuple(_wrap_text(value, width))

    if (
        _display_width(value) <= width
        or _display_width(_CANCEL_GENERATION_HINT) > width
    ):
        return tuple(_wrap_text(value, width))

    prefix = value[: -len(suffix)]
    lines = _wrap_text(prefix, width)
    if not lines:
        return (_CANCEL_GENERATION_HINT,)

    if _display_width(lines[-1]) + _display_width(suffix) <= width:
        lines[-1] += suffix
    else:
        lines.append(_CANCEL_GENERATION_HINT)
    return tuple(lines)


def format_background_operation_progress(
    progress: BackgroundOperationProgress | None,
    batch: CaptionBatch,
    cancel_generation_available: bool,
) -> str:
    """Format one operation-owned progress snapshot for the shared footer."""

    if progress is None:
        return ""

    owner = "Caption"
    if progress.item_id is not None:
        try:
            item = batch.get_item(progress.item_id)
        except KeyError:
            pass
        else:
            owner = f"Caption {batch.items.index(item) + 1}"

    if progress.operation == "initial":
        verb = "Generating"
    elif progress.operation in {"regenerate_one", "regenerate_all"}:
        verb = "Regenerating"
    elif progress.operation == "batch_generate":
        verb = "Generating selected"
    else:
        verb = "Working"

    parts = [verb]
    if progress.item_id is not None:
        parts.append(owner)
    if progress.take_number is not None:
        if progress.take_total is not None and progress.operation != "regenerate_one":
            parts.append(f"Take {progress.take_number}/{progress.take_total}")
        else:
            parts.append(f"Take {progress.take_number}")
    if progress.operation == "batch_generate" and progress.total > 0:
        parts.append(f"Overall {progress.completed}/{progress.total}")

    return background_with_cancel_generation_hint(
        " · ".join(parts),
        cancel_generation_available,
    )


_DICTIONARY_SORT_LABELS = {
    "surface_asc": "Surface ↑",
    "surface_desc": "Surface ↓",
    "word_type": "Word type",
    "priority_asc": "Priority ↑",
    "priority_desc": "Priority ↓",
    "added_asc": "Added ↑",
    "added_desc": "Added ↓",
}


_HELP_ITEMS = (
    ("Up/Down", ": move one selectable item"),
    (
        "Left/Right",
        ": Batch List Takes; Batch Item generation count or pronunciation controls",
    ),
    (
        "Enter",
        ": open a Batch List Caption or activate the focused Batch Item row",
    ),
    ("Space", ": toggle Batch List inclusion or replay a focused Take"),
    (
        main_shortcut("delete_caption").shortcut.upper(),
        ": delete current Batch Item Caption through confirmation",
    ),
    ("Esc", ": one level back"),
    ("Ctrl+C", ": cancel active Take generation; otherwise quit"),
    ("Tab / Shift+Tab", ": next / previous major Batch Item section"),
    (
        " / ".join(
            main_shortcut(name).shortcut.upper()
            for name in ("caption", "build_pronunciation", "add_section", "generate")
        ),
        ": Caption / Build pronunciation / Add section / Generate or regenerate all",
    ),
    ("1-9", ": focus and play an available Take"),
    ("[ / ]", ": previous / next Batch Item Caption or Dictionary word"),
    (main_shortcut("clear_candidates").shortcut.upper(), ": clear candidates through confirmation"),
    ("R", ": regenerate the focused Take"),
    (main_shortcut("settings").shortcut.upper(), ": open Settings"),
    (main_shortcut("dictionary").shortcut.upper(), ": open Dictionary"),
    ("A / G", ": Batch List Add captions / Generate selected"),
    (None, "Menu mode: editor/modal action letters are active."),
    (None, "Editing: Enter finishes; printable shortcut letters insert text."),
    (None, "Add captions: Ctrl+N inserts a new line; Enter finishes editing."),
    (main_shortcut("help").shortcut, ": open or close Help"),
    (main_shortcut("quit").shortcut.upper(), ": Quit"),
)


class EditorRenderState(Protocol):
    kind: str
    title: str
    selection: str | tuple[str, int | None]
    payload: dict[str, Any]
    active_field: str | None
    input_value: str
    input_cursor: int
    error: Status


class OutputPathEditRenderState(Protocol):
    owner: str
    value: str
    cursor: int


@dataclass(frozen=True)
class TuiRenderState:
    """Read-only snapshot of the application values needed to render a frame."""

    voiceger_root: Any
    settings: Settings
    session: UtteranceSession | None
    focus_key: tuple[str, int | None]
    status: Status
    segments: Sequence[tuple[str, str, int | None]]
    pronunciation_rows: Sequence[PronunciationRow]
    busy: bool
    worker_operation: str | None
    worker_target: int | None
    operation_completed: int
    operation_total: int
    pressed_adjustment: tuple[str, str, int] | None
    editor: EditorRenderState | None
    accepted_take_number: int | None = None
    batch_item_position: tuple[int, int] | None = None
    batch_item_id: str | None = None
    active_generation_item_id: str | None = None
    background_status: str = ""
    output_path_edit: OutputPathEditRenderState | None = None


@dataclass(frozen=True)
class NavigationLine:
    text: str
    key: tuple[str, int | None] | None
    focus_owner: tuple[str, int | None] | None = None
    bold_spans: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class StatusFooterLayout:
    """Rows reserved for the shared TUI Status footer."""

    start_row: int
    lines: tuple[str, ...]
    status: Status | None
    background_line_count: int = 0


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
    if editor.kind == "audio_output_settings":
        if editor.active_field == "filename_template":
            return "▶ Filename template  "
        return "▶ "
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
        if editor.active_field == "output_dir":
            item = menu_item(editor.kind, "output_dir", editor.payload)
            if item.shortcut is not None:
                return f"▶ [{item.shortcut.upper()}] {label:<12}"
        return f"▶ {label:<12}"
    if editor.kind in {
        "dictionary_import_path",
        "batch_recipe_read_path",
    }:
        item = menu_item(editor.kind, "path", editor.payload)
        prefix = f"[{item.shortcut.upper()}] " if item.shortcut is not None else ""
        return f"▶ {prefix}"
    if (
        editor.kind == "batch_recipe_write_path"
        and editor.active_field == "file_name"
    ):
        return "▶ File name: "
    return "▶ Input: "


def _duration_seconds(frame_count: int, sampling_rate: int) -> float:
    try:
        return frame_count / float(sampling_rate)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _positioned_title(
    title: str,
    position: tuple[int, int] | None,
    width: int,
    direction: int | None = None,
) -> str:
    if position is None:
        return title
    current, total = position
    indicator = _adjustable_value(f"{current} / {total}", direction)
    available = max(1, width - 1)
    title_width = max(0, available - _display_width(indicator) - 1)
    title_part = _truncate_display(title, title_width)
    gap = max(
        1,
        available - _display_width(title_part) - _display_width(indicator),
    )
    return title_part + (" " * gap) + indicator


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

    def _status_attribute(self, status: Status) -> int:
        attr = self._attribute("A_BOLD")
        if status.kind is StatusKind.ERROR:
            return attr | (
                self._error_color_attr or self._attribute("A_REVERSE")
            )
        if status.kind is StatusKind.WARNING:
            return attr | (
                self._warning_color_attr or self._attribute("A_REVERSE")
            )
        return attr

    def _status_footer_layout(
        self,
        status: Status,
        height: int,
        width: int,
        *,
        fallback_hint: str | None = None,
        background_status: str = "",
    ) -> StatusFooterLayout:
        available = max(1, width - 1)
        background_lines = _wrap_footer_text(background_status, available)
        visible_status = status if status else None
        text = (
            format_status(visible_status)
            if visible_status is not None
            else (fallback_hint or "")
        )
        status_lines = _wrap_footer_text(text, available)
        lines = background_lines + status_lines
        reserved_height = max(1, len(lines))
        start_row = max(0, height - reserved_height)
        if height <= 0:
            visible_lines: tuple[str, ...] = ()
        else:
            visible_lines = lines[: max(0, height - start_row)]
        return StatusFooterLayout(
            start_row,
            visible_lines,
            visible_status,
            min(len(background_lines), len(visible_lines)),
        )

    def _render_status_footer(
        self,
        screen: Any,
        layout: StatusFooterLayout,
        width: int,
    ) -> None:
        if not layout.lines:
            return
        for offset, line in enumerate(layout.lines):
            attr = (
                self._attribute("A_BOLD")
                if offset < layout.background_line_count or layout.status is None
                else self._status_attribute(layout.status)
            )
            self._safe_add(
                screen,
                layout.start_row + offset,
                0,
                line,
                width,
                attr,
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

    @staticmethod
    def help_document(width: int) -> list[tuple[tuple[int, str, bool], ...]]:
        """Build all physical Help rows before viewport clipping."""

        column = 1
        available = max(1, width - column - 1)
        rows: list[tuple[tuple[int, str, bool], ...]] = []

        def append_plain(value: str) -> None:
            for piece in _wrap_text(value, available) or [""]:
                rows.append(((column, piece, False),))

        append_plain(f"Voiceger Editor {__version__}")
        append_plain(f"Docs: {DOCUMENTATION_URL}")
        rows.append(())

        for shortcut, suffix in _HELP_ITEMS:
            if shortcut is None:
                append_plain(suffix)
                continue

            key_width = _display_width(shortcut)
            if key_width >= available:
                for piece in _wrap_text(shortcut, available) or [""]:
                    rows.append(((column, piece, True),))
                for piece in _wrap_text(suffix, available) or [""]:
                    rows.append(((column, piece, False),))
                continue

            explanation_pieces = _wrap_text(
                suffix, max(1, available - key_width)
            ) or [""]
            rows.append(
                (
                    (column, shortcut, True),
                    (column + key_width, explanation_pieces[0], False),
                )
            )
            for piece in explanation_pieces[1:]:
                rows.append(((column + key_width, piece, False),))

        return rows

    def help_max_scroll(
        self,
        height: int,
        width: int,
        status: Status = EMPTY_STATUS,
        background_status: str = "",
    ) -> int:
        """Return the largest valid Help body scroll offset."""

        footer = self._status_footer_layout(
            status,
            height,
            width,
            background_status=background_status,
        )
        back_row = max(0, footer.start_row - 1)
        body_rows = max(0, back_row - 1)
        return max(0, len(self.help_document(width)) - body_rows)

    def render_help(
        self,
        screen: Any,
        width: int,
        scroll: int = 0,
        *,
        status: Status = EMPTY_STATUS,
        background_status: str = "",
    ) -> int:
        """Render one Help viewport and return its clamped scroll offset."""

        safe_add = self._safe_add
        height = screen.getmaxyx()[0]
        footer = self._status_footer_layout(
            status,
            height,
            width,
            background_status=background_status,
        )
        back_row = max(0, footer.start_row - 1)
        if back_row > 0:
            safe_add(screen, 0, 0, "HELP", width, self._attribute("A_BOLD"))

        document = self.help_document(width)
        body_rows = max(0, back_row - 1)
        max_scroll = max(0, len(document) - body_rows)
        scroll = max(0, min(scroll, max_scroll))
        bold = self._attribute("A_BOLD")

        for row, segments in enumerate(
            document[scroll : scroll + body_rows],
            start=1,
        ):
            for column, value, is_bold in segments:
                safe_add(screen, row, column, value, width, bold if is_bold else 0)

        if footer.start_row > 0:
            safe_add(
                screen,
                back_row,
                0,
                f"▶ {menu_item('help', 'back').display_label}",
                width,
                self._focus_attribute(),
            )
        self._render_status_footer(screen, footer, width)
        return scroll

    def render_batch_delete_confirmation(
        self,
        screen: Any,
        caption: str,
        selection: str,
        status: Status,
        height: int,
        width: int,
        background_status: str = "",
    ) -> None:
        """Render Caption deletion with the standard modal layout."""

        safe_add = self._safe_add
        safe_add(
            screen,
            0,
            0,
            "DELETE CAPTION?",
            width,
            self._attribute("A_REVERSE") | self._attribute("A_BOLD"),
        )
        document = list(
            confirmation_lines(
                "batch_delete_confirmation",
                selection,
                warning="This Caption and its temporary Takes will be removed.",
                details=(ConfirmationDetail("Caption", caption),),
                width=width,
                wrap_text=_wrap_text,
            )
        )
        footer = self._status_footer_layout(
            status,
            height,
            width,
            background_status=background_status,
        )
        viewport_height = max(0, footer.start_row - 1)
        focused_index = next(
            index for index, (_line, key) in enumerate(document) if key == "delete"
        )
        start = max(0, focused_index - viewport_height // 3)
        if start + viewport_height > len(document):
            start = max(0, len(document) - viewport_height)
        for offset, (line, key) in enumerate(document[start : start + viewport_height]):
            safe_add(
                screen,
                offset + 1,
                0,
                line,
                width,
                self._focus_attribute() if key == selection else 0,
            )
        self._render_status_footer(screen, footer, width)

    def batch_list_document(
        self,
        batch: CaptionBatch,
        focus_key: tuple[str, int | None],
        width: int,
        pressed_adjustment: tuple[str, str, int] | None = None,
        active_generation: tuple[str, int, int] | None = None,
        generation_busy: bool = False,
    ) -> list[NavigationLine]:
        """Build the top-level Batch List document."""

        lines: list[NavigationLine] = []

        def plain(value: str = "") -> None:
            lines.append(NavigationLine(value, None))

        def action(key: tuple[str, int | None], label: str) -> None:
            marker = "▶ " if key == focus_key else "  "
            lines.append(NavigationLine(marker + label, key, key))

        take_direction = (
            pressed_adjustment[2]
            if (
                pressed_adjustment is not None
                and pressed_adjustment[:2] == ("batch_list", "takes")
            )
            else None
        )
        action(
            ("takes", None),
            f"Takes {_adjustable_value(str(batch.default_take_count), take_direction)}",
        )
        plain()

        for index, item in enumerate(batch.items):
            key = ("caption", index)
            marker = "▶ " if key == focus_key else "  "
            selected = "x" if item.included_for_generation else " "
            active_progress = (
                active_generation
                if active_generation is not None
                and active_generation[0] == item.item_id
                else None
            )
            if active_progress is not None:
                _item_id, completed, total = active_progress
                percent = round(completed * 100 / total)
                review_state = f"[{percent}%] "
            elif item.is_accepted:
                review_state = "[✓] "
            elif item.generation_outcome in {"cancelled", "failed"}:
                review_state = "[⚠] "
            elif item.generation_outcome == "completed":
                review_state = "[!] "
            else:
                review_state = ""
            prefix = f"{marker}[{selected}] {index + 1}  {review_state}"
            available = max(1, width - 1 - _display_width(prefix))
            pieces = _wrap_text(item.caption, available) or [""]
            lines.append(NavigationLine(prefix + pieces[0], key, key))
            continuation = " " * _display_width(prefix)
            lines.extend(
                NavigationLine(continuation + piece, None, key)
                for piece in pieces[1:]
            )

        if batch.items:
            plain()
        action_groups = (
            ("add_captions", "generate_selected"),
            ("read_batch", "write_batch"),
            ("settings", "dictionary"),
            ("help", "quit"),
        )
        for group_index, names in enumerate(action_groups):
            if group_index:
                plain()
            for name in names:
                label = batch_list_shortcut(name).display_label
                if name == "generate_selected" and generation_busy:
                    label += " [busy]"
                action((name, None), label)
        return lines

    def render_batch_list(
        self,
        screen: Any,
        batch: CaptionBatch,
        focus_key: tuple[str, int | None],
        status: Status,
        height: int,
        width: int,
        *,
        delete_confirmation_caption: str | None = None,
        delete_confirmation_selection: str = "delete",
        pressed_adjustment: tuple[str, str, int] | None = None,
        active_generation: tuple[str, int, int] | None = None,
        generation_busy: bool = False,
        background_status: str = "",
        number_jump_active: bool = False,
        number_jump_value: str = "",
    ) -> None:
        """Render the top-level Batch List screen."""

        if delete_confirmation_caption is not None:
            self.render_batch_delete_confirmation(
                screen,
                delete_confirmation_caption,
                delete_confirmation_selection,
                status,
                height,
                width,
                background_status,
            )
            return

        safe_add = self._safe_add
        selected_count = len(batch.included_items)
        accepted_count = len(batch.accepted_items)
        requested = sum(
            batch.effective_take_count(item) for item in batch.included_items
        )
        take_label = "take" if requested == 1 else "takes"
        header = (
            f"BATCH LIST · {selected_count}/{len(batch)} selected · "
            f"{requested} {take_label} · Accepted {accepted_count}/{len(batch)}"
        )
        safe_add(
            screen,
            0,
            0,
            header,
            width,
            self._attribute("A_BOLD"),
        )
        content_start_row = 2
        if len(batch) >= 10:
            if number_jump_active:
                safe_add(
                    screen,
                    1,
                    0,
                    f"▶ Jump to number: {number_jump_value}_ / {len(batch)}",
                    width,
                    self._focus_attribute(),
                )
                safe_add(
                    screen,
                    2,
                    0,
                    "  [Enter] Open   [Esc] Cancel",
                    width,
                )
            else:
                safe_add(
                    screen,
                    1,
                    0,
                    "  [0] Jump to number",
                    width,
                )
            content_start_row = 3
        lines = self.batch_list_document(
            batch,
            focus_key,
            width,
            pressed_adjustment,
            active_generation,
            generation_busy,
        )
        footer = self._status_footer_layout(
            status,
            height,
            width,
            background_status=background_status,
        )
        viewport_height = max(0, footer.start_row - content_start_row)
        focused_index = next(
            (
                index
                for index, line in enumerate(lines)
                if line.focus_owner == focus_key
            ),
            0,
        )
        start = max(0, focused_index - viewport_height // 3)
        if start + viewport_height > len(lines):
            start = max(0, len(lines) - viewport_height)
        for offset, line in enumerate(lines[start : start + viewport_height]):
            row = content_start_row + offset
            focused = line.focus_owner == focus_key
            safe_add(
                screen,
                row,
                0,
                line.text,
                width,
                self._focus_attribute() if focused else 0,
            )
        self._render_status_footer(screen, footer, width)

    def render_navigation(
        self,
        screen: Any,
        state: TuiRenderState,
        height: int,
        width: int,
        *,
        title: str = "Voiceger Editor",
    ) -> None:
        safe_add = self._safe_add
        header = _positioned_title(
            title,
            state.batch_item_position,
            width,
            self._adjustment_press_direction(state, "navigation", "batch_item"),
        )
        header_attr = self._attribute("A_BOLD")
        if state.focus_key == ("batch_item", None):
            header_attr |= self._focus_attribute()
        safe_add(
            screen,
            0,
            0,
            header,
            width,
            header_attr,
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
        output_edit = state.output_path_edit
        output_cursor_column: int | None = None
        if output_edit is not None and output_edit.owner == "batch_item":
            output_prefix = "▶ " + main_shortcut("output").display_with_label("Output: ")
            input_width = max(1, width - 1 - _display_width(output_prefix))
            wrapped, cursor_row, cursor_cells = _wrap_active_input(
                output_edit.value,
                output_edit.cursor,
                input_width,
            )
            visible = wrapped[min(cursor_row, len(wrapped) - 1)]
            safe_add(
                screen,
                2,
                0,
                output_prefix + visible,
                width,
                self._focus_attribute(),
            )
            output_cursor_column = _display_width(output_prefix) + cursor_cells
        else:
            safe_add(
                screen,
                2,
                0,
                output_marker
                + main_shortcut("output").display_with_label(
                    f"Output: {settings.output_dir}"
                ),
                width,
                output_attr,
            )

        lines = self.navigation_document(state, width)
        footer = self._status_footer_layout(
            state.status,
            height,
            width,
            background_status=state.background_status,
        )
        viewport_height = max(0, footer.start_row - 4)
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

        self._render_status_footer(screen, footer, width)
        if output_cursor_column is not None:
            try:
                screen.move(2, min(width - 1, output_cursor_column))
            except curses.error:
                pass

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
            prefix = (
                f"{marker}{main_shortcut('caption').display_with_label('Caption')} : "
            )
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
                if item.punctuation_suffix:
                    tokens[-1] += item.punctuation_suffix
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
            owns_generation = (
                state.busy
                and state.batch_item_id is not None
                and state.batch_item_id == state.active_generation_item_id
            )
            if owns_generation:
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
                if (
                    state.busy
                    and state.worker_operation
                    in {"initial", "regenerate_one", "regenerate_all", "batch_generate"}
                ):
                    generate_label += " [busy]"
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
                accepted_marker = (
                    "✓ " if candidate.number == state.accepted_take_number else ""
                )
                label = (
                    f"[{candidate.number}] {accepted_marker}Take {candidate.number}  {duration:.2f}s"
                    if candidate.number <= 9
                    else f"{accepted_marker}Take {candidate.number}  {duration:.2f}s"
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
            action(
                ("delete_caption", None),
                main_shortcut("delete_caption").display_label,
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

        def selectable_value(key: str, value: str) -> None:
            item = menu_item(editor.kind, key, editor.payload)
            wrapped_selectable_text(
                key,
                f"{item.display_label:<14}{_adjustable_value(value, self._adjustment_press_direction(state, 'dictionary', key))}",
            )

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

        def path_input_field(key: str = "path") -> None:
            item = menu_item(editor.kind, key, editor.payload)
            shortcut_prefix = (
                f"[{item.shortcut.upper()}] " if item.shortcut is not None else ""
            )
            if editor.active_field == key:
                input_field(key, f"▶ {shortcut_prefix}")
                return
            wrapped_selectable_text(
                key,
                shortcut_prefix + (str(editor.payload.get(key, "")) or "(not set)"),
            )

        def shared_output_field(key: str, owner: str) -> None:
            nonlocal cursor_line, cursor_column
            item = menu_item(editor.kind, key, editor.payload)
            output_edit = state.output_path_edit
            if output_edit is None or output_edit.owner != owner:
                wrapped_selectable_text(
                    key,
                    f"{item.display_label}: {state.settings.output_dir}",
                )
                return
            prefix = f"▶ {item.display_label}: "
            prefix_width = _display_width(prefix)
            input_width = max(1, width - 1 - prefix_width)
            wrapped, cursor_row, cursor_cells = _wrap_active_input(
                output_edit.value,
                output_edit.cursor,
                input_width,
            )
            first_line = len(lines)
            lines.append((prefix + wrapped[0], key))
            continuation = " " * prefix_width
            lines.extend((continuation + value, key) for value in wrapped[1:])
            cursor_line = first_line + cursor_row
            cursor_column = prefix_width + cursor_cells

        entry_position: tuple[int, int] | None = None
        if editor.kind in {
            "dictionary_japanese_entry",
            "dictionary_english_entry",
        }:
            entry_index = editor.payload.get("entry_index")
            entry_total = editor.payload.get("entry_total")
            if (
                isinstance(entry_index, int)
                and isinstance(entry_total, int)
                and entry_total > 0
                and 0 <= entry_index < entry_total
            ):
                entry_position = (entry_index + 1, entry_total)
        title_key = "entry_navigator" if entry_position is not None else None
        lines.append(
            (
                _positioned_title(
                    editor.title,
                    entry_position,
                    width,
                    self._adjustment_press_direction(
                        state,
                        "dictionary",
                        "entry_navigator",
                    ),
                ),
                title_key,
            )
        )
        if editor.kind in {
            "build_confirmation",
            "batch_recipe_replace_confirmation",
            "dictionary_delete_confirmation",
            "dictionary_discard_confirmation",
            "delete_confirmation",
            "clear_candidates_confirmation",
        }:
            details: tuple[ConfirmationDetail, ...] = ()
            if editor.kind == "batch_recipe_replace_confirmation":
                details = (
                    ConfirmationDetail("Path", str(editor.payload["path"])),
                )
            elif editor.kind == "dictionary_delete_confirmation":
                if editor.payload["language"] == "ja":
                    pronunciation = " ".join(
                        _japanese_mora_tokens(
                            editor.payload["moras"],
                            editor.payload["accent"] or len(editor.payload["moras"]),
                        )
                    )
                else:
                    pronunciation = " ".join(editor.payload["phonemes"])
                details = (
                    ConfirmationDetail("Surface", str(editor.payload["surface"])),
                    ConfirmationDetail("Pronunciation", pronunciation),
                )
            lines.extend(
                confirmation_lines(
                    editor.kind,
                    str(editor.selection),
                    warning=str(editor.payload["warning"]),
                    details=details,
                    payload=editor.payload,
                    width=width,
                    wrap_text=_wrap_text,
                )
            )
        elif editor.kind == "caption":
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
                    input_field(
                        key,
                        _active_input_prefix(editor)
                        if key == "output_dir"
                        else f"▶ {label:<16}",
                    )
                else:
                    if key in {
                        "style_id", "speed", "take_count",
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
                if key == "output_dir":
                    selectable("audio_output")
            selectable("reset_sampling")
            plain("Actions")
            selectable("apply")
            selectable("reset")
            selectable("back")
            plain("* Applying this setting clears existing candidates.")
        elif editor.kind == "audio_output_settings":
            draft = editor.payload["draft_settings"]
            output_format = str(draft.get("output_format", "wav"))
            controls = [
                (
                    "output_format",
                    _OUTPUT_FORMAT_LABELS.get(output_format, output_format),
                )
            ]
            if output_format == "mp3":
                bitrate = str(draft.get("mp3_bitrate", "192k"))
                controls.append(("mp3_bitrate", bitrate.replace("k", " kbps")))
            else:
                encoding_key = (
                    "wav_encoding" if output_format == "wav" else "flac_encoding"
                )
                output_encoding = str(draft.get(encoding_key, "source"))
                controls.append(
                    (
                        "output_encoding",
                        _OUTPUT_ENCODING_LABELS.get(output_encoding, output_encoding),
                    )
                )
            control_payload = dict(editor.payload)
            control_payload["show_output_encoding"] = output_format != "mp3"
            control_payload["show_mp3_bitrate"] = output_format == "mp3"
            plain()
            for key, value in controls:
                item = menu_item(editor.kind, key, control_payload)
                marker = "▶ " if editor.selection == key else "  "
                value = _adjustable_value(
                    value,
                    self._adjustment_press_direction(state, "settings", key),
                )
                lines.append((f"{marker}{item.display_label:<18}{value}", key))
            plain()
            if editor.active_field == "filename_template":
                input_field("filename_template")
            else:
                wrapped_selectable_text(
                    "filename_template",
                    "Filename template  " + str(draft["filename_template"]),
                )
            plain()
            plain("Preview")
            preview_error = str(editor.payload.get("filename_preview_error", ""))
            if preview_error:
                wrap("  Invalid: ", preview_error)
            else:
                wrap("  ", str(editor.payload.get("filename_preview", "")))
            plain()
            plain("Sidecars")
            for key in ("save_text", "save_lab"):
                item = menu_item(editor.kind, key, editor.payload)
                marker = "▶ " if editor.selection == key else "  "
                value = "ON" if draft.get(key, False) else "OFF"
                value = _adjustable_value(
                    value,
                    self._adjustment_press_direction(state, "settings", key),
                )
                lines.append((f"{marker}{item.display_label:<14}{value}", key))
            plain()
            plain("Tokens: YYYY MM DD HH mm ss · {text} {style}")
            selectable("back")
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
        elif editor.kind == "batch_recipe_read_path":
            plain()
            plain("File path")
            path_input_field()
            plain()
            selectable("read")
            selectable("back")
        elif editor.kind == "batch_recipe_write_path":
            plain()
            shared_output_field("output", "batch_write")
            plain()
            plain("File name")
            if editor.active_field == "file_name":
                input_field("file_name", "▶ ")
            else:
                wrapped_selectable_text(
                    "file_name",
                    str(editor.payload.get("file_name", "")) or "(not set)",
                )
            plain()
            selectable("write")
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
            selectable("import")
            selectable("export")
            plain()
            selectable("back")
        elif editor.kind == "dictionary_export":
            plain()
            shared_output_field("output", "dictionary_export")
            plain()
            selectable("voiceger")
            plain("  Japanese + English")
            plain()
            selectable("voicevox")
            plain("  Japanese dictionary only")
            plain()
            selectable("back")
        elif editor.kind == "dictionary_import_path":
            plain()
            plain("File path")
            path_input_field()
            plain()
            selectable("review")
            selectable("back")
        elif editor.kind == "dictionary_import_review":
            plain()
            total_count = int(editor.payload.get("total_count", 0))
            exact_count = int(editor.payload.get("exact_duplicate_count", 0))
            review_count = int(editor.payload.get("review_count", 0))
            plain(f"{total_count} words found")
            plain(f"{exact_count} already exist")
            plain(f"{review_count} to review")
            plain()
            word_type_labels = tuple(editor.payload.get("word_type_labels", ()))
            for index, item in enumerate(editor.payload.get("items", ())):
                key = ("import_entry", index)
                marker = "▶ " if editor.selection == key else "  "
                checkbox = "[x]" if item.selected else "[ ]"
                attention = "!" if item.relation.value == "conflict" else " "
                word_type_label = (
                    word_type_labels[index] if index < len(word_type_labels) else ""
                )
                suffix = f"  {word_type_label}" if word_type_label else ""
                value = f"{checkbox} {attention} {item.incoming.surface}{suffix}"
                available = max(1, width - 1 - _display_width(marker))
                lines.append((marker + _truncate_display(value, available), key))
            plain()
            selectable("import_selected")
            selectable("clear_selection")
            selectable("back")
        elif editor.kind == "dictionary_import_japanese_detail":
            plain()
            item = editor.payload["item"]
            incoming = item.incoming
            plain("Incoming")
            wrap("  Surface        ", str(incoming.surface))
            wrap("  Pronunciation  ", str(incoming.pronunciation))
            plain(f"  Accent         {incoming.accent_type}")
            marker = "▶ " if editor.selection == "word_type" else "  "
            lines.append(
                (
                    f"{marker}品詞            "
                    + _adjustable_value(
                        str(editor.payload["word_type_label"]),
                        self._adjustment_press_direction(
                            state,
                            "dictionary",
                            "word_type",
                        ),
                    ),
                    "word_type",
                )
            )
            plain(f"  Priority       {incoming.priority}")
            existing = item.existing
            if existing is not None:
                plain()
                plain("Existing")
                wrap("  Surface        ", str(existing.surface))
                wrap("  Pronunciation  ", str(existing.pronunciation))
                plain(f"  Accent         {existing.accent_type}")
                plain(
                    f"  品詞            {editor.payload['existing_word_type_label']}"
                )
                plain(f"  Priority       {existing.priority}")
            plain()
            selectable("back")
        elif editor.kind == "dictionary_import_english_detail":
            plain()
            item = editor.payload["item"]
            incoming = item.incoming
            plain("Incoming")
            wrap("  Surface        ", str(incoming.surface))
            wrap("  Pronunciation  ", " ".join(incoming.phonemes))
            existing = item.existing
            if existing is not None:
                plain()
                plain("Existing")
                wrap("  Surface        ", str(existing.surface))
                wrap("  Pronunciation  ", " ".join(existing.phonemes))
            plain()
            selectable("back")
        elif editor.kind == "dictionary_japanese_list":
            plain()
            entries = editor.payload["entries"]
            text_filter = str(editor.payload.get("text_filter", ""))
            word_type_filter = str(
                editor.payload.get("word_type_filter") or "ALL"
            )
            filter_active = bool(editor.payload.get("filter_enabled", False))
            visible_count = int(editor.payload.get("visible_count", len(entries)))
            total_count = int(editor.payload.get("total_count", len(entries)))
            if filter_active:
                plain(f"  Showing {visible_count} / {total_count} words")
            if not entries:
                plain(
                    "  No matching Japanese dictionary words."
                    if filter_active and total_count
                    else "  No Japanese dictionary words."
                )
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
            selectable_value(
                "sort",
                _DICTIONARY_SORT_LABELS.get(
                    str(editor.payload.get("sort_mode", "surface_asc")),
                    str(editor.payload.get("sort_mode", "surface_asc")),
                ),
            )
            filter_configured = bool(text_filter.strip()) or word_type_filter != "ALL"
            if not filter_configured:
                item = menu_item(editor.kind, "filter", editor.payload)
                wrapped_selectable_text("filter", f"{item.display_label:<14}Not set")
            else:
                filter_summary = "Off"
                if filter_active:
                    parts = []
                    if text_filter.strip():
                        parts.append(text_filter.strip())
                    if word_type_filter != "ALL":
                        parts.append(word_type_filter)
                    filter_summary = "On" + (
                        f": {' · '.join(parts)}" if parts else ""
                    )
                selectable_value("filter", filter_summary)
            selectable("add")
            if entries:
                selectable("delete")
            selectable("back")
        elif editor.kind == "dictionary_english_list":
            plain()
            entries = editor.payload["entries"]
            text_filter = str(editor.payload.get("text_filter", ""))
            filter_active = bool(editor.payload.get("filter_enabled", False))
            visible_count = int(editor.payload.get("visible_count", len(entries)))
            total_count = int(editor.payload.get("total_count", len(entries)))
            if filter_active:
                plain(f"  Showing {visible_count} / {total_count} words")
            if not entries:
                plain(
                    "  No matching English dictionary words."
                    if filter_active and total_count
                    else "  No English dictionary words."
                )
            for index, entry in enumerate(entries):
                key = ("entry", index)
                wrapped_selectable_text(
                    key,
                    f"{entry.surface}      {' '.join(entry.phonemes)}",
                )
            plain()
            selectable_value(
                "sort",
                _DICTIONARY_SORT_LABELS.get(
                    str(editor.payload.get("sort_mode", "surface_asc")),
                    str(editor.payload.get("sort_mode", "surface_asc")),
                ),
            )
            if not text_filter.strip():
                item = menu_item(editor.kind, "filter", editor.payload)
                wrapped_selectable_text("filter", f"{item.display_label:<14}Not set")
            else:
                selectable_value(
                    "filter",
                    (
                        f"On: {text_filter.strip()}"
                        if filter_active
                        else "Off"
                    ),
                )
            selectable("add")
            if entries:
                selectable("delete")
            selectable("back")
        elif editor.kind == "dictionary_sort":
            plain()
            modes = tuple(editor.payload["modes"])
            for index, mode in enumerate(modes):
                key = ("sort", index)
                wrapped_selectable_text(
                    key,
                    _DICTIONARY_SORT_LABELS.get(str(mode), str(mode)),
                )
            plain()
            selectable("back")
        elif editor.kind == "dictionary_japanese_filter":
            plain()
            plain("Surface / Pronunciation")
            if editor.active_field == "text_query":
                input_field("text_query", "▶ Query          ")
            else:
                marker = "▶ " if editor.selection == "text_query" else "  "
                wrap(
                    marker + "Query          ",
                    str(editor.payload["text_query"]) or "(any)",
                    "text_query",
                )
            marker = "▶ " if editor.selection == "word_type" else "  "
            lines.append(
                (
                    f"{marker}Word type      {_adjustable_value(str(editor.payload['word_type_filter']), self._adjustment_press_direction(state, 'dictionary', 'word_type'))}",
                    "word_type",
                )
            )
            plain()
            selectable("apply")
            selectable("clear")
            selectable("back")
        elif editor.kind == "dictionary_english_filter":
            plain()
            plain("Surface / ARPAbet")
            if editor.active_field == "text_query":
                input_field("text_query", "▶ Query          ")
            else:
                marker = "▶ " if editor.selection == "text_query" else "  "
                wrap(
                    marker + "Query          ",
                    str(editor.payload["text_query"]) or "(any)",
                    "text_query",
                )
            plain()
            selectable("apply")
            selectable("clear")
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
            selectable("generate_pronunciation")
            plain()
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
                    f"{marker}Word type      {_adjustable_value(str(editor.payload['word_type_label']), self._adjustment_press_direction(state, 'dictionary', 'word_type'))}",
                    "word_type",
                )
            )
            marker = "▶ " if editor.selection == "priority" else "  "
            lines.append(
                (
                    f"{marker}Priority       {_adjustable_value(str(editor.payload['priority']), self._adjustment_press_direction(state, 'dictionary', 'priority'))}",
                    "priority",
                )
            )
            plain()
            selectable("preview")
            selectable("save")
            if editor.payload.get("can_delete"):
                plain()
                selectable("delete")
            plain()
            selectable("dictionary")
            selectable("back")
        elif editor.kind == "dictionary_english_entry":
            plain()
            if editor.active_field == "surface":
                input_field("surface", "▶ Surface        ")
            else:
                marker = "▶ " if editor.selection == "surface" else "  "
                wrap(marker + "Surface        ", editor.payload["surface"], "surface")
            selectable("generate_pronunciation")
            plain()
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
            selectable("preview")
            selectable("save")
            if editor.payload.get("can_delete"):
                plain()
                selectable("delete")
            plain()
            selectable("dictionary")
            selectable("back")
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
                (
                    f"{marker}{language_item.label:<12}{_adjustable_value(language, self._adjustment_press_direction(state, 'editor', 'language'))}",
                    "language",
                )
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
        header, header_key = document[0]
        if header_key is None:
            header_attr = self._attribute("A_REVERSE") | self._attribute("A_BOLD")
        else:
            header_attr = self._attribute("A_BOLD")
            if header_key == editor.selection:
                header_attr |= self._focus_attribute()
        safe_add(
            screen,
            0,
            0,
            header,
            width,
            header_attr,
        )
        document = document[1:]
        if cursor_line is not None:
            cursor_line -= 1
        status = editor.error or state.status
        footer = self._status_footer_layout(
            status,
            height,
            width,
            background_status=state.background_status,
            fallback_hint=(
                (
                    "Ctrl+N: New line   Enter: Finish editing   Esc: Back"
                    if (
                        editor.kind == "caption"
                        and editor.payload.get("multiline", False)
                    )
                    else "Enter: Finish editing   Esc: Back"
                )
                if not status and editor.active_field is not None
                else None
            ),
        )
        viewport_height = max(0, footer.start_row - 1)
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
        self._render_status_footer(screen, footer, width)
        if cursor_line is not None and start <= cursor_line < start + viewport_height:
            try:
                screen.move(
                    cursor_line - start + 1,
                    min(width - 1, cursor_column),
                )
            except curses.error:
                pass
