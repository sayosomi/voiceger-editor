"""UI-neutral persistent Japanese and English dictionary operations."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import re
import tempfile
from threading import RLock
from typing import Any, Annotated, Optional
from uuid import UUID, uuid4

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

from .english_stress import normalize_english_phonemes
from .japanese_pitch_metadata import (
    METADATA_FILENAME, normalize_word_pitch_events, parse_pitch_metadata,
    serialize_pitch_metadata,
)
from .pronunciation import PitchEvent
from .openjtalk_dictionary import (
    OpenJTalkDictionary,
    OpenJTalkDictionaryError,
    expand_word_type,
    normalize_surface,
    validate_imported_pos,
)
from .runtime_locks import OPENJTALK_LOCK
from .settings import default_config_path


class UserDictionaryInputError(ValueError):
    """Raised for invalid dictionary input or missing UUIDs."""


class UserDictionaryStorageError(RuntimeError):
    """Raised when persistent dictionary data cannot be read or committed."""


class JapaneseWordType(str, Enum):
    PROPER_NOUN = "PROPER_NOUN"
    COMMON_NOUN = "COMMON_NOUN"
    VERB = "VERB"
    ADJECTIVE = "ADJECTIVE"
    SUFFIX = "SUFFIX"


class JapaneseDictionaryEntryRelation(str, Enum):
    """Relationship between one Japanese word and the current dictionary."""

    NEW = "new"
    EXACT = "exact"
    CONFLICT = "conflict"


def _check_newlines_and_null(text: str) -> str:
    if "\n" in text or "\r" in text:
        raise ValueError("ユーザー辞書データ内に改行が含まれています。")
    if "\x00" in text:
        raise ValueError("ユーザー辞書データ内にnull文字が含まれています。")
    return text


def _check_csv_safe(text: str) -> str:
    _check_newlines_and_null(text)
    if "," in text:
        raise ValueError("ユーザー辞書データ内にカンマが含まれています。")
    if '"' in text:
        raise ValueError("ユーザー辞書データ内にダブルクォートが含まれています。")
    return text


def _check_katakana_pronunciation(text: str) -> str:
    if re.fullmatch(r"[ァ-ヴー]+", text) is None:
        raise ValueError("発音は有効なカタカナでなくてはいけません。")
    small_kana = ("ァ", "ィ", "ゥ", "ェ", "ォ", "ャ", "ュ", "ョ", "ヮ", "ッ")
    for index, char in enumerate(text):
        if char in small_kana and index + 1 < len(text):
            next_char = text[index + 1]
            if next_char in small_kana[:-1] or (
                char == "ッ" and next_char == "ッ"
            ):
                raise ValueError("無効な発音です。(捨て仮名の連続)")
        if char == "ヮ" and index != 0 and text[index - 1] not in ("ク", "グ"):
            raise ValueError("無効な発音です。(「くゎ」「ぐゎ」以外の「ゎ」の使用)")
    return text


_MORA_PATTERN = re.compile(
    r"(?:[イ][ェ]|[ヴ][ャュョ]|[ウクグトド][ゥ]|[テデ][ィェャュョ]|"
    r"[クグ][ヮ]|[キシチニヒミリギジヂビピ][ェャュョ]|"
    r"[キニヒミリギビピ][ィ]|[クツフヴグ][ァ]|"
    r"[ウクスツフヴグズ][ィ]|[ウクツフヴグ][ェォ]|[ァ-ヴー])"
)

SurfaceStr = Annotated[
    str,
    AfterValidator(normalize_surface),
    AfterValidator(_check_newlines_and_null),
]
CsvSafeStr = Annotated[str, AfterValidator(_check_csv_safe)]
PronunciationStr = Annotated[
    CsvSafeStr,
    AfterValidator(_check_katakana_pronunciation),
]


class UserDictWord(BaseModel):
    """Canonical VOICEVOX expanded Japanese user dictionary record."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    surface: SurfaceStr = Field(description="表層形")
    priority: int = Field(ge=0, le=10, description="優先度")
    context_id: int = Field(default=1348, description="文脈ID")
    part_of_speech: CsvSafeStr
    part_of_speech_detail_1: CsvSafeStr
    part_of_speech_detail_2: CsvSafeStr
    part_of_speech_detail_3: CsvSafeStr
    inflectional_type: CsvSafeStr
    inflectional_form: CsvSafeStr
    stem: CsvSafeStr
    yomi: CsvSafeStr
    pronunciation: PronunciationStr
    accent_type: int
    mora_count: Optional[int] = None
    accent_associative_rule: CsvSafeStr

    @model_validator(mode="after")
    def validate_mora_and_accent(self):
        if self.mora_count is None:
            self.mora_count = len(_MORA_PATTERN.findall(self.pronunciation))
        if not 0 <= self.accent_type <= self.mora_count:
            raise ValueError(
                f"誤ったアクセント型です({self.accent_type})。 "
                f"expect: 0 <= accent_type <= {self.mora_count}"
            )
        return self


@dataclass(frozen=True)
class JapaneseDictionaryEntryClassification:
    """Reusable logical-identity comparison result for Japanese dictionary words."""

    relation: JapaneseDictionaryEntryRelation
    existing_uuid: str | None = None


def japanese_word_type(word: UserDictWord) -> JapaneseWordType:
    """Return the canonical Word type encoded by a validated Japanese word."""

    for word_type in JapaneseWordType:
        if expand_word_type(word_type.value)["context_id"] == word.context_id:
            return word_type
    raise UserDictionaryInputError("対応していない品詞です")


def japanese_logical_identity(
    word: UserDictWord,
) -> tuple[str, JapaneseWordType]:
    """Return the normalized Surface + Word type logical identity."""

    return normalize_surface(word.surface), japanese_word_type(word)


