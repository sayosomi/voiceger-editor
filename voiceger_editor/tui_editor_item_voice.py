"""Per-Batch-Item Style and Speed draft interaction."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Sequence

from .settings import Settings, SettingsError
from .tui_adjustments import step_bounded
from .tui_editor_common import (
    ApplyItemVoiceIntent,
    ClearAdjustmentFeedbackIntent,
    EditorIntent,
    EditorOwnerBase,
    EditorState,
    UpdateStatusIntent,
    adjustment_feedback_intents,
)
from .tui_status import EMPTY_STATUS, error_status


class TuiItemVoiceEditorOwner(EditorOwnerBase):
    """Edit a single item's voice without changing persisted global defaults."""

    def __init__(
        self,
        host: Any,
        *,
        available_styles: Callable[[], Sequence[Any]],
    ) -> None:
        super().__init__(host)
        self._available_styles = available_styles

    def open(
        self,
        *,
        item_id: str,
        settings: Settings,
        origin: tuple[str, int | None],
    ) -> tuple[EditorIntent, ...]:
        self.editor = EditorState(
            kind="item_voice",
            title="EDIT ITEM VOICE",
            origin=origin,
            selection="style_id",
            payload={
                "item_id": item_id,
                "style_id": str(settings.style_id),
                "speed": f"{settings.speed:.2f}",
            },
        )
        return (ClearAdjustmentFeedbackIntent(), UpdateStatusIntent(""))

    def adjust(self, direction: int) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind != "item_voice" or editor.active_field:
            return ()
        selected = editor.selection
        unchanged = adjustment_feedback_intents(changed=False)
        if selected == "style_id":
            styles = self._available_styles()
            current = next(
                (index for index, style in enumerate(styles)
                 if style.id == int(editor.payload["style_id"])),
                None,
            )
            if current is None:
                editor.error = error_status("Selected Style is unavailable.")
                return unchanged
            next_index = current + direction
            if not 0 <= next_index < len(styles):
                return unchanged
            editor.payload["style_id"] = str(styles[next_index].id)
        elif selected == "speed":
            try:
                value = Decimal(str(editor.payload["speed"]))
                if not value.is_finite() or value <= 0:
                    raise InvalidOperation
                result = step_bounded(
                    value.quantize(Decimal("0.01")),
                    direction=direction,
                    step=Decimal("0.01"),
                    minimum=Decimal("0.01"),
                )
            except (InvalidOperation, ValueError):
                editor.error = error_status("Speed must be a positive finite number.")
                return unchanged
            if not result.changed:
                return unchanged
            editor.payload["speed"] = f"{result.value:.2f}"
        else:
            return unchanged
        editor.error = EMPTY_STATUS
        return adjustment_feedback_intents(
            changed=True, area="item_voice", control=selected, direction=direction
        )

    def finish_field(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind != "item_voice" or editor.active_field != "speed":
            return ()
        try:
            speed = Decimal(editor.input_value)
            if not speed.is_finite() or speed <= 0:
                raise InvalidOperation
            value = str(speed)
        except (InvalidOperation, ValueError):
            editor.error = error_status("Speed must be a positive finite number.")
            return ()
        editor.payload["speed"] = value
        editor.input_original = value
        editor.active_field = None
        editor.error = EMPTY_STATUS
        return (UpdateStatusIntent(""),)

    def activate(self, global_settings: Settings) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind != "item_voice":
            return ()
        if editor.selection == "style_id":
            return self.adjust(1)
        if editor.selection == "speed":
            return self.begin_field("speed", str(editor.payload["speed"]))
        if editor.selection == "reset":
            editor.payload["style_id"] = str(global_settings.style_id)
            editor.payload["speed"] = f"{global_settings.speed:.2f}"
            editor.error = EMPTY_STATUS
            return (
                ClearAdjustmentFeedbackIntent(),
                UpdateStatusIntent("Item voice draft reset to Settings."),
            )
        if editor.selection == "back":
            return self.cancel()
        if editor.selection != "apply":
            return ()
        try:
            style_id = int(editor.payload["style_id"])
            speed = float(editor.payload["speed"])
            replace(global_settings, style_id=style_id, speed=speed)
            if not any(style.id == style_id for style in self._available_styles()):
                raise ValueError("Selected Style is unavailable.")
        except (TypeError, ValueError, OverflowError, SettingsError) as exc:
            editor.error = error_status(f"Item voice was not changed: {exc}")
            return ()
        return (ApplyItemVoiceIntent(editor.payload["item_id"], style_id, speed),)

    def complete(self, error: str | None) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind != "item_voice":
            return ()
        if error is not None:
            editor.error = error_status(f"Item voice was not changed: {error}")
            return ()
        return self._close_editor("Item voice applied.")
