"""Dictionary editor document construction."""

from __future__ import annotations

from typing import Sequence

from .pronunciation import parse_pronunciation
from .tui_display import (
    _adjustable_value,
    _display_width,
    _truncate_display,
)
from .tui_dictionary_pitch import format_dictionary_pitch
from .tui_rendering_editor_common import EditorDocumentBuilder
from .tui_rendering_dictionary_import import build_import_document
from .tui_rendering_dictionary_entry import (
    build_japanese_dictionary_entry,
    build_japanese_dictionary_pronunciation,
)
from .tui_rendering_dictionary_list import (
    _DICTIONARY_SORT_LABELS,
    _dictionary_list_row,
    _dictionary_surface_column_width,
    build_dictionary_list_document,
)
from .tui_rendering_shared import _numbered_shortcut_token, adjustment_press_direction
from .tui_shortcuts import menu_item

def build_document(builder: EditorDocumentBuilder) -> bool:
    if builder.editor.kind in {"dictionary_japanese_list", "dictionary_english_list"}:
        return build_dictionary_list_document(builder)
    if build_import_document(builder):
        return True
    editor = builder.editor
    state = builder.state
    width = builder.width
    lines = builder.lines
    plain = builder.plain
    wrap = builder.wrap
    selectable = builder.selectable
    selectable_value = builder.selectable_value
    wrapped_selectable_text = builder.wrapped_selectable_text
    input_field = builder.input_field
    path_input_field = builder.path_input_field
    shared_output_field = builder.shared_output_field
    if editor.kind == "dictionary_menu":
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
        selectable("restore")
        selectable("export")
        plain()
        selectable("back")
    elif editor.kind == "dictionary_export":
        plain()
        shared_output_field("output", "dictionary_export")
        plain()
        selectable("voiceger")
        plain("  One complete ZIP: Japanese + English + pitch metadata")
        plain()
        selectable("voicevox")
        plain("  Japanese dictionary only")
        plain()
        selectable("back")
    elif editor.kind == "dictionary_import_path":
        plain()
        plain("Backup ZIP path" if editor.payload.get("restore") else "File path")
        path_input_field()
        plain()
        selectable("review")
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
                f"{marker}Word type      {_adjustable_value(str(editor.payload['word_type_filter']), adjustment_press_direction(state, 'dictionary', 'word_type'))}",
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
            display = format_dictionary_pitch(
                parsed.phrases[0].morae, word.accent_type,
                editor.payload.get("pitch_events_by_uuid", {}).get(_word_uuid, ()),
            )
            key = ("entry", index)
            wrapped_selectable_text(key, f"{word.surface}      {display}")
        plain()
        plain("Enter Open")
        plain(menu_item(editor.kind, "back", editor.payload).display_label)
    elif editor.kind == "dictionary_japanese_entry":
        return build_japanese_dictionary_entry(builder)
    elif editor.kind == "dictionary_japanese_pronunciation":
        return build_japanese_dictionary_pronunciation(builder)
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
    else:
        return False
    return True
