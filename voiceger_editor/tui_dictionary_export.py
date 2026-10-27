"""Focused Dictionary Export TUI state, warning, and operation policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Literal

from .dictionary_export import (
    export_voiceger_editor_dictionaries,
    export_voicevox_dictionary,
)
from .tui_dictionary_operations import (
    DictionaryOperationIntent, dictionary_operation_request,
)
from .tui_editors import (
    ClearAdjustmentFeedbackIntent, EditorState, UpdateStatusIntent,
)
from .tui_status import EMPTY_STATUS, error_status, info_status, warning_status


class DictionaryExportOwner:
    """Own native/VOICEVOX export intents and loss-awareness."""

    def __init__(self, core, output_dir: Callable[[], Path]) -> None:
        self.core = core
        self._output_dir = output_dir

    @staticmethod
    def export_state() -> EditorState:
        return EditorState(
            kind="dictionary_export",
            title="EXPORT DICTIONARY",
            origin=("dictionary", None),
            selection="voiceger",
            payload={},
        )

    def voicevox_warning(self) -> EditorState | None:
        peaks = getattr(self.core, "list_japanese_pitch_events", lambda: {})()
        if not peaks:
            return None
        return EditorState(
            kind="dictionary_voicevox_loss_confirmation",
            title="VOICEVOX EXPORT WARNING",
            origin=("dictionary", None),
            selection="cancel",
            payload={
                "warning": (
                    f"{len(peaks)} Japanese word(s) have additional pitch "
                    "events. VOICEVOX JSON cannot include these peaks. "
                    "Export anyway?"
                ),
            },
        )

    def start(
        self, editor: EditorState, target: Literal["voiceger", "voicevox"]
    ) -> tuple[DictionaryOperationIntent, ...]:
        output_dir = Path(self._output_dir())
        core = self.core
        if target == "voiceger":
            operation = "export_voiceger_editor"
            status = "Exporting Voiceger Editor dictionaries…"

            def work() -> Any:
                return export_voiceger_editor_dictionaries(core, output_dir)
        else:
            operation = "export_voicevox"
            status = "Exporting VOICEVOX dictionary…"

            def work() -> Any:
                return export_voicevox_dictionary(core, output_dir)

        request = dictionary_operation_request(
            editor, operation=operation, language=None
        )
        return (
            DictionaryOperationIntent(
                request, info_status(status), work,
            ),
        )

    @staticmethod
    def complete(editor: EditorState, value: Any, error: BaseException | None):
        if error is not None:
            editor.error = error_status(f"Dictionary export was not completed: {error}")
            return (UpdateStatusIntent(editor.error),)
        editor.error = EMPTY_STATUS
        filenames = ", ".join(path.name for path in value.paths)
        lossy = getattr(value, "lossy_pitch_event_uuids", ())
        if lossy:
            outcome = warning_status(
                f"VOICEVOX export complete: {filenames}. {len(lossy)} word(s) "
                "have extra pitch peaks that VOICEVOX cannot import; "
                "use Voiceger Editor native export for a lossless backup."
            )
        else:
            outcome = f"Dictionary export complete: {filenames}"
        return (
            UpdateStatusIntent(outcome),
            ClearAdjustmentFeedbackIntent(),
        )
