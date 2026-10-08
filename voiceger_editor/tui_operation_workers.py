"""Background operation work builders; no shared lifecycle state is owned here."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import os
from threading import Event
from typing import Any, Callable, Iterable

from .caption_batch import CaptionBatchItem
from .session import UtteranceSession
from .tui_dictionary_operations import DictionaryOperationIntent
from .tui_operation_contracts import (
    BatchCandidateReadyEvent,
    BatchGenerationCancelledEvent,
    BatchGenerationFailedEvent,
    BatchGenerationProgressEvent,
    DictionaryOperationCompletedEvent,
    PreviewFailedEvent,
    PreviewReadyEvent,
    SessionPreparationCompletedEvent,
)
from .voicevox_api_models import AudioQuery


def make_batch_generation_work(
    plan: tuple[tuple[CaptionBatchItem, int], ...],
        *,
        overall_total: int,
        cancellation_event: Event,
        emit_event: Callable[[Any], None],
) -> Callable[[], None]:
    """Build background work from call-time inputs; emit events without owning lifecycle state."""

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
                                emit_event(
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
                                    emit_event(
                                        BatchGenerationCancelledEvent(
                                            item_id=item.item_id
                                        )
                                    )
                                    return
                                emit_event(
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
                                    emit_event(
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
                                    emit_event(
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
                                emit_event(
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
            emit_event(("done", None))

    return work


def make_preview_work(
    session: UtteranceSession,
        query_snapshot: AudioQuery,
        *,
        emit_event: Callable[[Any], None],
) -> Callable[[], None]:
    """Build background work from call-time inputs; emit events without owning lifecycle state."""

    def work() -> None:
        try:
            with open(os.devnull, "w", encoding="utf-8") as sink:
                with redirect_stdout(sink), redirect_stderr(sink):
                    result = session.preview_synthesis(query_snapshot)
            emit_event(
                PreviewReadyEvent(
                    audio=result["audio"],
                    sampling_rate=int(result["sampling_rate"]),
                )
            )
        except BaseException as exc:
            emit_event(PreviewFailedEvent(exc))
        finally:
            emit_event(("done", None))

    return work


def make_preparation_work(
    session: UtteranceSession,
        *,
        rebuild: bool,
        emit_event: Callable[[Any], None],
) -> Callable[[], None]:
    """Build background work from call-time inputs; emit events without owning lifecycle state."""

    def work() -> None:
        try:
            with open(os.devnull, "w", encoding="utf-8") as sink:
                with redirect_stdout(sink), redirect_stderr(sink):
                    session.prepare_from_caption()
        except BaseException as exc:
            emit_event(
                SessionPreparationCompletedEvent(
                    session=session,
                    rebuild=rebuild,
                    error=exc,
                )
            )
        else:
            emit_event(
                SessionPreparationCompletedEvent(
                    session=session,
                    rebuild=rebuild,
                )
            )

    return work


def make_dictionary_work(
    intent: DictionaryOperationIntent,
        *,
        emit_event: Callable[[Any], None],
) -> Callable[[], None]:
    """Build background work from call-time inputs; emit events without owning lifecycle state."""

    def work() -> None:
        try:
            with open(os.devnull, "w", encoding="utf-8") as sink:
                with redirect_stdout(sink), redirect_stderr(sink):
                    value = intent.work()
        except BaseException as exc:
            emit_event(
                DictionaryOperationCompletedEvent(
                    request=intent.request,
                    error=exc,
                )
            )
        else:
            emit_event(
                DictionaryOperationCompletedEvent(
                    request=intent.request,
                    value=value,
                )
            )

    return work


def make_generation_work(
    make_values: Callable[[], Iterable[Any]],
        *,
        cancellation_event: Event,
        emit_event: Callable[[Any], None],
) -> Callable[[], None]:
    """Build background work from call-time inputs; emit events without owning lifecycle state."""

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
                        emit_event(("candidate", candidate))
        except BaseException as exc:
            emit_event(("error", exc))
        finally:
            emit_event(("done", None))

    return work

