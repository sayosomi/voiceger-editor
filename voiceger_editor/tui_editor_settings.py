"""Settings and Audio Output editor ownership."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Sequence

from .filename import (
    FilenameTemplateError,
    render_output_basename,
    validate_filename_template,
)
from .output import (
    FLAC_ENCODINGS,
    MP3_BITRATES,
    WAV_ENCODINGS,
    available_output_formats,
    output_extension,
)
from .settings import (
    Settings,
    SettingsError,
    VOICEGER_DEFAULT_TEMPERATURE,
    VOICEGER_DEFAULT_TOP_K,
    VOICEGER_DEFAULT_TOP_P,
)
from .tui_adjustments import step_bounded, step_cyclic, step_ordered
from .tui_editor_common import (
    ApplySettingsIntent,
    ClearAdjustmentFeedbackIntent,
    EditorIntent,
    EditorOwnerBase,
    EditorState,
    SettingsApplicationResult,
    UpdateStatusIntent,
    adjustment_feedback_intents,
)
from .tui_status import EMPTY_STATUS, error_status


_SETTINGS_SECTIONS = (
    ("style_id", "speed"),
    ("take_count",),
    ("output_dir", "audio_output"),
    ("top_k", "top_p", "temperature", "reset_sampling"),
    ("apply", "reset", "back"),
)


class TuiSettingsEditorOwner(EditorOwnerBase):
    """Own Settings draft state, validation, adjustment, and apply policy."""

    def __init__(
        self,
        host,
        *,
        available_styles: Callable[[], Sequence[Any]],
    ) -> None:
        super().__init__(host)
        self._available_styles = available_styles

    def open_settings(
        self,
        settings: Settings,
        *,
        origin: tuple[str, int | None],
        busy: bool,
        selected_field: str | None = None,
        edit: bool = False,
    ) -> tuple[EditorIntent, ...]:
        if busy:
            return (
                UpdateStatusIntent("Wait for synthesis to finish before changing settings."),
            )
        self.editor = EditorState(
            kind="settings",
            title="EDIT SETTINGS",
            origin=origin,
            selection=selected_field or "style_id",
            payload={
                "opening_settings": settings,
                "draft_settings": self._settings_draft(settings),
            },
        )
        intents: list[EditorIntent] = [UpdateStatusIntent("")]
        if edit and selected_field is not None:
            intents.extend(
                self.begin_field(
                    selected_field,
                    str(self.editor.payload["draft_settings"][selected_field]),
                )
            )
        return tuple(intents)

    @staticmethod
    def _settings_draft(settings: Settings) -> dict[str, Any]:
        return {
            "style_id": str(settings.style_id),
            "speed": str(settings.speed),
            "take_count": str(settings.take_count),
            "output_dir": str(settings.output_dir),
            "filename_template": settings.filename_template,
            "output_format": settings.output_format,
            "wav_encoding": settings.wav_encoding,
            "flac_encoding": settings.flac_encoding,
            "mp3_bitrate": settings.mp3_bitrate,
            "save_text": settings.save_text,
            "save_lab": settings.save_lab,
            "top_k": str(settings.top_k),
            "top_p": f"{settings.top_p:.2f}",
            "temperature": f"{settings.temperature:.2f}",
        }

    def open_audio_output_settings(
        self,
        current_caption: str | None,
    ) -> tuple[EditorIntent, ...]:
        parent = self.editor
        if parent is None or parent.kind != "settings":
            return ()
        draft = parent.payload["draft_settings"]
        available_formats = self._host._available_output_formats()
        if draft["output_format"] not in available_formats:
            draft["output_format"] = "wav"
        style_name = f"Style {draft['style_id']}"
        try:
            style_id = int(draft["style_id"])
            style_name = next(
                (
                    str(style.name)
                    for style in self._available_styles()
                    if style.id == style_id
                ),
                style_name,
            )
        except (TypeError, ValueError):
            pass
        self.editor = EditorState(
            kind="audio_output_settings",
            title="AUDIO OUTPUT",
            origin=parent.origin,
            selection="output_format",
            payload={
                "parent_editor": parent,
                "draft_settings": draft,
                "preview_text": current_caption or "Sample text",
                "preview_style": style_name,
                "show_output_encoding": draft["output_format"] != "mp3",
                "show_mp3_bitrate": draft["output_format"] == "mp3",
            },
        )
        self._refresh_filename_preview(self.editor)
        return (ClearAdjustmentFeedbackIntent(), UpdateStatusIntent(""))

    @staticmethod
    def _refresh_filename_preview(
        editor: EditorState,
        template: str | None = None,
    ) -> None:
        if editor.kind != "audio_output_settings":
            return
        candidate = (
            str(template)
            if template is not None
            else str(editor.payload["draft_settings"]["filename_template"])
        )
        try:
            basename = render_output_basename(
                template=candidate,
                text=str(editor.payload.get("preview_text", "Sample text")),
                style=str(editor.payload.get("preview_style", "Style")),
            )
        except FilenameTemplateError as exc:
            editor.payload["filename_preview"] = ""
            editor.payload["filename_preview_error"] = str(exc)
            return
        editor.payload["filename_preview"] = (
            basename
            + output_extension(
                str(editor.payload["draft_settings"].get("output_format", "wav"))
            )
        )
        editor.payload["filename_preview_error"] = ""

    def move_settings_section(self, direction: int) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind != "settings" or editor.active_field is not None:
            return ()
        keys = set(self.selection_keys())
        sections = tuple(
            tuple(key for key in section if key in keys)
            for section in _SETTINGS_SECTIONS
        )
        sections = tuple(section for section in sections if section)
        if not sections:
            return ()
        current = next(
            (
                index
                for index, section in enumerate(sections)
                if editor.selection in section
            ),
            0,
        )
        target = (current + (1 if direction > 0 else -1)) % len(sections)
        editor.selection = sections[target][0]
        editor.error = EMPTY_STATUS
        return (ClearAdjustmentFeedbackIntent(),)

    def activate_selection(
        self,
        settings: Settings,
        current_caption: str | None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        selected = editor.selection
        if editor.kind == "settings":
            if selected in {"style_id", "speed", "apply"}:
                return self._apply_settings(settings)
            if selected in {
                "take_count", "output_dir", "top_k", "top_p", "temperature"
            }:
                value = editor.payload["draft_settings"][selected]
                return self.begin_field(selected, str(value))
            if selected == "audio_output":
                return self.open_audio_output_settings(current_caption)
            if selected == "reset_sampling":
                draft = editor.payload["draft_settings"]
                draft["top_k"] = str(VOICEGER_DEFAULT_TOP_K)
                draft["top_p"] = f"{VOICEGER_DEFAULT_TOP_P:.2f}"
                draft["temperature"] = f"{VOICEGER_DEFAULT_TEMPERATURE:.2f}"
                editor.error = EMPTY_STATUS
                return (
                    ClearAdjustmentFeedbackIntent(),
                    UpdateStatusIntent("Sampling reset to Voiceger defaults."),
                )
            if selected == "reset":
                editor.payload["draft_settings"] = self._settings_draft(
                    editor.payload["opening_settings"]
                )
                editor.error = EMPTY_STATUS
                return (
                    ClearAdjustmentFeedbackIntent(),
                    UpdateStatusIntent("Settings draft reset."),
                )
            if selected == "back":
                return self.cancel()
            return ()

        if editor.kind == "audio_output_settings":
            if selected == "filename_template":
                value = editor.payload["draft_settings"]["filename_template"]
                return self.begin_field("filename_template", str(value))
            if selected in {
                "output_format",
                "output_encoding",
                "mp3_bitrate",
                "save_text",
                "save_lab",
            }:
                return self.adjust_settings(1)
            if selected == "back":
                return self._restore_parent_editor("")
        return ()

    def finish_field(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if (
            editor is None
            or editor.active_field is None
            or editor.kind not in {"settings", "audio_output_settings"}
        ):
            return ()
        name = editor.active_field
        value = editor.input_value
        if editor.kind == "audio_output_settings" and name == "filename_template":
            try:
                validate_filename_template(value)
                self._refresh_filename_preview(editor, value)
            except FilenameTemplateError as exc:
                self._refresh_filename_preview(editor, value)
                editor.error = error_status(f"Filename template is invalid: {exc}")
                return ()
        elif editor.kind == "settings" and name == "take_count":
            try:
                take_count = int(value)
            except (TypeError, ValueError):
                editor.error = error_status(
                    "Take count must be an integer from 1 through 100."
                )
                return ()
            if not 1 <= take_count <= 100:
                editor.error = error_status(
                    "Take count must be an integer from 1 through 100."
                )
                return ()
            value = str(take_count)
            editor.input_value = value
        elif editor.kind == "settings" and name == "top_k":
            try:
                top_k = int(value)
            except (TypeError, ValueError):
                editor.error = error_status(
                    "Top K must be an integer from 1 through 100."
                )
                return ()
            if not 1 <= top_k <= 100:
                editor.error = error_status(
                    "Top K must be an integer from 1 through 100."
                )
                return ()
            value = str(top_k)
            editor.input_value = value
        elif editor.kind == "settings" and name in {"top_p", "temperature"}:
            label = "Top P" if name == "top_p" else "Temperature"
            try:
                numeric = Decimal(value)
            except (InvalidOperation, TypeError, ValueError):
                editor.error = error_status(
                    f"{label} must be a finite number from 0.00 through 1.00."
                )
                return ()
            if not numeric.is_finite() or not Decimal("0") <= numeric <= Decimal("1"):
                editor.error = error_status(
                    f"{label} must be a finite number from 0.00 through 1.00."
                )
                return ()
            value = f"{numeric:.2f}"
            editor.input_value = value

        editor.payload["draft_settings"][name] = value
        editor.active_field = None
        editor.input_original = value
        editor.input_cursor = len(value)
        editor.error = EMPTY_STATUS
        return (UpdateStatusIntent(""),)

    def _apply_settings(self, settings: Settings) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        draft = editor.payload["draft_settings"]
        try:
            updated = Settings(
                style_id=int(draft["style_id"]),
                speed=float(draft["speed"]),
                take_count=int(draft["take_count"]),
                output_dir=Path(draft["output_dir"]),
                filename_template=draft["filename_template"],
                output_format=draft["output_format"],
                wav_encoding=draft["wav_encoding"],
                flac_encoding=draft["flac_encoding"],
                mp3_bitrate=draft["mp3_bitrate"],
                save_text=draft["save_text"],
                save_lab=draft["save_lab"],
                top_k=int(draft["top_k"]),
                top_p=float(draft["top_p"]),
                temperature=float(draft["temperature"]),
            )
        except (TypeError, ValueError, SettingsError) as exc:
            editor.error = error_status(f"Settings were not changed: {exc}")
            return ()
        return (ApplySettingsIntent(updated),)

    def complete_settings_application(
        self,
        result: SettingsApplicationResult,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if result.error_status is not None:
            editor.error = result.error_status
            return ()
        return self._close_editor("Settings saved.")

    def adjust_settings(self, direction: int) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if (
            editor is None
            or editor.kind not in {"settings", "audio_output_settings"}
            or editor.active_field is not None
        ):
            return ()
        draft = editor.payload["draft_settings"]
        selected = editor.selection
        allowed = (
            {"output_format", "output_encoding", "mp3_bitrate", "save_text", "save_lab"}
            if editor.kind == "audio_output_settings"
            else {
                "style_id", "speed", "take_count",
                "top_k", "top_p", "temperature",
            }
        )
        if selected not in allowed:
            return ()
        clear_feedback = adjustment_feedback_intents(
            changed=False,
            area="settings",
            control=selected,
            direction=direction,
        )
        feedback = adjustment_feedback_intents(
            changed=True,
            area="settings",
            control=selected,
            direction=direction,
        )
        if selected == "style_id":
            styles = self._available_styles()
            if not styles:
                editor.error = error_status("No available styles can be selected.")
                return clear_feedback
            try:
                current_id = int(draft["style_id"])
            except (TypeError, ValueError):
                editor.error = error_status("Style ID must be a positive integer.")
                return clear_feedback
            index = next(
                (i for i, style in enumerate(styles) if style.id == current_id),
                None,
            )
            if index is None:
                editor.error = error_status(f"Style ID {current_id} is not available.")
                return clear_feedback
            target = index + direction
            if not 0 <= target < len(styles):
                return clear_feedback
            updated_id = styles[target].id
            if updated_id == current_id:
                return clear_feedback
            draft["style_id"] = str(updated_id)
        elif selected == "speed":
            try:
                current = Decimal(str(draft["speed"]))
                if not current.is_finite() or current <= 0:
                    raise InvalidOperation
                current = current.quantize(Decimal("0.01"))
                result = step_bounded(
                    current,
                    direction=direction,
                    step=Decimal("0.01"),
                    minimum=Decimal("0.01"),
                )
            except (InvalidOperation, ValueError):
                editor.error = error_status("Speed must be a positive finite number.")
                return clear_feedback
            if not result.changed:
                editor.error = EMPTY_STATUS
                return clear_feedback
            draft["speed"] = f"{result.value:.2f}"
        elif selected == "take_count":
            try:
                current = int(draft["take_count"])
            except (TypeError, ValueError):
                editor.error = error_status("Take count must be an integer from 1 through 100.")
                return clear_feedback
            result = step_bounded(
                current,
                direction=direction,
                step=1,
                minimum=1,
                maximum=100,
            )
            if not result.changed:
                editor.error = EMPTY_STATUS
                return clear_feedback
            draft["take_count"] = str(result.value)
        elif selected == "top_k":
            try:
                current = int(draft["top_k"])
            except (TypeError, ValueError):
                editor.error = error_status("Top K must be an integer from 1 through 100.")
                return clear_feedback
            if not 1 <= current <= 100:
                editor.error = error_status("Top K must be an integer from 1 through 100.")
                return clear_feedback
            result = step_bounded(
                current,
                direction=direction,
                step=1,
                minimum=1,
                maximum=100,
            )
            if not result.changed:
                editor.error = EMPTY_STATUS
                return clear_feedback
            draft["top_k"] = str(result.value)
        elif selected in {"top_p", "temperature"}:
            label = "Top P" if selected == "top_p" else "Temperature"
            try:
                current = Decimal(str(draft[selected]))
            except (InvalidOperation, TypeError, ValueError):
                editor.error = (
                    error_status(f"{label} must be a finite number from 0.00 through 1.00.")
                )
                return clear_feedback
            if (
                not current.is_finite()
                or not Decimal("0") <= current <= Decimal("1")
            ):
                editor.error = (
                    error_status(f"{label} must be a finite number from 0.00 through 1.00.")
                )
                return clear_feedback
            result = step_bounded(
                current,
                direction=direction,
                step=Decimal("0.05"),
                minimum=Decimal("0.00"),
                maximum=Decimal("1.00"),
            )
            if not result.changed:
                editor.error = EMPTY_STATUS
                return clear_feedback
            draft[selected] = f"{result.value:.2f}"
        elif selected == "output_format":
            formats = self._host._available_output_formats()
            current = str(draft["output_format"])
            if current not in formats:
                current = formats[0]
                draft["output_format"] = current
            result = step_cyclic(
                current,
                formats,
                direction=direction,
            )
            if not result.changed:
                return clear_feedback
            draft["output_format"] = result.value
            editor.payload["show_output_encoding"] = result.value != "mp3"
            editor.payload["show_mp3_bitrate"] = result.value == "mp3"
            self._refresh_filename_preview(editor)
        elif selected == "output_encoding":
            output_format = str(draft["output_format"])
            if output_format == "mp3":
                return clear_feedback
            encoding_key = "wav_encoding" if output_format == "wav" else "flac_encoding"
            encodings = WAV_ENCODINGS if output_format == "wav" else FLAC_ENCODINGS
            result = step_ordered(
                str(draft[encoding_key]),
                encodings,
                direction=direction,
            )
            if not result.changed:
                return clear_feedback
            draft[encoding_key] = result.value
        elif selected == "mp3_bitrate":
            if str(draft["output_format"]) != "mp3":
                return clear_feedback
            result = step_ordered(
                str(draft["mp3_bitrate"]),
                MP3_BITRATES,
                direction=direction,
            )
            if not result.changed:
                return clear_feedback
            draft["mp3_bitrate"] = result.value
        elif selected in {"save_text", "save_lab"}:
            result = step_cyclic(
                bool(draft[selected]),
                (False, True),
                direction=direction,
            )
            if not result.changed:
                return clear_feedback
            draft[selected] = result.value
        editor.error = EMPTY_STATUS
        return feedback
