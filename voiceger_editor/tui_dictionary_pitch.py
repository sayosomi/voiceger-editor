"""Japanese Dictionary pitch-event presentation and keyboard adjustments.

The core keeps one accent phrase: internal '[' and ']' are pitch changes,
never separators. The UI does not use '/' or spaces as internal boundaries.
"""

from __future__ import annotations

from typing import Sequence

from .pronunciation import (
    AccentPhrase, PitchEvent, Pronunciation, format_pronunciation,
)
from .tui_display import _japanese_mora_tokens


def format_dictionary_pitch(
    morae: Sequence[str], accent: int, events: Sequence[PitchEvent] = (),
) -> str:
    if not events:
        return " ".join(_japanese_mora_tokens(morae, accent or len(morae)))
    phrase = AccentPhrase(tuple(morae), accent, tuple(events))
    return format_pronunciation(Pronunciation(phrases=(phrase,)))


def move_pitch_marker(
    morae: Sequence[str],
    accent: int,
    events: Sequence[PitchEvent],
    cursor: int,
    direction: int,
) -> tuple[int, tuple[PitchEvent, ...], bool]:
    """Move one selected marker without crossing another marker or the final mora."""
    if not events:
        visual = accent or len(morae)
        target = min(len(morae), max(1, visual + direction))
        return target, (), target != visual
    if not 1 <= cursor < len(events):
        return accent, tuple(events), False
    updated = list(events)
    marker = updated[cursor]
    updated[cursor] = PitchEvent(marker.after_mora + direction, marker.symbol)
    try:
        candidate = AccentPhrase(tuple(morae), next(
            (event.after_mora for event in updated if event.symbol == "]"),
            len(morae),
        ), tuple(updated))
    except ValueError:
        return accent, tuple(events), False
    return candidate.accent, candidate.pitch_events or (), True


def append_pitch_peak(
    morae: Sequence[str],
    accent: int,
    events: Sequence[PitchEvent],
) -> tuple[int, tuple[PitchEvent, ...]]:
    """Append a rise/fall pair where there is room for a final unmarked mora."""
    count = len(morae)
    if events:
        updated = list(events)
    else:
        if accent < 2 or accent >= count:
            raise ValueError("Move the first accent inside the word before adding a peak.")
        updated = [PitchEvent(1, "["), PitchEvent(accent, "]")]
    last = updated[-1].after_mora
    if last + 2 >= count:
        raise ValueError("No space remains for another peak before the final mora.")
    updated.extend((PitchEvent(last + 1, "["), PitchEvent(last + 2, "]")))
    AccentPhrase(tuple(morae), accent, tuple(updated))
    return accent, tuple(updated)


def remove_pitch_peak(
    accent: int,
    events: Sequence[PitchEvent],
    cursor: int,
) -> tuple[int, tuple[PitchEvent, ...]]:
    if not events or len(events) <= 2:
        raise ValueError("There is no additional peak to remove.")
    if cursor < 2:
        raise ValueError("Select an additional peak with M before removing it.")
    start = 2 + 2 * ((cursor - 2) // 2)
    updated = tuple(event for index, event in enumerate(events)
                    if index not in {start, start + 1})
    if len(updated) == 2:
        return accent, ()
    return accent, updated
