"""Frontend-neutral state for a collection of editable Captions."""

from __future__ import annotations

from typing import Callable, Iterable, Iterator, TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from .session import UtteranceSession


SessionFactory = Callable[[str], "UtteranceSession"]


def _validate_take_count(value: int | None, *, name: str, nullable: bool) -> None:
    if value is None:
        if nullable:
            return
        raise TypeError(f"{name} must be an integer")
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not 1 <= value <= 100:
        raise ValueError(f"{name} must be from 1 through 100")


class CaptionBatchItem:
    """One stable Caption entry and its reusable single-utterance session."""

    def __init__(
        self,
        session: "UtteranceSession",
        *,
        item_id: str | None = None,
        included_for_generation: bool = True,
        take_count_override: int | None = None,
    ) -> None:
        resolved_item_id = str(uuid4()) if item_id is None else item_id
        if not isinstance(resolved_item_id, str):
            raise TypeError("item_id must be a string")
        if not resolved_item_id.strip():
            raise ValueError("item_id must not be empty")
        if not isinstance(included_for_generation, bool):
            raise TypeError("included_for_generation must be a boolean")
        _validate_take_count(
            take_count_override,
            name="take_count_override",
            nullable=True,
        )

        self._session = session
        self._item_id = resolved_item_id
        self._included_for_generation = included_for_generation
        self._take_count_override = take_count_override
        self._accepted_take_number: int | None = None

    @property
    def item_id(self) -> str:
        """Stable identity that does not depend on visible list position."""

        return self._item_id

    @property
    def session(self) -> "UtteranceSession":
        """Reuse the existing frontend-neutral single-utterance state."""

        return self._session

    @property
    def caption(self) -> str:
        """Return the Caption currently owned by the item's session."""

        return self._session.caption

    @property
    def included_for_generation(self) -> bool:
        return self._included_for_generation

    @included_for_generation.setter
    def included_for_generation(self, included: bool) -> None:
        if not isinstance(included, bool):
            raise TypeError("included_for_generation must be a boolean")
        self._included_for_generation = included

    @property
    def take_count_override(self) -> int | None:
        return self._take_count_override

    @take_count_override.setter
    def take_count_override(self, value: int | None) -> None:
        _validate_take_count(
            value,
            name="take_count_override",
            nullable=True,
        )
        self._take_count_override = value

    @property
    def accepted_take_number(self) -> int | None:
        return self._accepted_take_number

    @property
    def is_accepted(self) -> bool:
        return self._accepted_take_number is not None

    def mark_accepted(self, take_number: int) -> None:
        _validate_take_count(
            take_number,
            name="accepted_take_number",
            nullable=False,
        )
        self._accepted_take_number = take_number

    def clear_acceptance(self) -> None:
        self._accepted_take_number = None


