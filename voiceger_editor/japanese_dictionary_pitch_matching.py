"""Safely align dictionary multi-peak events to OpenJTalk morphology.

Only complete, consecutive frontend nodes are eligible. No raw substring
replacement is performed and unrepresentable merged contours are discarded.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Mapping, Sequence

from .openjtalk_dictionary import normalize_surface
from .pronunciation import AccentPhrase, PitchEvent

_LOG = logging.getLogger(__name__)
_SMALL_KANA = frozenset("ァィゥェォャュョヮぁぃぅぇぉゃゅょゎ")


@dataclass(frozen=True)
class PitchWordMatch:
    start: int
    end: int
    word_uuid: str
    events: tuple[PitchEvent, ...]


def _morae(reading: str) -> tuple[str, ...]:
    parts: list[str] = []
    for ch in reading.replace("’", ""):
        if ch in _SMALL_KANA:
            if not parts:
                raise ValueError("incomplete mora at node boundary")
            parts[-1] += ch
        else:
            parts.append(ch)
    if not parts:
        raise ValueError("empty reading")
    return tuple(parts)


def _node_morae(node: Mapping[str, Any]) -> tuple[str, ...]:
    reading = node.get("pron")
    if not isinstance(reading, str) or reading in {"", "*"}:
        raise ValueError("unknown frontend reading")
    morae = _morae(reading)
    count = node.get("mora_size")
    if type(count) is not int or count != len(morae):
        raise ValueError("frontend mora alignment mismatch")
    return morae


def match_pitch_words(
    features: Sequence[Mapping[str, Any]],
    pitch_words: Mapping[str, tuple[Any, Sequence[PitchEvent]]],
) -> tuple[PitchWordMatch, ...]:
    """Select left-to-right longest valid nonoverlapping node-aligned words.

    Same-length competing entries with different word types or event sequences
    are ambiguous and must not acquire an arbitrary accent.
    """
    words: dict[str, list[tuple[str, Any, tuple[PitchEvent, ...], tuple[str, ...]]]] = {}
    for word_uuid, (word, raw_events) in pitch_words.items():
        events = tuple(raw_events)
        if not events:
            continue
        try:
            word_morae = _morae(word.pronunciation)
            if len(word_morae) != word.mora_count:
                continue
            AccentPhrase(word_morae, word.accent_type or len(word_morae), events)
        except (AttributeError, TypeError, ValueError):
            continue
        surface = normalize_surface(word.surface)
        words.setdefault(surface, []).append((word_uuid, word, events, word_morae))

    selected: list[PitchWordMatch] = []
    index = 0
    while index < len(features):
        node = features[index]
        if node.get("pos") == "記号":
            index += 1
            continue

        candidates: list[tuple[int, str, Any, tuple[PitchEvent, ...]]] = []
        surface = ""
        reading_morae: tuple[str, ...] = ()
        for end in range(index + 1, len(features) + 1):
            current = features[end - 1]
            if current.get("pos") == "記号":
                break
            token = current.get("string")
            if not isinstance(token, str) or not token or token == "*":
                break
            try:
                node_morae = _node_morae(current)
            except ValueError:
                break
            surface += normalize_surface(token)
            reading_morae += node_morae
            if not any(key.startswith(surface) for key in words):
                break
            for word_uuid, word, events, expected_morae in words.get(surface, ()):
                if reading_morae == expected_morae:
                    candidates.append((end, word_uuid, word, events))

        if not candidates:
            index += 1
            continue

        longest = max(end for end, _, _, _ in candidates)
        finalists = [value for value in candidates if value[0] == longest]
        identities = {
            (word.context_id, word.part_of_speech,
             word.part_of_speech_detail_1, word.part_of_speech_detail_2,
             tuple(events))
            for _, _, word, events in finalists
        }
        if len(identities) != 1:
            _LOG.warning(
                "Ambiguous Japanese dictionary pitch entries at frontend node %d",
                index,
            )
            index += 1
            continue

        _, word_uuid, _, events = min(finalists, key=lambda item: item[1])
        selected.append(PitchWordMatch(index, longest, word_uuid, events))
        index = longest

    return tuple(selected)


def _legacy_events(phrase: AccentPhrase, offset: int) -> list[PitchEvent]:
    count = len(phrase.morae)
    result: list[PitchEvent] = []
    if count > 1:
        result.append(PitchEvent(offset + 1, "]" if phrase.accent == 1 else "["))
    if 1 < phrase.accent < count:
        result.append(PitchEvent(offset + phrase.accent, "]"))
    return result


def build_matched_phrase(
    indexed_nodes: Sequence[tuple[int, Mapping[str, Any]]],
    matches: Sequence[PitchWordMatch],
) -> AccentPhrase:
    """Combine exact word events with otherwise unchanged frontend contours.

    Raises ValueError if a contour cannot be represented losslessly by the
    current canonical AccentPhrase model. The caller must then skip matches.
    """
    from .openjtalk_converter import _phrase_from_nodes

    if not matches:
        return _phrase_from_nodes([node for _, node in indexed_nodes])

    node_morae = [_node_morae(node) for _, node in indexed_nodes]
    morae = tuple(mora for part in node_morae for mora in part)
    mora_offset: dict[int, int] = {}
    offset = 0
    for (node_index, _), part in zip(indexed_nodes, node_morae):
        mora_offset[node_index] = offset
        offset += len(part)
    mora_offset[indexed_nodes[-1][0] + 1] = offset

    legacy: list[PitchEvent] = []
    old_phrase_start = 0
    for local_index in range(1, len(indexed_nodes) + 1):
        if (local_index < len(indexed_nodes)
                and indexed_nodes[local_index][1].get("chain_flag") == 1):
            continue
        old_nodes = indexed_nodes[old_phrase_start:local_index]
        old_phrase = _phrase_from_nodes([node for _, node in old_nodes])
        legacy.extend(_legacy_events(
            old_phrase, mora_offset[old_nodes[0][0]]
        ))
        old_phrase_start = local_index

    spans = [
        (mora_offset[match.start], mora_offset[match.end], match)
        for match in matches
    ]
    events = [
        event for event in legacy
        if not any(start < event.after_mora <= end for start, end, _ in spans)
    ]
    for start, _, match in spans:
        events.extend(
            PitchEvent(start + event.after_mora, event.symbol)
            for event in match.events
        )
    events.sort(key=lambda event: event.after_mora)
    first_fall = next(
        (event.after_mora for event in events if event.symbol == "]"),
        len(morae),
    )
    return AccentPhrase(morae, first_fall, tuple(events))
