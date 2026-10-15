"""Mixed-language query construction for Voiceger's multilingual frontend."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from unicodedata import category
from dataclasses import dataclass
from typing import Any, List, Optional

from .english_stress import normalize_english_phonemes
from .openjtalk_converter import text_to_pronunciation
from .pronunciation import Pronunciation
from .voicevox_api_models import AudioQuery, VoicegerSegment
from .voiceger_tokens import pronunciation_to_voiceger_tokens
from .voicevox_query import (
    accent_phrases_to_pronunciation,
    build_audio_query,
    pronunciation_punctuation,
    pronunciation_to_accent_phrases,
    pronunciation_pitch_events,
    pitch_events_for_range,
)


@dataclass(frozen=True)
class DetectedSegment:
    language: str
    text: str


@dataclass(frozen=True)
class MixedSynthesisPlan:
    text: str
    text_language: str
    japanese_overrides: tuple[tuple[str, list[str]], ...]
    english_overrides: tuple[tuple[str, list[str]], ...]


def _character_language(char: str) -> str | None:
    """Classify supported writing systems; leave digits and separators neutral."""

    code = ord(char)
    if "A" <= char <= "Z" or "a" <= char <= "z":
        return "en"
    if (
        0x3040 <= code <= 0x30FF  # Hiragana / Katakana
        or 0x31F0 <= code <= 0x31FF  # Katakana phonetic extensions
        or 0xFF65 <= code <= 0xFF9F  # Halfwidth katakana
        or 0x3400 <= code <= 0x9FFF  # CJK ideographs
        or 0xF900 <= code <= 0xFAFF  # CJK compatibility ideographs
        or 0x20000 <= code <= 0x323AF  # CJK ideograph extensions
        or 0x1B000 <= code <= 0x1B16F  # Historic Japanese kana
        or char in "々〆ヶ〇〻"
    ):
        return "ja"
    if category(char).startswith("L"):
        raise ValueError(f"Unsupported writing system in Caption: {char!r}")
    return None


def detect_language_segments(text: str) -> List[DetectedSegment]:
    """Split losslessly into JA/EN runs without using language inference."""

    if not text or not text.strip():
        raise ValueError("text must not be empty")

    result: List[DetectedSegment] = []
    neutral = ""
    for char in text:
        language = _character_language(char)
        if language is None:
            neutral += char
            continue
        if result and result[-1].language == language:
            previous = result[-1]
            result[-1] = DetectedSegment(language, previous.text + neutral + char)
        elif result:
            # Separators between different scripts belong to the preceding run.
            previous = result[-1]
            result[-1] = DetectedSegment(previous.language, previous.text + neutral)
            result.append(DetectedSegment(language, char))
        else:
            # Leading separators belong to the first pronounceable run.
            result.append(DetectedSegment(language, neutral + char))
        neutral = ""

    if result:
        previous = result[-1]
        result[-1] = DetectedSegment(previous.language, previous.text + neutral)
    elif any(char.isdecimal() for char in text):
        result.append(DetectedSegment("ja", text))
    else:
        raise ValueError("Caption contains no pronounceable Japanese or English text")

    assert "".join(segment.text for segment in result) == text
    return result


def japanese_dictionary_pitch_options(adapter: Any) -> dict[str, Any]:
    """Opt in to dictionary peaks only when the adapter has an actual snapshot."""
    dictionary = getattr(adapter, "user_dictionary", None)
    snapshot = getattr(dictionary, "japanese_multi_peak_snapshot", None)
    words = snapshot() if callable(snapshot) else {}
    return {"japanese_pitch_words": words} if words else {}


def is_pure_japanese(segments: Sequence[DetectedSegment]) -> bool:
    return bool(segments) and all(segment.language == "ja" for segment in segments)


def resolve_japanese_segment_terminator(
    segment: VoicegerSegment,
) -> str | None:
    """Resolve explicit pronunciation state or a legacy source-text ending."""

    explicit = segment.pronunciationTerminator
    if explicit is not None:
        return explicit or None

    if segment.text.endswith(("。", ".")):
        return "。"
    if segment.text.endswith(("？", "?")):
        return "？"
    if segment.text.endswith(("！", "!")):
        return "！"
    return None


def build_mixed_audio_query(
    text: str,
    *,
    segments: Optional[Sequence[DetectedSegment]] = None,
    english_g2p: Optional[Callable[[str], Sequence[str]]] = None,
    output_sampling_rate: int = 32000,
    japanese_pitch_words: dict[str, tuple[Any, Sequence[Any]]] | None = None,
) -> AudioQuery:
    """Build AudioQuery plus voicegerSegments for mixed-language input."""

    detected = list(segments) if segments is not None else detect_language_segments(text)
    if not detected or any(segment.language not in {"ja", "en"} or not segment.text for segment in detected):
        raise ValueError("Pronunciation segments must contain only nonempty ja/en sections")
    if not text or not text.strip():
        raise ValueError("text must not be empty")
    # Preserve the historical full-source English G2P path even when callers
    # supply legacy pre-normalized English section hints.
    if all(segment.language == "en" for segment in detected):
        detected = [DetectedSegment("en", text)]
    elif "".join(segment.text for segment in detected) != text:
        raise ValueError("Pronunciation segments must reconstruct the complete Caption")

    def prepare_japanese(value: str) -> Pronunciation:
        if japanese_pitch_words:
            return text_to_pronunciation(value, pitch_words=japanese_pitch_words)
        return text_to_pronunciation(value)
    if is_pure_japanese(detected):
        pronunciation = prepare_japanese(text)
        return build_audio_query(
            pronunciation=pronunciation,
            output_sampling_rate=output_sampling_rate,
        )

    accent_phrases = []
    extension_segments: List[VoicegerSegment] = []
    pitch_records = []

    for segment in detected:
        if segment.language == "ja":
            pronunciation = prepare_japanese(segment.text)
            phrases = pronunciation_to_accent_phrases(pronunciation)
            start = len(accent_phrases)
            accent_phrases.extend(phrases)
            for record in pronunciation_pitch_events(pronunciation) or ():
                pitch_records.append(record.model_copy(
                    update={"accentPhraseIndex": start + record.accentPhraseIndex},
                    deep=True,
                ))
            extension_segments.append(
                VoicegerSegment(
                    language="ja",
                    text=segment.text,
                    accentPhraseStart=start,
                    accentPhraseCount=len(phrases),
                    pronunciationTerminator=(
                        pronunciation.terminator or ""
                    ),
                    pronunciationPunctuation=(
                        pronunciation_punctuation(pronunciation)
                    ),
                )
            )
        elif segment.language == "en":
            phonemes = (
                list(english_g2p(segment.text))
                if english_g2p is not None
                else None
            )
            if phonemes is not None and not phonemes:
                raise ValueError(f"English pronunciation is empty for {segment.text!r}")
            extension_segments.append(
                VoicegerSegment(
                    language="en",
                    text=segment.text,
                    phonemes=phonemes,
                )
            )

    return AudioQuery(
        accent_phrases=accent_phrases,
        speedScale=1,
        pitchScale=0,
        intonationScale=1,
        volumeScale=1,
        prePhonemeLength=0.1,
        postPhonemeLength=0.1,
        pauseLength=None,
        pauseLengthScale=1,
        outputSamplingRate=output_sampling_rate,
        outputStereo=False,
        kana=None,
        voicegerSegments=extension_segments,
        pronunciationPitchEvents=pitch_records or None,
    )


def voiceger_text_language(segments: Sequence[VoicegerSegment]) -> str:
    languages = {segment.language for segment in segments}

    if languages == {"en"}:
        return "English"
    if languages <= {"ja", "en"}:
        return "Japanese-English Mixed"
    return "Multilingual Mixed"



def build_mixed_synthesis_plan(query: AudioQuery) -> MixedSynthesisPlan:
    """Resolve adapter mixed-query metadata into Voiceger synthesis inputs."""

    if not query.voicegerSegments:
        raise ValueError("voicegerSegments are required for mixed synthesis")

    if query.pronunciationPitchEvents:
        # Validate all global extension records before segment slicing, so
        # out-of-range or orphaned metadata cannot be silently discarded.
        accent_phrases_to_pronunciation(
            query.accent_phrases, pitch_events=query.pronunciationPitchEvents
        )

    synthesis_text = "".join(
        segment.text for segment in query.voicegerSegments
    )
    japanese_overrides: list[tuple[str, list[str]]] = []
    english_overrides: list[tuple[str, list[str]]] = []

    for segment in query.voicegerSegments:
        if segment.language == "en":
            if segment.phonemes is not None:
                english_overrides.append(
                    (
                        segment.text,
                        normalize_english_phonemes(segment.phonemes),
                    )
                )
            continue

        if segment.phonemes is not None:
            raise ValueError(
                "voicegerSegments.phonemes is supported only for English"
            )

        if segment.language != "ja":
            continue

        if (
            segment.accentPhraseStart is None
            or segment.accentPhraseCount is None
        ):
            raise ValueError(
                "Japanese voicegerSegments require accent phrase references"
            )

        start = segment.accentPhraseStart
        end = start + segment.accentPhraseCount
        if start < 0 or end > len(query.accent_phrases):
            raise ValueError(
                "voicegerSegments accent phrase range is out of bounds"
            )

        segment_phrases = query.accent_phrases[start:end]
        if not segment_phrases:
            raise ValueError(
                "Japanese voicegerSegments must reference accent phrases"
            )

        pronunciation = accent_phrases_to_pronunciation(
            segment_phrases,
            punctuation=segment.pronunciationPunctuation,
            terminator=resolve_japanese_segment_terminator(segment),
            pitch_events=pitch_events_for_range(
                query.pronunciationPitchEvents, start, len(segment_phrases)
            ),
        )
        japanese_overrides.append(
            (
                segment.text,
                pronunciation_to_voiceger_tokens(pronunciation),
            )
        )

    return MixedSynthesisPlan(
        text=synthesis_text,
        text_language=voiceger_text_language(query.voicegerSegments),
        japanese_overrides=tuple(japanese_overrides),
        english_overrides=tuple(english_overrides),
    )
