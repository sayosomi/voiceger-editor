"""Frontend-neutral user dictionary export and collision-safe naming."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .japanese_pitch_metadata import serialize_pitch_metadata

from .user_dictionary import (
    UserDictionaryCore,
    serialize_english_dictionary,
    serialize_japanese_dictionary,
)


@dataclass(frozen=True)
class DictionaryExportResult:
    """Paths created by one dictionary export operation."""

    paths: tuple[Path, ...]
    lossy_pitch_event_uuids: tuple[str, ...] = ()


def _timestamp_prefix(timestamp: datetime | None) -> str:
    return (timestamp or datetime.now()).strftime("%Y%m%d%H%M")


def _remove_owned_paths(paths: Iterable[Path]) -> None:
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _write_payload(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)


def _export_payloads(
    *,
    output_dir: Path,
    timestamp: datetime | None,
    payloads: tuple[tuple[str, bytes], ...],
) -> DictionaryExportResult:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = _timestamp_prefix(timestamp)
    collision_number = 1

    while True:
        suffix = "" if collision_number == 1 else f"-{collision_number}"
        paths = tuple(
            output_dir / f"{prefix}_{stem}{suffix}.json"
            for stem, _payload in payloads
        )
        reserved: list[Path] = []
        try:
            for path in paths:
                with path.open("xb"):
                    pass
                reserved.append(path)
        except FileExistsError:
            _remove_owned_paths(reserved)
            collision_number += 1
            continue
        except BaseException:
            _remove_owned_paths(reserved)
            raise

        try:
            for path, (_stem, payload) in zip(paths, payloads):
                _write_payload(path, payload)
        except BaseException:
            _remove_owned_paths(paths)
            raise
        return DictionaryExportResult(paths=paths)


def export_voiceger_editor_dictionaries(
    core: UserDictionaryCore,
    output_dir: Path,
    *,
    timestamp: datetime | None = None,
) -> DictionaryExportResult:
    """Atomically publish one versioned, checksummed native ZIP backup."""

    if hasattr(core, "native_dictionary_backup_snapshot"):
        words, english_words, events = core.native_dictionary_backup_snapshot()
    else:
        # Support duck-typed dictionary cores used by client integrations.
        words = core.list_japanese_entries()
        english_words = core.list_english_entries()
        events = getattr(core, "list_japanese_pitch_events", lambda: {})()
    japanese = serialize_japanese_dictionary(words)
    english = serialize_english_dictionary(english_words)
    members = {
        "user_dict.json": japanese,
        "english_user_dict.json": english,
    }
    if events:
        members["user_dict_pitch_events.json"] = serialize_pitch_metadata(
            words, events, japanese
        )
    manifest = {
        "version": 1,
        "members": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in members.items()
        },
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".voiceger-dictionary-",
            suffix=".tmp",
            dir=output_dir,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", manifest_bytes)
                for name, data in members.items():
                    archive.writestr(name, data)
            temporary.flush()
            os.fsync(temporary.fileno())

        prefix = _timestamp_prefix(timestamp)
        collision = 1
        while True:
            suffix = "" if collision == 1 else f"-{collision}"
            destination = (
                output_dir / f"{prefix}_voiceger_editor_dictionary{suffix}.zip"
            )
            try:
                # Same-filesystem hard link publishes only a complete archive;
                # an already-existing destination can never be overwritten.
                os.link(temporary_name, destination)
                return DictionaryExportResult(paths=(destination,))
            except FileExistsError:
                collision += 1
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def export_voicevox_dictionary(
    core: UserDictionaryCore,
    output_dir: Path,
    *,
    timestamp: datetime | None = None,
) -> DictionaryExportResult:
    """Export the Japanese dictionary in VOICEVOX-compatible form."""

    japanese = serialize_japanese_dictionary(core.list_japanese_entries())
    result = _export_payloads(
        output_dir=output_dir,
        timestamp=timestamp,
        payloads=(("voicevox_user_dict", japanese),),
    )
    events = getattr(core, "list_japanese_pitch_events", lambda: {})()
    return DictionaryExportResult(
        paths=result.paths,
        lossy_pitch_event_uuids=tuple(events),
    )