class CaptionBatch:
    """Ordered, frontend-neutral collection of Caption batch items."""

    def __init__(
        self,
        *,
        default_take_count: int,
        items: Iterable[CaptionBatchItem] = (),
    ) -> None:
        _validate_take_count(
            default_take_count,
            name="default_take_count",
            nullable=False,
        )
        self._default_take_count = default_take_count
        self._items: list[CaptionBatchItem] = []
        for item in items:
            self.add_item(item)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[CaptionBatchItem]:
        return iter(self._items)

    @property
    def default_take_count(self) -> int:
        return self._default_take_count

    @default_take_count.setter
    def default_take_count(self, value: int) -> None:
        _validate_take_count(
            value,
            name="default_take_count",
            nullable=False,
        )
        self._default_take_count = value

    @property
    def items(self) -> tuple[CaptionBatchItem, ...]:
        """Return item order without exposing the mutable backing list."""

        return tuple(self._items)

    @property
    def included_items(self) -> tuple[CaptionBatchItem, ...]:
        return tuple(
            item for item in self._items if item.included_for_generation
        )

    @property
    def accepted_items(self) -> tuple[CaptionBatchItem, ...]:
        return tuple(item for item in self._items if item.is_accepted)

    def get_item(self, item_id: str) -> CaptionBatchItem:
        for item in self._items:
            if item.item_id == item_id:
                return item
        raise KeyError(item_id)

    def add_item(self, item: CaptionBatchItem) -> CaptionBatchItem:
        return self.insert_item(len(self._items), item)

    def insert_item(
        self,
        index: int,
        item: CaptionBatchItem,
    ) -> CaptionBatchItem:
        if not isinstance(item, CaptionBatchItem):
            raise TypeError("item must be a CaptionBatchItem")
        if any(existing.item_id == item.item_id for existing in self._items):
            raise ValueError(f"duplicate item_id {item.item_id!r}")
        self._items.insert(index, item)
        return item

    def add_caption(
        self,
        caption: str,
        *,
        session_factory: SessionFactory,
        item_id: str | None = None,
        included_for_generation: bool = True,
        take_count_override: int | None = None,
    ) -> CaptionBatchItem:
        """Create one item from Caption text without choosing a frontend."""

        if not isinstance(caption, str):
            raise TypeError("caption must be a string")
        if not caption.strip():
            raise ValueError("caption must not be empty")
        if "\n" in caption or "\r" in caption:
            raise ValueError("caption must contain exactly one line")

        item = CaptionBatchItem(
            session_factory(caption),
            item_id=item_id,
            included_for_generation=included_for_generation,
            take_count_override=take_count_override,
        )
        return self.add_item(item)

    def add_captions_from_text(
        self,
        text: str,
        *,
        session_factory: SessionFactory,
    ) -> tuple[CaptionBatchItem, ...]:
        """Create one included item for every non-empty pasted line.

        Session construction completes before the collection is mutated so a
        failing factory does not leave a partially added paste operation.
        """

        if not isinstance(text, str):
            raise TypeError("text must be a string")

        captions = [line for line in text.splitlines() if line.strip()]
        pending = [
            CaptionBatchItem(session_factory(caption))
            for caption in captions
        ]
        pending_ids = {item.item_id for item in pending}
        if len(pending_ids) != len(pending):
            raise ValueError("generated duplicate item_id")
        existing_ids = {item.item_id for item in self._items}
        duplicate_ids = pending_ids & existing_ids
        if duplicate_ids:
            duplicate = sorted(duplicate_ids)[0]
            raise ValueError(f"duplicate item_id {duplicate!r}")

        self._items.extend(pending)
        return tuple(pending)

    def move_item(self, item_id: str, new_index: int) -> CaptionBatchItem:
        """Move an item by stable identity while preserving that identity."""

        item = self.get_item(item_id)
        old_index = self._items.index(item)
        self._items.pop(old_index)
        self._items.insert(new_index, item)
        return item

    def remove_item(self, item_id: str) -> CaptionBatchItem:
        """Remove and return one item by stable identity."""

        item = self.get_item(item_id)
        self._items.remove(item)
        return item

    def set_included(self, item_id: str, included: bool) -> CaptionBatchItem:
        item = self.get_item(item_id)
        item.included_for_generation = included
        return item

    def toggle_included(self, item_id: str) -> CaptionBatchItem:
        item = self.get_item(item_id)
        item.included_for_generation = not item.included_for_generation
        return item

    def mark_accepted(self, item_id: str, take_number: int) -> CaptionBatchItem:
        item = self.get_item(item_id)
        item.mark_accepted(take_number)
        return item

    def clear_acceptance(self, item_id: str) -> CaptionBatchItem:
        item = self.get_item(item_id)
        item.clear_acceptance()
        return item

    def effective_take_count(self, item: CaptionBatchItem) -> int:
        """Resolve an item's override against the batch default."""

        owned = self.get_item(item.item_id)
        if owned is not item:
            raise ValueError("item does not belong to this batch")
        if item.take_count_override is not None:
            return item.take_count_override
        return self._default_take_count
