"""Bounded native ZIP dictionary backup and selective two-language Merge."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import stat
from typing import Any
from zipfile import BadZipFile, ZipFile

from .dictionary_import import (
    DictionaryImportCommitResult,
    DictionaryImportError,
    DictionaryImportFormat,
    DictionaryImportRelation,
    EnglishDictionaryImportReview,
    JapaneseDictionaryImportReview,
    _parse_english,
    _parse_japanese,
    _reject_duplicate_keys,
)
from .japanese_pitch_metadata import parse_pitch_metadata
from .pronunciation import PitchEvent
from .user_dictionary import (
    EnglishUserDictionaryEntry,
    UserDictWord,
    UserDictionaryCore,
    _MORA_PATTERN,
    serialize_english_dictionary,
    serialize_japanese_dictionary,
)

_BACKUP_MEMBERS = {"user_dict.json", "english_user_dict.json"}
_OPTIONAL_MEMBER = "user_dict_pitch_events.json"
_ALLOWED_MEMBERS = _BACKUP_MEMBERS | {_OPTIONAL_MEMBER}
_MAX_ZIP_BYTES = 32 * 1024 * 1024
_MAX_MEMBER_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_BYTES = 40 * 1024 * 1024


@dataclass(frozen=True)
class ParsedDictionaryBackup:
    source_path: Path
    japanese_entries: tuple[tuple[str, UserDictWord], ...]
    english_entries: tuple[EnglishUserDictionaryEntry, ...]
    pitch_events: tuple[tuple[str, tuple[PitchEvent, ...]], ...]


def _json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise DictionaryImportError(f"malformed {label} in dictionary backup") from exc
    if not isinstance(parsed, dict):
        raise DictionaryImportError(f"{label} in dictionary backup must be an object")
    return parsed


def load_dictionary_backup(path: str | Path) -> ParsedDictionaryBackup:
    """Validate the entire ZIP before constructing a Merge review."""

    source = Path(path).expanduser()
    try:
        if not source.is_file() or source.stat().st_size > _MAX_ZIP_BYTES:
            raise DictionaryImportError("dictionary backup is missing or too large")
        with ZipFile(source) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) not in (3, 4) or len(set(names)) != len(names):
                raise DictionaryImportError("dictionary backup member count/uniqueness is invalid")
            expected_names = set(names)
            if not _BACKUP_MEMBERS.issubset(expected_names) or not expected_names.issubset(
                _ALLOWED_MEMBERS | {"manifest.json"}
            ) or "manifest.json" not in expected_names:
                raise DictionaryImportError("dictionary backup is missing required members")
            total = 0
            for info in infos:
                mode = info.external_attr >> 16
                if (
                    info.is_dir()
                    or stat.S_ISLNK(mode)
                    or info.flag_bits & 1
                    or info.file_size > _MAX_MEMBER_BYTES
                    or info.file_size < 0
                    or info.compress_size < 0
                    or (
                        info.file_size > 1_000_000
                        and info.file_size > 300 * max(1, info.compress_size)
                    )
                ):
                    raise DictionaryImportError("unsafe dictionary backup archive member")
                total += info.file_size
                if total > _MAX_TOTAL_BYTES:
                    raise DictionaryImportError("dictionary backup expanded size limit exceeded")
            payloads = {
                name: archive.read(name)
                for name in names
            }
    except DictionaryImportError:
        raise
    except (BadZipFile, OSError, RuntimeError, EOFError, ValueError, MemoryError) as exc:
        raise DictionaryImportError("dictionary backup archive is invalid") from exc

    manifest = _json_object(payloads.pop("manifest.json"), "manifest.json")
    if set(manifest) != {"version", "members"} or type(manifest["version"]) is not int or manifest["version"] != 1:
        raise DictionaryImportError("unsupported dictionary backup manifest version/shape")
    digests = manifest["members"]
    if not isinstance(digests, dict) or set(digests) != set(payloads):
        raise DictionaryImportError("dictionary backup manifest member list is incomplete")
    for name, data in payloads.items():
        checksum = digests[name]
        if not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None:
            raise DictionaryImportError("dictionary backup checksum is malformed")
        if sha256(data).hexdigest() != checksum:
            raise DictionaryImportError(f"dictionary backup checksum mismatch: {name}")

    japanese = _parse_japanese(source, _json_object(payloads["user_dict.json"], "user_dict.json"))
    english = _parse_english(source, _json_object(payloads["english_user_dict.json"], "english_user_dict.json"))
    words = dict(japanese.japanese_entries)
    english_words = {word.surface: word for word in english.english_entries}
    if serialize_japanese_dictionary(words) != payloads["user_dict.json"] or (
        serialize_english_dictionary(english_words) != payloads["english_user_dict.json"]
    ):
        raise DictionaryImportError("dictionary backup contains noncanonical dictionary bytes")
    pitch_events: dict[str, tuple[PitchEvent, ...]] = {}
    if _OPTIONAL_MEMBER in payloads:
        try:
            pitch_events = parse_pitch_metadata(
                _json_object(payloads[_OPTIONAL_MEMBER], _OPTIONAL_MEMBER),
                words,
                payloads["user_dict.json"],
                lambda word: tuple(_MORA_PATTERN.findall(word.pronunciation)),
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise DictionaryImportError("invalid or unmatched dictionary backup pitch metadata") from exc
        if serialize_pitch_metadata_for_backup(words, pitch_events, payloads["user_dict.json"]) != payloads[_OPTIONAL_MEMBER]:
            raise DictionaryImportError("dictionary backup contains noncanonical pitch metadata")
    return ParsedDictionaryBackup(
        source_path=source,
        japanese_entries=japanese.japanese_entries,
        english_entries=english.english_entries,
        pitch_events=tuple(pitch_events.items()),
    )


def serialize_pitch_metadata_for_backup(words, events, japanese):
    from .japanese_pitch_metadata import serialize_pitch_metadata

    return serialize_pitch_metadata(words, events, japanese)


class DictionaryBackupReview:
    """Selectable Japanese/English Merge; never delete local-only words."""

    def __init__(self, parsed: ParsedDictionaryBackup, core: UserDictionaryCore) -> None:
        self.format = DictionaryImportFormat.BACKUP
        self.source_path = parsed.source_path
        self._base_japanese = core.list_japanese_entries()
        self._base_english = core.list_english_entries()
        self._base_pitch = core.list_japanese_pitch_events()
        self._incoming_japanese = dict(parsed.japanese_entries)
        self._incoming_english = {
            entry.surface: entry.model_copy(deep=True) for entry in parsed.english_entries
        }
        self._incoming_pitch = dict(parsed.pitch_events)
        self.japanese = JapaneseDictionaryImportReview(
            self._base_japanese, parsed.japanese_entries,
            base_pitch_events=self._base_pitch,
            incoming_pitch_events=self._incoming_pitch,
            native_pitch_metadata=True,
        )
        self.english = EnglishDictionaryImportReview(
            self._base_english, parsed.english_entries,
        )
        self._committed = False

    @property
    def items(self):
        return (*self.japanese.items, *self.english.items)

    @property
    def total_count(self) -> int:
        return len(self._incoming_japanese) + len(self._incoming_english)

    @property
    def exact_duplicate_count(self) -> int:
        return self.japanese.exact_duplicate_count + self.english.exact_duplicate_count

    @property
    def language_counts(self) -> tuple[int, int]:
        return len(self._incoming_japanese), len(self._incoming_english)

    def set_selected(self, identity: str, selected: bool, *, language: str) -> None:
        if language == "ja":
            self.japanese.set_selected(identity, selected)
        else:
            self.english.set_selected(identity, selected)

    def set_word_type(self, uuid: str, word_type) -> None:
        self.japanese.set_word_type(uuid, word_type)

    def _merged_snapshot(self):
        japanese = dict(self._base_japanese)
        english = dict(self._base_english)
        pitch = dict(self._base_pitch)
        imported = replaced = 0
        for candidate in self.japanese._candidates:
            if not candidate.selected or candidate.relation is DictionaryImportRelation.EXACT:
                continue
            target_uuid = (
                candidate.existing_uuid if candidate.relation is DictionaryImportRelation.CONFLICT
                else candidate.source_uuid
            )
            if target_uuid is None:
                raise DictionaryImportError("Japanese backup conflict has no target UUID")
            japanese[target_uuid] = candidate.incoming.model_copy(deep=True)
            pitch.pop(target_uuid, None)
            if candidate.source_uuid in self._incoming_pitch:
                pitch[target_uuid] = self._incoming_pitch[candidate.source_uuid]
            if candidate.relation is DictionaryImportRelation.CONFLICT:
                replaced += 1
            else:
                imported += 1
        for candidate in self.english._candidates:
            if not candidate.selected or candidate.relation is DictionaryImportRelation.EXACT:
                continue
            entry = candidate.incoming.model_copy(deep=True)
            if candidate.relation is DictionaryImportRelation.CONFLICT:
                key = candidate.existing_surface
                if key is None:
                    raise DictionaryImportError("English backup conflict has no target")
                english = {
                    (entry.surface if surface == key else surface): (
                        entry if surface == key else old
                    )
                    for surface, old in english.items()
                }
                replaced += 1
            else:
                english[entry.surface] = entry
                imported += 1
        return japanese, english, pitch, DictionaryImportCommitResult(
            imported=imported,
            replaced=replaced,
            skipped=self.total_count - imported - replaced,
        )

    def commit(self, core: UserDictionaryCore) -> DictionaryImportCommitResult:
        if self._committed:
            raise DictionaryImportError("dictionary backup review was already committed")
        japanese, english, pitch, result = self._merged_snapshot()
        core.apply_dictionary_snapshot(
            japanese,
            english,
            pitch,
            expected_japanese=self._base_japanese,
            expected_english=self._base_english,
            expected_pitch_events=self._base_pitch,
        )
        self._committed = True
        return result


def prepare_dictionary_backup(
    path: str | Path, core: UserDictionaryCore
) -> DictionaryBackupReview:
    return DictionaryBackupReview(load_dictionary_backup(path), core)
