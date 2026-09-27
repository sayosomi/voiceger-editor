"""Shared AudioQuery-to-Voiceger synthesis orchestration."""

from __future__ import annotations

from typing import Any

from .mixed_language import build_mixed_synthesis_plan
from .pronunciation import format_pronunciation
from .styles import VoicegerStyle
from .voiceger_adapter import VoicegerAdapter, pronunciation_to_spoken_text
from .voicevox_api_models import AudioQuery
from .voicevox_query import accent_phrases_to_pronunciation


def _query_terminator(query: AudioQuery) -> str:
    if query.kana:
        if query.kana.endswith("？"):
            return "？"
        if query.kana.endswith("。"):
            return "。"

    if query.accent_phrases and query.accent_phrases[-1].is_interrogative:
        return "？"
    return "。"


def _validate_supported_query_controls(query: AudioQuery) -> None:
    unsupported = []

    if query.pitchScale != 0:
        unsupported.append("pitchScale")
    if query.intonationScale != 1:
        unsupported.append("intonationScale")
    if query.volumeScale != 1:
        unsupported.append("volumeScale")
    if query.prePhonemeLength != 0.1:
        unsupported.append("prePhonemeLength")
    if query.postPhonemeLength != 0.1:
        unsupported.append("postPhonemeLength")
    if query.pauseLength is not None:
        unsupported.append("pauseLength")
    if query.pauseLengthScale != 1:
        unsupported.append("pauseLengthScale")
    if query.outputSamplingRate != 32000:
        unsupported.append("outputSamplingRate")
    if query.outputStereo:
        unsupported.append("outputStereo")

    if unsupported:
        raise ValueError(
            "currently unsupported AudioQuery fields were changed: "
            + ", ".join(unsupported)
        )


def synthesize_audio_query(
    *,
    adapter: VoicegerAdapter,
    query: AudioQuery,
    style: VoicegerStyle,
    top_k: int = 20,
    top_p: float = 0.6,
    temperature: float = 0.6,
) -> dict[str, Any]:
    """Synthesize an AudioQuery through the selected Voiceger style."""

    _validate_supported_query_controls(query)
    ref_wav_path = style.reference_path(adapter.voiceger_root)

    if query.voicegerSegments:
        plan = build_mixed_synthesis_plan(query)
        return adapter.synthesize_mixed_audio(
            text=plan.text,
            japanese_overrides=list(plan.japanese_overrides),
            text_language=plan.text_language,
            english_overrides=list(plan.english_overrides),
            ref_wav_path=ref_wav_path,
            prompt_text=style.prompt_text,
            speed=query.speedScale,
            top_k=top_k,
            top_p=top_p,
            temperature=temperature,
        )

    pronunciation = accent_phrases_to_pronunciation(
        query.accent_phrases,
        terminator=_query_terminator(query),
    )
    resolved_pronunciation = format_pronunciation(pronunciation)
    synthesis_text = pronunciation_to_spoken_text(pronunciation)

    return adapter.synthesize_audio(
        text=synthesis_text,
        pronunciation=resolved_pronunciation,
        ref_wav_path=ref_wav_path,
        prompt_text=style.prompt_text,
        speed=query.speedScale,
        top_k=top_k,
        top_p=top_p,
        temperature=temperature,
    )
