"""Batch List document construction."""

from __future__ import annotations

from .caption_batch import CaptionBatch
from .settings import Settings
from .tui_display import _display_width, _wrap_active_input, _wrap_text
from .tui_rendering_shared import NavigationLine, OutputPathEditRenderState, _numbered_shortcut_token
from .tui_shortcuts import batch_list_shortcut

def batch_list_document(
    batch: CaptionBatch,
    focus_key: tuple[str, int | None],
    width: int,
    pressed_adjustment: tuple[str, str, int] | None = None,
    active_generation: tuple[str, int, int] | None = None,
    generation_busy: bool = False,
    settings: Settings | None = None,
    output_path_edit: OutputPathEditRenderState | None = None,
) -> list[NavigationLine]:
    """Build the top-level Batch List document."""

    lines: list[NavigationLine] = []

    def plain(value: str = "") -> None:
        lines.append(NavigationLine(value, None))

    def action(key: tuple[str, int | None], label: str) -> None:
        marker = "▶ " if key == focus_key else "  "
        lines.append(NavigationLine(marker + label, key, key))

    global_settings = settings if settings is not None else Settings()
    enabled_formats = [global_settings.output_format.upper()]
    if global_settings.save_lab:
        enabled_formats.append("LAB")
    if global_settings.save_text:
        enabled_formats.append("TXT")
    summary = (
        f"[S] Settings Takes {batch.default_take_count}"
        f" | {' '.join(enabled_formats)}"
    )
    summary_key = ("settings", None)
    summary_marker = "▶ " if focus_key == summary_key else "  "
    summary_width = max(1, width - 1 - _display_width(summary_marker))
    summary_lines = _wrap_text(summary, summary_width) or [summary]
    lines.append(
        NavigationLine(
            summary_marker + summary_lines[0], summary_key, summary_key
        )
    )
    for continuation in summary_lines[1:]:
        lines.append(NavigationLine("  " + continuation, None, summary_key))

    output_key = ("output", None)
    editing_output = (
        output_path_edit is not None and output_path_edit.owner == "batch_list"
    )
    output_marker = "▶ " if focus_key == output_key or editing_output else "  "
    output_prefix = "[F] Output: "
    output_width = max(1, width - 1 - _display_width(output_marker + output_prefix))
    if editing_output:
        pieces, cursor_row, _cursor_cells = _wrap_active_input(
            output_path_edit.value, output_path_edit.cursor, output_width
        )
        lines.append(NavigationLine(
            output_marker + output_prefix + pieces[min(cursor_row, len(pieces) - 1)],
            output_key,
            output_key,
        ))
    else:
        pieces = _wrap_text(str(global_settings.output_dir), output_width) or [""]
        lines.append(NavigationLine(output_marker + output_prefix + pieces[0], output_key, output_key))
        indentation = " " * _display_width(output_marker + output_prefix)
        for piece in pieces[1:]:
            lines.append(NavigationLine(indentation + piece, None, output_key))
    plain()
    plain("Captions")

    for index, item in enumerate(batch.items):
        key = ("caption", index)
        marker = "▶ " if key == focus_key else "  "
        selected = "x" if item.included_for_generation else " "
        active_progress = (
            active_generation
            if active_generation is not None
            and active_generation[0] == item.item_id
            else None
        )
        if active_progress is not None:
            _item_id, completed, total = active_progress
            percent = round(completed * 100 / total)
            review_state = f"[{percent}%] "
        elif item.is_accepted:
            accepted_count = len(item.accepted_take_numbers)
            review_state = f"[✓{accepted_count}] " if accepted_count > 1 else "[✓] "
        elif item.generation_outcome in {"cancelled", "failed"}:
            review_state = "[⚠] "
        elif item.generation_outcome == "completed":
            review_state = "[!] "
        else:
            review_state = ""
        number_token = _numbered_shortcut_token(index + 1, len(batch))
        prefix = f"{marker}[{selected}] {number_token}  {review_state}"
        available = max(1, width - 1 - _display_width(prefix))
        pieces = _wrap_text(item.caption, available) or [""]
        lines.append(NavigationLine(prefix + pieces[0], key, key))
        continuation = " " * _display_width(prefix)
        lines.extend(
            NavigationLine(continuation + piece, None, key)
            for piece in pieces[1:]
        )

    if batch.items:
        plain()
    action_groups = (
        ("add_captions", "generate_selected"),
        ("read_batch", "write_batch"),
        ("dictionary",),
        ("help", "quit"),
    )
    for group_index, names in enumerate(action_groups):
        if group_index:
            plain()
        for name in names:
            label = batch_list_shortcut(name).display_label
            if name == "generate_selected" and generation_busy:
                label += " [busy]"
            action((name, None), label)
    return lines

