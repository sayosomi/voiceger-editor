"""Pure clamped selection movement for shared TUI Up / Down semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Sequence, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class SelectionMoveResult(Generic[T]):
    """Resolved selection movement plus whether the resolved index changed."""

    selection: T
    index: int
    changed: bool


def move_clamped_selection(
    current: T,
    items: Sequence[T],
    *,
    delta: int,
) -> SelectionMoveResult[T] | None:
    """Move within an owner-provided ordered sequence, stopping at its ends."""

    if not items:
        return None

    try:
        index = items.index(current)
    except ValueError:
        index = 0

    target = min(max(index + delta, 0), len(items) - 1)
    return SelectionMoveResult(
        selection=items[target],
        index=target,
        changed=target != index,
    )
