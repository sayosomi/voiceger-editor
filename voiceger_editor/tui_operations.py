"""Synthesis operation, candidate playback, and acceptance coordination."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
import os
import queue
import shutil
import subprocess
import sys
import tempfile
from threading import Event, Thread
from typing import TYPE_CHECKING, Any, Callable, Iterable, Union

from .caption_batch import CaptionBatch
from .session import UtteranceSession
from .settings import Settings
from .tui_status import Status, error_status, info_status, warning_status
from .voiceger_adapter import VoicegerAdapter
from .voicevox_api_models import AudioQuery

if TYPE_CHECKING:
    from .tui_dictionary import DictionaryOperationIntent, DictionaryOperationRequest


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
    DictionaryOperationCompletedEffect,
    SessionPreparationCompletedEffect,
]


class TuiOperations:
    """Own operation state and return typed effects for app-owned actions."""

    def __init__(
        self,
        *,
        platform: Callable[[], str] | None = None,
        which: Callable[[str], str | None] | None = None,
        popen: Callable[..., subprocess.Popen[Any]] | None = None,
    ) -> None:
        self._platform = platform or (lambda: sys.platform)
        self._which = which or (lambda name: shutil.which(name))
        self._popen = popen or (
            lambda *args, **kwargs: subprocess.Popen(*args, **kwargs)
        )
        self.events: queue.Queue[Any] = queue.Queue()
        self.worker: Thread | None = None
        self.worker_operation: str | None = None
        self.worker_target: int | None = None
        self.worker_error: BaseException | None = None
        self.busy = False
        self.operation_completed = 0
        self.operation_total = 0
        self.operation_focus_revision = 0
        self._cancellation_event: Event | None = None
        self.cancellation_requested = False
        self._worker_item_id: str | None = None
        self._ctrl_c_cancellation_guard = False
        self.current_take: int | None = None
        self.playback_process: subprocess.Popen[Any] | None = None
        self._preview_temporary_directory: (
            tempfile.TemporaryDirectory[str] | None
        ) = None
        self._pending_worker: tuple[Callable[[], None], str] | None = None

    def start_batch_generation(
        self,
        batch: CaptionBatch,
        *,
        navigation_revision: int,
    ) -> tuple[OperationEffect, ...]:
        """Generate selected Caption items sequentially on one worker."""

        if self.busy:
            return (
                UpdateStatusEffect("Another operation is already running."),
            )

        selected = batch.included_items
        if not selected:
            return (
                UpdateStatusEffect(
                    "Select at least one Caption before generating."
                ),
            )

        plan = tuple(
            (item, batch.effective_take_count(item))
            for item in selected
        )
        overall_total = sum(take_total for _item, take_total in plan)
        first_take_total = plan[0][1]

        self.stop_playback()
        self.current_take = None
        self.busy = True
        self.worker_operation = "batch_generate"
        self.worker_target = None
        self._worker_item_id = None
        self.worker_error = None
        self.operation_focus_revision = navigation_revision
        self.operation_completed = 0
        self.operation_total = overall_total
        cancellation_event = Event()
        self._cancellation_event = cancellation_event
        self.cancellation_requested = False
        self._ctrl_c_cancellation_guard = True

        def work() -> None:
            overall_completed = 0
            try:
                with open(os.devnull, "w", encoding="utf-8") as sink:
                    with redirect_stdout(sink), redirect_stderr(sink):
                        for caption_number, (item, take_total) in enumerate(
                            plan, start=1
                        ):
                            if cancellation_event.is_set():
                                break
                            iterator = None
                            try:
                                try:
                                    if not item.session.is_prepared:
                                        item.session.prepare_from_caption()
                                    replacing_existing = item.session.has_active_batch
                                    if replacing_existing:
                                        values = item.session.regenerate_all_takes(
                                            take_count=take_total
                                        )
                                    else:
                                        values = item.session.generate_takes(
                                            take_count=take_total
                                        )
                                    iterator = iter(values)
                                except BaseException as exc:
                                    self.events.put(
                                        BatchGenerationFailedEvent(
                                            item_id=item.item_id,
                                            caption_number=caption_number,
                                            caption_total=len(plan),
                                            take_number=1,
                                            take_total=take_total,
                                            error=exc,
                                        )
                                    )
                                    return

                                for take_number in range(1, take_total + 1):
                                    if cancellation_event.is_set():
                                        return
                                    self.events.put(
                                        BatchGenerationProgressEvent(
                                            item_id=item.item_id,
                                            caption_number=caption_number,
                                            caption_total=len(plan),
                                            take_number=take_number,
                                            take_total=take_total,
                                            overall_completed=overall_completed,
                                            overall_total=overall_total,
                                        )
                                    )
                                    try:
                                        next(iterator)
                                    except StopIteration:
                                        self.events.put(
                                            BatchGenerationFailedEvent(
                                                item_id=item.item_id,
                                                caption_number=caption_number,
                                                caption_total=len(plan),
                                                take_number=take_number,
                                                take_total=take_total,
                                                error=RuntimeError(
                                                    "take generation ended before the requested count"
                                                ),
                                            )
                                        )
                                        return
                                    except BaseException as exc:
                                        self.events.put(
                                            BatchGenerationFailedEvent(
                                                item_id=item.item_id,
                                                caption_number=caption_number,
                                                caption_total=len(plan),
                                                take_number=take_number,
                                                take_total=take_total,
                                                error=exc,
                                            )
                                        )
                                        return

                                    overall_completed += 1
                                    self.events.put(
                                        BatchCandidateReadyEvent(
                                            item_id=item.item_id,
                                            caption_number=caption_number,
                                            caption_total=len(plan),
                                            take_number=take_number,
                                            take_total=take_total,
                                            overall_completed=overall_completed,
                                            overall_total=overall_total,
                                            replacing_existing=replacing_existing,
                                        )
                                    )
                            finally:
                                if iterator is not None:
                                    close = getattr(iterator, "close", None)
                                    if callable(close):
                                        close()
            finally:
                self.events.put(("done", None))

        self.worker = Thread(
            target=work,
            name="voiceger-tui-batch-synthesis",
            daemon=True,
        )
        self.worker.start()
        return (
            UpdateStatusEffect(
                f"Generating {len(plan)} selected Caption(s), "
                f"{overall_total} take(s) total · "
                f"Caption 1/{len(plan)} · Take 1/{first_take_total} · "
                f"Overall 0/{overall_total}",
                channel="background",
            ),
        )

    def start_generation(
        self,
        session: UtteranceSession | None,
        *,
        take_count: int,
        navigation_revision: int,
        item_id: str | None = None,
    ) -> tuple[OperationEffect, ...]:
        if self.busy:
            return (
                UpdateStatusEffect("Another operation is already running."),
            )
        if session is None:
            return ()
        if session.has_active_batch:
            return (
                UpdateStatusEffect(
                    "A take batch already exists; use g to regenerate all takes."
                ),
            )
        try:
            values = session.generate_takes()
        except Exception as exc:
            return (
                UpdateStatusEffect(error_status(f"Could not start take generation: {exc}")),
            )
        self.current_take = None
        return self.run_worker(
            lambda: values,
            f"Generating 1/{take_count}",
            operation="initial",
            take_count=take_count,
            navigation_revision=navigation_revision,
            item_id=item_id,
        )

    def start_regeneration(
        self,
        session: UtteranceSession | None,
        number: int,
        *,
        take_count: int,
        navigation_revision: int,
        item_id: str | None = None,
    ) -> tuple[OperationEffect, ...]:
        if self.busy:
            return (
                UpdateStatusEffect("Another operation is already running."),
            )
        if session is None:
            return ()
        self.stop_playback()
        self.current_take = number
        return self.run_worker(
            lambda: (session.regenerate_take(number),),
            f"Regenerating take {number}…",
            operation="regenerate_one",
            target=number,
            take_count=take_count,
            navigation_revision=navigation_revision,
            item_id=item_id,
        )

    def start_regenerate_all(
        self,
        session: UtteranceSession | None,
        *,
        take_count: int,
        navigation_revision: int,
        item_id: str | None = None,
    ) -> tuple[OperationEffect, ...]:
        if self.busy:
            return (
                UpdateStatusEffect("Another operation is already running."),
            )
        if session is None:
            return ()
        try:
            values = session.regenerate_all_takes()
        except Exception as exc:
            return (
                UpdateStatusEffect(error_status(f"Could not regenerate all takes: {exc}")),
            )
        return self.run_worker(
            lambda: values,
            f"Regenerating 1/{take_count}",
            operation="regenerate_all",
            take_count=take_count,
            navigation_revision=navigation_revision,
            item_id=item_id,
        )

    def start_preview(
        self,
        session: UtteranceSession | None,
        query: AudioQuery,
        *,
        adapter: VoicegerAdapter | None = None,
        settings: Settings | None = None,
    ) -> tuple[OperationEffect, ...]:
        """Synthesize one fixed transient query on the background worker."""

        if self.busy:
            return (
                UpdateStatusEffect("Wait for the current operation to finish."),
            )
        try:
            query_snapshot = query.model_copy(deep=True)
            if session is None:
                if adapter is None or settings is None:
                    raise RuntimeError("Preview synthesis context is unavailable")
                session = UtteranceSession(
                    adapter=adapter,
                    caption="Dictionary Preview",
                    query=query_snapshot,
                    settings=settings,
                )
        except Exception as exc:
            return (UpdateStatusEffect(error_status(f"Could not start Preview: {exc}")),)

        # A single owned player is reused for takes and previews. Stopping it
        # does not clear the user's selected candidate.
        self.stop_playback()
        self.busy = True
        self.worker_operation = "preview"
        self.worker_target = None
        self.worker_error = None
        self.operation_completed = 0
        self.operation_total = 1

        def work() -> None:
            try:
                with open(os.devnull, "w", encoding="utf-8") as sink:
                    with redirect_stdout(sink), redirect_stderr(sink):
                        result = session.preview_synthesis(query_snapshot)
                self.events.put(
                    PreviewReadyEvent(
                        audio=result["audio"],
                        sampling_rate=int(result["sampling_rate"]),
                    )
                )
            except BaseException as exc:
                self.events.put(PreviewFailedEvent(exc))
            finally:
                self.events.put(("done", None))

        self.worker = Thread(
            target=work,
            name="voiceger-tui-preview",
            daemon=True,
        )
        self.worker.start()
        return (UpdateStatusEffect("Synthesizing pronunciation Preview…"),)

    def start_session_preparation(
        self,
        session: UtteranceSession,
        *,
        rebuild: bool,
    ) -> tuple[OperationEffect, ...]:
        """Prepare one session after an in-progress Status has rendered."""

        if self.busy:
            return (UpdateStatusEffect("Wait for the current operation to finish."),)
        if not rebuild and session.is_prepared:
            return ()

        self.busy = True
        self.worker_operation = "prepare"
        self.worker_target = None
        self.worker_error = None
        self.operation_completed = 0
        self.operation_total = 1
        self._cancellation_event = None
        self.cancellation_requested = False

        def work() -> None:
            try:
                with open(os.devnull, "w", encoding="utf-8") as sink:
                    with redirect_stdout(sink), redirect_stderr(sink):
                        session.prepare_from_caption()
            except BaseException as exc:
                self.events.put(
                    SessionPreparationCompletedEvent(
                        session=session,
                        rebuild=rebuild,
                        error=exc,
                    )
                )
            else:
                self.events.put(
                    SessionPreparationCompletedEvent(
                        session=session,
                        rebuild=rebuild,
                    )
                )

        self._pending_worker = (work, "voiceger-tui-pronunciation")
        return (
            UpdateStatusEffect(
                "Rebuilding pronunciation…"
                if rebuild
                else "Preparing pronunciation…"
            ),
        )

    def start_dictionary_operation(
        self,
        intent: DictionaryOperationIntent,
    ) -> tuple[OperationEffect, ...]:
        """Defer Dictionary analysis or persistence until its Status can render."""

        if self.busy:
            return (UpdateStatusEffect("Wait for the current operation to finish."),)

        self.busy = True
        self.worker_operation = "dictionary"
        self.worker_target = None
        self.worker_error = None
        self.operation_completed = 0
        self.operation_total = 1
        self._cancellation_event = None
        self.cancellation_requested = False

        def work() -> None:
            try:
                with open(os.devnull, "w", encoding="utf-8") as sink:
                    with redirect_stdout(sink), redirect_stderr(sink):
                        value = intent.work()
            except BaseException as exc:
                self.events.put(
                    DictionaryOperationCompletedEvent(
                        request=intent.request,
                        error=exc,
                    )
                )
            else:
                self.events.put(
                    DictionaryOperationCompletedEvent(
                        request=intent.request,
                        value=value,
                    )
                )

        self._pending_worker = (work, "voiceger-tui-dictionary")
        return (UpdateStatusEffect(intent.status),)

    def start_pending_worker(self) -> None:
        """Start work deferred until its in-progress Status has been rendered."""

        pending = self._pending_worker
        if pending is None:
            return
        work, name = pending
        self._pending_worker = None
        self.worker = Thread(target=work, name=name, daemon=True)
        self.worker.start()

    def run_worker(
        self,
        make_values: Callable[[], Iterable[Any]],
        status: str,
        *,
        operation: str,
        take_count: int,
        navigation_revision: int,
        target: int | None = None,
        item_id: str | None = None,
    ) -> tuple[OperationEffect, ...]:
        self.busy = True
        self.worker_operation = operation
        self.worker_target = target
        self._worker_item_id = item_id
        self.worker_error = None
        self.operation_focus_revision = navigation_revision
        self.operation_completed = 0
        self.operation_total = 1 if operation == "regenerate_one" else take_count
        cancellation_event = Event()
        self._cancellation_event = cancellation_event
        self.cancellation_requested = False
        if operation in {"initial", "regenerate_all"}:
            self._ctrl_c_cancellation_guard = True

        def work() -> None:
            try:
                with open(os.devnull, "w", encoding="utf-8") as sink:
                    with redirect_stdout(sink), redirect_stderr(sink):
                        values = iter(make_values())
                        while not cancellation_event.is_set():
                            try:
                                candidate = next(values)
                            except StopIteration:
                                break
                            self.events.put(("candidate", candidate))
            except BaseException as exc:
                self.events.put(("error", exc))
            finally:
                self.events.put(("done", None))

        self.worker = Thread(
            target=work,
            name="voiceger-tui-synthesis",
            daemon=True,
        )
        self.worker.start()
        return (UpdateStatusEffect(status, channel="background"),)

    @property
    def can_cancel_batch(self) -> bool:
        """Whether the active worker is an initial or all-takes operation."""

        return self.busy and self.worker_operation in {
            "initial",
            "regenerate_all",
            "batch_generate",
        }

    @property
    def active_item_generation_progress(self) -> tuple[str, int, int] | None:
        """Return progress for the currently generating individual Batch Item."""

        if (
            not self.busy
            or self.worker_operation not in {"initial", "regenerate_all"}
            or self._worker_item_id is None
            or self.operation_total <= 0
        ):
            return None
        return (
            self._worker_item_id,
            self.operation_completed,
            self.operation_total,
        )

    @property
    def active_generation_item_id(self) -> str | None:
        """Return the stable owner of an active individual Take operation."""

        if (
            not self.busy
            or self.worker_operation
            not in {"initial", "regenerate_one", "regenerate_all"}
        ):
            return None
        return self._worker_item_id

    @property
    def generation_slot_busy(self) -> bool:
        """Whether a Take synthesis operation currently owns the single slot."""

        return self.busy and self.worker_operation in {
            "initial",
            "regenerate_one",
            "regenerate_all",
            "batch_generate",
        }

    def background_generation_status(self, batch: CaptionBatch) -> str:
        """Describe active Take synthesis independently from transient Status."""

        if not self.generation_slot_busy:
            return ""

        def caption_number(item_id: str | None) -> int | None:
            if item_id is None:
                return None
            try:
                item = batch.get_item(item_id)
            except KeyError:
                return None
            return batch.items.index(item) + 1

        operation = self.worker_operation
        total = max(0, self.operation_total)
        completed = max(0, min(self.operation_completed, total)) if total else 0
        percent = round(completed * 100 / total) if total else 0

        if operation in {"initial", "regenerate_all"}:
            number = caption_number(self._worker_item_id)
            owner = f"Caption {number}" if number is not None else "Caption"
            verb = "Regenerating" if operation == "regenerate_all" else "Generating"
            return f"{verb}: {owner} · {completed}/{total} ({percent}%)"

        if operation == "regenerate_one":
            number = caption_number(self._worker_item_id)
            owner = f"Caption {number}" if number is not None else "Caption"
            return f"Regenerating: {owner} · Take {self.worker_target}"

        if operation == "batch_generate":
            return (
                f"Generating: selected Captions · "
                f"{completed}/{total} ({percent}%)"
            )

        return ""

    def generation_conflict_status(
        self,
        batch: CaptionBatch,
        *,
        requested_item_id: str | None = None,
        requested_batch: bool = False,
    ) -> Status | None:
        """Explain why a new generation request cannot start right now."""

        if not self.busy:
            return None

        def caption_number(item_id: str | None) -> int | None:
            if item_id is None:
                return None
            try:
                item = batch.get_item(item_id)
            except KeyError:
                return None
            return batch.items.index(item) + 1

        operation = self.worker_operation
        active_number = caption_number(self._worker_item_id)
        requested_number = caption_number(requested_item_id)
        individual_generation = operation in {
            "initial",
            "regenerate_one",
            "regenerate_all",
        }
        batch_generation = operation == "batch_generate"

        if requested_batch:
            if batch_generation:
                return warning_status("Generate selected is already running.")
            if individual_generation:
                return warning_status(
                    "Generate selected is unavailable while generation is active."
                )
            return warning_status(
                "Generate selected is unavailable while another operation is active."
            )

        if requested_number is not None:
            if individual_generation and active_number == requested_number:
                return warning_status(
                    f"Caption {requested_number} is already generating."
                )
            if batch_generation:
                return warning_status(
                    f"Generate Caption {requested_number} is unavailable "
                    "while batch generation is active."
                )
            if individual_generation:
                return warning_status(
                    f"Generate Caption {requested_number} is unavailable "
                    "while generation is active."
                )
            return warning_status(
                f"Generate Caption {requested_number} is unavailable "
                "while another operation is active."
            )

        if batch_generation:
            return warning_status(
                "Generate is unavailable while batch generation is active."
            )
        if individual_generation:
            return warning_status(
                "Generate is unavailable while generation is active."
            )
        return warning_status(
            "Generate is unavailable while another operation is active."
        )

    @property
    def cancellation_guard_armed(self) -> bool:
        """Whether Ctrl+C still belongs to the most recent cancellable generation."""

        return self._ctrl_c_cancellation_guard

    def clear_completed_cancellation_guard(self) -> None:
        """Release Ctrl+C back to quit after post-generation user interaction."""

        if not self.can_cancel_batch:
            self._ctrl_c_cancellation_guard = False

    def request_batch_cancellation(self) -> tuple[OperationEffect, ...]:
        """Request cancellation at the next take boundary."""

        if not self.can_cancel_batch:
            return ()
        cancellation_event = self._cancellation_event
        if cancellation_event is not None:
            cancellation_event.set()
        self.cancellation_requested = True
        return (UpdateStatusEffect("Cancelling…"),)

    def request_shutdown(self) -> tuple[OperationEffect, ...]:
        """Prepare a safe shutdown without forcibly terminating Voiceger."""

        if self.can_cancel_batch:
            self.request_batch_cancellation()
            return (UpdateStatusEffect("Cancelling current batch before cleanup…"),)
        if self.busy:
            if self.worker_operation == "accept":
                return (
                    UpdateStatusEffect("Finishing the current Take save before cleanup…"),
                )
            if self.worker_operation == "dictionary":
                return (
                    UpdateStatusEffect(
                        "Finishing the current Dictionary operation before cleanup…"
                    ),
                )
            if self.worker_operation == "prepare":
                return (
                    UpdateStatusEffect(
                        "Finishing pronunciation preparation before cleanup…"
                    ),
                )
            return (UpdateStatusEffect("Finishing the current synthesis before cleanup…"),)
        return ()

    def consume_pending_events(
        self,
        session: UtteranceSession | None,
        *,
        navigation_revision: int,
        pronunciation_index: int,
        exit_requested: bool,
    ) -> tuple[OperationEffect, ...]:
        effects: list[OperationEffect] = []
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return tuple(effects)

            if isinstance(event, PreviewReadyEvent):
                self.operation_completed = 1
                effects.append(PlayPreviewEffect(event.audio, event.sampling_rate))
                continue
            if isinstance(event, PreviewFailedEvent):
                self.worker_error = event.error
                effects.append(
                    UpdateStatusEffect(error_status(f"Preview failed: {event.error}"))
                )
                continue
            if isinstance(event, SessionPreparationCompletedEvent):
                self.busy = False
                self.operation_completed = 1
                self.operation_total = 1
                self.worker_error = event.error
                self.worker_operation = None
                self.worker_target = None
                self._cancellation_event = None
                self.cancellation_requested = False
                effects.append(
                    SessionPreparationCompletedEffect(
                        session=event.session,
                        rebuild=event.rebuild,
                        error=event.error,
                    )
                )
                continue
            if isinstance(event, DictionaryOperationCompletedEvent):
                self.busy = False
                self.operation_completed = 1
                self.operation_total = 1
                self.worker_error = event.error
                self.worker_operation = None
                self.worker_target = None
                self._cancellation_event = None
                self.cancellation_requested = False
                effects.append(
                    DictionaryOperationCompletedEffect(
                        request=event.request,
                        value=event.value,
                        error=event.error,
                    )
                )
                continue
            if isinstance(event, TakeAcceptanceCompletedEvent):
                self.busy = False
                self.operation_completed = 1
                self.worker_error = event.error
                self.worker_operation = None
                self.worker_target = None
                self._cancellation_event = None
                self.cancellation_requested = False
                if event.error is not None:
                    effects.append(
                        UpdateStatusEffect(
                            error_status(
                                f"Take {event.number} was not saved: {event.error}"
                            )
                        )
                    )
                else:
                    self.current_take = None
                    effects.append(TakeAcceptedEffect(event.item_id, event.number))
                    effects.append(
                        UpdateStatusEffect(self._saved_output_status(event.saved))
                    )
                continue
            if isinstance(event, BatchGenerationProgressEvent):
                self.operation_completed = event.overall_completed
                effects.append(
                    UpdateStatusEffect(
                        f"Caption {event.caption_number}/{event.caption_total} · "
                        f"Take {event.take_number}/{event.take_total} · "
                        f"Overall {event.overall_completed}/{event.overall_total}",
                        channel="background",
                    )
                )
                continue
            if isinstance(event, BatchCandidateReadyEvent):
                self.operation_completed = event.overall_completed
                effects.append(
                    UpdateStatusEffect(
                        f"Caption {event.caption_number}/{event.caption_total} · "
                        f"Take {event.take_number}/{event.take_total} · "
                        f"Overall {event.overall_completed}/{event.overall_total}",
                        channel="background",
                    )
                )
                if event.replacing_existing:
                    effects.append(
                        BatchCandidateReplacedEffect(
                            item_id=event.item_id,
                            number=event.take_number,
                        )
                    )
                continue
            if isinstance(event, BatchGenerationFailedEvent):
                self.worker_error = event.error
                effects.append(
                    UpdateStatusEffect(
                        error_status(
                            "Batch generation failed at "
                            f"Caption {event.caption_number}/{event.caption_total}, "
                            f"Take {event.take_number}/{event.take_total}: {event.error}"
                        )
                    )
                )
                continue

            kind, value = event

            if kind == "candidate":
                operation = self.worker_operation
                self.operation_completed += 1
                if operation == "initial":
                    status = (
                        f"Generating {min(self.operation_completed + 1, self.operation_total)}"
                        f"/{self.operation_total} · {self.operation_completed} ready"
                    )
                elif operation == "regenerate_all":
                    status = (
                        f"Regenerating {min(self.operation_completed + 1, self.operation_total)}"
                        f"/{self.operation_total} · {self.operation_completed} ready"
                    )
                else:
                    status = f"Take {value.number} replacement ready."
                effects.append(UpdateStatusEffect(status, channel="background"))

                if operation == "initial":
                    if (
                        self.operation_completed == 1
                        and navigation_revision == self.operation_focus_revision
                    ):
                        self.current_take = value.number
                        effects.append(FocusEffect(("candidate", value.number)))
                        effects.append(PlayTakeEffect(value.number))
                elif operation == "regenerate_one":
                    effects.append(
                        CandidateReplacedEffect(
                            value.number,
                            item_id=self._worker_item_id,
                        )
                    )
                    if (
                        value.number == self.worker_target
                        and self.current_take == value.number
                    ):
                        effects.append(PlayTakeEffect(value.number))
                elif operation == "regenerate_all":
                    effects.append(
                        CandidateReplacedEffect(
                            value.number,
                            item_id=self._worker_item_id,
                        )
                    )
                    if value.number == self.current_take:
                        effects.append(PlayTakeEffect(value.number))

            elif kind == "error":
                self.worker_error = value
                if self.worker_operation == "preview":
                    effects.append(
                        UpdateStatusEffect(error_status(f"Preview failed: {value}"))
                    )
                else:
                    effects.append(
                        UpdateStatusEffect(error_status(f"Generation failed: {value}"))
                    )
                if (
                    self.worker_operation == "initial"
                    and not self.cancellation_requested
                ):
                    effects.append(StopPlaybackEffect())
                    effects.append(DiscardInitialBatchEffect(self._worker_item_id))
                    self.current_take = None
                    effects.append(FocusEffect(("pronunciation", pronunciation_index)))

            elif kind == "done":
                operation = self.worker_operation
                cancelled = self.cancellation_requested
                self.busy = False
                if operation == "preview":
                    status = None
                elif operation == "batch_generate":
                    if cancelled:
                        status = (
                            "Batch generation cancelled. "
                            f"{self.operation_completed}/{self.operation_total} "
                            "take(s) ready."
                        )
                    elif self.worker_error is not None:
                        status = None
                    else:
                        status = (
                            "Batch generation finished. "
                            f"{self.operation_completed}/{self.operation_total} "
                            "take(s) ready."
                        )
                elif cancelled and operation == "initial":
                    ready = self.operation_completed
                    status = f"Generation cancelled. {ready} take(s) ready."
                    if ready == 0:
                        effects.append(StopPlaybackEffect())
                        effects.append(DiscardInitialBatchEffect(self._worker_item_id))
                        self.current_take = None
                        effects.append(
                            FocusEffect(("pronunciation", pronunciation_index))
                        )
                elif cancelled and operation == "regenerate_all":
                    status = (
                        "Regeneration cancelled after "
                        f"{self.operation_completed} replacement(s)."
                    )
                elif self.worker_error is not None:
                    status = error_status(f"Generation failed: {self.worker_error}")
                elif operation == "initial" and self.operation_completed:
                    status = f"{self.operation_completed} take(s) ready."
                elif operation in {"regenerate_one", "regenerate_all"}:
                    status = "Take regeneration finished."
                elif not exit_requested:
                    status = "No takes were generated. Select Generate to try again."
                else:
                    status = None
                if status is not None:
                    effects.append(UpdateStatusEffect(status))
                self.worker_operation = None
                self.worker_target = None
                self._worker_item_id = None
                self._cancellation_event = None
                self.cancellation_requested = False

    def play_take(
        self,
        session: UtteranceSession | None,
        number: int,
    ) -> tuple[OperationEffect, ...]:
        if session is None:
            return ()
        candidate = next(
            (item for item in session.candidates if item.number == number),
            None,
        )
        if candidate is None:
            return (UpdateStatusEffect(f"Take {number} is not available yet."),)

        return self._play_path(
            candidate.wav_path,
            status=f"Playing take {number}.",
            error_prefix=f"Could not play take {number}",
            take_number=number,
        )

    def play_preview(
        self,
        audio: Any,
        sampling_rate: int,
    ) -> tuple[OperationEffect, ...]:
        """Write and play preview audio from a temporary runtime directory."""

        self.stop_playback()
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="voiceger-preview-"
        )
        wav_path = Path(temporary_directory.name) / "preview.wav"
        try:
            import soundfile as sf

            sf.write(wav_path, audio, sampling_rate)
        except Exception as exc:
            temporary_directory.cleanup()
            return (UpdateStatusEffect(error_status(f"Could not prepare Preview: {exc}")),)
        return self._play_path(
            wav_path,
            status="Playing pronunciation Preview.",
            error_prefix="Could not play Preview",
            preview_temporary_directory=temporary_directory,
        )

    def _play_path(
        self,
        wav_path: Path,
        *,
        status: str,
        error_prefix: str,
        take_number: int | None = None,
        preview_temporary_directory: tempfile.TemporaryDirectory[str] | None = None,
    ) -> tuple[OperationEffect, ...]:
        self.stop_playback()
        try:
            command = self._player_command(wav_path)
            if command is None:
                if preview_temporary_directory is not None:
                    preview_temporary_directory.cleanup()
                return (UpdateStatusEffect(self._missing_player_status()),)
            self.playback_process = self._popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._preview_temporary_directory = preview_temporary_directory
            if take_number is not None:
                self.current_take = take_number
            return (UpdateStatusEffect(status),)
        except OSError as exc:
            if preview_temporary_directory is not None:
                preview_temporary_directory.cleanup()
            return (UpdateStatusEffect(error_status(f"{error_prefix}: {exc}")),)

    def _missing_player_status(self) -> Status:
        if self._platform() == "win32":
            return error_status(
                "Playback on Windows requires ffplay.exe in PATH. "
                "Install an FFmpeg build that includes ffplay.exe and add its bin "
                "directory to PATH."
            )
        return error_status(
            "Playback needs afplay (macOS) or ffplay (other systems)."
        )

    def _player_command(self, wav_path: Path) -> list[str] | None:
        if self._platform() == "darwin":
            player = self._which("afplay")
            if player:
                return [player, str(wav_path)]
        player = self._which("ffplay")
        if not player:
            return None
        return [
            player,
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "error",
            str(wav_path),
        ]

    def stop_playback(self) -> None:
        process = self.playback_process
        self.playback_process = None
        if process is None:
            self._cleanup_preview_temporary_directory()
            return
        try:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        finally:
            self._cleanup_preview_temporary_directory()

    def _cleanup_preview_temporary_directory(self) -> None:
        temporary_directory = self._preview_temporary_directory
        self._preview_temporary_directory = None
        if temporary_directory is not None:
            temporary_directory.cleanup()

    def clear_current_take(self) -> None:
        self.current_take = None

    @staticmethod
    def _saved_output_status(saved: Any) -> Status:
        sidecars = []
        if saved.text_path is not None:
            sidecars.append(saved.text_path.name)
        lab_path = getattr(saved, "lab_path", None)
        if lab_path is not None:
            sidecars.append(lab_path.name)
        names = [saved.wav_path.name, *sidecars]
        status = info_status(f"Saved {' and '.join(names)}.")
        lab_warning = getattr(saved, "lab_warning", None)
        if lab_warning:
            status = warning_status(f"{status} {lab_warning}")
        return status

    def accept_take(
        self,
        session: UtteranceSession | None,
        number: int,
        *,
        item_id: str,
        busy: bool,
        pronunciation_index: int,
    ) -> tuple[OperationEffect, ...]:
        if session is None or busy or self.busy:
            return ()

        self.stop_playback()
        self.busy = True
        self.worker_operation = "accept"
        self.worker_target = number
        self.worker_error = None
        self.operation_completed = 0
        self.operation_total = 1
        self._cancellation_event = None
        self.cancellation_requested = False

        def work() -> None:
            try:
                with open(os.devnull, "w", encoding="utf-8") as sink:
                    with redirect_stdout(sink), redirect_stderr(sink):
                        saved = session.accept_take(number)
            except BaseException as exc:
                self.events.put(
                    TakeAcceptanceCompletedEvent(
                        item_id=item_id,
                        number=number,
                        error=exc,
                    )
                )
            else:
                self.events.put(
                    TakeAcceptanceCompletedEvent(
                        item_id=item_id,
                        number=number,
                        saved=saved,
                    )
                )

        self._pending_worker = (work, "voiceger-tui-acceptance")
        return (UpdateStatusEffect(f"Saving Take {number}…"),)

    def join_worker(self) -> None:
        self.start_pending_worker()
        worker = self.worker
        if worker is None or worker.ident is None:
            return
        while worker.is_alive():
            try:
                worker.join(timeout=0.1)
            except KeyboardInterrupt:
                self.request_batch_cancellation()

    def worker_is_alive(self) -> bool:
        return self._pending_worker is not None or (
            self.worker is not None and self.worker.is_alive()
        )
