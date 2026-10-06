"""Frontend-neutral user dictionary export and collision-safe naming."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .user_dictionary import (
    UserDictionaryCore,
    serialize_english_dictionary,
    serialize_japanese_dictionary,
)


@dataclass(frozen=True)
class DictionaryExportResult:
    """Paths created by one dictionary export operation."""

    paths: tuple[Path, ...]


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
    """Export native Japanese and English dictionaries as one paired operation."""

    japanese = serialize_japanese_dictionary(core.list_japanese_entries())
    english = serialize_english_dictionary(core.list_english_entries())
    return _export_payloads(
        output_dir=output_dir,
        timestamp=timestamp,
        payloads=(
            ("user_dict", japanese),
            ("english_user_dict", english),
        ),
    )


def export_voicevox_dictionary(
    core: UserDictionaryCore,
    output_dir: Path,
    *,
    timestamp: datetime | None = None,
) -> DictionaryExportResult:
    """Export the Japanese dictionary in VOICEVOX-compatible form."""

    japanese = serialize_japanese_dictionary(core.list_japanese_entries())
    return _export_payloads(
        output_dir=output_dir,
        timestamp=timestamp,
        payloads=(("voicevox_user_dict", japanese),),
    )
