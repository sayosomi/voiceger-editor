"""Focused Dictionary backup and legacy import review rendering."""

from __future__ import annotations

from .pronunciation import parse_pronunciation
from .tui_dictionary_pitch import format_dictionary_pitch
from .tui_display import _adjustable_value, format_english_phonemes
from .tui_rendering_editor_common import EditorDocumentBuilder
from .tui_rendering_dictionary_list import _dictionary_list_row, _dictionary_surface_column_width
from .tui_rendering_shared import _numbered_shortcut_token, adjustment_press_direction


def build_import_document(builder: EditorDocumentBuilder) -> bool:
    editor = builder.editor
    if editor.kind not in {
        "dictionary_import_review",
        "dictionary_import_japanese_detail",
        "dictionary_import_english_detail",
    }:
        return False
    state = builder.state
    width = builder.width
    lines = builder.lines
    plain = builder.plain
    wrap = builder.wrap
    selectable = builder.selectable
    if editor.kind == "dictionary_import_review":
        paired_backup = bool(editor.payload.get("paired_backup"))
        items = tuple(editor.payload.get("items", ()))
        plain()
        if paired_backup:
            counts = editor.payload.get("language_counts", (0, 0))
            plain(f"Backup: {counts[0]} Japanese, {counts[1]} English")
        selected = sum(bool(item.selected) for item in items)
        plain(f"Selected: {selected} / {len(items)} words")
        exact = int(editor.payload.get("exact_duplicate_count", 0))
        if exact:
            plain(f"{exact} unchanged word(s) omitted")
        if any(item.relation.value == "conflict" for item in items):
            plain("! Conflicts with an existing word")

        japanese = tuple(
            (index, item) for index, item in enumerate(items)
            if hasattr(item, "source_uuid")
        )
        english = tuple(
            (index, item) for index, item in enumerate(items)
            if not hasattr(item, "source_uuid")
        )
        events = editor.payload.get("incoming_pitch_events", {})
        groups = (("Japanese", japanese), ("English", english))
        for label, group in groups:
            if not group:
                continue
            plain()
            plain(label)
            surface_width = _dictionary_surface_column_width(
                tuple(str(item.incoming.surface) for _, item in group)
            )
            for index, item in group:
                key = ("import_entry", index)
                checkbox = "[x]" if item.selected else "[ ]"
                attention = "!" if item.relation.value == "conflict" else " "
                number = _numbered_shortcut_token(index + 1, len(items))
                incoming = item.incoming
                if hasattr(item, "source_uuid"):
                    parsed = parse_pronunciation(incoming.pronunciation + "'")
                    pronunciation = format_dictionary_pitch(
                        parsed.phrases[0].morae,
                        incoming.accent_type,
                        events.get(item.source_uuid, ()),
                    )
                else:
                    pronunciation = format_english_phonemes(incoming.phonemes)
                builder.wrapped_selectable_text(
                    key,
                    _dictionary_list_row(
                        f"{number} {checkbox} {attention}",
                        str(incoming.surface),
                        pronunciation,
                        surface_width,
                    ),
                )
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
                    adjustment_press_direction(state, "dictionary", "word_type"),
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
    return True
