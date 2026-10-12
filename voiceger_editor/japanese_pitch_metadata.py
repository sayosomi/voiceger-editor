"""Versioned Voiceger-only Japanese dictionary pitch metadata.

The canonical VOICEVOX word JSON and compiled OpenJTalk CSV never contain
these additional events.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import hashlib
import json
from typing import Any
from uuid import UUID

from .pronunciation import AccentPhrase, PitchEvent


METADATA_VERSION = 1
METADATA_FILENAME = "user_dict_pitch_events.json"


def normalize_word_pitch_events(
    word: Any,
    events: Sequence[PitchEvent | Mapping[str, Any]],
    morae: Sequence[str],
) -> tuple[PitchEvent, ...]:
    """Validate one complete multi-peak event sequence for a canonical word."""
    if isinstance(events, (str, bytes)) or not isinstance(events, (tuple, list)):
        raise ValueError("Japanese pitch events must be a sequence")
    normalized: list[PitchEvent] = []
    for value in events:
        if isinstance(value, PitchEvent):
            normalized.append(value)
        elif isinstance(value, Mapping) and set(value) == {"afterMora", "symbol"}:
            normalized.append(PitchEvent(value["afterMora"], value["symbol"]))
        else:
            raise ValueError("invalid Japanese pitch event")
    if not normalized:
        return ()
    if len(morae) != word.mora_count or "".join(morae) != word.pronunciation:
        raise ValueError("Japanese dictionary mora count does not match reading")
    AccentPhrase(tuple(morae), word.accent_type, tuple(normalized))
    return tuple(normalized)


def serialize_pitch_metadata(
    words: Mapping[str, Any],
    events_by_uuid: Mapping[str, tuple[PitchEvent, ...]],
    dictionary_payload: bytes,
) -> bytes:
    """Bind strict extra events to the exact canonical base dictionary bytes."""
    payload = {
        "version": METADATA_VERSION,
        "dictionarySha256": hashlib.sha256(dictionary_payload).hexdigest(),
        "entries": {
            word_uuid: {
                "reading": words[word_uuid].pronunciation,
                "moraCount": words[word_uuid].mora_count,
                "events": [
                    {"afterMora": event.after_mora, "symbol": event.symbol}
                    for event in events
                ],
            }
            for word_uuid, events in events_by_uuid.items()
        },
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def parse_pitch_metadata(
    raw: Mapping[str, Any],
    words: Mapping[str, Any],
    dictionary_payload: bytes,
    morae_for_word: Callable[[Any], Sequence[str]],
) -> dict[str, tuple[PitchEvent, ...]]:
    """Fail closed on stale, unpaired or malformed metadata."""
    if not isinstance(raw, Mapping) or set(raw) != {
        "version", "dictionarySha256", "entries"
    }:
        raise ValueError("invalid Japanese pitch metadata shape")
    if type(raw["version"]) is not int or raw["version"] != METADATA_VERSION:
        raise ValueError("unsupported Japanese pitch metadata version")
    if raw["dictionarySha256"] != hashlib.sha256(dictionary_payload).hexdigest():
        raise ValueError("Japanese pitch metadata does not match dictionary")
    if not isinstance(raw["entries"], dict):
        raise ValueError("Japanese pitch metadata entries must be an object")
    result: dict[str, tuple[PitchEvent, ...]] = {}
    for raw_uuid, record in raw["entries"].items():
        word_uuid = str(UUID(raw_uuid))
        if word_uuid in result or word_uuid not in words:
            raise ValueError("Japanese pitch metadata has unknown/duplicate UUID")
        word = words[word_uuid]
        if not isinstance(record, dict) or set(record) != {
            "reading", "moraCount", "events"
        }:
            raise ValueError("invalid Japanese pitch metadata record")
        if record["reading"] != word.pronunciation or (
            type(record["moraCount"]) is not int
            or record["moraCount"] != word.mora_count
        ):
            raise ValueError("Japanese pitch metadata reading/mora mismatch")
        events = normalize_word_pitch_events(
            word, record["events"], morae_for_word(word)
        )
        if not events:
            raise ValueError("empty Japanese pitch metadata record")
        result[word_uuid] = events
    if not result:
        raise ValueError("empty Japanese pitch metadata must not be stored")
    return result
