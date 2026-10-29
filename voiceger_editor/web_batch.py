"""Batch List actions using the existing frontend-neutral CaptionBatch owner."""

from __future__ import annotations

from typing import Any

from .caption_batch import CaptionBatch, CaptionBatchItem


MAX_BATCH_ITEMS = 200
MAX_CAPTION_CHARACTERS = 2000
MAX_PASTE_CHARACTERS = 32000


class WebBatchValidation(ValueError):
    """Invalid client-supplied Batch value."""


def _valid_caption(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WebBatchValidation("Caption must not be empty")
    if len(value) > MAX_CAPTION_CHARACTERS or "\n" in value or "\r" in value:
        raise WebBatchValidation("Caption must be one line (up to 2000 characters)")
    return value


def _take_count(value: int | None, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise WebBatchValidation("Take count must be from 1 to 100")


def _row(batch: CaptionBatch, item: CaptionBatchItem) -> dict[str, Any]:
    return {
        "id": item.item_id,
        "caption": item.caption,
        "included": item.included_for_generation,
        "take_count_override": item.take_count_override,
        "effective_take_count": batch.effective_take_count(item),
        "is_prepared": item.session.is_prepared,
        "candidate_count": item.session.active_candidate_count,
        "accepted_take_numbers": sorted(item.accepted_take_numbers),
        "generation_outcome": item.generation_outcome,
        "spoken_text": (
            getattr(item.session, "synthesis_source_text", None)
            if item.session.is_prepared else None
        ),
        "takes": [
            {
                "number": candidate.number,
                "duration_seconds": round(
                    candidate.frame_count / candidate.sampling_rate, 2
                ) if candidate.sampling_rate else 0,
                "accepted": item.is_take_accepted(candidate.number),
                "style": candidate.style_name,
            }
            for candidate in getattr(item.session, "candidates", ())
        ],
    }


class WebBatchMixin:
    """Narrow Batch mutations under WebSessionOperations' authoritative lock."""

    def _caption_session(self, caption: str):
        if self._caption_factory is not None:
            return self._caption_factory(caption)
        if self._batch_adapter is None:
            from .voiceger_adapter import VoicegerAdapter
            from .settings import load_settings

            # Lazy adapter construction does not load the synthesis models.
            self._batch_adapter = VoicegerAdapter()
            self._batch_settings = load_settings()
        from .session import UtteranceSession

        return UtteranceSession.from_caption(
            adapter=self._batch_adapter,
            caption=caption,
            settings=self._batch_settings,
        )

    @staticmethod
    def _batch_snapshot(session) -> dict[str, Any]:
        batch = session.batch
        return {
            "revision": session.revision,
            "default_take_count": batch.default_take_count,
            "items": [_row(batch, item) for item in batch.items],
        }

    def get_batch(self, identifier: str) -> dict[str, Any]:
        with self._lock:
            session = self._session(identifier)
            return self._batch_snapshot(session)

    def _edit_batch(self, identifier: str, expected_revision: int, action):
        from .web_sessions import WebSessionConflict

        with self._lock:
            session = self._session(identifier)
            if expected_revision != session.revision:
                raise WebSessionConflict("Batch was changed in another tab; reload it")
            if self._active is not None:
                raise WebSessionConflict("Cannot edit Batch while an operation is active")
            try:
                action(session.batch)
            except KeyError:
                from .web_sessions import WebSessionNotFound

                raise WebSessionNotFound("Batch item not found") from None
            session.revision += 1
            return self._batch_snapshot(session)

    def add_captions(self, identifier: str, expected_revision: int, text: str):
        if not isinstance(text, str) or len(text) > MAX_PASTE_CHARACTERS:
            raise WebBatchValidation("Paste is too large")
        captions = [_valid_caption(line) for line in text.splitlines() if line.strip()]
        if not captions:
            raise WebBatchValidation("Enter at least one Caption")

        def action(batch):
            if len(batch) + len(captions) > MAX_BATCH_ITEMS:
                raise WebBatchValidation("Batch is full (200 Captions maximum)")
            # Atomic core operation: build all sessions before adding any items.
            batch.add_captions_from_text("\n".join(captions), session_factory=self._caption_session)

        return self._edit_batch(identifier, expected_revision, action)

    def edit_caption(self, identifier: str, expected_revision: int, item_id: str, caption: str):
        _valid_caption(caption)
        return self._edit_batch(
            identifier,
            expected_revision,
            lambda batch: batch.get_item(item_id).session.replace_caption(caption),
        )

    def remove_caption(self, identifier: str, expected_revision: int, item_id: str):
        def action(batch):
            item = batch.get_item(item_id)
            item.session.discard_takes()
            batch.remove_item(item_id)
        return self._edit_batch(identifier, expected_revision, action)

    def remove_captions(self, identifier: str, expected_revision: int, item_ids: list[str]):
        """Atomically validate a selection before removing any Batch items.

        Reuse the existing per-item Take disposal owner. The revision guard and
        single-worker exclusion are provided by _edit_batch.
        """
        if (not isinstance(item_ids, list) or not 1 <= len(item_ids) <= MAX_BATCH_ITEMS
                or any(not isinstance(item_id, str) or not item_id for item_id in item_ids)
                or len(set(item_ids)) != len(item_ids)):
            raise WebBatchValidation("Select unique Caption IDs to delete")

        def action(batch):
            # Resolve every ID before mutating the list or cleaning Takes.
            items = [batch.get_item(item_id) for item_id in item_ids]
            for item in items:
                item.session.discard_takes()
            for item in items:
                batch.remove_item(item.item_id)

        return self._edit_batch(identifier, expected_revision, action)

    def move_caption(self, identifier: str, expected_revision: int, item_id: str, new_index: int):
        def action(batch):
            if isinstance(new_index, bool) or not isinstance(new_index, int) or not 0 <= new_index < len(batch):
                raise WebBatchValidation("Position is outside Batch")
            batch.move_item(item_id, new_index)
        return self._edit_batch(identifier, expected_revision, action)

    def set_included(self, identifier: str, expected_revision: int, item_id: str, included: bool):
        if not isinstance(included, bool):
            raise WebBatchValidation("Included must be a boolean")
        return self._edit_batch(
            identifier,
            expected_revision,
            lambda batch: batch.set_included(item_id, included),
        )

    def set_default_take_count(self, identifier: str, expected_revision: int, take_count: int):
        _take_count(take_count)
        return self._edit_batch(
            identifier,
            expected_revision,
            lambda batch: setattr(batch, "default_take_count", take_count),
        )

    def set_item_take_count(
        self, identifier: str, expected_revision: int, item_id: str, take_count: int | None
    ):
        _take_count(take_count, nullable=True)
        return self._edit_batch(
            identifier,
            expected_revision,
            lambda batch: setattr(batch.get_item(item_id), "take_count_override", take_count),
        )
