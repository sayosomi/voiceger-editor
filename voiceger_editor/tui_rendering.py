"""Low-level terminal layout and curses rendering for the TUI."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from typing import Any

from .caption_batch import CaptionBatch
from .styles import available_styles
from .tui_confirmation import ConfirmationDetail, confirmation_lines
from .tui_display import _display_width, _truncate_display, _wrap_active_input, _wrap_text
from .tui_rendering_batch import batch_list_document as _batch_list_document
from .tui_rendering_dictionary import (
    _DICTIONARY_SORT_LABELS,
    _dictionary_list_row,
    _dictionary_surface_column_width,
)
from .tui_rendering_editor import editor_document as _editor_document
from .tui_rendering_help import _HELP_ITEMS, help_document as _help_document
from .tui_rendering_navigation import navigation_document as _navigation_document
from .tui_rendering_settings import _OUTPUT_ENCODING_LABELS, _OUTPUT_FORMAT_LABELS
from .tui_rendering_shared import (
    _CANCEL_GENERATION_HINT,
    EditorRenderState,
    NavigationLine,
    OutputPathEditRenderState,
    TuiRenderState,
    _active_input_prefix,
    _numbered_shortcut_token,
    _positioned_title,
    background_with_cancel_generation_hint,
    format_background_operation_progress,
    status_with_cancel_generation_hint,
    setting_display as _setting_display,
)
from .tui_shortcuts import main_shortcut, menu_item
from .tui_status import EMPTY_STATUS, Status, StatusKind, format_status


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




@dataclass(frozen=True)
class StatusFooterLayout:
    """Rows reserved for the shared TUI Status footer."""

    start_row: int
    lines: tuple[str, ...]
    status: Status | None
    background_line_count: int = 0


class TuiRenderer:
    """Own terminal layout and curses drawing; documents live in focused owners."""

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
    def help_document(width: int):
        return _help_document(width)

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
        return _batch_list_document(
            batch,
            focus_key,
            width,
            pressed_adjustment,
            active_generation,
            generation_busy,
        )

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
                    f"▶ Jump to Caption: {number_jump_value}_ / {len(batch)}",
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
                    "  [0] Jump to Caption",
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
        lab_state = "LAB ON" if settings.save_lab else "LAB OFF"
        suffix = f" | {text_state} | {lab_state}"
        prefix = f"{style_name} | {settings.speed:.2f}x | Takes {settings.take_count}"
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
        return _navigation_document(state, width)

    def editor_document(
        self,
        state: TuiRenderState,
        width: int,
    ):
        return _editor_document(state, width)

    @staticmethod
    def setting_display(name: str, value: Any, voiceger_root: Any) -> str:
        return _setting_display(name, value, voiceger_root)

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
        content_start_row = 1
        if editor.kind in {
            "dictionary_japanese_list",
            "dictionary_english_list",
        }:
            entries = tuple(editor.payload.get("entries", ()))
            if len(entries) >= 10:
                if bool(editor.payload.get("number_jump_active", False)):
                    safe_add(
                        screen,
                        1,
                        0,
                        (
                            "▶ Jump to word: "
                            f"{editor.payload.get('number_jump_value', '')}_ / {len(entries)}"
                        ),
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
                        "  [0] Jump to word",
                        width,
                    )
                content_start_row = 3
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
        viewport_height = max(0, footer.start_row - content_start_row)
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
            safe_add(screen, offset + content_start_row, 0, line, width, attr)
        self._render_status_footer(screen, footer, width)
        if cursor_line is not None and start <= cursor_line < start + viewport_height:
            try:
                screen.move(
                    cursor_line - start + content_start_row,
                    min(width - 1, cursor_column),
                )
            except curses.error:
                pass

