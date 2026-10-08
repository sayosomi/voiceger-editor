"""Editor document dispatch by presentation family."""

from __future__ import annotations

from .tui_rendering_dictionary import build_document as build_dictionary_document
from .tui_rendering_editor_common import EditorDocumentBuilder
from .tui_rendering_editor_general import build_document as build_general_document
from .tui_rendering_settings import build_document as build_settings_document
from .tui_rendering_shared import (
    TuiRenderState,
    _positioned_title,
    adjustment_press_direction,
)


def editor_document(
    state: TuiRenderState,
    width: int,
) -> tuple[
    list[tuple[str, str | tuple[str, int | None] | None]],
    int | None,
    int,
]:
    builder = EditorDocumentBuilder(state, width)
    editor = builder.editor

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
    builder.lines.append(
        (
            _positioned_title(
                editor.title,
                entry_position,
                width,
                adjustment_press_direction(
                    state,
                    "dictionary",
                    "entry_navigator",
                ),
            ),
            title_key,
        )
    )

    if not build_settings_document(builder):
        if not build_dictionary_document(builder):
            build_general_document(builder)

    return builder.lines, builder.cursor_line, builder.cursor_column
