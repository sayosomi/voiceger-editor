"""Selected Web Batch generation on the Mac's existing single audio worker.

The browser supplies no synthesis policy. Planning follows the frontend-neutral
CaptionBatch and UtteranceSession owners, with TUI equivalence as a test oracle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .caption_batch import CaptionBatchItem


@dataclass(frozen=True)
class _Row:
    item: CaptionBatchItem
    take_count: int
    numbers: tuple[int, ...]
    accepted: frozenset[int]
    shrink: bool


def _plan(batch: Any) -> tuple[tuple[_Row, ...], int]:
    from .web_sessions import WebSessionConflict

    rows: list[_Row] = []
    for item in batch.included_items:
        count = batch.effective_take_count(item)
        accepted = item.accepted_take_numbers
        if item.session.has_active_batch and any(n > count for n in accepted):
            raise WebSessionConflict(
                "Accepted Take would be removed by the selected count",
                code="accepted_take_protected",
            )
        numbers = tuple(
            number for number in range(1, count + 1)
            if not item.session.has_active_batch or number not in accepted
        )
        shrink = bool(
            item.session.has_active_batch
            and any(candidate.number > count for candidate in item.session.candidates)
        )
        if numbers or shrink:
            rows.append(_Row(item, count, numbers, accepted, shrink))
    return tuple(rows), sum(len(row.numbers) for row in rows)


class WebBatchGenerationMixin:
    """Submit one ordered selected Batch job and publish progress snapshots."""

    def start_batch_generation(self, session_id: str, revision: int) -> dict[str, Any]:
        from .web_sessions import WebSessionConflict

        with self._lock:
            session = self._session(session_id)
            if revision != session.revision:
                raise WebSessionConflict(
                    "Batch was changed in another tab; reload it",
                    code="revision_conflict",
                )
            if self._active is not None:
                raise WebSessionConflict(
                    "One Web operation is already running", code="worker_busy",
                )
            selected = session.batch.included_items
            if not selected:
                return {"kind": "batch-generate", "status": "no-op",
                        "reason": "empty_selection", "total": 0, "completed": 0}
            rows, total = _plan(session.batch)
            if not rows:
                return {"kind": "batch-generate", "status": "no-op",
                        "reason": "all_accepted", "total": 0, "completed": 0}
            self._require_terms()
            first = rows[0]
            detail = {
                "item_id": first.item.item_id, "caption_number": 1,
                "caption_total": len(rows),
                "take_number": first.numbers[0] if first.numbers else 0,
                "take_total": first.take_count,
            }

            def work(op: Any) -> dict[str, Any]:
                for index, row in enumerate(rows, start=1):
                    if op.cancellation.is_set():
                        break
                    item = row.item
                    with self._lock:
                        op.detail = {
                            "item_id": item.item_id, "caption_number": index,
                            "caption_total": len(rows),
                            "take_number": row.numbers[0] if row.numbers else 0,
                            "take_total": row.take_count,
                        }
                    iterator = None
                    finished = False
                    try:
                        if not item.session.is_prepared:
                            item.session.prepare_from_caption()
                            with self._lock:
                                session.revision += 1
                        if op.cancellation.is_set():
                            with self._lock:
                                item.set_generation_outcome("cancelled")
                                session.revision += 1
                            break
                        if item.session.has_active_batch:
                            iterator = iter(item.session.regenerate_all_takes(
                                take_count=row.take_count,
                                protected_numbers=row.accepted,
                            ))
                        else:
                            iterator = iter(item.session.generate_takes(
                                take_count=row.take_count,
                            ))
                        for number in row.numbers:
                            if op.cancellation.is_set():
                                break
                            with self._lock:
                                op.detail["take_number"] = number
                            try:
                                next(iterator)
                            except StopIteration as exc:
                                raise RuntimeError("Generation stopped before all Takes") from exc
                            # A generated Take is retained even if cancellation arrived
                            # while the model was synthesizing it.
                            with self._lock:
                                op.completed += 1
                                session.revision += 1
                        else:
                            # Explicitly exhaust an all-accepted shrink-only iterator.
                            if not row.numbers:
                                try:
                                    next(iterator)
                                except StopIteration:
                                    pass
                                else:
                                    raise RuntimeError("Shrink-only step generated a Take")
                            finished = True
                    except BaseException:
                        with self._lock:
                            item.set_generation_outcome("failed")
                            session.revision += 1
                        raise
                    finally:
                        if iterator is not None:
                            close = getattr(iterator, "close", None)
                            if callable(close):
                                close()
                        with self._lock:
                            # Failed/cancelled initial generation must not leave a
                            # spurious active empty Take batch.
                            if item.session.has_active_batch and not item.session.candidates:
                                item.session.discard_takes()
                    with self._lock:
                        item.set_generation_outcome(
                            "completed" if finished else "cancelled"
                        )
                        session.revision += 1
                    if not finished:
                        break
                return {"generated": op.completed}

            return self._start_take_work(
                session_id, session, kind="batch-generate",
                total=total, run=work, detail=detail,
            )
