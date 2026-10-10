"""Dictionary editor document construction."""

from __future__ import annotations

from typing import Sequence

from .pronunciation import parse_pronunciation
from .tui_display import (
    _adjustable_value,
    _display_width,
    _japanese_mora_tokens,
    _truncate_display,
)
from .tui_rendering_editor_common import EditorDocumentBuilder
from .tui_rendering_shared import _numbered_shortcut_token, adjustment_press_direction
from .tui_shortcuts import menu_item

_DICTIONARY_SURFACE_COLUMN_MAX_WIDTH = 24
_DICTIONARY_SURFACE_PRONUNCIATION_GAP = 6


def _dictionary_surface_column_width(surfaces: Sequence[str]) -> int:
    """Return a bounded display-width column for visible dictionary surfaces."""

    return min(
        max((_display_width(str(surface)) for surface in surfaces), default=0),
        _DICTIONARY_SURFACE_COLUMN_MAX_WIDTH,
    )


def _dictionary_list_row(
    number_token: str,
    surface: str,
    pronunciation: str,
    surface_column_width: int,
) -> str:
    """Align pronunciation after a display-width-aware surface column."""

    surface = str(surface)
    gap = max(
        _DICTIONARY_SURFACE_PRONUNCIATION_GAP,
        surface_column_width
        - _display_width(surface)
        + _DICTIONARY_SURFACE_PRONUNCIATION_GAP,
    )
    return f"{number_token}  {surface}{' ' * gap}{pronunciation}"


_DICTIONARY_SORT_LABELS = {
    "surface_asc": "Surface ↑",
    "surface_desc": "Surface ↓",
    "word_type": "Word type",
    "priority_asc": "Priority ↑",
    "priority_desc": "Priority ↓",
    "added_asc": "Added ↑",
    "added_desc": "Added ↓",
}


def build_document(builder: EditorDocumentBuilder) -> bool:
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
                    adjustment_press_direction(
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
        if editor.payload.get("accent_saving"):
            plain("  Saving accent changes…")
        elif editor.payload.get("accent_pending"):
            plain("  Unsaved accent changes (auto-save pending)")
        surface_column_width = _dictionary_surface_column_width(
            tuple(str(word.surface) for _word_uuid, word in entries)
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
            number_token = _numbered_shortcut_token(index + 1, len(entries))
            wrapped_selectable_text(
                key,
                _dictionary_list_row(
                    number_token,
                    str(word.surface),
                    display,
                    surface_column_width,
                ),
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
        selectable("preview")
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
        surface_column_width = _dictionary_surface_column_width(
            tuple(str(entry.surface) for entry in entries)
        )
        for index, entry in enumerate(entries):
            key = ("entry", index)
            number_token = _numbered_shortcut_token(index + 1, len(entries))
            wrapped_selectable_text(
                key,
                _dictionary_list_row(
                    number_token,
                    str(entry.surface),
                    " ".join(entry.phonemes),
                    surface_column_width,
                ),
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
        selectable("preview")
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
