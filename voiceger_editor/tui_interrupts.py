"""Global Ctrl+C routing for the keyboard-first TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .tui_operations import OperationEffect, TuiOperations, UpdateStatusEffect


_CTRL_C = "\x03"


@dataclass(frozen=True)
class InterruptResult:
    """Top-level routing result for one possible interrupt key."""

    handled: bool
    effects: tuple[OperationEffect, ...] = ()


class TuiInterruptController:
    """Coordinate Ctrl+C with cancellable generation lifecycle state."""

    def handle_key(
        self,
        key: Any,
        operations: TuiOperations,
    ) -> InterruptResult:
        if key == _CTRL_C:
            if operations.can_cancel_batch:
                return InterruptResult(
                    handled=True,
                    effects=operations.request_batch_cancellation(),
                )
            if operations.cancellation_guard_armed:
                return InterruptResult(
                    handled=True,
                    effects=(
                        UpdateStatusEffect(
                            "Generation already finished; nothing to cancel."
                        ),
                    ),
                )
            return InterruptResult(handled=False)

        operations.clear_completed_cancellation_guard()
        return InterruptResult(handled=False)
