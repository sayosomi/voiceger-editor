"""Convert OpenJTalk frontend output to editable pronunciation notation.

The converter operates on pyopenjtalk.run_frontend() output rather than on
Voiceger's postprocessed phone tokens. That keeps the public pronunciation
representation independent of Voiceger's current symbol vocabulary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .pronunciation import (
    AccentPhrase,
    Pronunciation,
    PronunciationPunctuation,
    canonicalize_punctuation,
    format_pronunciation,
)
from .runtime_locks import OPENJTALK_LOCK
from .japanese_dictionary_pitch_matching import (
    PitchWordMatch, build_matched_phrase, match_pitch_words,
)
import logging

_LOG = logging.getLogger(__name__)


_SMALL_KANA = frozenset("ァィゥェォャュョヮぁぃぅぇぉゃゅょゎ")
class OpenJTalkConversionError(ValueError):
    """Raised when OpenJTalk frontend data cannot be converted safely."""


def _split_morae(reading: str) -> tuple[str, ...]:
    morae: list[str] = []

    for ch in reading:
        if ch == "’":
            # pyopenjtalk itself removes this marker in g2p(..., kana=True).
            continue
        if ch in _SMALL_KANA:
            if not morae:
                raise OpenJTalkConversionError(
                    f"small kana cannot start a reading: {reading!r}"
                )
            morae[-1] += ch
        else:
            morae.append(ch)

    if not morae:
        raise OpenJTalkConversionError("OpenJTalk returned an empty reading")
    return tuple(morae)


def _node_reading(node: Mapping[str, Any]) -> str:
    pron = node.get("pron")
    if not isinstance(pron, str) or not pron or pron == "*":
        raise OpenJTalkConversionError(
            f"OpenJTalk node has no usable pronunciation: {node!r}"
        )
    return pron.replace("’", "")


def _phrase_from_nodes(nodes: Sequence[Mapping[str, Any]]) -> AccentPhrase:
    if not nodes:
        raise OpenJTalkConversionError("empty OpenJTalk accent phrase")

    reading = "".join(_node_reading(node) for node in nodes)
    morae = _split_morae(reading)

    raw_acc = nodes[0].get("acc")
    if not isinstance(raw_acc, int):
        raise OpenJTalkConversionError(
            f"OpenJTalk node has invalid acc value: {raw_acc!r}"
        )

    # In OpenJTalk's NJD representation, 0 denotes a heiban accent type.
    # The editable VOICEVOX-style notation requires exactly one accent
    # position, so canonicalize heiban to the last mora (e.g. アメ').
    accent = len(morae) if raw_acc <= 0 else min(raw_acc, len(morae))

    return AccentPhrase(morae=morae, accent=accent)


def frontend_features_to_pronunciation(
    features: Sequence[Mapping[str, Any]],
    *,
    pitch_words: Mapping[str, tuple[Any, Sequence[Any]]] | None = None,
) -> Pronunciation:
    """Convert frontend nodes and apply only safely aligned dictionary peaks."""
    active = list(match_pitch_words(features, pitch_words)) if pitch_words else []

    while True:
        items: list[AccentPhrase | PronunciationPunctuation] = []
        current: list[tuple[int, Mapping[str, Any]]] = []
        unsafe: list[PitchWordMatch] = []

        def flush() -> None:
            nonlocal current
            if not current:
                return
            span_start = current[0][0]
            span_end = current[-1][0] + 1
            inside = [
                match for match in active
                if span_start <= match.start and match.end <= span_end
            ]
            if inside:
                try:
                    items.append(build_matched_phrase(current, inside))
                except ValueError:
                    unsafe.extend(inside)
            else:
                items.append(_phrase_from_nodes([node for _, node in current]))
            current = []

        for index, node in enumerate(features):
            if node.get("pos") == "記号":
                flush()
                symbol = node.get("string")
                punctuation = (
                    canonicalize_punctuation(symbol)
                    if isinstance(symbol, str)
                    else None
                )
                if punctuation is not None:
                    items.append(PronunciationPunctuation(punctuation))
                continue

            internal_boundary = any(
                match.start < index < match.end for match in active
            )
            if current and node.get("chain_flag") != 1 and not internal_boundary:
                flush()
            current.append((index, node))

        flush()
        if unsafe:
            for match in unsafe:
                _LOG.warning(
                    "Skipping unsafe Japanese dictionary pitch match for UUID %s",
                    match.word_uuid,
                )
            active = [match for match in active if match not in unsafe]
            continue

        if not any(isinstance(item, AccentPhrase) for item in items):
            raise OpenJTalkConversionError(
                "OpenJTalk produced no pronounceable accent phrases"
            )
        return Pronunciation(items=tuple(items))


def text_to_pronunciation(
    text: str,
    *,
    run_frontend: Callable[[str], Sequence[Mapping[str, Any]]] | None = None,
    pitch_words: Mapping[str, tuple[Any, Sequence[Any]]] | None = None,
) -> Pronunciation:
    """Analyze Japanese text with pyopenjtalk and return Pronunciation.

    run_frontend is injectable so the conversion logic can be tested without
    pyopenjtalk or Voiceger installed.
    """

    if run_frontend is None:
        try:
            import pyopenjtalk
        except ImportError as exc:
            raise RuntimeError(
                "pyopenjtalk is required for automatic pronunciation analysis; "
                "run this from Voiceger's Python environment or install pyopenjtalk"
            ) from exc
        run_frontend = pyopenjtalk.run_frontend

    with OPENJTALK_LOCK:
        features = run_frontend(text)
    return frontend_features_to_pronunciation(features, pitch_words=pitch_words)


def text_to_pronunciation_string(
    text: str,
    *,
    run_frontend: Callable[[str], Sequence[Mapping[str, Any]]] | None = None,
) -> str:
    """Analyze text and serialize it to editable pronunciation notation."""

    return format_pronunciation(
        text_to_pronunciation(text, run_frontend=run_frontend)
    )