def classify_japanese_entry(
    entries: Mapping[str, UserDictWord],
    incoming: UserDictWord,
    *,
    exclude_uuid: str | None = None,
) -> JapaneseDictionaryEntryClassification:
    """Classify an incoming word by the Japanese logical-identity invariant."""

    identity = japanese_logical_identity(incoming)
    match: tuple[str, UserDictWord] | None = None
    for word_uuid, existing in entries.items():
        if exclude_uuid is not None and word_uuid == exclude_uuid:
            continue
        if japanese_logical_identity(existing) != identity:
            continue
        if match is not None:
            raise UserDictionaryInputError(
                "Japanese dictionary contains duplicate logical entries"
            )
        match = (word_uuid, existing)

    if match is None:
        return JapaneseDictionaryEntryClassification(
            JapaneseDictionaryEntryRelation.NEW
        )

    word_uuid, existing = match
    relation = (
        JapaneseDictionaryEntryRelation.EXACT
        if existing.model_dump(mode="json") == incoming.model_dump(mode="json")
        else JapaneseDictionaryEntryRelation.CONFLICT
    )
    return JapaneseDictionaryEntryClassification(
        relation,
        existing_uuid=word_uuid,
    )


class EnglishUserDictionaryEntry(BaseModel):
    """An exact spelling mapped to validated Voiceger ARPAbet tokens."""

    model_config = ConfigDict(extra="forbid")

    surface: str
    phonemes: list[str]

    @model_validator(mode="after")
    def validate_entry(self):
        if not self.surface.strip():
            raise ValueError("English dictionary surface must not be empty")
        if any(char in self.surface for char in ("\n", "\r", "\x00")):
            raise ValueError("English dictionary surface must not contain newlines or nulls")
        self.phonemes = normalize_english_phonemes(self.phonemes)
        return self


def default_japanese_dictionary_path() -> Path:
    """Return the Japanese adapter dictionary path beside the settings file."""

    return default_config_path().with_name("user_dict.json")


def default_english_dictionary_path() -> Path:
    """Return the English adapter dictionary path beside the settings file."""

    return default_config_path().with_name("english_user_dict.json")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise


def serialize_japanese_dictionary(
    entries: Mapping[str, UserDictWord],
) -> bytes:
    """Serialize Japanese entries in canonical insertion order."""

    payload = {
        word_uuid: word.model_dump(mode="json")
        for word_uuid, word in entries.items()
    }
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def serialize_english_dictionary(
    entries: Mapping[str, EnglishUserDictionaryEntry],
) -> bytes:
    """Serialize English entries in canonical insertion order."""

    payload = {
        surface: entry.phonemes
        for surface, entry in entries.items()
    }
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


