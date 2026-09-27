"""Mixed-language query construction for Voiceger's multilingual frontend."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, List, Optional

from .openjtalk_converter import text_to_pronunciation
from .pronunciation import Pronunciation
from .voicevox_api_models import AudioQuery, VoicegerSegment
from .voicevox_query import build_audio_query, pronunciation_to_accent_phrases


@dataclass(frozen=True)
class DetectedSegment:
    language: str
    text: str


def _voiceger_segments(text: str) -> Sequence[dict[str, Any]]:
    try:
        import LangSegment
    except ImportError as exc:
        raise RuntimeError(
            "LangSegment is required for mixed-language text; "
            "run this from Voiceger's Python environment"
        ) from exc

    previous = LangSegment.getfilters()
    try:
        LangSegment.setfilters(["zh", "ja", "en", "ko"])
        return LangSegment.getTexts(text)
    finally:
        LangSegment.setfilters(previous)


def detect_language_segments(
    text: str,
    *,
    get_texts: Optional[Callable[[str], Sequence[dict[str, Any]]]] = None,
) -> List[DetectedSegment]:
    """Detect and merge adjacent Voiceger/LangSegment language runs."""

    if not text or not text.strip():
        raise ValueError("text must not be empty")

    raw = (get_texts or _voiceger_segments)(text)
    result: List[DetectedSegment] = []

    for item in raw:
        segment_text = str(item.get("text", ""))
        language = str(item.get("lang", ""))
        if not segment_text:
            continue

        if language not in {"ja", "en", "zh", "ko"}:
            language = "auto"

        if result and result[-1].language == language:
            previous = result[-1]
            result[-1] = DetectedSegment(
                language=language,
                text=previous.text + segment_text,
            )
        else:
            result.append(
                DetectedSegment(language=language, text=segment_text)
            )

    if not result:
        raise ValueError("language segmentation produced no text")
    return result


def is_pure_japanese(segments: Sequence[DetectedSegment]) -> bool:
    return bool(segments) and all(segment.language == "ja" for segment in segments)


def build_mixed_audio_query(
    text: str,
    *,
    segments: Optional[Sequence[DetectedSegment]] = None,
    output_sampling_rate: int = 32000,
) -> AudioQuery:
    """Build AudioQuery plus voicegerSegments for mixed-language input."""

    detected = list(segments or detect_language_segments(text))
    if is_pure_japanese(detected):
        pronunciation = text_to_pronunciation(text)
        return build_audio_query(
            pronunciation=pronunciation,
            output_sampling_rate=output_sampling_rate,
        )

    accent_phrases = []
    extension_segments: List[VoicegerSegment] = []

    for segment in detected:
        if segment.language == "ja":
            pronunciation = text_to_pronunciation(segment.text)
            phrases = pronunciation_to_accent_phrases(pronunciation)
            start = len(accent_phrases)
            accent_phrases.extend(phrases)
            extension_segments.append(
                VoicegerSegment(
                    language="ja",
                    text=segment.text,
                    accentPhraseStart=start,
                    accentPhraseCount=len(phrases),
                )
            )
        else:
            extension_segments.append(
                VoicegerSegment(
                    language=segment.language,
                    text=segment.text,
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
    )


def voiceger_text_language(segments: Sequence[VoicegerSegment]) -> str:
    languages = {segment.language for segment in segments}

    if languages == {"en"}:
        return "English"
    if languages <= {"ja", "en"}:
        return "Japanese-English Mixed"
    return "Multilingual Mixed"
