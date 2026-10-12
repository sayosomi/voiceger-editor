"""Focused Dictionary backup and legacy import review rendering."""

from __future__ import annotations

from .tui_display import _adjustable_value, _display_width, _truncate_display
from .tui_rendering_editor_common import EditorDocumentBuilder
from .tui_rendering_shared import adjustment_press_direction


def build_import_document(builder: EditorDocumentBuilder) -> bool:
    editor = builder.editor
    if editor.kind not in {
        "dictionary_import_review",
        "dictionary_restore_review",
        "dictionary_import_japanese_detail",
        "dictionary_restore_japanese_detail",
        "dictionary_import_english_detail",
    }:
        return False
    state = builder.state
    width = builder.width
    lines = builder.lines
    plain = builder.plain
    wrap = builder.wrap
    selectable = builder.selectable
    if editor.kind in {"dictionary_import_review", "dictionary_restore_review"}:
        restoring = editor.kind == "dictionary_restore_review"
        paired_backup = editor.payload.get("paired_backup", False)
        plain()
        if paired_backup:
            counts = editor.payload.get("language_counts", (0, 0))
            plain(f"Backup: {counts[0]} Japanese, {counts[1]} English")
        total_count = int(editor.payload.get("total_count", 0))
        exact_count = int(editor.payload.get("exact_duplicate_count", 0))
        review_count = int(editor.payload.get("review_count", 0))
        plain(f"{total_count} words found")
        plain(f"{exact_count} already exist")
        plain(f"{review_count} to review")
        if restoring:
            japanese_deleted = editor.payload.get("deleted_japanese", ())
            english_deleted = editor.payload.get("deleted_english", ())
            plain()
            plain(f"Local entries to delete: {len(japanese_deleted)} Japanese, {len(english_deleted)} English")
            for surface in japanese_deleted:
                wrap("  - Japanese: ", str(surface))
            for surface in english_deleted:
                wrap("  - English:  ", str(surface))
            plain("All local entries absent from the ZIP will be deleted.")
        plain()
        word_type_labels = tuple(editor.payload.get("word_type_labels", ()))
        for index, item in enumerate(editor.payload.get("items", ())):
            key = ("import_entry", index)
            marker = "▶ " if editor.selection == key else "  "
            checkbox = ("   " if restoring else ("[x]" if item.selected else "[ ]"))
            attention = "!" if item.relation.value == "conflict" else " "
            word_type_label = (
                word_type_labels[index] if index < len(word_type_labels) else ""
            )
            suffix = f"  {word_type_label}" if word_type_label else ""
            language = (
                "JA " if hasattr(item, "source_uuid") else "EN "
            ) if paired_backup else ""
            value = f"{checkbox} {attention} {language}{item.incoming.surface}{suffix}"
            available = max(1, width - 1 - _display_width(marker))
            lines.append((marker + _truncate_display(value, available), key))
        plain()
        if restoring:
            selectable("restore")
            selectable("cancel")
        else:
            selectable("import_selected")
            selectable("clear_selection")
            selectable("back")
    elif editor.kind in {
        "dictionary_import_japanese_detail", "dictionary_restore_japanese_detail"
    }:
        plain()
        item = editor.payload["item"]
        incoming = item.incoming
        plain("Incoming")
        wrap("  Surface        ", str(incoming.surface))
        wrap("  Pronunciation  ", str(incoming.pronunciation))
        plain(f"  Accent         {incoming.accent_type}")
        if editor.kind == "dictionary_restore_japanese_detail":
            plain(f"  品詞            {editor.payload['word_type_label']}")
        else:
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
    return True