class UserDictionaryCore:
    """Persistent, frontend-independent Japanese and English dictionaries."""

    def __init__(
        self,
        voiceger_root: str | os.PathLike[str],
        *,
        data_directory: str | os.PathLike[str] | None = None,
        openjtalk_dictionary: OpenJTalkDictionary | None = None,
    ) -> None:
        self.voiceger_root = Path(voiceger_root).expanduser().resolve()
        if data_directory is None:
            self.japanese_path = default_japanese_dictionary_path()
            self.english_path = default_english_dictionary_path()
            self.data_directory = self.japanese_path.parent.resolve()
        else:
            self.data_directory = Path(data_directory).expanduser().resolve()
            self.japanese_path = self.data_directory / "user_dict.json"
            self.english_path = self.data_directory / "english_user_dict.json"
        try:
            self.data_directory.relative_to(self.voiceger_root)
        except ValueError:
            pass
        else:
            raise ValueError(
                "adapter dictionary files must be stored outside Voiceger"
            )
        self.japanese_pitch_path = self.data_directory / METADATA_FILENAME
        self.japanese_journal_path = self.data_directory / "user_dict.pending.json"
        self.backup_journal_path = self.data_directory / "dictionaries.pending.json"
        self._recover_backup_transaction()
        self._recover_japanese_transaction()
        self.openjtalk_dictionary = openjtalk_dictionary or OpenJTalkDictionary(
            self.voiceger_root
        )
        self._lock = RLock()
        self._japanese = self._load_japanese()
        self._pitch_events = self._load_japanese_pitch_events()
        self._english = self._load_english()

    def _read_json_object(self, path: Path) -> dict[str, Any]:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeError) as exc:
            raise UserDictionaryStorageError(
                f"could not read dictionary file: {path.name}"
            ) from exc
        try:
            value = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
        except (json.JSONDecodeError, ValueError) as exc:
            raise UserDictionaryStorageError(
                f"dictionary file is malformed: {path.name}"
            ) from exc
        if not isinstance(value, dict):
            raise UserDictionaryStorageError(
                f"dictionary file must contain an object: {path.name}"
            )
        return value

    def _load_japanese(self) -> dict[str, UserDictWord]:
        raw = self._read_json_object(self.japanese_path)
        result: dict[str, UserDictWord] = {}
        try:
            for raw_uuid, value in raw.items():
                normalized_uuid = str(UUID(raw_uuid))
                if normalized_uuid in result:
                    raise ValueError("duplicate normalized UUID")
                word = UserDictWord.model_validate(value)
                validate_imported_pos(word.model_dump())
                result[normalized_uuid] = word
        except (ValueError, TypeError, ValidationError) as exc:
            raise UserDictionaryStorageError(
                "Japanese dictionary file contains invalid data"
            ) from exc
        return result

    def _recover_backup_transaction(self) -> None:
        """Complete rollback after an interrupted three-file dictionary operation."""

        journal = self.backup_journal_path
        if not journal.exists():
            return
        try:
            data = json.loads(
                journal.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
            if not isinstance(data, dict) or set(data) != {"version", "files"}:
                raise ValueError("invalid dictionary backup journal")
            if type(data["version"]) is not int or data["version"] != 1:
                raise ValueError("invalid dictionary backup journal version")
            files = data["files"]
            if not isinstance(files, list) or len(files) != 3:
                raise ValueError("invalid dictionary backup journal members")
            decoded: list[bytes | None] = []
            for value in files:
                if value is not None and not isinstance(value, str):
                    raise ValueError("invalid dictionary backup journal bytes")
                decoded.append(
                    None if value is None else base64.b64decode(value, validate=True)
                )
            paths = (
                self.japanese_path, self.english_path, self.japanese_pitch_path
            )
            for path, previous in zip(paths, decoded):
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    _atomic_write(path, previous)
            journal.unlink()
        except Exception as exc:
            raise UserDictionaryStorageError(
                "dictionary backup recovery journal could not be applied"
            ) from exc

    def _recover_japanese_transaction(self) -> None:
        """Recover the previous complete pair if interrupted between file writes."""
        journal = self.japanese_journal_path
        if not journal.exists():
            return
        try:
            data = json.loads(
                journal.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
            if not isinstance(data, dict) or set(data) != {"version", "files"}:
                raise ValueError("invalid recovery journal shape")
            if type(data["version"]) is not int or data["version"] != 1:
                raise ValueError("unsupported recovery journal version")
            files = data["files"]
            if not isinstance(files, list) or len(files) != 2:
                raise ValueError("invalid recovery files")
            for value, path in zip(files, (self.japanese_path, self.japanese_pitch_path)):
                if value is not None and not isinstance(value, str):
                    raise ValueError("invalid recovery bytes")
                if value is None:
                    path.unlink(missing_ok=True)
                else:
                    _atomic_write(path, base64.b64decode(value, validate=True))
            journal.unlink()
        except Exception as exc:
            raise UserDictionaryStorageError(
                "Japanese dictionary recovery journal could not be applied"
            ) from exc

    @staticmethod
    def _word_morae(word: UserDictWord) -> tuple[str, ...]:
        return tuple(_MORA_PATTERN.findall(word.pronunciation))

    def _load_japanese_pitch_events(self) -> dict[str, tuple[PitchEvent, ...]]:
        if not self.japanese_pitch_path.exists():
            return {}
        try:
            raw = self._read_json_object(self.japanese_pitch_path)
            return parse_pitch_metadata(
                raw, self._japanese, self._serialize_japanese(self._japanese),
                self._word_morae,
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise UserDictionaryStorageError(
                "Japanese pitch metadata is invalid or does not match the dictionary"
            ) from exc

    def list_japanese_pitch_events(self) -> dict[str, tuple[PitchEvent, ...]]:
        """Get immutable multi-peak sequences by stable Japanese word UUID."""
        with self._lock:
            return dict(self._pitch_events)

    def get_japanese_pitch_events(self, word_uuid: str) -> tuple[PitchEvent, ...]:
        normalized_uuid = self._parse_uuid(word_uuid)
        with self._lock:
            if normalized_uuid not in self._japanese:
                raise UserDictionaryInputError("UUIDに該当するワードが見つかりませんでした")
            return self._pitch_events.get(normalized_uuid, ())

    def japanese_multi_peak_snapshot(
        self,
    ) -> dict[str, tuple[UserDictWord, tuple[PitchEvent, ...]]]:
        """Return an atomic, detached snapshot of words with extra pitch events."""
        with self._lock:
            return {
                word_uuid: (self._japanese[word_uuid].model_copy(deep=True), events)
                for word_uuid, events in self._pitch_events.items()
            }

    def _persist_japanese_pair(
        self,
        candidate: Mapping[str, UserDictWord],
        events: Mapping[str, tuple[PitchEvent, ...]],
    ) -> None:
        """Journal prior bytes so a partial two-file write is recoverable."""
        base = self._serialize_japanese(candidate)
        if not (events or self._pitch_events):
            _atomic_write(self.japanese_path, base)
            return
        metadata = serialize_pitch_metadata(candidate, events, base) if events else None
        files = (self.japanese_path, self.japanese_pitch_path)
        previous = tuple(path.read_bytes() if path.exists() else None for path in files)
        journal = {
            "version": 1,
            "files": [
                None if value is None else base64.b64encode(value).decode("ascii")
                for value in previous
            ],
        }
        _atomic_write(
            self.japanese_journal_path,
            (json.dumps(journal) + "\n").encode("utf-8"),
        )
        try:
            _atomic_write(self.japanese_path, base)
            if metadata is None:
                self.japanese_pitch_path.unlink(missing_ok=True)
            else:
                _atomic_write(self.japanese_pitch_path, metadata)
            self.japanese_journal_path.unlink()
        except Exception as exc:
            try:
                self._recover_japanese_transaction()
            except UserDictionaryStorageError as rollback_error:
                raise UserDictionaryStorageError(
                    "Japanese dictionary pair could not be restored; recovery journal retained"
                ) from rollback_error
            raise UserDictionaryStorageError(
                "Japanese dictionary pair could not be persisted"
            ) from exc

    def _load_english(self) -> dict[str, EnglishUserDictionaryEntry]:
        raw = self._read_json_object(self.english_path)
        result: dict[str, EnglishUserDictionaryEntry] = {}
        normalized_keys: set[str] = set()
        try:
            for surface, phonemes in raw.items():
                entry = EnglishUserDictionaryEntry(
                    surface=surface,
                    phonemes=phonemes,
                )
                normalized = self._english_key(entry.surface)
                if normalized in normalized_keys:
                    raise ValueError("duplicate normalized English surface")
                normalized_keys.add(normalized)
                result[entry.surface] = entry
        except (ValueError, TypeError, ValidationError) as exc:
            raise UserDictionaryStorageError(
                "English dictionary file contains invalid data"
            ) from exc
        return result

    @staticmethod
    def _serialize_japanese(entries: Mapping[str, UserDictWord]) -> bytes:
        return serialize_japanese_dictionary(entries)

    @staticmethod
    def _serialize_english(
        entries: Mapping[str, EnglishUserDictionaryEntry],
    ) -> bytes:
        return serialize_english_dictionary(entries)

    def native_dictionary_backup_snapshot(
        self,
    ) -> tuple[
        dict[str, UserDictWord],
        dict[str, EnglishUserDictionaryEntry],
        dict[str, tuple[PitchEvent, ...]],
    ]:
        """Take one coherent detached backup snapshot under the dictionary lock."""

        with self._lock:
            return (
                {
                    uuid: word.model_copy(deep=True)
                    for uuid, word in self._japanese.items()
                },
                {
                    surface: entry.model_copy(deep=True)
                    for surface, entry in self._english.items()
                },
                dict(self._pitch_events),
            )

    def list_japanese_entries(self) -> dict[str, UserDictWord]:
        with self._lock:
            return {
                word_uuid: word.model_copy(deep=True)
                for word_uuid, word in self._japanese.items()
            }

    def classify_japanese_word(
        self,
        word: UserDictWord,
    ) -> JapaneseDictionaryEntryClassification:
        """Compare one validated word against the current logical entries."""

        with self._lock:
            return classify_japanese_entry(self._japanese, word)

    def _ensure_japanese_active_locked(self, *, force: bool = False) -> None:
        try:
            self.openjtalk_dictionary.ensure_active(
                self._japanese,
                force=force,
            )
        except OpenJTalkDictionaryError:
            raise
        except Exception as exc:
            raise OpenJTalkDictionaryError(
                "Japanese user dictionary activation failed"
            ) from exc

    def ensure_japanese_active(self, *, force: bool = False) -> None:
        with self._lock, OPENJTALK_LOCK:
            self._ensure_japanese_active_locked(force=force)

    @contextmanager
    def voiceger_japanese_runtime_transition(self):
        """Serialize Voiceger's OpenJTalk reset and merged-dictionary restore."""

        with self._lock, OPENJTALK_LOCK:
            try:
                yield
            finally:
                self._ensure_japanese_active_locked(force=True)

    def _create_word(
        self,
        *,
        surface: str,
        pronunciation: str,
        accent_type: int,
        word_type: JapaneseWordType | str | None,
        priority: int | None,
    ) -> UserDictWord:
        selected_type = JapaneseWordType.PROPER_NOUN if word_type is None else word_type
        selected_type = str(selected_type.value if isinstance(selected_type, Enum) else selected_type)
        selected_priority = 5 if priority is None else priority
        if isinstance(selected_priority, bool) or not isinstance(selected_priority, int) or not 0 <= selected_priority <= 10:
            raise UserDictionaryInputError("優先度の値が無効です")
        try:
            expanded = expand_word_type(selected_type)
            return UserDictWord.model_validate(
                {
                    "surface": surface,
                    "priority": selected_priority,
                    **expanded,
                    "inflectional_type": "*",
                    "inflectional_form": "*",
                    "stem": "*",
                    "yomi": pronunciation,
                    "pronunciation": pronunciation,
                    "accent_type": accent_type,
                    "mora_count": None,
                    "accent_associative_rule": "*",
                }
            )
        except (ValueError, TypeError, ValidationError) as exc:
            raise UserDictionaryInputError(str(exc)) from exc

    def _commit_japanese(
        self,
        candidate: dict[str, UserDictWord],
        candidate_metadata: Mapping[str, Sequence[PitchEvent | Mapping[str, Any]]] | None = None,
    ) -> None:
        if candidate_metadata is None:
            # Edits to an old multi-peak reading require an explicit replacement
            # rather than silently discarding previously saved pitch events.
            for word_uuid, events in self._pitch_events.items():
                word = candidate.get(word_uuid)
                previous = self._japanese[word_uuid]
                if word is not None and (
                    word.pronunciation != previous.pronunciation
                    or word.accent_type != previous.accent_type
                ):
                    raise UserDictionaryInputError(
                        "Japanese multi-peak word requires explicit pitch events when editing pronunciation/accent"
                    )
            candidate_metadata = {
                key: value for key, value in self._pitch_events.items()
                if key in candidate
            }
        normalized: dict[str, tuple[PitchEvent, ...]] = {}
        try:
            for word_uuid, events in candidate_metadata.items():
                if word_uuid not in candidate:
                    raise ValueError("unknown Japanese pitch metadata UUID")
                parsed = normalize_word_pitch_events(
                    candidate[word_uuid], events,
                    self._word_morae(candidate[word_uuid]),
                )
                if parsed:
                    normalized[word_uuid] = parsed
        except (ValueError, TypeError, KeyError) as exc:
            raise UserDictionaryInputError("invalid Japanese pitch metadata") from exc
        if candidate == self._japanese and normalized == self._pitch_events:
            return
        if candidate == self._japanese:
            try:
                if normalized:
                    _atomic_write(
                        self.japanese_pitch_path,
                        serialize_pitch_metadata(
                            candidate, normalized, self._serialize_japanese(candidate),
                        ),
                    )
                else:
                    self.japanese_pitch_path.unlink(missing_ok=True)
            except OSError as exc:
                raise UserDictionaryStorageError(
                    "Japanese pitch metadata could not be persisted"
                ) from exc
            self._pitch_events = normalized
            return
        try:
            with OPENJTALK_LOCK:
                # Make the previous persisted state the active rollback point
                # before compiling the candidate.
                self.openjtalk_dictionary.ensure_active(
                    self._japanese,
                    force=True,
                )
                previous = self.openjtalk_dictionary.activate_entries(candidate)
                try:
                    self._persist_japanese_pair(candidate, normalized)
                except Exception as persist_error:
                    current = self.openjtalk_dictionary.snapshot()
                    try:
                        self.openjtalk_dictionary.restore(previous)
                    except OpenJTalkDictionaryError as rollback_error:
                        if current.compilation is not None and current.compilation is not previous.compilation:
                            current.compilation.close()
                        raise UserDictionaryStorageError(
                            "dictionary persistence failed and the previous OpenJTalk dictionary could not be restored"
                        ) from rollback_error
                    if current.compilation is not None and current.compilation is not previous.compilation:
                        current.compilation.close()
                    raise UserDictionaryStorageError(
                        "Japanese dictionary could not be persisted"
                    ) from persist_error
                self._japanese = candidate
                self._pitch_events = normalized
                self.openjtalk_dictionary.commit(previous)
        except (UserDictionaryInputError, UserDictionaryStorageError, OpenJTalkDictionaryError):
            raise
        except Exception as exc:
            raise OpenJTalkDictionaryError(
                "Japanese dictionary compilation or application failed"
            ) from exc

    def update_japanese_pitch_events(
        self,
        word_uuid: str,
        events: Sequence[PitchEvent | Mapping[str, Any]],
    ) -> None:
        """Add/replace/remove the extra peaks without recompiling the word CSV."""
        normalized_uuid = self._parse_uuid(word_uuid)
        with self._lock:
            if normalized_uuid not in self._japanese:
                raise UserDictionaryInputError("UUIDに該当するワードが見つかりませんでした")
            candidate = dict(self._pitch_events)
            candidate[normalized_uuid] = events
            self._commit_japanese(dict(self._japanese), candidate)

    def delete_japanese_pitch_events(self, word_uuid: str) -> None:
        """Remove extra peaks, leaving the canonical word and accent untouched."""
        self.update_japanese_pitch_events(word_uuid, ())

    def add_japanese_word(
        self,
        *,
        surface: str,
        pronunciation: str,
        accent_type: int,
        word_type: JapaneseWordType | str | None = None,
        priority: int | None = None,
        pitch_events: Sequence[PitchEvent | Mapping[str, Any]] = (),
    ) -> str:
        word = self._create_word(
            surface=surface,
            pronunciation=pronunciation,
            accent_type=accent_type,
            word_type=word_type,
            priority=priority,
        )
        with self._lock:
            classification = classify_japanese_entry(self._japanese, word)
            if classification.relation is not JapaneseDictionaryEntryRelation.NEW:
                raise UserDictionaryInputError(
                    "同じSurfaceと品詞の単語が既に登録されています"
                )
            word_uuid = str(uuid4())
            candidate = dict(self._japanese)
            candidate[word_uuid] = word
            metadata = dict(self._pitch_events)
            if pitch_events:
                metadata[word_uuid] = pitch_events
            self._commit_japanese(candidate, metadata)
        return word_uuid

    @staticmethod
    def _parse_uuid(word_uuid: str) -> str:
        try:
            return str(UUID(word_uuid))
        except (ValueError, TypeError, AttributeError) as exc:
            raise UserDictionaryInputError("invalid word UUID") from exc

    def update_japanese_word(
        self,
        word_uuid: str,
        *,
        surface: str,
        pronunciation: str,
        accent_type: int,
        word_type: JapaneseWordType | str | None = None,
        priority: int | None = None,
        pitch_events: Sequence[PitchEvent | Mapping[str, Any]] | None = None,
    ) -> None:
        normalized_uuid = self._parse_uuid(word_uuid)
        word = self._create_word(
            surface=surface,
            pronunciation=pronunciation,
            accent_type=accent_type,
            word_type=word_type,
            priority=priority,
        )
        with self._lock:
            if normalized_uuid not in self._japanese:
                raise UserDictionaryInputError(
                    "UUIDに該当するワードが見つかりませんでした"
                )
            classification = classify_japanese_entry(
                self._japanese,
                word,
                exclude_uuid=normalized_uuid,
            )
            if classification.relation is not JapaneseDictionaryEntryRelation.NEW:
                raise UserDictionaryInputError(
                    "同じSurfaceと品詞の単語が既に登録されています"
                )
            candidate = dict(self._japanese)
            candidate[normalized_uuid] = word
            if pitch_events is None:
                self._commit_japanese(candidate)
            else:
                metadata = dict(self._pitch_events)
                metadata[normalized_uuid] = pitch_events
                self._commit_japanese(candidate, metadata)

    def update_japanese_accents(self, accents: Mapping[str, int]) -> None:
        """Atomically update first accent falls without dropping extra peaks."""
        if not accents:
            return
        with self._lock:
            candidate = dict(self._japanese)
            metadata = dict(self._pitch_events)
            for raw_uuid, accent in accents.items():
                word_uuid = self._parse_uuid(raw_uuid)
                if word_uuid not in candidate:
                    raise UserDictionaryInputError(
                        "UUIDに該当するワードが見つかりませんでした"
                    )
                if isinstance(accent, bool) or not isinstance(accent, int):
                    raise UserDictionaryInputError("invalid Japanese accent type")
                original = candidate[word_uuid]
                if not 0 <= accent <= original.mora_count:
                    raise UserDictionaryInputError("invalid Japanese accent type")
                updated = original.model_copy(deep=True)
                updated.accent_type = accent
                candidate[word_uuid] = updated
                if word_uuid in metadata and accent != original.accent_type:
                    old_events = metadata[word_uuid]
                    first_fall = next(
                        i for i, event in enumerate(old_events) if event.symbol == "]"
                    )
                    adjusted = list(old_events)
                    try:
                        adjusted[first_fall] = PitchEvent(accent, "]")
                        metadata[word_uuid] = normalize_word_pitch_events(
                            updated, adjusted, self._word_morae(updated),
                        )
                    except ValueError as exc:
                        raise UserDictionaryInputError(
                            "accent change conflicts with other Japanese pitch events"
                        ) from exc
            self._commit_japanese(candidate, metadata)

    def delete_japanese_word(self, word_uuid: str) -> None:
        normalized_uuid = self._parse_uuid(word_uuid)
        with self._lock:
            if normalized_uuid not in self._japanese:
                raise UserDictionaryInputError(
                    "UUIDに該当するワードが見つかりませんでした"
                )
            candidate = dict(self._japanese)
            del candidate[normalized_uuid]
            self._commit_japanese(candidate)

    def import_japanese(
        self,
        entries: Mapping[str, UserDictWord | Mapping[str, Any]],
        *,
        override: bool = False,
        pitch_events: Mapping[str, Sequence[PitchEvent | Mapping[str, Any]]] | None = None,
    ) -> None:
        if not isinstance(entries, Mapping):
            raise UserDictionaryInputError("import data must be a UUID-keyed object")
        if not isinstance(override, bool):
            raise UserDictionaryInputError("override must be a boolean")
        imported: dict[str, UserDictWord] = {}
        try:
            for raw_uuid, raw_word in entries.items():
                normalized_uuid = self._parse_uuid(raw_uuid)
                if normalized_uuid in imported:
                    raise UserDictionaryInputError(
                        "import data contains duplicate normalized UUIDs"
                    )
                if isinstance(raw_word, UserDictWord):
                    word = UserDictWord.model_validate(raw_word.model_dump())
                else:
                    word = UserDictWord.model_validate(raw_word)
                validate_imported_pos(word.model_dump())
                imported[normalized_uuid] = word
        except UserDictionaryInputError:
            raise
        except (ValueError, TypeError, ValidationError) as exc:
            raise UserDictionaryInputError(str(exc)) from exc

        incoming_metadata: dict[str, Sequence[PitchEvent | Mapping[str, Any]]] = {}
        if pitch_events is not None:
            if not isinstance(pitch_events, Mapping):
                raise UserDictionaryInputError("pitch metadata must be UUID-keyed")
            for raw_uuid, events in pitch_events.items():
                word_uuid = self._parse_uuid(raw_uuid)
                if word_uuid in incoming_metadata or word_uuid not in imported:
                    raise UserDictionaryInputError("invalid imported pitch metadata UUID")
                incoming_metadata[word_uuid] = events

        with self._lock:
            candidate = dict(self._japanese)
            metadata = dict(self._pitch_events)
            for word_uuid, word in imported.items():
                if override or word_uuid not in candidate:
                    previous_word = candidate.get(word_uuid)
                    candidate[word_uuid] = word
                    if pitch_events is not None:
                        metadata.pop(word_uuid, None)
                        if word_uuid in incoming_metadata:
                            metadata[word_uuid] = incoming_metadata[word_uuid]
                    elif previous_word is not None and (
                        previous_word.pronunciation != word.pronunciation
                        or previous_word.accent_type != word.accent_type
                    ):
                        metadata.pop(word_uuid, None)
            self._commit_japanese(candidate, metadata)

    def apply_dictionary_snapshot(
        self,
        japanese: Mapping[str, UserDictWord],
        english: Mapping[str, EnglishUserDictionaryEntry],
        pitch_events: Mapping[str, Sequence[PitchEvent | Mapping[str, Any]]],
        *,
        expected_japanese: Mapping[str, UserDictWord],
        expected_english: Mapping[str, EnglishUserDictionaryEntry],
        expected_pitch_events: Mapping[str, tuple[PitchEvent, ...]],
    ) -> None:
        """Commit Japanese, English and pitch data together with crash recovery.

        Validate and stage every replacement before activating or writing anything.
        A journal covers all three persistent files; OpenJTalk state is restored
        on failure and in-memory snapshots change only after persistence succeeds.
        """
        prepared_japanese: dict[str, UserDictWord] = {}
        prepared_english: dict[str, EnglishUserDictionaryEntry] = {}
        identities: set[tuple[str, JapaneseWordType]] = set()
        english_identities: set[str] = set()
        prepared_events: dict[str, tuple[PitchEvent, ...]] = {}
        try:
            for raw_uuid, value in japanese.items():
                uuid = self._parse_uuid(raw_uuid)
                word = UserDictWord.model_validate(
                    value.model_dump(mode="python") if isinstance(value, UserDictWord) else value
                )
                validate_imported_pos(word.model_dump())
                identity = japanese_logical_identity(word)
                if uuid in prepared_japanese or identity in identities:
                    raise ValueError("duplicate Japanese backup entry")
                prepared_japanese[uuid] = word
                identities.add(identity)
            for surface, value in english.items():
                entry = EnglishUserDictionaryEntry.model_validate(
                    value.model_dump(mode="python")
                    if isinstance(value, EnglishUserDictionaryEntry) else value
                )
                key = self._english_key(surface)
                if surface != entry.surface or key in english_identities:
                    raise ValueError("duplicate or mismatched English backup entry")
                english_identities.add(key)
                prepared_english[surface] = entry
            for raw_uuid, values in pitch_events.items():
                uuid = self._parse_uuid(raw_uuid)
                if uuid not in prepared_japanese or uuid in prepared_events:
                    raise ValueError("orphaned or duplicate Japanese backup pitch events")
                word = prepared_japanese[uuid]
                normalized = normalize_word_pitch_events(
                    word, values, self._word_morae(word)
                )
                if not normalized:
                    raise ValueError("empty Japanese backup pitch events")
                prepared_events[uuid] = normalized
        except (TypeError, ValueError, ValidationError) as exc:
            raise UserDictionaryInputError("invalid combined dictionary snapshot") from exc

        with self._lock, OPENJTALK_LOCK:
            if (
                list(self._japanese.items()) != list(expected_japanese.items())
                or list(self._english.items()) != list(expected_english.items())
                or self._pitch_events != expected_pitch_events
            ):
                raise UserDictionaryInputError(
                    "dictionary changed after backup review was prepared"
                )
            if (
                list(self._japanese.items()) == list(prepared_japanese.items())
                and list(self._english.items()) == list(prepared_english.items())
                and self._pitch_events == prepared_events
            ):
                return

            japanese_changed = list(self._japanese.items()) != list(
                prepared_japanese.items()
            )
            previous_runtime = None
            if japanese_changed:
                self.openjtalk_dictionary.ensure_active(
                    self._japanese, force=True
                )
                previous_runtime = self.openjtalk_dictionary.activate_entries(
                    prepared_japanese
                )

            paths = (
                self.japanese_path, self.english_path, self.japanese_pitch_path
            )
            try:
                previous_bytes = [
                    path.read_bytes() if path.exists() else None for path in paths
                ]
                base = serialize_japanese_dictionary(prepared_japanese)
                metadata = (
                    serialize_pitch_metadata(prepared_japanese, prepared_events, base)
                    if prepared_events else None
                )
                journal = {
                    "version": 1,
                    "files": [
                        None if value is None
                        else base64.b64encode(value).decode("ascii")
                        for value in previous_bytes
                    ],
                }
                _atomic_write(
                    self.backup_journal_path,
                    (json.dumps(journal) + "\n").encode("utf-8"),
                )
                _atomic_write(self.japanese_path, base)
                _atomic_write(
                    self.english_path,
                    serialize_english_dictionary(prepared_english),
                )
                if metadata is None:
                    self.japanese_pitch_path.unlink(missing_ok=True)
                else:
                    _atomic_write(self.japanese_pitch_path, metadata)
                self.backup_journal_path.unlink()
            except Exception as exc:
                try:
                    self._recover_backup_transaction()
                except UserDictionaryStorageError as rollback_error:
                    raise UserDictionaryStorageError(
                        "combined dictionary backup failed; recovery journal retained"
                    ) from rollback_error
                finally:
                    if previous_runtime is not None:
                        current = self.openjtalk_dictionary.snapshot()
                        try:
                            self.openjtalk_dictionary.restore(previous_runtime)
                        except Exception as restore_error:
                            raise UserDictionaryStorageError(
                                "combined dictionary backup rollback could not restore OpenJTalk"
                            ) from restore_error
                        if (
                            current.compilation is not None
                            and current.compilation is not previous_runtime.compilation
                        ):
                            current.compilation.close()
                raise UserDictionaryStorageError(
                    "combined dictionary backup could not be persisted"
                ) from exc

            self._japanese = prepared_japanese
            self._english = prepared_english
            self._pitch_events = prepared_events
            if previous_runtime is not None:
                self.openjtalk_dictionary.commit(previous_runtime)

    @staticmethod
    def _english_key(surface: str) -> str:
        if not isinstance(surface, str):
            raise UserDictionaryInputError("English dictionary surface must be a string")
        if any(char in surface for char in ("\n", "\r", "\x00")):
            raise UserDictionaryInputError(
                "English dictionary surface must not contain newlines or nulls"
            )
        key = surface.strip().casefold()
        if not key:
            raise UserDictionaryInputError("English dictionary surface must not be empty")
        return key

    def list_english_entries(self) -> dict[str, EnglishUserDictionaryEntry]:
        with self._lock:
            return {
                surface: entry.model_copy(deep=True)
                for surface, entry in self._english.items()
            }

    def lookup_english_entry(self, surface: str) -> list[str] | None:
        key = self._english_key(surface)
        with self._lock:
            for entry in self._english.values():
                if self._english_key(entry.surface) == key:
                    return list(entry.phonemes)
        return None

    def _replace_english_entry_preserving_order(
        self,
        original_key: str,
        entry: EnglishUserDictionaryEntry,
    ) -> dict[str, EnglishUserDictionaryEntry]:
        candidate: dict[str, EnglishUserDictionaryEntry] = {}
        replaced = False
        for old_surface, old_entry in self._english.items():
            if self._english_key(old_surface) == original_key:
                candidate[entry.surface] = entry
                replaced = True
            else:
                candidate[old_surface] = old_entry
        if not replaced:
            candidate[entry.surface] = entry
        return candidate

    def update_english_stresses(
        self, updates: Mapping[str, Sequence[str]],
    ) -> None:
        """Atomically save inline stress moves without changing surface or order."""

        if not isinstance(updates, Mapping):
            raise UserDictionaryInputError("English stress updates must be surface-keyed")
        validated: dict[str, list[str]] = {}
        for surface, phonemes in updates.items():
            if not isinstance(surface, str):
                raise UserDictionaryInputError("English dictionary surface must be a string")
            if isinstance(phonemes, (str, bytes)) or not isinstance(phonemes, Sequence):
                raise UserDictionaryInputError("English phonemes must be a token sequence")
            try:
                validated[surface] = normalize_english_phonemes(phonemes)
            except (TypeError, ValueError) as exc:
                raise UserDictionaryInputError(str(exc)) from exc
        if not validated:
            return

        with self._lock:
            candidate = dict(self._english)
            for surface, phonemes in validated.items():
                if surface not in candidate:
                    raise UserDictionaryInputError(
                        f"English dictionary word no longer exists: {surface}"
                    )
                entry = candidate[surface]
                candidate[surface] = EnglishUserDictionaryEntry(
                    surface=entry.surface,
                    phonemes=phonemes,
                )
            if candidate == self._english:
                return
            try:
                _atomic_write(self.english_path, self._serialize_english(candidate))
            except Exception as exc:
                raise UserDictionaryStorageError(
                    "English dictionary stresses could not be persisted"
                ) from exc
            self._english = candidate

    def set_english_entry(
        self,
        surface: str,
        phonemes: Sequence[str],
    ) -> EnglishUserDictionaryEntry:
        key = self._english_key(surface)
        if isinstance(phonemes, (str, bytes)) or not isinstance(phonemes, Sequence):
            raise UserDictionaryInputError("English phonemes must be a token sequence")
        try:
            entry = EnglishUserDictionaryEntry(
                surface=surface,
                phonemes=list(phonemes),
            )
        except (ValueError, TypeError, ValidationError) as exc:
            raise UserDictionaryInputError(str(exc)) from exc

        with self._lock:
            candidate = self._replace_english_entry_preserving_order(key, entry)
            try:
                _atomic_write(self.english_path, self._serialize_english(candidate))
            except Exception as exc:
                raise UserDictionaryStorageError(
                    "English dictionary could not be persisted"
                ) from exc
            self._english = candidate
        return entry.model_copy(deep=True)

    def import_english(
        self,
        entries: Mapping[str, Sequence[str]],
        *,
        override: bool = False,
    ) -> None:
        """Validate and atomically merge English dictionary entries."""

        if not isinstance(entries, Mapping):
            raise UserDictionaryInputError(
                "English import data must be a surface-keyed object"
            )
        if not isinstance(override, bool):
            raise UserDictionaryInputError("override must be a boolean")

        imported: list[tuple[str, EnglishUserDictionaryEntry]] = []
        imported_keys: set[str] = set()
        try:
            for surface, phonemes in entries.items():
                key = self._english_key(surface)
                if key in imported_keys:
                    raise UserDictionaryInputError(
                        "English import contains duplicate normalized surfaces"
                    )
                if isinstance(phonemes, (str, bytes)) or not isinstance(
                    phonemes, Sequence
                ):
                    raise UserDictionaryInputError(
                        "English phonemes must be a token sequence"
                    )
                entry = EnglishUserDictionaryEntry(
                    surface=surface,
                    phonemes=list(phonemes),
                )
                imported_keys.add(key)
                imported.append((key, entry))
        except UserDictionaryInputError:
            raise
        except (ValueError, TypeError, ValidationError) as exc:
            raise UserDictionaryInputError(str(exc)) from exc

        with self._lock:
            candidate = dict(self._english)
            for key, entry in imported:
                matching_surface = next(
                    (
                        old_surface
                        for old_surface in candidate
                        if self._english_key(old_surface) == key
                    ),
                    None,
                )
                if matching_surface is None:
                    candidate[entry.surface] = entry
                    continue
                if not override:
                    continue

                replacement: dict[str, EnglishUserDictionaryEntry] = {}
                for old_surface, old_entry in candidate.items():
                    if self._english_key(old_surface) == key:
                        replacement[entry.surface] = entry
                    else:
                        replacement[old_surface] = old_entry
                candidate = replacement

            if candidate == self._english:
                return
            try:
                _atomic_write(self.english_path, self._serialize_english(candidate))
            except Exception as exc:
                raise UserDictionaryStorageError(
                    "English dictionary could not be persisted"
                ) from exc
            self._english = candidate

    def add_english_entry(
        self,
        surface: str,
        phonemes: Sequence[str],
    ) -> EnglishUserDictionaryEntry:
        return self.set_english_entry(surface, phonemes)

    def update_english_entry(
        self,
        original_surface: str,
        *,
        surface: str,
        phonemes: Sequence[str],
    ) -> EnglishUserDictionaryEntry:
        original_key = self._english_key(original_surface)
        target_key = self._english_key(surface)
        if isinstance(phonemes, (str, bytes)) or not isinstance(phonemes, Sequence):
            raise UserDictionaryInputError("English phonemes must be a token sequence")
        try:
            entry = EnglishUserDictionaryEntry(
                surface=surface,
                phonemes=list(phonemes),
            )
        except (ValueError, TypeError, ValidationError) as exc:
            raise UserDictionaryInputError(str(exc)) from exc

        with self._lock:
            matching_surfaces = [
                old_surface
                for old_surface in self._english
                if self._english_key(old_surface) == original_key
            ]
            if not matching_surfaces:
                raise UserDictionaryInputError("English dictionary entry was not found")
            if target_key != original_key and any(
                self._english_key(old_surface) == target_key
                for old_surface in self._english
            ):
                raise UserDictionaryInputError(
                    "English dictionary target surface already exists"
                )

            candidate = self._replace_english_entry_preserving_order(
                original_key,
                entry,
            )
            try:
                _atomic_write(self.english_path, self._serialize_english(candidate))
            except Exception as exc:
                raise UserDictionaryStorageError(
                    "English dictionary could not be persisted"
                ) from exc
            self._english = candidate
        return entry.model_copy(deep=True)

    def delete_english_entry(self, surface: str) -> None:
        key = self._english_key(surface)
        with self._lock:
            candidate = {
                old_surface: old_entry
                for old_surface, old_entry in self._english.items()
                if self._english_key(old_surface) != key
            }
            if len(candidate) == len(self._english):
                raise UserDictionaryInputError("English dictionary entry was not found")
            try:
                _atomic_write(self.english_path, self._serialize_english(candidate))
            except Exception as exc:
                raise UserDictionaryStorageError(
                    "English dictionary could not be persisted"
                ) from exc
            self._english = candidate
