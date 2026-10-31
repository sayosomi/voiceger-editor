"""Output-only dictionary source validation and import review presentation."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import re
import stat
from tempfile import TemporaryDirectory

from .dictionary_backup import DictionaryBackupReview
from .dictionary_editing import japanese_word_notation
from .dictionary_import import DictionaryImportError, prepare_dictionary_import
from .user_dictionary import japanese_word_type

MAX_SOURCE_BYTES = 32 * 1024 * 1024


class WebDictionaryImportValidation(ValueError):
    CODES = frozenset({
        "invalid_import", "invalid_filename", "import_io", "review_expired",
        "source_changed", "confirmation_required",
    })

    def __init__(self, code: str):
        if code not in self.CODES:
            raise ValueError("Unknown dictionary import error")
        self.code = code
        super().__init__(code)


def allowed_filename(value: str) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= 200
            or value in {".", ".."} or value.startswith(".")
            or value != Path(value).name or "/" in value or "\\" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or not value.lower().endswith((".zip", ".json"))):
        raise WebDictionaryImportValidation("invalid_filename")
    # Native legacy pitch-sidecar pairs need special joint validation.
    # Do not accept one half of a pair as an ordinary lossless JSON import.
    if re.fullmatch(r"\d{12}_user_dict_(?:with_pitch_events|pitch_events)(?:-\d+)?\.json",
                    value, re.IGNORECASE):
        raise WebDictionaryImportValidation("invalid_filename")
    return value


def read_source(directory: int, filename: str) -> tuple[bytes, tuple]:
    name = allowed_filename(filename)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        before = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SOURCE_BYTES:
            raise WebDictionaryImportValidation("invalid_import")
        descriptor = os.open(name, flags, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_SOURCE_BYTES:
                raise WebDictionaryImportValidation("invalid_import")
            data = handle.read(MAX_SOURCE_BYTES + 1)
            after = os.fstat(handle.fileno())
        latest = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except WebDictionaryImportValidation:
        raise
    except OSError:
        raise WebDictionaryImportValidation("source_changed") from None

    def identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

    if len(data) > MAX_SOURCE_BYTES:
        raise WebDictionaryImportValidation("invalid_import")
    if not stat.S_ISREG(latest.st_mode) or not (
            identity(before) == identity(opened) == identity(after) == identity(latest)):
        raise WebDictionaryImportValidation("source_changed")
    return data, (identity(after), sha256(data).hexdigest())


def plan_from_bytes(filename, data, core):
    # The canonical parser uses a file path; stage bounded bytes in a private
    # temporary file so no client path is accepted or re-opened by the parser.
    with TemporaryDirectory(prefix="voiceger-import-") as folder:
        name = "source.zip" if filename.lower().endswith(".zip") else "source.json"
        staged = Path(folder) / name
        staged.write_bytes(data)
        return prepare_dictionary_import(staged, core)


def review_payload(state, core):
    review = state.review
    incoming_events = (review._incoming_pitch if isinstance(review, DictionaryBackupReview)
                       else getattr(review, "incoming_pitch_events", {}))
    existing_events = core.list_japanese_pitch_events()
    items = []
    for candidate in review.items:
        japanese = hasattr(candidate, "source_uuid")
        language = "ja" if japanese else "en"
        identity = candidate.source_uuid if japanese else candidate.incoming.surface
        incoming = candidate.incoming
        existing = candidate.existing
        current_events = existing_events.get(candidate.existing_uuid, ()) if japanese else ()
        row = {
            "language": language, "identity": identity, "surface": incoming.surface,
            "selected": candidate.selected, "relation": candidate.relation.value,
            "pronunciation": (
                japanese_word_notation(incoming, incoming_events.get(identity, ()))
                if japanese else " ".join(incoming.phonemes)
            ),
            "existing_pronunciation": (
                (japanese_word_notation(existing, current_events) if japanese
                 else " ".join(existing.phonemes)) if existing is not None else None
            ),
            "word_type": japanese_word_type(incoming).value if japanese else None,
            "priority": incoming.priority if japanese else None,
            "existing_priority": existing.priority if japanese and existing else None,
            "existing_word_type": (
                japanese_word_type(existing).value if japanese and existing else None
            ),
        }
        items.append(row)
    return {
        "token": state.token, "filename": state.filename, "format": review.format.value,
        "total": review.total_count, "exact": review.exact_duplicate_count,
        "new": sum(x["relation"] == "new" for x in items),
        "conflicts": sum(x["relation"] == "conflict" for x in items),
        "selected": sum(x["selected"] for x in items),
        "replacements": sum(x["selected"] and x["relation"] == "conflict" for x in items),
        "items": items,
    }
