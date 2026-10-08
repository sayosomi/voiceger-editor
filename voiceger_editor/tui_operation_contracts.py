"""Typed effects, events and immutable progress snapshots for TUI operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Union

from .session import UtteranceSession
from .tui_status import Status, info_status

if TYPE_CHECKING:
    from .tui_dictionary_operations import DictionaryOperationRequest


@dataclass(frozen=True)
class UpdateStatusEffect:
    status: Status
    channel: str = field(default="status", compare=False)

    def __init__(self, status: Status | str, *, channel: str = "status") -> None:
        object.__setattr__(
            self,
            "status",
            status if isinstance(status, Status) else info_status(status),
        )
        object.__setattr__(self, "channel", channel)


@dataclass(frozen=True)
class BackgroundOperationProgress:
    """Stable snapshot for cross-screen Take-generation presentation."""

    operation_id: int
    operation: str
    item_id: str | None
    completed: int
    total: int
    take_number: int | None = None
    take_completed: int = 0
    take_total: int | None = None
    caption_number: int | None = None
    caption_total: int | None = None


@dataclass(frozen=True)
class FocusEffect:
    focus_key: tuple[str, int | None]


@dataclass(frozen=True)
class PlayTakeEffect:
    number: int


@dataclass(frozen=True)
class StopPlaybackEffect:
    pass


@dataclass(frozen=True)
class DiscardInitialBatchEffect:
    item_id: str | None = None


@dataclass(frozen=True)
class BatchCandidateReplacedEffect:
    item_id: str
    number: int


@dataclass(frozen=True)
class CandidateReplacedEffect:
    number: int
    item_id: str | None = None


@dataclass(frozen=True)
class TakeAcceptedEffect:
    item_id: str
    number: int


@dataclass(frozen=True)
class GenerationOutcomeEffect:
    item_id: str
    outcome: str


@dataclass(frozen=True)
class DictionaryOperationCompletedEffect:
    request: DictionaryOperationRequest
    value: Any = None
    error: BaseException | None = None


@dataclass(frozen=True)
class SessionPreparationCompletedEffect:
    session: UtteranceSession
    rebuild: bool
    error: BaseException | None = None


@dataclass(frozen=True)
class TakeAcceptanceCompletedEvent:
    item_id: str
    number: int
    saved: Any | None = None
    error: BaseException | None = None


@dataclass(frozen=True)
class DictionaryOperationCompletedEvent:
    request: DictionaryOperationRequest
    value: Any = None
    error: BaseException | None = None


@dataclass(frozen=True)
class SessionPreparationCompletedEvent:
    session: UtteranceSession
    rebuild: bool
    error: BaseException | None = None


@dataclass(frozen=True)
class PlayPreviewEffect:
    audio: Any
    sampling_rate: int


@dataclass(frozen=True)
class PreviewReadyEvent:
    audio: Any
    sampling_rate: int


@dataclass(frozen=True)
class PreviewFailedEvent:
    error: BaseException


@dataclass(frozen=True)
class GenerationCandidateEvent:
    candidate: Any


@dataclass(frozen=True)
class GenerationFailedEvent:
    error: BaseException


@dataclass(frozen=True)
class OperationDoneEvent:
    pass


@dataclass(frozen=True)
class BatchGenerationProgressEvent:
    item_id: str
    caption_number: int
    caption_total: int
    take_number: int
    take_total: int
    overall_completed: int
    overall_total: int


@dataclass(frozen=True)
class BatchCandidateReadyEvent:
    item_id: str
    caption_number: int
    caption_total: int
    take_number: int
    take_total: int
    overall_completed: int
    overall_total: int
    replacing_existing: bool


@dataclass(frozen=True)
class BatchGenerationFailedEvent:
    item_id: str
    caption_number: int
    caption_total: int
    take_number: int
    take_total: int
    error: BaseException


@dataclass(frozen=True)
class BatchGenerationCancelledEvent:
    item_id: str


OperationEffect = Union[
    UpdateStatusEffect,
    FocusEffect,
    PlayTakeEffect,
    PlayPreviewEffect,
    StopPlaybackEffect,
    DiscardInitialBatchEffect,
    BatchCandidateReplacedEffect,
    CandidateReplacedEffect,
    TakeAcceptedEffect,
    GenerationOutcomeEffect,
    DictionaryOperationCompletedEffect,
    SessionPreparationCompletedEffect,
]

