"""Focused Japanese Dictionary entry document, including pitch event controls."""

from __future__ import annotations

from .tui_dictionary_pitch import format_dictionary_pitch
from .tui_display import _adjustable_value
from .tui_rendering_editor_common import EditorDocumentBuilder
from .tui_rendering_shared import adjustment_press_direction


def render_dictionary_word_field(
    builder: EditorDocumentBuilder,
    label: str,
    value: str | int,
    *,
    key: str | None = None,
    adjustable: bool = False,
) -> None:
    """One shared Dictionary/Import detail row, including focus and wrapping."""
    editor = builder.editor
    marker = "▶ " if key is not None and editor.selection == key else "  "
    prefix = f"{marker}{label:<15}"
    if key is not None and editor.active_field == key:
        builder.input_field(key, prefix)
    elif adjustable:
        assert key is not None
        direction = adjustment_press_direction(builder.state, "dictionary", key)
        builder.lines.append(
            (prefix + _adjustable_value(str(value), direction), key)
        )
    else:
        builder.wrap(prefix, str(value), key)


def build_japanese_dictionary_entry(builder: EditorDocumentBuilder) -> bool:
    """Render one Japanese Dictionary draft using the shared document builder."""
    editor = builder.editor
    plain = builder.plain
    selectable = builder.selectable
    plain()
    render_dictionary_word_field(
        builder, "Surface", editor.payload["surface"], key="surface"
    )
    selectable("generate_pronunciation")
    plain()
    display = format_dictionary_pitch(
        editor.payload["moras"],
        editor.payload["accent"],
        editor.payload.get("pitch_events", ()),
    )
    render_dictionary_word_field(builder, "Pronunciation", display, key="pronunciation")
    render_dictionary_word_field(
        builder, "Word type", editor.payload["word_type_label"],
        key="word_type", adjustable=True,
    )
    render_dictionary_word_field(
        builder, "Priority", editor.payload["priority"],
        key="priority", adjustable=True,
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
    return True

def build_japanese_dictionary_pronunciation(builder: EditorDocumentBuilder) -> bool:
    """Reuse the BATCH ITEM pronunciation editor layout for Dictionary text edits."""
    editor = builder.editor
    builder.plain()
    builder.plain("Source")
    builder.wrap("  ", str(editor.payload["source_text"]))
    builder.plain()
    builder.input_field(
        "pronunciation",
        "▶ " if editor.selection == "pronunciation" else "  ",
    )
    builder.plain()
    for key in ("preview", "apply", "clear", "reset", "back"):
        builder.selectable(key)
    return True
