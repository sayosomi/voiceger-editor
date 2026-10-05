"""Pure stepping helpers for shared TUI Left / Right adjustment semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Sequence, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class StepResult(Generic[T]):
    """One pure adjustment result plus whether the visible value changed."""

    value: T
    changed: bool


def step_bounded(
    current: T,
    *,
    direction: int,
    step: T,
    minimum: T | None = None,
    maximum: T | None = None,
) -> StepResult[T]:
    """Move one step toward a bound, stopping at the configured endpoint."""

    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("minimum must not exceed maximum")
    if direction == 0:
        return StepResult(current, False)

    signed_direction = -1 if direction < 0 else 1
    updated = current + step * signed_direction

    if minimum is not None and updated < minimum:
        updated = minimum
    if maximum is not None and updated > maximum:
        updated = maximum

    return StepResult(updated, updated != current)


def step_cyclic(
    current: T,
    choices: Sequence[T],
    *,
    direction: int,
) -> StepResult[T]:
    """Move through categorical choices and intentionally wrap at either end."""

    if not choices:
        raise ValueError("cyclic stepping requires at least one choice")
    if direction == 0:
        return StepResult(current, False)

    index = choices.index(current)
    signed_direction = -1 if direction < 0 else 1
    updated = choices[(index + signed_direction) % len(choices)]
    return StepResult(updated, updated != current)
