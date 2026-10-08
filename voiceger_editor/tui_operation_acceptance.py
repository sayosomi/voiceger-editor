"""Focused deferred Take-acceptance work and output-completion policy."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import os
from typing import Any, Callable

from .session import UtteranceSession
from .tui_status import Status, error_status, info_status, warning_status


class TuiTakeAcceptanceOwner:
    """Own Take save execution and completion effects, not shared worker state."""

    def __init__(
        self,
        *,
        update_status: Callable[[Status | str], Any],
        accepted_effect: Callable[[str, int], Any],
    ) -> None:
        self._update_status = update_status
        self._accepted_effect = accepted_effect

    def make_work(
        self,
        session: UtteranceSession,
        number: int,
        *,
        item_id: str,
        emit_event: Callable[[Any], None],
        event_factory: Callable[..., Any],
    ) -> Callable[[], None]:
        def work() -> None:
            try:
                with open(os.devnull, "w", encoding="utf-8") as sink:
                    with redirect_stdout(sink), redirect_stderr(sink):
                        saved = session.accept_take(number)
            except BaseException as exc:
                emit_event(
                    event_factory(
                        item_id=item_id,
                        number=number,
                        error=exc,
                    )
                )
            else:
                emit_event(
                    event_factory(
                        item_id=item_id,
                        number=number,
                        saved=saved,
                    )
                )

        return work

    def completion_effects(self, event: Any) -> tuple[Any, ...]:
        if event.error is not None:
            return (
                self._update_status(
                    error_status(
                        f"Take {event.number} was not saved: {event.error}"
                    )
                ),
            )
        return (
            self._accepted_effect(event.item_id, event.number),
            self._update_status(self.saved_output_status(event.saved)),
        )

    @staticmethod
    def saved_output_status(saved: Any) -> Status:
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
