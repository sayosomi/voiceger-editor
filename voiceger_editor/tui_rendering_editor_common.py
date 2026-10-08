"""Shared editor-document construction primitives."""

from __future__ import annotations

from .tui_display import (
    _adjustable_value,
    _display_width,
    _wrap_active_input,
    _wrap_text,
)
from .tui_rendering_shared import (
    TuiRenderState,
    _active_input_prefix,
    adjustment_press_direction,
)
from .tui_shortcuts import menu_item


class EditorDocumentBuilder:
    """Accumulate one editor document without owning feature behavior."""

    def __init__(self, state: TuiRenderState, width: int) -> None:
        self.state = state
        self.width = width
        self.editor = state.editor
        assert self.editor is not None
        self.lines: list[tuple[str, str | tuple[str, int | None] | None]] = []
        self.cursor_line: int | None = None
        self.cursor_column = 0

    def plain(self, value: str = "") -> None:
        self.lines.append((value, None))

    def wrap(self, prefix: str, value: str, key=None) -> None:
        available = max(1, self.width - 1 - _display_width(prefix))
        pieces = _wrap_text(value, available)
        self.lines.append((prefix + (pieces[0] if pieces else ""), key))
        for piece in pieces[1:]:
            self.lines.append((" " * _display_width(prefix) + piece, key))

    def selectable(self, key: str) -> None:
        marker = "▶ " if self.editor.selection == key else "  "
        item = menu_item(self.editor.kind, key, self.editor.payload)
        self.lines.append((marker + item.display_label, key))

    def selectable_value(self, key: str, value: str) -> None:
        item = menu_item(self.editor.kind, key, self.editor.payload)
        self.wrapped_selectable_text(
            key,
            f"{item.display_label:<14}{_adjustable_value(value, adjustment_press_direction(self.state, 'dictionary', key))}",
        )

    def wrapped_selectable_text(
        self,
        key: str | tuple[str, int | None],
        value: str,
    ) -> None:
        marker = "▶ " if self.editor.selection == key else "  "
        marker_width = _display_width(marker)
        available = max(1, self.width - 1 - marker_width)
        pieces = _wrap_text(value, available) or [""]
        self.lines.append((marker + pieces[0], key))
        continuation = " " * marker_width
        self.lines.extend((continuation + piece, key) for piece in pieces[1:])

    def input_field(self, name: str, prefix: str | None = None) -> None:
        prefix = prefix if prefix is not None else _active_input_prefix(self.editor)
        prefix_width = _display_width(prefix)
        input_width = max(1, self.width - 1 - prefix_width)
        wrapped, cursor_row, cursor_cells = _wrap_active_input(
            self.editor.input_value,
            self.editor.input_cursor,
            input_width,
        )
        first_line = len(self.lines)
        self.lines.append((prefix + wrapped[0], name))
        continuation = " " * prefix_width
        self.lines.extend((continuation + value, name) for value in wrapped[1:])
        if self.editor.active_field == name:
            self.cursor_line = first_line + cursor_row
            self.cursor_column = prefix_width + cursor_cells

    def path_input_field(self, key: str = "path") -> None:
        item = menu_item(self.editor.kind, key, self.editor.payload)
        shortcut_prefix = (
            f"[{item.shortcut.upper()}] " if item.shortcut is not None else ""
        )
        if self.editor.active_field == key:
            self.input_field(key, f"▶ {shortcut_prefix}")
            return
        self.wrapped_selectable_text(
            key,
            shortcut_prefix + (str(self.editor.payload.get(key, "")) or "(not set)"),
        )

    def shared_output_field(self, key: str, owner: str) -> None:
        item = menu_item(self.editor.kind, key, self.editor.payload)
        output_edit = self.state.output_path_edit
        if output_edit is None or output_edit.owner != owner:
            self.wrapped_selectable_text(
                key,
                f"{item.display_label}: {self.state.settings.output_dir}",
            )
            return
        prefix = f"▶ {item.display_label}: "
        prefix_width = _display_width(prefix)
        input_width = max(1, self.width - 1 - prefix_width)
        wrapped, cursor_row, cursor_cells = _wrap_active_input(
            output_edit.value,
            output_edit.cursor,
            input_width,
        )
        first_line = len(self.lines)
        self.lines.append((prefix + wrapped[0], key))
        continuation = " " * prefix_width
        self.lines.extend((continuation + value, key) for value in wrapped[1:])
        self.cursor_line = first_line + cursor_row
        self.cursor_column = prefix_width + cursor_cells
