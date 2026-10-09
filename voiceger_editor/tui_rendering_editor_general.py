"""General and confirmation editor document construction."""

from __future__ import annotations

from .tui_confirmation import ConfirmationDetail, confirmation_lines
from .tui_display import _adjustable_value, _japanese_mora_tokens, _wrap_text
from .tui_rendering_editor_common import EditorDocumentBuilder
from .tui_rendering_shared import adjustment_press_direction
from .tui_shortcuts import menu_item


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
    if editor.kind in {
        "build_confirmation",
        "batch_recipe_replace_confirmation",
        "dictionary_delete_confirmation",
        "dictionary_discard_confirmation",
        "delete_confirmation",
        "clear_candidates_confirmation",
    }:
        details: tuple[ConfirmationDetail, ...] = ()
        if editor.kind == "batch_recipe_replace_confirmation":
            details = (
                ConfirmationDetail("Path", str(editor.payload["path"])),
            )
        elif editor.kind == "delete_confirmation":
            if "target_text" in editor.payload:
                language = (
                    "Japanese"
                    if editor.payload["target_language"] == "ja"
                    else "English"
                )
                details = (
                    ConfirmationDetail(f"{language} section", editor.payload["target_text"]),
                )
        elif editor.kind == "dictionary_delete_confirmation":
            if editor.payload["language"] == "ja":
                pronunciation = " ".join(
                    _japanese_mora_tokens(
                        editor.payload["moras"],
                        editor.payload["accent"] or len(editor.payload["moras"]),
                    )
                )
            else:
                pronunciation = " ".join(editor.payload["phonemes"])
            details = (
                ConfirmationDetail("Surface", str(editor.payload["surface"])),
                ConfirmationDetail("Pronunciation", pronunciation),
            )
        lines.extend(
            confirmation_lines(
                editor.kind,
                str(editor.selection),
                warning=str(editor.payload["warning"]),
                details=details,
                payload=editor.payload,
                width=width,
                wrap_text=_wrap_text,
            )
        )
    elif editor.kind == "caption":
        plain()
        if editor.active_field == "draft":
            input_field("draft", "▶ ")
        else:
            wrapped_selectable_text("draft", editor.payload["draft"])
        plain()
        selectable("apply")
        selectable("clear")
        selectable("reset")
        selectable("back")
    elif editor.kind == "japanese":
        plain()
        plain("Source")
        wrap("  ", editor.payload["source_text"])
        plain()
        input_field(
            "pronunciation",
            "▶ " if editor.selection == "pronunciation" else "  ",
        )
        plain()
        selectable("preview")
        selectable("apply")
        selectable("save_dictionary")
        selectable("dictionary")
        selectable("edit_text")
        if editor.payload.get("can_delete", False):
            selectable("delete_section")
        selectable("clear")
        selectable("reset")
        selectable("back")
    elif editor.kind == "english_word":
        plain()
        plain("Word")
        plain(f"  {editor.payload['label']}")
        plain()
        input_field(
            "phonemes",
            "▶ " if editor.selection == "phonemes" else "  ",
        )
        plain()
        selectable("preview")
        selectable("apply")
        selectable("save_dictionary")
        selectable("dictionary")
        selectable("edit_text")
        if editor.payload.get("can_delete", False):
            selectable("delete_section")
        selectable("clear")
        selectable("reset")
        selectable("back")
    elif editor.kind == "batch_recipe_read_path":
        plain()
        plain("File path")
        path_input_field()
        plain()
        selectable("read")
        selectable("back")
    elif editor.kind == "batch_recipe_write_path":
        plain()
        shared_output_field("output", "batch_write")
        plain()
        plain("File name")
        if editor.active_field == "file_name":
            input_field("file_name", "▶ ")
        else:
            wrapped_selectable_text(
                "file_name",
                str(editor.payload.get("file_name", "")) or "(not set)",
            )
        plain()
        selectable("write")
        selectable("back")
    elif editor.kind == "section_text":
        language = "Japanese" if editor.payload["language"] == "ja" else "English"
        plain()
        plain("Language")
        plain(f"  {language}")
        plain()
        if editor.active_field == "draft":
            input_field("draft", "▶ " if editor.selection == "draft" else "  ")
        else:
            wrapped_selectable_text("draft", editor.payload["draft"])
        plain()
        selectable("preview")
        selectable("apply")
        selectable("reset")
        if editor.payload["can_delete"]:
            selectable("delete_section")
        selectable("back")
    elif editor.kind == "add_section":
        language = "Japanese" if editor.payload["language"] == "ja" else "English"
        marker = "▶ " if editor.selection == "language" else "  "
        plain()
        language_item = menu_item(editor.kind, "language", editor.payload)
        lines.append(
            (
                f"{marker}{language_item.label:<12}{_adjustable_value(language, adjustment_press_direction(state, 'editor', 'language'))}",
                "language",
            )
        )
        if editor.active_field == "draft":
            input_field("draft", "▶ " if editor.selection == "draft" else "  ")
        else:
            wrapped_selectable_text("draft", editor.payload["draft"])
        plain()
        selectable("add")
        selectable("clear")
        selectable("reset")
        selectable("back")
    else:
        return False
    return True
