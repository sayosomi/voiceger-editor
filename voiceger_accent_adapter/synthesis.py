"""Shared AudioQuery-to-Voiceger synthesis orchestration."""

from __future__ import annotations

import warnings
from typing import Any

from .mixed_language import build_mixed_synthesis_plan
from .pronunciation import format_pronunciation
from .styles import VoicegerStyle
from .voiceger_adapter import (
    VoicegerAdapter,
    VoicegerAdapterError,
    pronunciation_to_spoken_text,
)
from .voicevox_api_models import AudioQuery
from .voicevox_query import accent_phrases_to_pronunciation


def _query_terminator(query: AudioQuery) -> str | None:
    if query.kana is not None:
        if query.kana.endswith("。"):
            return "。"
        if query.kana.endswith("？"):
            return "？"
        if query.kana.endswith("！"):
            return "！"
        return None

    if query.accent_phrases and query.accent_phrases[-1].is_interrogative:
        return "？"
    return "。"


def _ignored_query_controls(query: AudioQuery) -> tuple[str, ...]:
    ignored = []

    if query.pitchScale != 0:
        ignored.append("pitchScale")
    if query.intonationScale != 1:
        ignored.append("intonationScale")
    if query.volumeScale != 1:
        ignored.append("volumeScale")
    if query.prePhonemeLength != 0.1:
        ignored.append("prePhonemeLength")
    if query.postPhonemeLength != 0.1:
        ignored.append("postPhonemeLength")
    if query.pauseLength is not None:
        ignored.append("pauseLength")
    if query.pauseLengthScale != 1:
        ignored.append("pauseLengthScale")

    return tuple(ignored)


def _warn_ignored_query_controls(query: AudioQuery) -> None:
    ignored = _ignored_query_controls(query)
    if ignored:
        warnings.warn(
            "ignored unsupported VOICEVOX AudioQuery fields: "
            + ", ".join(ignored),
            UserWarning,
            stacklevel=2,
        )


def _mono_pcm_array(audio: Any):
    try:
        import numpy as np
    except ImportError as exc:
        raise VoicegerAdapterError(
            "NumPy is required to transform synthesized audio output"
        ) from exc

    values = np.asarray(audio)
    if values.ndim == 1:
        return values
    if values.ndim == 2 and values.shape[1] == 1:
        return values[:, 0]
    if (
        values.ndim == 2
        and values.shape[1] == 2
        and np.array_equal(values[:, 0], values[:, 1])
    ):
        return values[:, 0]
    raise VoicegerAdapterError(
        "Voiceger synthesis returned unsupported multi-channel audio"
    )


def _resample_mono_pcm(audio: Any, source_rate: int, target_rate: int):
    if source_rate <= 0:
        raise VoicegerAdapterError(
            f"Voiceger synthesis returned invalid sampling rate: {source_rate}"
        )
    if target_rate <= 0:
        raise ValueError("outputSamplingRate must be positive")

    values = _mono_pcm_array(audio)
    import numpy as np

    if source_rate == target_rate:
        return values
    if values.size == 0:
        return values.copy()

    target_samples = max(
        1,
        int(round(values.shape[0] * target_rate / source_rate)),
    )
    source_positions = np.arange(values.shape[0], dtype=np.float64)
    target_positions = (
        np.arange(target_samples, dtype=np.float64) * source_rate / target_rate
    )
    converted = np.interp(
        target_positions,
        source_positions,
        values.astype(np.float64, copy=False),
    )

    if np.issubdtype(values.dtype, np.integer):
        limits = np.iinfo(values.dtype)
        converted = np.clip(np.rint(converted), limits.min, limits.max)
        return converted.astype(values.dtype)

    if np.issubdtype(values.dtype, np.floating):
        return converted.astype(values.dtype, copy=False)

    raise VoicegerAdapterError(
        f"Voiceger synthesis returned unsupported audio dtype: {values.dtype}"
    )


def _apply_output_format(
    result: dict[str, Any],
    query: AudioQuery,
) -> dict[str, Any]:
    try:
        source_rate = int(result["sampling_rate"])
        audio = result["audio"]
    except (KeyError, TypeError, ValueError) as exc:
        raise VoicegerAdapterError(
            "Voiceger synthesis returned malformed audio metadata"
        ) from exc

    target_rate = query.outputSamplingRate
    if source_rate == target_rate and not query.outputStereo:
        return result

    mono = _resample_mono_pcm(audio, source_rate, target_rate)
    if query.outputStereo:
        import numpy as np

        formatted_audio = np.column_stack((mono, mono))
    else:
        formatted_audio = mono

    formatted = dict(result)
    formatted["audio"] = formatted_audio
    formatted["sampling_rate"] = target_rate
    return formatted


def synthesize_audio_query(
    *,
    adapter: VoicegerAdapter,
    query: AudioQuery,
    style: VoicegerStyle,
    top_k: int = 20,
    top_p: float = 1.0,
    temperature: float = 1.0,
) -> dict[str, Any]:
    """Synthesize an AudioQuery through the selected Voiceger style."""

    _warn_ignored_query_controls(query)
    ref_wav_path = style.reference_path(adapter.voiceger_root)

    if query.voicegerSegments:
        plan = build_mixed_synthesis_plan(query)
        result = adapter.synthesize_mixed_audio(
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
        return _apply_output_format(result, query)

    pronunciation = accent_phrases_to_pronunciation(
        query.accent_phrases,
        terminator=_query_terminator(query),
    )
    resolved_pronunciation = format_pronunciation(pronunciation)
    synthesis_text = pronunciation_to_spoken_text(pronunciation)

    result = adapter.synthesize_audio(
        text=synthesis_text,
        pronunciation=resolved_pronunciation,
        ref_wav_path=ref_wav_path,
        prompt_text=style.prompt_text,
        speed=query.speedScale,
        top_k=top_k,
        top_p=top_p,
        temperature=temperature,
    )
    return _apply_output_format(result, query)
