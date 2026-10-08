"""Batch List document construction."""

from __future__ import annotations

from .caption_batch import CaptionBatch
from .tui_display import _adjustable_value, _display_width, _wrap_text
from .tui_rendering_shared import NavigationLine, _numbered_shortcut_token
from .tui_shortcuts import batch_list_shortcut

def batch_list_document(
    batch: CaptionBatch,
    focus_key: tuple[str, int | None],
    width: int,
    pressed_adjustment: tuple[str, str, int] | None = None,
    active_generation: tuple[str, int, int] | None = None,
    generation_busy: bool = False,
) -> list[NavigationLine]:
    """Build the top-level Batch List document."""

    lines: list[NavigationLine] = []

    def plain(value: str = "") -> None:
        lines.append(NavigationLine(value, None))

    def action(key: tuple[str, int | None], label: str) -> None:
        marker = "▶ " if key == focus_key else "  "
        lines.append(NavigationLine(marker + label, key, key))

    take_direction = (
        pressed_adjustment[2]
        if (
            pressed_adjustment is not None
            and pressed_adjustment[:2] == ("batch_list", "takes")
        )
        else None
    )
    action(
        ("takes", None),
        f"Takes {_adjustable_value(str(batch.default_take_count), take_direction)}",
    )
    plain()

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
            review_state = "[✓] "
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
        ("settings", "dictionary"),
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

