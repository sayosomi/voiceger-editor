"""Read-only document for per-Item Voice editing."""

from __future__ import annotations

from .tui_display import _adjustable_value
from .tui_rendering_editor_common import EditorDocumentBuilder
from .tui_rendering_shared import adjustment_press_direction, setting_display


def build_document(builder: EditorDocumentBuilder) -> bool:
    editor = builder.editor
    if editor.kind != "item_voice":
        return False
    builder.plain()
    for key in ("style_id", "speed"):
        label = "Style" if key == "style_id" else "Speed"
        if editor.active_field == key:
            builder.input_field(key, f"▶ {label:<12}")
        else:
            display = setting_display(key, editor.payload[key], builder.state.voiceger_root)
            if key == "speed":
                display += "x"
            value = _adjustable_value(
                display,
                adjustment_press_direction(builder.state, "item_voice", key),
            )
            builder.wrapped_selectable_text(key, f"{label:<12}{value}")
    builder.plain()
    builder.selectable("apply")
    builder.selectable("reset")
    builder.selectable("back")
    return True
