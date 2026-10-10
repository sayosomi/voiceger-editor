"""Typed request boundary for Dictionary background operations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Literal

from .tui_editors import EditorState
from .tui_status import Status


DictionaryOperationIdentity = Literal[
    "generate_japanese_pronunciation",
    "generate_english_pronunciation",
    "save_japanese",
    "save_japanese_list_accents",
    "save_english",
    "delete_japanese",
    "delete_english",
    "load_dictionary_import",
    "commit_dictionary_import",
    "export_voiceger_editor",
    "export_voicevox",
]
DictionaryLanguage = Literal["ja", "en"]


@dataclass(frozen=True)
class DictionaryOperationRequest:
    """Snapshot requested work and retain the originating editor identity."""

    operation: DictionaryOperationIdentity
    language: DictionaryLanguage | None
    editor_snapshot: EditorState
    originating_editor: EditorState


@dataclass(frozen=True)
class DictionaryOperationIntent:
    request: DictionaryOperationRequest
    status: Status
    work: Callable[[], Any]


def dictionary_operation_request(
    editor: EditorState,
    *,
    operation: DictionaryOperationIdentity,
    language: DictionaryLanguage | None,
) -> DictionaryOperationRequest:
    """Create an immutable work snapshot tied to the current editor instance."""

    return DictionaryOperationRequest(
        operation=operation,
        language=language,
        editor_snapshot=deepcopy(editor),
        originating_editor=editor,
    )
