"""Dictionary word-list rows, Preview actions, and accent save presentation."""

from __future__ import annotations

from typing import Sequence

from .pronunciation import parse_pronunciation
from .tui_display import _display_width, _japanese_mora_tokens
from .tui_rendering_editor_common import EditorDocumentBuilder
from .tui_rendering_shared import _numbered_shortcut_token
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


def build_dictionary_list_document(builder: EditorDocumentBuilder) -> bool:
    editor = builder.editor
    plain = builder.plain
    selectable = builder.selectable
    selectable_value = builder.selectable_value
    wrapped_selectable_text = builder.wrapped_selectable_text
    if editor.kind == "dictionary_japanese_list":
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
    else:
        return False
    return True
