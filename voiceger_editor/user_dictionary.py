"""UI-neutral persistent Japanese and English dictionary operations."""

from __future__ import annotations

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
        self.openjtalk_dictionary = openjtalk_dictionary or OpenJTalkDictionary(
            self.voiceger_root
        )
        self._lock = RLock()
        self._japanese = self._load_japanese()
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

    def _commit_japanese(self, candidate: dict[str, UserDictWord]) -> None:
        if candidate == self._japanese:
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
                    _atomic_write(self.japanese_path, self._serialize_japanese(candidate))
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
                self.openjtalk_dictionary.commit(previous)
        except (UserDictionaryInputError, UserDictionaryStorageError, OpenJTalkDictionaryError):
            raise
        except Exception as exc:
            raise OpenJTalkDictionaryError(
                "Japanese dictionary compilation or application failed"
            ) from exc

    def add_japanese_word(
        self,
        *,
        surface: str,
        pronunciation: str,
        accent_type: int,
        word_type: JapaneseWordType | str | None = None,
        priority: int | None = None,
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
            self._commit_japanese(candidate)
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
            self._commit_japanese(candidate)

    def update_japanese_accents(self, accents: Mapping[str, int]) -> None:
        """Atomically compile and commit multiple accent-only edits.

        Preserve UUIDs, canonical entry order, and all other word properties.
        """
        if not accents:
            return
        with self._lock:
            candidate = dict(self._japanese)
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
            self._commit_japanese(candidate)

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

        with self._lock:
            candidate = dict(self._japanese)
            for word_uuid, word in imported.items():
                if override or word_uuid not in candidate:
                    candidate[word_uuid] = word
            self._commit_japanese(candidate)

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
