"""Frontend-neutral dictionary import parsing, review planning, and commit."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID

from pydantic import ValidationError

from .openjtalk_dictionary import expand_word_type, validate_imported_pos
from .user_dictionary import (
    EnglishUserDictionaryEntry,
    JapaneseWordType,
    UserDictWord,
    UserDictionaryCore,
    UserDictionaryInputError,
    classify_japanese_entry,
    japanese_logical_identity,
)


class DictionaryImportError(UserDictionaryInputError):
    """Raised when dictionary import data cannot be parsed or planned safely."""


class DictionaryImportFormat(str, Enum):
    JAPANESE = "japanese"
    ENGLISH = "english"


class DictionaryImportRelation(str, Enum):
    NEW = "new"
    EXACT = "exact"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class ParsedDictionaryImport:
    """Validated import payload before comparison with the active dictionary."""

    format: DictionaryImportFormat
    source_path: Path
    japanese_entries: tuple[tuple[str, UserDictWord], ...] = ()
    english_entries: tuple[EnglishUserDictionaryEntry, ...] = ()


@dataclass(frozen=True)
class DictionaryImportCommitResult:
    imported: int
    replaced: int
    skipped: int


@dataclass(frozen=True)
class JapaneseImportReviewItem:
    source_uuid: str
    incoming: UserDictWord
    relation: DictionaryImportRelation
    selected: bool
    existing_uuid: str | None = None
    existing: UserDictWord | None = None


@dataclass(frozen=True)
class EnglishImportReviewItem:
    incoming: EnglishUserDictionaryEntry
    relation: DictionaryImportRelation
    selected: bool
    existing_surface: str | None = None
    existing: EnglishUserDictionaryEntry | None = None


@dataclass
class _JapaneseCandidate:
    source_uuid: str
    incoming: UserDictWord
    relation: DictionaryImportRelation
    selected: bool
    existing_uuid: str | None = None
    existing: UserDictWord | None = None


@dataclass
class _EnglishCandidate:
    incoming: EnglishUserDictionaryEntry
    relation: DictionaryImportRelation
    selected: bool
    existing_surface: str | None = None
    existing: EnglishUserDictionaryEntry | None = None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _read_json_object(path: str | Path) -> tuple[Path, dict[str, Any]]:
    source_path = Path(path).expanduser()
    try:
        text = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DictionaryImportError(
            f"could not read dictionary import file: {source_path}"
        ) from exc
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, ValueError) as exc:
        raise DictionaryImportError("dictionary import file is malformed") from exc
    if not isinstance(value, dict):
        raise DictionaryImportError("dictionary import file must contain an object")
    if not value:
        raise DictionaryImportError(
            "empty dictionary import file has no detectable format"
        )
    return source_path, value


def _parse_japanese(
    source_path: Path,
    raw: Mapping[str, Any],
) -> ParsedDictionaryImport:
    entries: list[tuple[str, UserDictWord]] = []
    normalized_uuids: set[str] = set()
    logical_identities: set[tuple[str, JapaneseWordType]] = set()
    try:
        for raw_uuid, raw_word in raw.items():
            normalized_uuid = str(UUID(raw_uuid))
            if normalized_uuid in normalized_uuids:
                raise ValueError("duplicate normalized UUID")
            normalized_uuids.add(normalized_uuid)
            word = UserDictWord.model_validate(raw_word)
            validate_imported_pos(word.model_dump())
            identity = japanese_logical_identity(word)
            if identity in logical_identities:
                raise ValueError(
                    "Japanese import contains duplicate Surface + Word type entries"
                )
            logical_identities.add(identity)
            entries.append((normalized_uuid, word))
    except (ValueError, TypeError, ValidationError) as exc:
        raise DictionaryImportError(
            "Japanese dictionary import contains invalid data"
        ) from exc
    return ParsedDictionaryImport(
        format=DictionaryImportFormat.JAPANESE,
        source_path=source_path,
        japanese_entries=tuple(entries),
    )


def _parse_english(
    source_path: Path,
    raw: Mapping[str, Any],
) -> ParsedDictionaryImport:
    entries: list[EnglishUserDictionaryEntry] = []
    normalized_surfaces: set[str] = set()
    try:
        for surface, phonemes in raw.items():
            if not isinstance(phonemes, list):
                raise TypeError("English dictionary values must be token arrays")
            entry = EnglishUserDictionaryEntry(
                surface=surface,
                phonemes=phonemes,
            )
            identity = entry.surface.strip().casefold()
            if identity in normalized_surfaces:
                raise ValueError("duplicate normalized English surface")
            normalized_surfaces.add(identity)
            entries.append(entry)
    except (ValueError, TypeError, ValidationError) as exc:
        raise DictionaryImportError(
            "English dictionary import contains invalid data"
        ) from exc
    return ParsedDictionaryImport(
        format=DictionaryImportFormat.ENGLISH,
        source_path=source_path,
        english_entries=tuple(entries),
    )


def load_dictionary_import(path: str | Path) -> ParsedDictionaryImport:
    """Read, detect, and fully validate one supported dictionary file."""

    source_path, raw = _read_json_object(path)
    values = list(raw.values())
    if all(isinstance(value, Mapping) for value in values):
        return _parse_japanese(source_path, raw)
    if all(isinstance(value, list) for value in values):
        return _parse_english(source_path, raw)
    raise DictionaryImportError("unsupported or mixed dictionary import shape")


def _copy_japanese_item(candidate: _JapaneseCandidate) -> JapaneseImportReviewItem:
    return JapaneseImportReviewItem(
        source_uuid=candidate.source_uuid,
        incoming=candidate.incoming.model_copy(deep=True),
        relation=candidate.relation,
        selected=candidate.selected,
        existing_uuid=candidate.existing_uuid,
        existing=(
            None
            if candidate.existing is None
            else candidate.existing.model_copy(deep=True)
        ),
    )


def _copy_english_item(candidate: _EnglishCandidate) -> EnglishImportReviewItem:
    return EnglishImportReviewItem(
        incoming=candidate.incoming.model_copy(deep=True),
        relation=candidate.relation,
        selected=candidate.selected,
        existing_surface=candidate.existing_surface,
        existing=(
            None
            if candidate.existing is None
            else candidate.existing.model_copy(deep=True)
        ),
    )


class JapaneseDictionaryImportReview:
    """Mutable selection/Word-type review over validated Japanese import data."""

    format = DictionaryImportFormat.JAPANESE

    def __init__(
        self,
        base_entries: Mapping[str, UserDictWord],
        entries: Sequence[tuple[str, UserDictWord]],
    ) -> None:
        self._base_entries = {
            word_uuid: word.model_copy(deep=True)
            for word_uuid, word in base_entries.items()
        }
        self._candidates = [
            _JapaneseCandidate(
                source_uuid=source_uuid,
                incoming=word.model_copy(deep=True),
                relation=DictionaryImportRelation.NEW,
                selected=True,
            )
            for source_uuid, word in entries
        ]
        self._committed = False
        for candidate in self._candidates:
            self._classify(candidate, reset_selection=True)

    @property
    def items(self) -> tuple[JapaneseImportReviewItem, ...]:
        return tuple(
            _copy_japanese_item(candidate)
            for candidate in self._candidates
            if candidate.relation is not DictionaryImportRelation.EXACT
        )

    @property
    def exact_duplicate_count(self) -> int:
        return sum(
            candidate.relation is DictionaryImportRelation.EXACT
            for candidate in self._candidates
        )

    @property
    def total_count(self) -> int:
        return len(self._candidates)

    def _find(self, source_uuid: str) -> _JapaneseCandidate:
        try:
            normalized_uuid = str(UUID(source_uuid))
        except (ValueError, TypeError, AttributeError) as exc:
            raise DictionaryImportError("invalid Japanese import UUID") from exc
        for candidate in self._candidates:
            if candidate.source_uuid == normalized_uuid:
                return candidate
        raise DictionaryImportError("Japanese import review entry was not found")

    def _classify(
        self,
        candidate: _JapaneseCandidate,
        *,
        reset_selection: bool,
    ) -> None:
        try:
            classification = classify_japanese_entry(
                self._base_entries,
                candidate.incoming,
            )
        except UserDictionaryInputError as exc:
            raise DictionaryImportError(str(exc)) from exc

        relation = DictionaryImportRelation(classification.relation.value)
        if (
            relation is DictionaryImportRelation.NEW
            and candidate.source_uuid in self._base_entries
        ):
            raise DictionaryImportError(
                "Japanese import UUID collides with an unrelated existing entry"
            )

        previous_relation = candidate.relation
        candidate.relation = relation
        candidate.existing_uuid = classification.existing_uuid
        candidate.existing = (
            None
            if classification.existing_uuid is None
            else self._base_entries[classification.existing_uuid].model_copy(deep=True)
        )
        if (
            reset_selection
            or relation is not previous_relation
            or relation is DictionaryImportRelation.EXACT
        ):
            candidate.selected = relation is DictionaryImportRelation.NEW

    def set_selected(self, source_uuid: str, selected: bool) -> None:
        if not isinstance(selected, bool):
            raise DictionaryImportError("selection must be a boolean")
        candidate = self._find(source_uuid)
        if candidate.relation is DictionaryImportRelation.EXACT:
            raise DictionaryImportError("exact duplicates are not reviewable")
        candidate.selected = selected

    def set_word_type(
        self,
        source_uuid: str,
        word_type: JapaneseWordType | str,
    ) -> None:
        candidate = self._find(source_uuid)
        try:
            selected_type = (
                word_type
                if isinstance(word_type, JapaneseWordType)
                else JapaneseWordType(str(word_type))
            )
            payload = candidate.incoming.model_dump(mode="python")
            payload.update(expand_word_type(selected_type.value))
            try:
                validate_imported_pos(payload)
            except ValueError:
                payload["accent_associative_rule"] = "*"
                validate_imported_pos(payload)
            updated = UserDictWord.model_validate(payload)
        except (ValueError, TypeError, ValidationError) as exc:
            raise DictionaryImportError(str(exc)) from exc

        proposed_identity = japanese_logical_identity(updated)
        for other in self._candidates:
            if other is candidate:
                continue
            if japanese_logical_identity(other.incoming) == proposed_identity:
                raise DictionaryImportError(
                    "Word type change would duplicate another imported logical entry"
                )

        previous = candidate.incoming
        candidate.incoming = updated
        try:
            self._classify(candidate, reset_selection=False)
        except Exception:
            candidate.incoming = previous
            self._classify(candidate, reset_selection=False)
            raise

    def commit(self, core: UserDictionaryCore) -> DictionaryImportCommitResult:
        if self._committed:
            raise DictionaryImportError("dictionary import review was already committed")
        if core.list_japanese_entries() != self._base_entries:
            raise DictionaryImportError(
                "Japanese dictionary changed after import review was prepared"
            )

        selected: dict[str, UserDictWord] = {}
        imported = 0
        replaced = 0
        for candidate in self._candidates:
            if (
                candidate.relation is DictionaryImportRelation.EXACT
                or not candidate.selected
            ):
                continue
            if candidate.relation is DictionaryImportRelation.CONFLICT:
                if candidate.existing_uuid is None:
                    raise DictionaryImportError("conflict is missing its existing UUID")
                target_uuid = candidate.existing_uuid
                replaced += 1
            else:
                target_uuid = candidate.source_uuid
                imported += 1
            selected[target_uuid] = candidate.incoming.model_copy(deep=True)

        core.import_japanese(selected, override=True)
        self._committed = True
        return DictionaryImportCommitResult(
            imported=imported,
            replaced=replaced,
            skipped=len(self._candidates) - imported - replaced,
        )


class EnglishDictionaryImportReview:
    """Mutable selection review over validated English import data."""

    format = DictionaryImportFormat.ENGLISH

    def __init__(
        self,
        base_entries: Mapping[str, EnglishUserDictionaryEntry],
        entries: Sequence[EnglishUserDictionaryEntry],
    ) -> None:
        self._base_entries = {
            surface: entry.model_copy(deep=True)
            for surface, entry in base_entries.items()
        }
        self._candidates: list[_EnglishCandidate] = []
        base_by_identity = {
            surface.strip().casefold(): (surface, entry)
            for surface, entry in self._base_entries.items()
        }
        for entry in entries:
            incoming = entry.model_copy(deep=True)
            match = base_by_identity.get(incoming.surface.strip().casefold())
            if match is None:
                relation = DictionaryImportRelation.NEW
                existing_surface = None
                existing = None
            else:
                existing_surface, existing = match
                relation = (
                    DictionaryImportRelation.EXACT
                    if existing.model_dump(mode="json")
                    == incoming.model_dump(mode="json")
                    else DictionaryImportRelation.CONFLICT
                )
            self._candidates.append(
                _EnglishCandidate(
                    incoming=incoming,
                    relation=relation,
                    selected=relation is DictionaryImportRelation.NEW,
                    existing_surface=existing_surface,
                    existing=(
                        None
                        if existing is None
                        else existing.model_copy(deep=True)
                    ),
                )
            )
        self._committed = False

    @property
    def items(self) -> tuple[EnglishImportReviewItem, ...]:
        return tuple(
            _copy_english_item(candidate)
            for candidate in self._candidates
            if candidate.relation is not DictionaryImportRelation.EXACT
        )

    @property
    def exact_duplicate_count(self) -> int:
        return sum(
            candidate.relation is DictionaryImportRelation.EXACT
            for candidate in self._candidates
        )

    @property
    def total_count(self) -> int:
        return len(self._candidates)

    def set_selected(self, surface: str, selected: bool) -> None:
        if not isinstance(selected, bool):
            raise DictionaryImportError("selection must be a boolean")
        identity = surface.strip().casefold()
        for candidate in self._candidates:
            if candidate.incoming.surface.strip().casefold() != identity:
                continue
            if candidate.relation is DictionaryImportRelation.EXACT:
                raise DictionaryImportError("exact duplicates are not reviewable")
            candidate.selected = selected
            return
        raise DictionaryImportError("English import review entry was not found")

    def commit(self, core: UserDictionaryCore) -> DictionaryImportCommitResult:
        if self._committed:
            raise DictionaryImportError("dictionary import review was already committed")
        if core.list_english_entries() != self._base_entries:
            raise DictionaryImportError(
                "English dictionary changed after import review was prepared"
            )

        selected: dict[str, list[str]] = {}
        imported = 0
        replaced = 0
        for candidate in self._candidates:
            if (
                candidate.relation is DictionaryImportRelation.EXACT
                or not candidate.selected
            ):
                continue
            selected[candidate.incoming.surface] = list(candidate.incoming.phonemes)
            if candidate.relation is DictionaryImportRelation.CONFLICT:
                replaced += 1
            else:
                imported += 1

        core.import_english(selected, override=True)
        self._committed = True
        return DictionaryImportCommitResult(
            imported=imported,
            replaced=replaced,
            skipped=len(self._candidates) - imported - replaced,
        )


DictionaryImportReview = JapaneseDictionaryImportReview | EnglishDictionaryImportReview


def plan_dictionary_import(
    parsed: ParsedDictionaryImport,
    core: UserDictionaryCore,
) -> DictionaryImportReview:
    """Compare validated import data with the current dictionary state."""

    if parsed.format is DictionaryImportFormat.JAPANESE:
        return JapaneseDictionaryImportReview(
            core.list_japanese_entries(),
            parsed.japanese_entries,
        )
    if parsed.format is DictionaryImportFormat.ENGLISH:
        return EnglishDictionaryImportReview(
            core.list_english_entries(),
            parsed.english_entries,
        )
    raise DictionaryImportError("unsupported dictionary import format")


def prepare_dictionary_import(
    path: str | Path,
    core: UserDictionaryCore,
) -> DictionaryImportReview:
    """Load, validate, detect, and plan one dictionary import."""

    return plan_dictionary_import(load_dictionary_import(path), core)
