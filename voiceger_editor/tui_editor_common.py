"""Shared editor state, typed intents/results, and focused-owner plumbing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING, Union

from .settings import Settings
from .voicevox_api_models import AudioQuery
from .tui_status import EMPTY_STATUS, Status, info_status

if TYPE_CHECKING:
    from .tui_editor_english import EnglishGroupingCache


@dataclass
class EditorState:
    kind: str
    title: str
    origin: tuple[str, int | None]
    selection: str | tuple[str, int | None]
    payload: dict[str, Any] = field(default_factory=dict)
    active_field: str | None = None
    input_value: str = ""
    input_cursor: int = 0
    input_original: str = ""
    error: Status = EMPTY_STATUS
    scroll: int = 0


@dataclass(frozen=True)
class ReplaceQueryIntent:
    query: AudioQuery
    editor_kind: str
    success_status: Status
    grouping_index: int | None = None
    accepted_grouping: EnglishGroupingCache | None = None
    deleted_segment_index: int | None = None
    pure_japanese_utterance_text: str | None = None
    close_editor: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.success_status, Status):
            object.__setattr__(
                self,
                "success_status",
                info_status(str(self.success_status)),
            )


@dataclass(frozen=True)
class PreviewIntent:
    query: AudioQuery


@dataclass(frozen=True)
class ApplyCaptionIntent:
    caption: str


@dataclass(frozen=True)
class BuildPronunciationIntent:
    pass


@dataclass(frozen=True)
class ApplySettingsIntent:
    settings: Settings


@dataclass(frozen=True)
class CloseEditorIntent:
    origin: tuple[str, int | None]
    status: Status

    def __post_init__(self) -> None:
        if not isinstance(self.status, Status):
            object.__setattr__(self, "status", info_status(str(self.status)))


@dataclass(frozen=True)
class UpdateStatusIntent:
    status: Status

    def __init__(self, status: Status | str) -> None:
        object.__setattr__(
            self,
            "status",
            status if isinstance(status, Status) else info_status(status),
        )


@dataclass(frozen=True)
class AdjustmentPressedIntent:
    area: str
    control: str
    direction: int


@dataclass(frozen=True)
class ClearAdjustmentFeedbackIntent:
    pass


@dataclass(frozen=True)
class OpenHelpIntent:
    pass


@dataclass(frozen=True)
class OpenDictionaryIntent:
    pass


@dataclass(frozen=True)
class SaveToDictionaryIntent:
    language: str
    surface: str
    pronunciation: str


@dataclass(frozen=True)
class QuitIntent:
    pass


@dataclass(frozen=True)
class ClearCandidatesIntent:
    pass


EditorIntent = Union[
    ReplaceQueryIntent,
    PreviewIntent,
    ApplyCaptionIntent,
    BuildPronunciationIntent,
    ApplySettingsIntent,
    CloseEditorIntent,
    UpdateStatusIntent,
    AdjustmentPressedIntent,
    ClearAdjustmentFeedbackIntent,
    OpenHelpIntent,
    OpenDictionaryIntent,
    SaveToDictionaryIntent,
    QuitIntent,
    ClearCandidatesIntent,
]


def adjustment_feedback_intents(
    *,
    changed: bool,
    area: str | None = None,
    control: str | None = None,
    direction: int = 0,
) -> tuple[EditorIntent, ...]:
    """Return the shared transient feedback intent for one Left / Right action."""

    if not changed:
        return (ClearAdjustmentFeedbackIntent(),)
    if area is None or control is None:
        raise ValueError("changed adjustment feedback requires area and control")
    return (
        AdjustmentPressedIntent(
            area,
            control,
            -1 if direction < 0 else 1,
        ),
    )


@dataclass(frozen=True)
class QueryApplicationResult:
    error: str | None = None


@dataclass(frozen=True)
class CaptionApplicationResult:
    unchanged: bool = False
    initial_session_created: bool = False
    added_caption_count: int = 0
    error: str | None = None


@dataclass(frozen=True)
class BuildPronunciationResult:
    error: str | None = None


@dataclass(frozen=True)
class SettingsApplicationResult:
    error_status: Status | None = None


class EditorOwnerBase:
    """Let focused owners share one active EditorState through the facade."""

    def __init__(self, host: Any) -> None:
        self._host = host

    @property
    def editor(self) -> EditorState | None:
        return self._host.editor

    @editor.setter
    def editor(self, value: EditorState | None) -> None:
        self._host.editor = value

    def __getattr__(self, name: str) -> Any:
        return getattr(self._host, name)
