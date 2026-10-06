"""Frontend-neutral Read/Write core for versioned batch recipe files."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence, TYPE_CHECKING

from .caption_batch import CaptionBatch, CaptionBatchItem
from .english_stress import normalize_english_phonemes
from .mixed_language import resolve_japanese_segment_terminator
from .pronunciation import format_pronunciation, parse_pronunciation
from .session import UtteranceSession
from .settings import Settings, SettingsError
from .styles import VoicegerStyle, get_style
from .voicevox_api_models import AudioQuery, VoicegerSegment
from .voicevox_query import (
    accent_phrases_to_pronunciation,
    build_audio_query,
    pronunciation_punctuation,
    pronunciation_to_accent_phrases,
)

if TYPE_CHECKING:
    from .voiceger_adapter import VoicegerAdapter


SCHEMA_VERSION = 1
RECOMMENDED_SUFFIX = ".voiceger.json"
_SUPPORTED_SECTION_LANGUAGES = frozenset({"ja", "en", "zh", "ko", "auto"})


class BatchRecipeError(ValueError):
    """Raised when a batch recipe cannot be validated, read, or written."""


@dataclass(frozen=True)
class _StyleRecipe:
    id: int
    name: str
    reference_filename: str
    prompt_text: str


@dataclass(frozen=True)
class _SynthesisRecipe:
    style: _StyleRecipe
    speed: float
    top_k: int
    top_p: float
    temperature: float


@dataclass(frozen=True)
class _SectionRecipe:
    language: str
    text: str
    pronunciation: str | None = None
    phonemes: tuple[str, ...] | None = None


@dataclass(frozen=True)
class _ItemRecipe:
    item_id: str
    caption: str
    included: bool
    take_count: int | None
    synthesis: _SynthesisRecipe
    sections: tuple[_SectionRecipe, ...]


@dataclass(frozen=True)
class _BatchRecipe:
    take_count: int
    items: tuple[_ItemRecipe, ...]


def _fail(path: str, message: str) -> BatchRecipeError:
    return BatchRecipeError(f"{path}: {message}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in pairs:
        if key in values:
            raise BatchRecipeError(f"duplicate JSON object key {key!r}")
        values[key] = value
    return values


def _require_object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise _fail(path, "must be a JSON object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    path: str,
    required: Sequence[str],
) -> None:
    required_set = set(required)
    actual = set(value)
    missing = sorted(required_set - actual)
    unknown = sorted(actual - required_set)
    if missing:
        names = ", ".join(repr(name) for name in missing)
        raise _fail(path, f"missing field(s): {names}")
    if unknown:
        names = ", ".join(repr(name) for name in unknown)
        raise _fail(path, f"unknown field(s): {names}")


def _require_string(value: Any, path: str, *, single_line: bool = False) -> str:
    if not isinstance(value, str):
        raise _fail(path, "must be a string")
    if not value or not value.strip():
        raise _fail(path, "must not be empty")
    if single_line and ("\n" in value or "\r" in value):
        raise _fail(path, "must contain exactly one line")
    return value


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise _fail(path, "must be a boolean")
    return value


def _require_take_count(value: Any, path: str, *, nullable: bool) -> int | None:
    if value is None:
        if nullable:
            return None
        raise _fail(path, "must be an integer from 1 through 100")
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(path, "must be an integer from 1 through 100")
    if not 1 <= value <= 100:
        raise _fail(path, "must be an integer from 1 through 100")
    return value


def _parse_style(value: Any, path: str) -> _StyleRecipe:
    obj = _require_object(value, path)
    _require_exact_keys(
        obj,
        path=path,
        required=("id", "name", "reference_filename", "prompt_text"),
    )
    style_id = obj["id"]
    if isinstance(style_id, bool) or not isinstance(style_id, int) or style_id <= 0:
        raise _fail(f"{path}.id", "must be a positive integer")
    name = _require_string(obj["name"], f"{path}.name")
    reference_filename = _require_string(
        obj["reference_filename"],
        f"{path}.reference_filename",
    )
    if "/" in reference_filename or "\\" in reference_filename:
        raise _fail(
            f"{path}.reference_filename",
            "must be a reference filename, not a path",
        )
    prompt_text = _require_string(obj["prompt_text"], f"{path}.prompt_text")
    return _StyleRecipe(
        id=style_id,
        name=name,
        reference_filename=reference_filename,
        prompt_text=prompt_text,
    )


def _parse_synthesis(value: Any, path: str) -> _SynthesisRecipe:
    obj = _require_object(value, path)
    _require_exact_keys(
        obj,
        path=path,
        required=("style", "speed", "top_k", "top_p", "temperature"),
    )
    style = _parse_style(obj["style"], f"{path}.style")
    try:
        validated = Settings(
            style_id=style.id,
            speed=obj["speed"],
            top_k=obj["top_k"],
            top_p=obj["top_p"],
            temperature=obj["temperature"],
        )
    except SettingsError as exc:
        raise _fail(path, str(exc)) from exc
    return _SynthesisRecipe(
        style=style,
        speed=validated.speed,
        top_k=validated.top_k,
        top_p=validated.top_p,
        temperature=validated.temperature,
    )


def _parse_section(value: Any, path: str) -> _SectionRecipe:
    obj = _require_object(value, path)
    language = obj.get("language")
    if not isinstance(language, str) or language not in _SUPPORTED_SECTION_LANGUAGES:
        supported = ", ".join(sorted(_SUPPORTED_SECTION_LANGUAGES))
        raise _fail(
            f"{path}.language",
            f"must be one of: {supported}",
        )

    if language == "ja":
        _require_exact_keys(
            obj,
            path=path,
            required=("language", "text", "pronunciation"),
        )
        text = _require_string(obj["text"], f"{path}.text", single_line=True)
        source = _require_string(
            obj["pronunciation"],
            f"{path}.pronunciation",
            single_line=True,
        )
        try:
            pronunciation = format_pronunciation(parse_pronunciation(source))
        except (TypeError, ValueError) as exc:
            raise _fail(f"{path}.pronunciation", str(exc)) from exc
        return _SectionRecipe(
            language="ja",
            text=text,
            pronunciation=pronunciation,
        )

    if language == "en":
        _require_exact_keys(
            obj,
            path=path,
            required=("language", "text", "phonemes"),
        )
        text = _require_string(obj["text"], f"{path}.text", single_line=True)
        raw_phonemes = obj["phonemes"]
        if not isinstance(raw_phonemes, list):
            raise _fail(f"{path}.phonemes", "must be a JSON array")
        try:
            phonemes = tuple(normalize_english_phonemes(raw_phonemes))
        except (TypeError, ValueError) as exc:
            raise _fail(f"{path}.phonemes", str(exc)) from exc
        return _SectionRecipe(
            language="en",
            text=text,
            phonemes=phonemes,
        )

    _require_exact_keys(
        obj,
        path=path,
        required=("language", "text"),
    )
    text = _require_string(obj["text"], f"{path}.text", single_line=True)
    return _SectionRecipe(language=language, text=text)


def _parse_item(value: Any, path: str) -> _ItemRecipe:
    obj = _require_object(value, path)
    _require_exact_keys(
        obj,
        path=path,
        required=(
            "id",
            "caption",
            "included",
            "take_count",
            "synthesis",
            "sections",
        ),
    )
    item_id = _require_string(obj["id"], f"{path}.id")
    caption = _require_string(obj["caption"], f"{path}.caption", single_line=True)
    included = _require_bool(obj["included"], f"{path}.included")
    take_count = _require_take_count(
        obj["take_count"],
        f"{path}.take_count",
        nullable=True,
    )
    synthesis = _parse_synthesis(obj["synthesis"], f"{path}.synthesis")
    raw_sections = obj["sections"]
    if not isinstance(raw_sections, list):
        raise _fail(f"{path}.sections", "must be a JSON array")
    if not raw_sections:
        raise _fail(
            f"{path}.sections",
            "must contain explicit prepared pronunciation/source sections",
        )
    sections = tuple(
        _parse_section(section, f"{path}.sections[{index}]")
        for index, section in enumerate(raw_sections)
    )
    return _ItemRecipe(
        item_id=item_id,
        caption=caption,
        included=included,
        take_count=take_count,
        synthesis=synthesis,
        sections=sections,
    )


def _parse_document(value: Any) -> _BatchRecipe:
    obj = _require_object(value, "$")
    _require_exact_keys(
        obj,
        path="$",
        required=("schema_version", "take_count", "items"),
    )
    schema_version = obj["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise _fail("$.schema_version", "must be an integer")
    if schema_version != SCHEMA_VERSION:
        raise _fail(
            "$.schema_version",
            f"unsupported schema version {schema_version!r}; expected {SCHEMA_VERSION}",
        )
    take_count = _require_take_count(
        obj["take_count"],
        "$.take_count",
        nullable=False,
    )
    assert take_count is not None
    raw_items = obj["items"]
    if not isinstance(raw_items, list):
        raise _fail("$.items", "must be a JSON array")
    items = tuple(
        _parse_item(item, f"$.items[{index}]")
        for index, item in enumerate(raw_items)
    )
    seen: set[str] = set()
    for item in items:
        if item.item_id in seen:
            raise _fail("$.items", f"duplicate item id {item.item_id!r}")
        seen.add(item.item_id)
    return _BatchRecipe(take_count=take_count, items=items)


def _style_payload(style: VoicegerStyle) -> dict[str, Any]:
    return {
        "id": style.id,
        "name": style.name,
        "reference_filename": style.filename,
        "prompt_text": style.prompt_text,
    }


def _pronunciation_from_accent_phrases(
    accent_phrases: Sequence[Any],
    *,
    punctuation: Sequence[Any] | None,
    terminator: str | None = None,
) -> str:
    try:
        pronunciation = accent_phrases_to_pronunciation(
            accent_phrases,
            punctuation=punctuation,
            terminator=terminator,
        )
        return format_pronunciation(pronunciation)
    except (TypeError, ValueError) as exc:
        raise BatchRecipeError(f"invalid Japanese pronunciation state: {exc}") from exc


def _sections_from_session(session: UtteranceSession) -> list[dict[str, Any]]:
    if not session.is_prepared:
        raise BatchRecipeError(
            f"Caption {session.caption!r} has no prepared pronunciation"
        )

    query = session.query
    if query.voicegerSegments is None:
        source_text = (
            session.pure_japanese_utterance_text
            or session.synthesis_source_text
        )
        pronunciation = _pronunciation_from_accent_phrases(
            query.accent_phrases,
            punctuation=query.pronunciationPunctuation,
        )
        return [
            {
                "language": "ja",
                "text": source_text,
                "pronunciation": pronunciation,
            }
        ]

    sections: list[dict[str, Any]] = []
    next_accent_phrase = 0
    for section_index, segment in enumerate(query.voicegerSegments):
        language = segment.language
        if language not in _SUPPORTED_SECTION_LANGUAGES:
            raise BatchRecipeError(
                f"section {section_index}: unsupported language {language!r}"
            )
        if not segment.text or not segment.text.strip():
            raise BatchRecipeError(
                f"section {section_index}: source text must not be empty"
            )

        if language == "ja":
            start = segment.accentPhraseStart
            count = segment.accentPhraseCount
            if (
                isinstance(start, bool)
                or not isinstance(start, int)
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count <= 0
            ):
                raise BatchRecipeError(
                    f"section {section_index}: Japanese section has invalid accent phrase references"
                )
            if start != next_accent_phrase:
                raise BatchRecipeError(
                    f"section {section_index}: Japanese accent phrase order is ambiguous"
                )
            end = start + count
            if end > len(query.accent_phrases):
                raise BatchRecipeError(
                    f"section {section_index}: Japanese accent phrase range is out of bounds"
                )
            pronunciation = _pronunciation_from_accent_phrases(
                query.accent_phrases[start:end],
                punctuation=segment.pronunciationPunctuation,
                terminator=resolve_japanese_segment_terminator(segment),
            )
            sections.append(
                {
                    "language": "ja",
                    "text": segment.text,
                    "pronunciation": pronunciation,
                }
            )
            next_accent_phrase = end
            continue

        if (
            segment.accentPhraseStart is not None
            or segment.accentPhraseCount is not None
        ):
            raise BatchRecipeError(
                f"section {section_index}: only Japanese sections may reference accent phrases"
            )

        if language == "en":
            if segment.phonemes is None:
                raise BatchRecipeError(
                    f"section {section_index}: English section has no explicit ARPAbet phonemes"
                )
            try:
                phonemes = normalize_english_phonemes(segment.phonemes)
            except ValueError as exc:
                raise BatchRecipeError(
                    f"section {section_index}: invalid English phonemes: {exc}"
                ) from exc
            sections.append(
                {
                    "language": "en",
                    "text": segment.text,
                    "phonemes": phonemes,
                }
            )
            continue

        if segment.phonemes is not None:
            raise BatchRecipeError(
                f"section {section_index}: only English sections may contain phonemes"
            )
        sections.append(
            {
                "language": language,
                "text": segment.text,
            }
        )

    if next_accent_phrase != len(query.accent_phrases):
        raise BatchRecipeError(
            "Japanese accent phrases are not fully represented by sections"
        )
    if not sections:
        raise BatchRecipeError("prepared query has no source sections")
    return sections


def _document_from_batch(batch: CaptionBatch) -> dict[str, Any]:
    if not isinstance(batch, CaptionBatch):
        raise TypeError("batch must be a CaptionBatch")

    items: list[dict[str, Any]] = []
    for item in batch:
        session = item.session
        settings = session.settings
        style = session.style
        items.append(
            {
                "id": item.item_id,
                "caption": item.caption,
                "included": item.included_for_generation,
                "take_count": item.take_count_override,
                "synthesis": {
                    "style": _style_payload(style),
                    "speed": settings.speed,
                    "top_k": settings.top_k,
                    "top_p": settings.top_p,
                    "temperature": settings.temperature,
                },
                "sections": _sections_from_session(session),
            }
        )

    document = {
        "schema_version": SCHEMA_VERSION,
        "take_count": batch.default_take_count,
        "items": items,
    }
    _parse_document(document)
    return document


def serialize_batch_recipe(batch: CaptionBatch) -> str:
    """Serialize a validated logical batch recipe as readable stable JSON."""

    document = _document_from_batch(batch)
    return json.dumps(
        document,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"


def _resolve_path(path: str | os.PathLike[str]) -> Path:
    try:
        raw = os.fspath(path)
    except TypeError as exc:
        raise BatchRecipeError("recipe path must be a filesystem path") from exc
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise BatchRecipeError("recipe path must be a non-empty filesystem path")
    try:
        return Path(raw).expanduser()
    except (RuntimeError, ValueError) as exc:
        raise BatchRecipeError(f"invalid recipe path: {exc}") from exc


def write_batch_recipe(
    path: str | os.PathLike[str],
    batch: CaptionBatch,
) -> Path:
    """Atomically write a validated batch recipe and return the target path."""

    target = _resolve_path(path)
    serialized = serialize_batch_recipe(batch)
    payload = serialized.encode("utf-8")
    temporary: Path | None = None

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    except OSError as exc:
        raise BatchRecipeError(f"{target}: could not write recipe: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    return target


def _load_document(path: Path) -> _BatchRecipe:
    try:
        contents = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise BatchRecipeError(f"{path}: recipe is not valid UTF-8") from exc
    except OSError as exc:
        raise BatchRecipeError(f"{path}: could not read recipe: {exc}") from exc

    try:
        raw = json.loads(contents, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise BatchRecipeError(
            f"{path}: malformed JSON at line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}"
        ) from exc
    except BatchRecipeError as exc:
        raise BatchRecipeError(f"{path}: {exc}") from exc

    try:
        return _parse_document(raw)
    except BatchRecipeError as exc:
        raise BatchRecipeError(f"{path}: {exc}") from exc


def _resolve_style(
    *,
    adapter: "VoicegerAdapter",
    recipe: _StyleRecipe,
    path: str,
) -> VoicegerStyle:
    try:
        style = get_style(adapter.voiceger_root, recipe.id)
    except (OSError, ValueError) as exc:
        raise _fail(
            path,
            f"required style/reference is unavailable: {exc}",
        ) from exc

    expected = (
        recipe.name,
        recipe.reference_filename,
        recipe.prompt_text,
    )
    actual = (
        style.name,
        style.filename,
        style.prompt_text,
    )
    if actual != expected:
        raise _fail(
            path,
            "style/reference identity does not match the installed Voiceger reference",
        )
    return style


def _build_query(
    sections: Sequence[_SectionRecipe],
    *,
    item_path: str,
) -> tuple[AudioQuery, str | None]:
    if len(sections) == 1 and sections[0].language == "ja":
        section = sections[0]
        assert section.pronunciation is not None
        try:
            pronunciation = parse_pronunciation(section.pronunciation)
            query = build_audio_query(
                pronunciation=pronunciation,
                output_sampling_rate=32000,
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            raise _fail(
                f"{item_path}.sections[0].pronunciation",
                f"could not reconstruct Japanese pronunciation: {exc}",
            ) from exc
        return query, section.text

    accent_phrases = []
    segments: list[VoicegerSegment] = []
    for index, section in enumerate(sections):
        section_path = f"{item_path}.sections[{index}]"
        if section.language == "ja":
            assert section.pronunciation is not None
            try:
                pronunciation = parse_pronunciation(section.pronunciation)
                phrases = pronunciation_to_accent_phrases(pronunciation)
            except (RuntimeError, TypeError, ValueError) as exc:
                raise _fail(
                    f"{section_path}.pronunciation",
                    f"could not reconstruct Japanese pronunciation: {exc}",
                ) from exc
            start = len(accent_phrases)
            accent_phrases.extend(phrases)
            segments.append(
                VoicegerSegment(
                    language="ja",
                    text=section.text,
                    accentPhraseStart=start,
                    accentPhraseCount=len(phrases),
                    pronunciationTerminator=pronunciation.terminator or "",
                    pronunciationPunctuation=pronunciation_punctuation(
                        pronunciation
                    ),
                )
            )
        elif section.language == "en":
            assert section.phonemes is not None
            segments.append(
                VoicegerSegment(
                    language="en",
                    text=section.text,
                    phonemes=list(section.phonemes),
                )
            )
        else:
            segments.append(
                VoicegerSegment(
                    language=section.language,
                    text=section.text,
                )
            )

    query = AudioQuery(
        accent_phrases=accent_phrases,
        speedScale=1,
        pitchScale=0,
        intonationScale=1,
        volumeScale=1,
        prePhonemeLength=0.1,
        postPhonemeLength=0.1,
        pauseLength=None,
        pauseLengthScale=1,
        outputSamplingRate=32000,
        outputStereo=False,
        kana=None,
        voicegerSegments=segments,
    )
    return query, None


def read_batch_recipe(
    path: str | os.PathLike[str],
    *,
    adapter: "VoicegerAdapter",
    runtime_settings: Settings,
) -> CaptionBatch:
    """Read and fully validate a recipe before returning replacement batch state.

    runtime_settings supplies preferences intentionally excluded from the
    recipe, such as output directory and TXT/LAB sidecar choices.
    """

    if not isinstance(runtime_settings, Settings):
        raise TypeError("runtime_settings must be a Settings instance")

    source = _resolve_path(path)
    recipe = _load_document(source)

    prepared: list[
        tuple[_ItemRecipe, AudioQuery, str | None, Settings]
    ] = []
    for index, item in enumerate(recipe.items):
        item_path = f"$.items[{index}]"
        _resolve_style(
            adapter=adapter,
            recipe=item.synthesis.style,
            path=f"{item_path}.synthesis.style",
        )
        query, pure_japanese_text = _build_query(
            item.sections,
            item_path=item_path,
        )
        effective_take_count = (
            item.take_count
            if item.take_count is not None
            else recipe.take_count
        )
        try:
            item_settings = replace(
                runtime_settings,
                take_count=effective_take_count,
                style_id=item.synthesis.style.id,
                speed=item.synthesis.speed,
                top_k=item.synthesis.top_k,
                top_p=item.synthesis.top_p,
                temperature=item.synthesis.temperature,
            )
        except SettingsError as exc:
            raise _fail(f"{item_path}.synthesis", str(exc)) from exc
        prepared.append(
            (item, query, pure_japanese_text, item_settings)
        )

    created_sessions: list[UtteranceSession] = []
    try:
        batch_items: list[CaptionBatchItem] = []
        for item, query, pure_japanese_text, item_settings in prepared:
            session = UtteranceSession(
                adapter=adapter,
                caption=item.caption,
                query=query,
                settings=item_settings,
                pure_japanese_utterance_text=pure_japanese_text,
            )
            created_sessions.append(session)
            batch_items.append(
                CaptionBatchItem(
                    session,
                    item_id=item.item_id,
                    included_for_generation=item.included,
                    take_count_override=item.take_count,
                )
            )
        return CaptionBatch(
            default_take_count=recipe.take_count,
            items=batch_items,
        )
    except Exception as exc:
        for session in created_sessions:
            session.close()
        if isinstance(exc, BatchRecipeError):
            raise
        raise BatchRecipeError(
            f"{source}: could not reconstruct batch state: {exc}"
        ) from exc
