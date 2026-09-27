"""VOICEVOX-style FastAPI surface for voiceger-accent-adapter."""

from __future__ import annotations

from functools import lru_cache
from typing import List

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from .openjtalk_converter import OpenJTalkConversionError
from .pronunciation import (
    PronunciationSyntaxError,
    format_pronunciation,
    parse_pronunciation,
)
from .voiceger_adapter import (
    VoicegerAdapter,
    VoicegerAdapterError,
    resolve_pronunciation,
)
from .voicevox_api_models import AccentPhrase, AudioQuery
from .voicevox_query import (
    accent_phrases_to_pronunciation,
    build_audio_query,
    pronunciation_to_accent_phrases,
)


app = FastAPI(
    title="voiceger-accent-adapter",
    version="0.1.0-dev",
)


@lru_cache(maxsize=1)
def get_adapter() -> VoicegerAdapter:
    return VoicegerAdapter()


def _validate_speaker(speaker: int) -> None:
    if speaker < 0:
        raise HTTPException(status_code=422, detail="speaker must be non-negative")


def _query_terminator(query: AudioQuery) -> str:
    if query.kana:
        if query.kana.endswith("？"):
            return "？"
        if query.kana.endswith("。"):
            return "。"

    text = query.text.strip()
    if text.endswith(("？", "?")):
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
        raise HTTPException(
            status_code=400,
            detail=(
                "currently unsupported AudioQuery fields were changed: "
                + ", ".join(unsupported)
            ),
        )


@app.get("/")
def root():
    return {
        "name": "voiceger-accent-adapter",
        "version": "0.1.0-dev",
        "endpoints": [
            "/audio_query",
            "/accent_phrases",
            "/synthesis",
        ],
    }


@app.post("/audio_query", response_model=AudioQuery)
def audio_query(
    text: str,
    speaker: int = Query(...),
):
    """Create a VOICEVOX-style synthesis query from ordinary Japanese text."""

    _validate_speaker(speaker)

    try:
        _, parsed, _ = resolve_pronunciation(text)
        return build_audio_query(
            text=text.strip(),
            pronunciation=parsed,
            output_sampling_rate=32000,
        )
    except (ValueError, OpenJTalkConversionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/accent_phrases", response_model=List[AccentPhrase])
def accent_phrases(
    text: str,
    speaker: int = Query(...),
    is_kana: bool = Query(False),
):
    """Create accent phrases from normal text or editable AquesTalk-style kana."""

    _validate_speaker(speaker)

    try:
        if is_kana:
            parsed = parse_pronunciation(text)
        else:
            _, parsed, _ = resolve_pronunciation(text)

        return pronunciation_to_accent_phrases(parsed)
    except (
        ValueError,
        PronunciationSyntaxError,
        OpenJTalkConversionError,
    ) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/synthesis",
    response_class=FileResponse,
    responses={
        200: {
            "content": {
                "audio/wav": {
                    "schema": {
                        "type": "string",
                        "format": "binary",
                    }
                }
            }
        }
    },
)
def synthesis(
    query: AudioQuery,
    speaker: int = Query(...),
):
    """Synthesize a WAV from a VOICEVOX-style AudioQuery."""

    _validate_speaker(speaker)
    _validate_supported_query_controls(query)

    try:
        pronunciation = accent_phrases_to_pronunciation(
            query.accent_phrases,
            terminator=_query_terminator(query),
        )
        resolved_pronunciation = format_pronunciation(pronunciation)

        result = get_adapter().synthesize(
            text=query.text,
            pronunciation=resolved_pronunciation,
            speed=query.speedScale,
        )
    except (
        ValueError,
        PronunciationSyntaxError,
        OpenJTalkConversionError,
    ) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VoicegerAdapterError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return FileResponse(
        result["file_path"],
        media_type="audio/wav",
        filename=result["file_name"],
    )
