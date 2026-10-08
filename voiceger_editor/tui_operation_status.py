"""Pure generation Status decisions from immutable lifecycle snapshots."""

from __future__ import annotations

from .tui_status import Status, error_status


def generation_candidate_status(
    operation: str | None,
    completed: int,
    total: int,
    take_number: int,
) -> str:
    if operation == "initial":
        return (
            f"Generating {min(completed + 1, total)}"
            f"/{total} · {completed} ready"
        )
    if operation == "regenerate_all":
        return (
            f"Regenerating {min(completed + 1, total)}"
            f"/{total} · {completed} ready"
        )
    return f"Take {take_number} replacement ready."


def generation_error_status(
    operation: str | None,
    owner: str | None,
    error: BaseException,
) -> Status:
    if operation == "preview":
        return error_status(f"Preview failed: {error}")
    return error_status(
        f"{owner} generation failed: {error}"
        if owner is not None
        else f"Generation failed: {error}"
    )


def generation_done_status(
    *,
    operation: str | None,
    owner: str | None,
    batch_owner: str | None,
    completed: int,
    total: int,
    worker_error: BaseException | None,
    cancelled: bool,
    exit_requested: bool,
) -> Status | str | None:
    """Return final Status without performing state transitions or effects."""

    if operation == "preview":
        return None
    if operation == "batch_generate":
        if cancelled:
            owner_suffix = f" at {batch_owner}" if batch_owner is not None else ""
            return (
                f"Batch generation cancelled{owner_suffix}. "
                f"{completed}/{total} take(s) ready."
            )
        if worker_error is not None:
            return None
        return f"Batch generation finished. {completed}/{total} take(s) ready."
    if cancelled and operation == "initial":
        return (
            f"{owner} generation cancelled. {completed} take(s) ready."
            if owner is not None
            else f"Generation cancelled. {completed} take(s) ready."
        )
    if cancelled and operation == "regenerate_all":
        return (
            f"{owner} regeneration cancelled after {completed} replacement(s)."
            if owner is not None
            else f"Regeneration cancelled after {completed} replacement(s)."
        )
    if worker_error is not None:
        return error_status(
            f"{owner} generation failed: {worker_error}"
            if owner is not None
            else f"Generation failed: {worker_error}"
        )
    if operation == "initial" and completed:
        return (
            f"{owner} generation finished. {completed} take(s) ready."
            if owner is not None
            else f"{completed} take(s) ready."
        )
    if operation in {"regenerate_one", "regenerate_all"}:
        return (
            f"{owner} Take regeneration finished."
            if owner is not None
            else "Take regeneration finished."
        )
    if not exit_requested:
        return "No takes were generated. Select Generate to try again."
    return None
