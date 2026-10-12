"""Focused Japanese Dictionary entry document, including pitch event controls."""

from __future__ import annotations

from .tui_dictionary_pitch import format_dictionary_pitch
from .tui_display import _adjustable_value
from .tui_rendering_editor_common import EditorDocumentBuilder
from .tui_rendering_shared import adjustment_press_direction


def build_japanese_dictionary_entry(builder: EditorDocumentBuilder) -> bool:
    """Render one Japanese Dictionary draft using the shared document builder."""
    editor = builder.editor
    state = builder.state
    lines = builder.lines
    plain = builder.plain
    wrap = builder.wrap
    selectable = builder.selectable
    input_field = builder.input_field
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
        display = format_dictionary_pitch(
            editor.payload["moras"],
            editor.payload["accent"],
            editor.payload.get("pitch_events", ()),
        )
        marker = "▶ " if editor.selection == "pronunciation" else "  "
        lines.append((f"{marker}Pronunciation  {display}", "pronunciation"))
        if editor.selection == "pronunciation":
            events = editor.payload.get("pitch_events", ())
            if events:
                cursor = editor.payload.get("pitch_cursor", 1)
                current = events[cursor]
                plain(
                    f"  Marker {cursor + 1}/{len(events)}: {current.symbol} after mora "
                    f"{current.after_mora}. M select · Left/Right move"
                )
            plain("  [+] Add peak · [-] Remove selected peak · Enter edit reading")
            plain("  [ and ] navigate dictionary words; / is a real phrase boundary.")
    marker = "▶ " if editor.selection == "word_type" else "  "
    lines.append(
        (
            f"{marker}Word type      {_adjustable_value(str(editor.payload['word_type_label']), adjustment_press_direction(state, 'dictionary', 'word_type'))}",
            "word_type",
        )
    )
    marker = "▶ " if editor.selection == "priority" else "  "
    lines.append(
        (
            f"{marker}Priority       {_adjustable_value(str(editor.payload['priority']), adjustment_press_direction(state, 'dictionary', 'priority'))}",
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
    return True
