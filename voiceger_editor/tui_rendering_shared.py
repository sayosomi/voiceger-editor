"""Shared render-state models and pure presentation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, Sequence

from .caption_batch import CaptionBatch
from .session import UtteranceSession
from .settings import Settings
from .styles import available_styles
from .tui_display import _adjustable_value, _display_width, _truncate_display
from .tui_editors import PronunciationRow
from .tui_operations import BackgroundOperationProgress
from .tui_shortcuts import menu_item
from .tui_status import Status

_CANCEL_GENERATION_HINT = "[Ctrl+C] Cancel generation"

def status_with_cancel_generation_hint(
    status: Status,
    cancel_generation_available: bool,
) -> Status:
    """Add the generation-cancellation affordance without mutating Status."""

    if not cancel_generation_available:
        return status
    message = (
        f"{status} · {_CANCEL_GENERATION_HINT}"
        if status
        else _CANCEL_GENERATION_HINT
    )
    return Status(status.kind, message)


def background_with_cancel_generation_hint(
    message: str,
    cancel_generation_available: bool,
) -> str:
    """Add the cancellation affordance to background progress presentation."""

    if not message:
        return ""
    if not cancel_generation_available:
        return message
    return f"{message} · {_CANCEL_GENERATION_HINT}"



def format_background_operation_progress(
    progress: BackgroundOperationProgress | None,
    batch: CaptionBatch,
    cancel_generation_available: bool,
) -> str:
    """Format one operation-owned progress snapshot for the shared footer."""

    if progress is None:
        return ""

    owner = "Caption"
    if progress.item_id is not None:
        try:
            item = batch.get_item(progress.item_id)
        except KeyError:
            pass
        else:
            owner = f"Caption {batch.items.index(item) + 1}"

    if progress.operation == "initial":
        verb = "Generating"
    elif progress.operation in {"regenerate_one", "regenerate_all"}:
        verb = "Regenerating"
    elif progress.operation == "batch_generate":
        verb = "Generating selected"
    else:
        verb = "Working"

    parts = [verb]
    if progress.item_id is not None:
        parts.append(owner)
    if progress.take_number is not None:
        if progress.take_total is not None and progress.operation != "regenerate_one":
            parts.append(f"Take {progress.take_number}/{progress.take_total}")
        else:
            parts.append(f"Take {progress.take_number}")
    if progress.operation == "batch_generate" and progress.total > 0:
        parts.append(f"Overall {progress.completed}/{progress.total}")

    return background_with_cancel_generation_hint(
        " · ".join(parts),
        cancel_generation_available,
    )


class EditorRenderState(Protocol):
    kind: str
    title: str
    selection: str | tuple[str, int | None]
    payload: dict[str, Any]
    active_field: str | None
    input_value: str
    input_cursor: int
    error: Status


class OutputPathEditRenderState(Protocol):
    owner: str
    value: str
    cursor: int


@dataclass(frozen=True)
class TuiRenderState:
    """Read-only snapshot of the application values needed to render a frame."""

    voiceger_root: Any
    settings: Settings
    session: UtteranceSession | None
    focus_key: tuple[str, int | None]
    status: Status
    segments: Sequence[tuple[str, str, int | None]]
    pronunciation_rows: Sequence[PronunciationRow]
    busy: bool
    worker_operation: str | None
    worker_target: int | None
    operation_completed: int
    operation_total: int
    pressed_adjustment: tuple[str, str, int] | None
    editor: EditorRenderState | None
    accepted_take_number: int | None = None
    batch_item_position: tuple[int, int] | None = None
    batch_item_id: str | None = None
    active_generation_item_id: str | None = None
    background_status: str = ""
    output_path_edit: OutputPathEditRenderState | None = None
    batch_item_number_jump_active: bool = False
    batch_item_number_jump_value: str = ""


@dataclass(frozen=True)
class NavigationLine:
    text: str
    key: tuple[str, int | None] | None
    focus_owner: tuple[str, int | None] | None = None
    bold_spans: tuple[tuple[int, int], ...] = ()



def adjustment_press_direction(
    state: TuiRenderState,
    area: str,
    control: str,
) -> int | None:
    """Return the transient Left/Right feedback direction for one control."""

    pressed = state.pressed_adjustment
    if pressed is None or pressed[:2] != (area, control):
        return None
    return pressed[2]


def _active_input_prefix(editor: EditorRenderState) -> str:
    if editor.kind == "caption":
        return "▶ "
    if editor.kind == "japanese":
        return "▶ "
    if editor.kind == "english_word":
        return "▶ "
    if editor.kind in {"section_text", "add_section"}:
        return "▶ "
    if editor.kind in {"dictionary_japanese_entry", "dictionary_english_entry"}:
        label = "Surface" if editor.active_field == "surface" else "Pronunciation"
        return f"▶ {label:<15}"
    if editor.kind == "audio_output_settings":
        if editor.active_field == "filename_template":
            return "▶ Filename template  "
        return "▶ "
    if editor.kind == "settings":
        labels = {
            "style_id": "Style",
            "speed": "Speed",
            "take_count": "Takes",
            "output_dir": "Output",
            "save_text": "TXT",
            "save_lab": "LAB",
            "top_k": "Top K",
            "top_p": "Top P",
            "temperature": "Temperature",
        }
        label = labels.get(editor.active_field or "", "Setting")
        if editor.active_field == "output_dir":
            item = menu_item(editor.kind, "output_dir", editor.payload)
            if item.shortcut is not None:
                return f"▶ [{item.shortcut.upper()}] {label:<12}"
        return f"▶ {label:<12}"
    if editor.kind in {
        "dictionary_import_path",
        "batch_recipe_read_path",
    }:
        item = menu_item(editor.kind, "path", editor.payload)
        prefix = f"[{item.shortcut.upper()}] " if item.shortcut is not None else ""
        return f"▶ {prefix}"
    if (
        editor.kind == "batch_recipe_write_path"
        and editor.active_field == "file_name"
    ):
        return "▶ File name: "
    return "▶ Input: "


def _duration_seconds(frame_count: int, sampling_rate: int) -> float:
    try:
        return frame_count / float(sampling_rate)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _positioned_title(
    title: str,
    position: tuple[int, int] | None,
    width: int,
    direction: int | None = None,
) -> str:
    if position is None:
        return title
    current, total = position
    indicator = _adjustable_value(f"{current} / {total}", direction)
    available = max(1, width - 1)
    title_width = max(0, available - _display_width(indicator) - 1)
    title_part = _truncate_display(title, title_width)
    gap = max(
        1,
        available - _display_width(title_part) - _display_width(indicator),
    )
    return title_part + (" " * gap) + indicator


def _numbered_shortcut_token(number: int, item_count: int) -> str:
    """Format one numbered-list position with direct-shortcut semantics."""

    token_width = max(3, len(str(max(1, item_count))))
    token = f"[{number}]" if 1 <= number <= 9 else str(number)
    return token.rjust(token_width)



def setting_display(name: str, value: Any, voiceger_root: Any) -> str:
    if name == "style_id":
        try:
            style_id = int(value)
        except (TypeError, ValueError):
            return str(value)
        try:
            style = next(
                (
                    item
                    for item in available_styles(voiceger_root)
                    if item.id == style_id
                ),
                None,
            )
            style_name = str(style.name) if style is not None else ""
        except Exception:
            return str(style_id)
        return style_name or str(style_id)
    if name == "speed":
        try:
            return f"{Decimal(str(value)):.2f}"
        except (InvalidOperation, ValueError):
            return str(value)
    return str(value)

