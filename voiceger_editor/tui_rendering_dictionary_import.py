"""Focused Dictionary backup and legacy import review rendering."""

from __future__ import annotations

from .pronunciation import parse_pronunciation
from .tui_dictionary_pitch import format_dictionary_pitch
from .tui_display import format_english_phonemes
from .tui_rendering_editor_common import EditorDocumentBuilder
from .tui_rendering_dictionary_list import _dictionary_list_row, _dictionary_surface_column_width
from .tui_rendering_shared import _numbered_shortcut_token
from .tui_rendering_dictionary_entry import render_dictionary_word_field


def _japanese_pitch_text(word, pitch_events=()) -> str:
    """Render the same Japanese pitch notation used by the Dictionary list."""
    parsed = parse_pronunciation(word.pronunciation + "'")
    return format_dictionary_pitch(
        parsed.phrases[0].morae, word.accent_type, pitch_events
    )


def build_import_document(builder: EditorDocumentBuilder) -> bool:
    editor = builder.editor
    if editor.kind not in {
        "dictionary_import_review",
        "dictionary_import_japanese_detail",
        "dictionary_import_english_detail",
    }:
        return False
    plain = builder.plain
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
        item = editor.payload["item"]
        incoming = item.incoming
        plain()
        incoming_pitch = _japanese_pitch_text(
            incoming, editor.payload.get("incoming_pitch_events", ())
        )
        render_dictionary_word_field(builder, "Surface", incoming.surface)
        render_dictionary_word_field(builder, "Pronunciation", incoming_pitch)
        render_dictionary_word_field(
            builder, "Word type", editor.payload["word_type_label"],
            key="word_type", adjustable=True,
        )
        render_dictionary_word_field(builder, "Priority", incoming.priority)

        existing = item.existing
        if existing is not None:
            existing_pitch = _japanese_pitch_text(
                existing, editor.payload.get("existing_pitch_events", ())
            )
            comparisons = (
                ("Surface", str(incoming.surface), str(existing.surface)),
                ("Pronunciation", incoming_pitch, existing_pitch),
                (
                    "Word type", str(editor.payload["word_type_label"]),
                    str(editor.payload["existing_word_type_label"]),
                ),
                ("Priority", str(incoming.priority), str(existing.priority)),
            )
            plain()
            plain("Existing — differences only")
            differences = 0
            for label, current, previous in comparisons:
                if current != previous:
                    render_dictionary_word_field(builder, label, previous)
                    differences += 1
            if not differences:
                plain("  No differences in displayed fields.")
        plain()
        selectable("back")
    elif editor.kind == "dictionary_import_english_detail":
        item = editor.payload["item"]
        incoming = item.incoming
        current_phonemes = format_english_phonemes(incoming.phonemes)
        plain()
        render_dictionary_word_field(builder, "Surface", incoming.surface)
        render_dictionary_word_field(builder, "Pronunciation", current_phonemes)
        existing = item.existing
        if existing is not None:
            plain()
            plain("Existing — differences only")
            differences = 0
            if str(existing.surface) != str(incoming.surface):
                render_dictionary_word_field(builder, "Surface", existing.surface)
                differences += 1
            old_phonemes = format_english_phonemes(existing.phonemes)
            if old_phonemes != current_phonemes:
                render_dictionary_word_field(
                    builder, "Pronunciation", old_phonemes
                )
                differences += 1
            if not differences:
                plain("  No differences in displayed fields.")
        plain()
        selectable("back")
    return True
