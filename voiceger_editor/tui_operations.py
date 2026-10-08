"""Shared TUI background-operation lifecycle and compatibility facade."""

from __future__ import annotations

import queue
import shutil
import subprocess
import sys
from threading import Event, Thread
from typing import TYPE_CHECKING, Any, Callable, Iterable

from .caption_batch import CaptionBatch
from .session import UtteranceSession
from .settings import Settings
from .tui_operation_acceptance import TuiTakeAcceptanceOwner
from .tui_operation_contracts import (
    BackgroundOperationProgress,
    BatchCandidateReadyEvent,
    BatchCandidateReplacedEffect,
    BatchGenerationCancelledEvent,
    BatchGenerationFailedEvent,
    BatchGenerationProgressEvent,
    CandidateReplacedEffect,
    DictionaryOperationCompletedEffect,
    DictionaryOperationCompletedEvent,
    DiscardInitialBatchEffect,
    FocusEffect,
    GenerationOutcomeEffect,
    GenerationCandidateEvent,
    GenerationFailedEvent,
    OperationDoneEvent,
    OperationEffect,
    PlayPreviewEffect,
    PlayTakeEffect,
    PreviewFailedEvent,
    PreviewReadyEvent,
    SessionPreparationCompletedEffect,
    SessionPreparationCompletedEvent,
    StopPlaybackEffect,
    TakeAcceptanceCompletedEvent,
    TakeAcceptedEffect,
    UpdateStatusEffect,
)
from .tui_operation_workers import (
    make_batch_generation_work,
    make_dictionary_work,
    make_generation_work,
    make_preparation_work,
    make_preview_work,
)
from .tui_operation_conflicts import TuiOperationConflictPolicy
from .tui_operation_playback import TuiPlaybackOwner
from .tui_operation_status import (
    generation_candidate_status,
    generation_done_status,
    generation_error_status,
)
from .tui_status import Status, error_status
from .voiceger_adapter import VoicegerAdapter
from .voicevox_api_models import AudioQuery

if TYPE_CHECKING:
    from .tui_dictionary_operations import DictionaryOperationIntent


