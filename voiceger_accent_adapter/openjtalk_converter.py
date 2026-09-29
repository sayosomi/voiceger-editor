"""Convert OpenJTalk frontend output to editable pronunciation notation.

The converter operates on pyopenjtalk.run_frontend() output rather than on
Voiceger's postprocessed phone tokens. That keeps the public pronunciation
representation independent of Voiceger's current symbol vocabulary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .pronunciation import AccentPhrase, Pronunciation, format_pronunciation
from .runtime_locks import OPENJTALK_LOCK


_SMALL_KANA = frozenset("ァィゥェォャュョヮぁぃぅぇぉゃゅょゎ")
_SENTENCE_END = {
    "。": "。",
    ".": "。",
    "！": "！",
    "!": "！",
    "？": "？",
    "?": "？",
}


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
) -> Pronunciation:
    """Convert pyopenjtalk.run_frontend() features to Pronunciation.

    Non-symbol nodes are grouped into accent phrases using chain_flag:
    chain_flag == 1 continues the previous accent phrase; any other value
    starts a new one. Symbol nodes end the current phrase. Sentence-final
    punctuation is preserved as a normalized terminator.
    """

    phrases: list[AccentPhrase] = []
    current: list[Mapping[str, Any]] = []
    terminator: str | None = None

    def flush() -> None:
        nonlocal current
        if current:
            phrases.append(_phrase_from_nodes(current))
            current = []

    for node in features:
        pos = node.get("pos")
        if pos == "記号":
            flush()
            symbol = node.get("string")
            if isinstance(symbol, str) and symbol in _SENTENCE_END:
                terminator = _SENTENCE_END[symbol]
            continue

        chain_flag = node.get("chain_flag")
        if current and chain_flag != 1:
            flush()
        current.append(node)

    flush()

    if not phrases:
        raise OpenJTalkConversionError(
            "OpenJTalk produced no pronounceable accent phrases"
        )

    return Pronunciation(tuple(phrases), terminator)


def text_to_pronunciation(
    text: str,
    *,
    run_frontend: Callable[[str], Sequence[Mapping[str, Any]]] | None = None,
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
    return frontend_features_to_pronunciation(features)


def text_to_pronunciation_string(
    text: str,
    *,
    run_frontend: Callable[[str], Sequence[Mapping[str, Any]]] | None = None,
) -> str:
    """Analyze text and serialize it to editable pronunciation notation."""

    return format_pronunciation(
        text_to_pronunciation(text, run_frontend=run_frontend)
    )
