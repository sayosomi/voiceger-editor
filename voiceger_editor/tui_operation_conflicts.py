"""Explicit conflict policy for the shared TUI background-operation resource."""

from __future__ import annotations

from typing import Iterable

from .caption_batch import CaptionBatch
from .tui_status import Status, warning_status


class TuiOperationConflictPolicy:
    """Own conflict/status policy without owning or copying lifecycle state."""

    @staticmethod
    def resource_conflict_status(
        action: str,
        *,
        busy: bool,
        operation: str | None,
    ) -> Status | None:
        if not busy:
            return None
        if operation in {"initial", "regenerate_one", "regenerate_all", "batch_generate"}:
            detail = "Take generation is active"
        elif operation == "preview":
            detail = "pronunciation Preview synthesis is active"
        elif operation == "prepare":
            detail = "pronunciation preparation is active"
        elif operation == "accept":
            detail = "a Take is being saved"
        elif operation == "dictionary":
            detail = "a Dictionary operation is active"
        else:
            detail = "another background operation is active"
        return warning_status(f"{action} is unavailable while {detail}.")

    @staticmethod
    def item_mutation_conflict_status(
        batch: CaptionBatch,
        item_id: str | None,
        *,
        action: str,
        owned_item_ids: frozenset[str],
        operation: str | None,
    ) -> Status | None:
        if item_id is None or item_id not in owned_item_ids:
            return None

        number: int | None = None
        try:
            item = batch.get_item(item_id)
        except KeyError:
            pass
        else:
            number = batch.items.index(item) + 1
        owner = f"Caption {number}" if number is not None else "This Caption"
        if operation in {"initial", "regenerate_one", "regenerate_all", "batch_generate"}:
            return warning_status(
                f"{owner} is currently generating; {action} is unavailable "
                "until generation finishes."
            )
        if operation == "prepare":
            return warning_status(
                f"{owner} pronunciation is being prepared; {action} is unavailable "
                "until preparation finishes."
            )
        if operation == "accept":
            return warning_status(
                f"{owner} is saving a Take; {action} is unavailable until the save finishes."
            )
        return warning_status(
            f"{owner} is owned by the active operation; {action} is unavailable "
            "until it finishes."
        )

    @staticmethod
    def settings_change_conflict_status(
        changed_names: Iterable[str],
        *,
        busy: bool,
        operation: str | None,
    ) -> Status | None:
        if not busy:
            return None
        changed = set(changed_names)
        synthesis_names = {"style_id", "speed", "top_k", "top_p", "temperature"}
        if changed & synthesis_names:
            return warning_status(
                "Synthesis settings cannot change while the current operation is active."
            )
        output_names = {
            "output_dir",
            "filename_template",
            "output_format",
            "wav_encoding",
            "flac_encoding",
            "mp3_bitrate",
            "save_text",
            "save_lab",
        }
        if operation == "accept" and changed & output_names:
            return warning_status(
                "Output settings cannot change while a Take is being saved."
            )
        return None

    @staticmethod
    def generation_conflict_status(
        batch: CaptionBatch,
        *,
        busy: bool,
        operation: str | None,
        active_item_id: str | None,
        requested_item_id: str | None = None,
        requested_batch: bool = False,
    ) -> Status | None:
        if not busy:
            return None

        def caption_number(item_id: str | None) -> int | None:
            if item_id is None:
                return None
            try:
                item = batch.get_item(item_id)
            except KeyError:
                return None
            return batch.items.index(item) + 1

        active_number = caption_number(active_item_id)
        requested_number = caption_number(requested_item_id)
        individual_generation = operation in {
            "initial",
            "regenerate_one",
            "regenerate_all",
        }
        batch_generation = operation == "batch_generate"

        if requested_batch:
            if batch_generation:
                return warning_status("Generate selected is already running.")
            if individual_generation:
                return warning_status(
                    "Generate selected is unavailable while generation is active."
                )
            return warning_status(
                "Generate selected is unavailable while another operation is active."
            )

        if requested_number is not None:
            if individual_generation and active_number == requested_number:
                return warning_status(
                    f"Caption {requested_number} is already generating."
                )
            if batch_generation:
                return warning_status(
                    f"Generate Caption {requested_number} is unavailable "
                    "while batch generation is active."
                )
            if individual_generation:
                return warning_status(
                    f"Generate Caption {requested_number} is unavailable "
                    "while generation is active."
                )
            return warning_status(
                f"Generate Caption {requested_number} is unavailable "
                "while another operation is active."
            )

        if batch_generation:
            return warning_status(
                "Generate is unavailable while batch generation is active."
            )
        if individual_generation:
            return warning_status(
                "Generate is unavailable while generation is active."
            )
        return warning_status(
            "Generate is unavailable while another operation is active."
        )