class TuiOperations:
    """Own operation state and return typed effects for app-owned actions."""

    def __init__(
        self,
        *,
        platform: Callable[[], str] | None = None,
        which: Callable[[str], str | None] | None = None,
        popen: Callable[..., subprocess.Popen[Any]] | None = None,
    ) -> None:
        self._playback = TuiPlaybackOwner(
            platform=platform or (lambda: sys.platform),
            which=which or (lambda name: shutil.which(name)),
            popen=popen or (
                lambda *args, **kwargs: subprocess.Popen(*args, **kwargs)
            ),
            update_status=UpdateStatusEffect,
        )
        self._conflict_policy = TuiOperationConflictPolicy()
        self._acceptance = TuiTakeAcceptanceOwner(
            update_status=UpdateStatusEffect,
            accepted_effect=TakeAcceptedEffect,
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
        self._owned_item_ids: frozenset[str] = frozenset()
        self._operation_serial = 0
        self._active_operation_id: int | None = None
        self._batch_progress_item_id: str | None = None
        self._batch_progress_caption_number: int | None = None
        self._batch_progress_caption_total: int | None = None
        self._batch_progress_take_number: int | None = None
        self._batch_progress_take_completed = 0
        self._batch_progress_take_total: int | None = None
        self._ctrl_c_cancellation_guard = False
        self._pending_worker: tuple[Callable[[], None], str] | None = None

    def start_batch_generation(
        self,
        batch: CaptionBatch,
        *,
        navigation_revision: int,
    ) -> tuple[OperationEffect, ...]:
        """Generate selected Caption items sequentially on one worker."""

        conflict = self.resource_conflict_status("Generate selected")
        if conflict is not None:
            return (UpdateStatusEffect(conflict),)

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
        self._owned_item_ids = frozenset(item.item_id for item, _take_total in plan)
        self._operation_serial += 1
        self._active_operation_id = self._operation_serial
        self._batch_progress_item_id = plan[0][0].item_id
        self._batch_progress_caption_number = 1
        self._batch_progress_caption_total = len(plan)
        self._batch_progress_take_number = 1
        self._batch_progress_take_completed = 0
        self._batch_progress_take_total = first_take_total
        self.worker_error = None
        self.operation_focus_revision = navigation_revision
        self.operation_completed = 0
        self.operation_total = overall_total
        cancellation_event = Event()
        self._cancellation_event = cancellation_event
        self.cancellation_requested = False
        self._ctrl_c_cancellation_guard = True

        work = make_batch_generation_work(
            plan,
                        overall_total=overall_total,
                        cancellation_event=cancellation_event,
                        emit_event=self.events.put,
        )

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
        conflict = self.resource_conflict_status("Generate Caption")
        if conflict is not None:
            return (UpdateStatusEffect(conflict),)
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
        conflict = self.resource_conflict_status(f"Regenerate Take {number}")
        if conflict is not None:
            return (UpdateStatusEffect(conflict),)
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
        conflict = self.resource_conflict_status("Regenerate all Takes")
        if conflict is not None:
            return (UpdateStatusEffect(conflict),)
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

        conflict = self.resource_conflict_status("Pronunciation Preview")
        if conflict is not None:
            return (UpdateStatusEffect(conflict),)
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
        self._owned_item_ids = frozenset()
        self.worker_error = None
        self.operation_completed = 0
        self.operation_total = 1

        work = make_preview_work(
            session, query_snapshot, emit_event=self.events.put,
        )

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
        item_id: str | None = None,
    ) -> tuple[OperationEffect, ...]:
        """Prepare one session after an in-progress Status has rendered."""

        conflict = self.resource_conflict_status("Pronunciation preparation")
        if conflict is not None:
            return (UpdateStatusEffect(conflict),)
        if not rebuild and session.is_prepared:
            return ()

        self.busy = True
        self.worker_operation = "prepare"
        self.worker_target = None
        self._owned_item_ids = (
            frozenset({item_id}) if item_id is not None else frozenset()
        )
        self.worker_error = None
        self.operation_completed = 0
        self.operation_total = 1
        self._cancellation_event = None
        self.cancellation_requested = False

        work = make_preparation_work(
            session, rebuild=rebuild, emit_event=self.events.put,
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

        conflict = self.resource_conflict_status("Dictionary operation")
        if conflict is not None:
            return (UpdateStatusEffect(conflict),)

        self.busy = True
        self.worker_operation = "dictionary"
        self.worker_target = None
        self._owned_item_ids = frozenset()
        self.worker_error = None
        self.operation_completed = 0
        self.operation_total = 1
        self._cancellation_event = None
        self.cancellation_requested = False

        work = make_dictionary_work(
            intent, emit_event=self.events.put,
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
        self._owned_item_ids = (
            frozenset({item_id}) if item_id is not None else frozenset()
        )
        self._operation_serial += 1
        self._active_operation_id = self._operation_serial
        self._batch_progress_item_id = None
        self._batch_progress_caption_number = None
        self._batch_progress_caption_total = None
        self._batch_progress_take_number = None
        self._batch_progress_take_completed = 0
        self._batch_progress_take_total = None
        self.worker_error = None
        self.operation_focus_revision = navigation_revision
        self.operation_completed = 0
        self.operation_total = 1 if operation == "regenerate_one" else take_count
        cancellation_event = Event()
        self._cancellation_event = cancellation_event
        self.cancellation_requested = False
        if operation in {"initial", "regenerate_all"}:
            self._ctrl_c_cancellation_guard = True

        work = make_generation_work(
            make_values,
                        cancellation_event=cancellation_event,
                        emit_event=self.events.put,
        )

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
    def background_operation_progress(self) -> BackgroundOperationProgress | None:
        """Return stable cross-screen progress for the active Take operation."""

        operation_id = self._active_operation_id
        operation = self.worker_operation
        if (
            not self.generation_slot_busy
            or operation_id is None
            or operation is None
        ):
            return None

        if operation == "batch_generate":
            return BackgroundOperationProgress(
                operation_id=operation_id,
                operation=operation,
                item_id=self._batch_progress_item_id,
                completed=self.operation_completed,
                total=self.operation_total,
                take_number=self._batch_progress_take_number,
                take_completed=self._batch_progress_take_completed,
                take_total=self._batch_progress_take_total,
                caption_number=self._batch_progress_caption_number,
                caption_total=self._batch_progress_caption_total,
            )

        take_total = self.operation_total if self.operation_total > 0 else None
        if operation == "regenerate_one":
            take_number = self.worker_target
        elif take_total is not None:
            take_number = min(self.operation_completed + 1, take_total)
        else:
            take_number = None
        return BackgroundOperationProgress(
            operation_id=operation_id,
            operation=operation,
            item_id=self._worker_item_id,
            completed=self.operation_completed,
            total=self.operation_total,
            take_number=take_number,
            take_completed=self.operation_completed,
            take_total=take_total,
        )

    @property
    def active_item_generation_progress(self) -> tuple[str, int, int] | None:
        """Return item-local progress for the Caption currently being synthesized."""

        progress = self.background_operation_progress
        if (
            progress is None
            or progress.item_id is None
            or progress.take_total is None
            or progress.take_total <= 0
        ):
            return None
        return (
            progress.item_id,
            progress.take_completed,
            progress.take_total,
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

    @property
    def operation_resource_busy(self) -> bool:
        """Whether the shared single-worker operation resource is occupied."""

        return self.busy

    @property
    def owned_item_ids(self) -> frozenset[str]:
        """Stable Caption item IDs owned by the active operation plan."""

        if not self.busy:
            return frozenset()
        return self._owned_item_ids

    def owns_item(self, item_id: str | None) -> bool:
        """Whether the active operation owns one stable Caption item."""

        return item_id is not None and item_id in self.owned_item_ids

    def resource_conflict_status(self, action: str) -> Status | None:
        """Explain why an action needing the shared worker cannot start."""

        return self._conflict_policy.resource_conflict_status(
            action,
            busy=self.busy,
            operation=self.worker_operation,
        )

    def item_mutation_conflict_status(
        self,
        batch: CaptionBatch,
        item_id: str | None,
        *,
        action: str,
    ) -> Status | None:
        """Explain a mutation conflict for one operation-owned Caption item."""

        return self._conflict_policy.item_mutation_conflict_status(
            batch,
            item_id,
            action=action,
            owned_item_ids=self.owned_item_ids,
            operation=self.worker_operation,
        )

    def settings_change_conflict_status(
        self,
        changed_names: Iterable[str],
    ) -> Status | None:
        """Block only settings mutations that conflict with the active operation."""

        return self._conflict_policy.settings_change_conflict_status(
            changed_names,
            busy=self.busy,
            operation=self.worker_operation,
        )

    def generation_conflict_status(
        self,
        batch: CaptionBatch,
        *,
        requested_item_id: str | None = None,
        requested_batch: bool = False,
    ) -> Status | None:
        """Explain why a new generation request cannot start right now."""

        return self._conflict_policy.generation_conflict_status(
            batch,
            busy=self.busy,
            operation=self.worker_operation,
            active_item_id=self._worker_item_id,
            requested_item_id=requested_item_id,
            requested_batch=requested_batch,
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
        batch: CaptionBatch | None = None,
    ) -> tuple[OperationEffect, ...]:
        effects: list[OperationEffect] = []

        def caption_label(item_id: str | None) -> str | None:
            if batch is None or item_id is None:
                return None
            try:
                item = batch.get_item(item_id)
            except KeyError:
                return None
            return f"Caption {batch.items.index(item) + 1}"

        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return tuple(effects)

            if self._consume_preview_event(event, effects):
                continue
            if self._consume_completion_event(event, effects):
                continue
            if self._consume_batch_generation_event(
                event,
                effects,
                caption_label=caption_label,
            ):
                continue
            self._consume_generation_event(
                event,
                effects,
                navigation_revision=navigation_revision,
                pronunciation_index=pronunciation_index,
                exit_requested=exit_requested,
                caption_label=caption_label,
            )

    def _consume_preview_event(
        self,
        event: Any,
        effects: list[OperationEffect],
    ) -> bool:
        if isinstance(event, PreviewReadyEvent):
            self.operation_completed = 1
            effects.append(PlayPreviewEffect(event.audio, event.sampling_rate))
            return True
        if isinstance(event, PreviewFailedEvent):
            self.worker_error = event.error
            effects.append(
                UpdateStatusEffect(error_status(f"Preview failed: {event.error}"))
            )
            return True
        return False

    def _finish_deferred_operation(self, error: BaseException | None) -> None:
        self.busy = False
        self.operation_completed = 1
        self.operation_total = 1
        self.worker_error = error
        self.worker_operation = None
        self.worker_target = None
        self._owned_item_ids = frozenset()
        self._cancellation_event = None
        self.cancellation_requested = False

    def _consume_completion_event(
        self,
        event: Any,
        effects: list[OperationEffect],
    ) -> bool:
        if isinstance(event, SessionPreparationCompletedEvent):
            self._finish_deferred_operation(event.error)
            effects.append(
                SessionPreparationCompletedEffect(
                    session=event.session,
                    rebuild=event.rebuild,
                    error=event.error,
                )
            )
            return True
        if isinstance(event, DictionaryOperationCompletedEvent):
            self._finish_deferred_operation(event.error)
            effects.append(
                DictionaryOperationCompletedEffect(
                    request=event.request,
                    value=event.value,
                    error=event.error,
                )
            )
            return True
        if isinstance(event, TakeAcceptanceCompletedEvent):
            self._finish_deferred_operation(event.error)
            if event.error is None:
                self.current_take = None
            effects.extend(self._acceptance.completion_effects(event))
            return True
        return False

    def _consume_batch_generation_event(
        self,
        event: Any,
        effects: list[OperationEffect],
        *,
        caption_label: Callable[[str | None], str | None],
    ) -> bool:
        if isinstance(event, BatchGenerationProgressEvent):
            self.operation_completed = event.overall_completed
            self._batch_progress_item_id = event.item_id
            self._batch_progress_caption_number = event.caption_number
            self._batch_progress_caption_total = event.caption_total
            self._batch_progress_take_number = event.take_number
            self._batch_progress_take_completed = max(0, event.take_number - 1)
            self._batch_progress_take_total = event.take_total
            effects.append(
                UpdateStatusEffect(
                    f"Caption {event.caption_number}/{event.caption_total} · "
                    f"Take {event.take_number}/{event.take_total} · "
                    f"Overall {event.overall_completed}/{event.overall_total}",
                    channel="background",
                )
            )
            return True
        if isinstance(event, BatchCandidateReadyEvent):
            self.operation_completed = event.overall_completed
            self._batch_progress_item_id = event.item_id
            self._batch_progress_caption_number = event.caption_number
            self._batch_progress_caption_total = event.caption_total
            self._batch_progress_take_number = event.take_number
            self._batch_progress_take_completed = event.take_number
            self._batch_progress_take_total = event.take_total
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
            if event.take_number == event.take_total:
                effects.append(
                    GenerationOutcomeEffect(event.item_id, "completed")
                )
            return True
        if isinstance(event, BatchGenerationCancelledEvent):
            effects.append(
                GenerationOutcomeEffect(event.item_id, "cancelled")
            )
            return True
        if isinstance(event, BatchGenerationFailedEvent):
            self.worker_error = event.error
            self._batch_progress_item_id = event.item_id
            self._batch_progress_caption_number = event.caption_number
            self._batch_progress_caption_total = event.caption_total
            self._batch_progress_take_number = event.take_number
            self._batch_progress_take_completed = max(0, event.take_number - 1)
            self._batch_progress_take_total = event.take_total
            owner = caption_label(event.item_id)
            location = (
                owner
                if owner is not None
                else f"Caption {event.caption_number}/{event.caption_total}"
            )
            effects.append(
                UpdateStatusEffect(
                    error_status(
                        "Batch generation failed at "
                        f"{location}, Take {event.take_number}/{event.take_total}: "
                        f"{event.error}"
                    )
                )
            )
            effects.append(
                GenerationOutcomeEffect(event.item_id, "failed")
            )
            return True
        return False

    def _consume_generation_event(
        self,
        event: Any,
        effects: list[OperationEffect],
        *,
        navigation_revision: int,
        pronunciation_index: int,
        exit_requested: bool,
        caption_label: Callable[[str | None], str | None],
    ) -> None:
        # Accept legacy tuple events from direct callers while worker builders
        # use explicit event contracts for the single authoritative queue.
        if isinstance(event, GenerationCandidateEvent):
            kind, value = "candidate", event.candidate
        elif isinstance(event, GenerationFailedEvent):
            kind, value = "error", event.error
        elif isinstance(event, OperationDoneEvent):
            kind, value = "done", None
        else:
            kind, value = event

        if kind == "candidate":
            operation = self.worker_operation
            self.operation_completed += 1
            status = generation_candidate_status(
                operation, self.operation_completed, self.operation_total, value.number
            )
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
            return

        if kind == "error":
            self.worker_error = value
            effects.append(
                UpdateStatusEffect(
                    generation_error_status(
                        self.worker_operation, caption_label(self._worker_item_id), value
                    )
                )
            )
            if (
                self.worker_operation == "initial"
                and not self.cancellation_requested
            ):
                effects.append(StopPlaybackEffect())
                effects.append(DiscardInitialBatchEffect(self._worker_item_id))
                self.current_take = None
                effects.append(FocusEffect(("pronunciation", pronunciation_index)))
            if (
                self.worker_operation in {"initial", "regenerate_all"}
                and self._worker_item_id is not None
            ):
                effects.append(
                    GenerationOutcomeEffect(self._worker_item_id, "failed")
                )
            return

        if kind != "done":
            return

        operation = self.worker_operation
        owner = caption_label(self._worker_item_id)
        batch_owner = caption_label(self._batch_progress_item_id)
        finished_full_count = (
            operation in {"initial", "regenerate_all"}
            and self.operation_total > 0
            and self.operation_completed >= self.operation_total
            and self.worker_error is None
        )
        cancelled = self.cancellation_requested and not finished_full_count
        self.busy = False
        status = generation_done_status(
            operation=operation,
            owner=owner,
            batch_owner=batch_owner,
            completed=self.operation_completed,
            total=self.operation_total,
            worker_error=self.worker_error,
            cancelled=cancelled,
            exit_requested=exit_requested,
        )
        if cancelled and operation == "initial" and self.operation_completed == 0:
            effects.append(StopPlaybackEffect())
            effects.append(DiscardInitialBatchEffect(self._worker_item_id))
            self.current_take = None
            effects.append(FocusEffect(("pronunciation", pronunciation_index)))
        if status is not None:
            effects.append(UpdateStatusEffect(status))
        if (
            operation in {"initial", "regenerate_all"}
            and self._worker_item_id is not None
            and self.worker_error is None
        ):
            if cancelled:
                effects.append(
                    GenerationOutcomeEffect(
                        self._worker_item_id,
                        "cancelled",
                    )
                )
            elif finished_full_count:
                effects.append(
                    GenerationOutcomeEffect(
                        self._worker_item_id,
                        "completed",
                    )
                )
            elif self.operation_total > 0:
                effects.append(
                    GenerationOutcomeEffect(
                        self._worker_item_id,
                        "failed",
                    )
                )
        self.worker_operation = None
        self.worker_target = None
        self._worker_item_id = None
        self._owned_item_ids = frozenset()
        self._active_operation_id = None
        self._batch_progress_item_id = None
        self._batch_progress_caption_number = None
        self._batch_progress_caption_total = None
        self._batch_progress_take_number = None
        self._batch_progress_take_completed = 0
        self._batch_progress_take_total = None
        self._cancellation_event = None
        self.cancellation_requested = False

    @property
    def _platform(self) -> Callable[[], str]:
        return self._playback._platform

    @_platform.setter
    def _platform(self, value: Callable[[], str]) -> None:
        self._playback._platform = value

    @property
    def _which(self) -> Callable[[str], str | None]:
        return self._playback._which

    @_which.setter
    def _which(self, value: Callable[[str], str | None]) -> None:
        self._playback._which = value

    @property
    def _popen(self) -> Callable[..., subprocess.Popen[Any]]:
        return self._playback._popen

    @_popen.setter
    def _popen(self, value: Callable[..., subprocess.Popen[Any]]) -> None:
        self._playback._popen = value

    @property
    def current_take(self) -> int | None:
        return self._playback.current_take

    @current_take.setter
    def current_take(self, value: int | None) -> None:
        self._playback.current_take = value

    @property
    def playback_process(self) -> subprocess.Popen[Any] | None:
        return self._playback.playback_process

    @playback_process.setter
    def playback_process(self, value: subprocess.Popen[Any] | None) -> None:
        self._playback.playback_process = value

    def play_take(
        self,
        session: UtteranceSession | None,
        number: int,
    ) -> tuple[OperationEffect, ...]:
        return self._playback.play_take(session, number)

    def play_preview(
        self,
        audio: Any,
        sampling_rate: int,
    ) -> tuple[OperationEffect, ...]:
        return self._playback.play_preview(audio, sampling_rate)

    def stop_playback(self) -> None:
        self._playback.stop_playback()

    def clear_current_take(self) -> None:
        self._playback.clear_current_take()

    @staticmethod
    def _saved_output_status(saved: Any) -> Status:
        return TuiTakeAcceptanceOwner.saved_output_status(saved)

    def accept_take(
        self,
        session: UtteranceSession | None,
        number: int,
        *,
        item_id: str,
        pronunciation_index: int,
    ) -> tuple[OperationEffect, ...]:
        if session is None:
            return ()
        conflict = self.resource_conflict_status(f"Save Take {number}")
        if conflict is not None:
            return (UpdateStatusEffect(conflict),)

        self.stop_playback()
        self.busy = True
        self.worker_operation = "accept"
        self.worker_target = number
        self._owned_item_ids = frozenset({item_id})
        self.worker_error = None
        self.operation_completed = 0
        self.operation_total = 1
        self._cancellation_event = None
        self.cancellation_requested = False

        work = self._acceptance.make_work(
            session,
            number,
            item_id=item_id,
            emit_event=self.events.put,
            event_factory=TakeAcceptanceCompletedEvent,
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
