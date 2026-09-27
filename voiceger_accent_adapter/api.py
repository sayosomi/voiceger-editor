"""VOICEVOX-style FastAPI surface for voiceger-accent-adapter."""

from __future__ import annotations

from functools import lru_cache
import os
from tempfile import NamedTemporaryFile
from typing import List

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from .mixed_language import (
    build_mixed_audio_query,
    build_mixed_synthesis_plan,
)
from .openjtalk_converter import OpenJTalkConversionError
from .pronunciation import (
    PronunciationSyntaxError,
    format_pronunciation,
    parse_pronunciation,
)
from .styles import available_styles, get_style
from .voiceger_adapter import (
    VoicegerAdapter,
    VoicegerAdapterError,
    pronunciation_to_spoken_text,
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


def _resolve_style(speaker: int):
    adapter = get_adapter()
    try:
        return get_style(adapter.voiceger_root, speaker)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
            "/version",
            "/speakers",
            "/audio_query",
            "/accent_phrases",
            "/synthesis",
        ],
    }


@app.get("/version")
def version():
    """Return an engine-style version string."""

    return "0.1.0-dev"


@app.get("/speakers")
def speakers():
    """Expose local Voiceger reference WAVs as VOICEVOX talk styles."""

    adapter = get_adapter()
    styles = available_styles(adapter.voiceger_root)

    return [
        {
            "name": adapter.character_name,
            "speaker_uuid": "voiceger-accent-adapter-zundamon",
            "styles": [
                {
                    "name": style.name,
                    "id": style.id,
                    "type": "talk",
                }
                for style in styles
            ],
            "version": "1",
            "supported_features": {
                "permitted_synthesis_morphing": "NOTHING"
            },
        }
    ]


@app.post("/audio_query", response_model=AudioQuery)
def audio_query(
    text: str,
    speaker: int = Query(...),
):
    """Create a VOICEVOX-style synthesis query from ordinary Japanese text."""

    _resolve_style(speaker)

    try:
        return build_mixed_audio_query(
            text,
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

    _resolve_style(speaker)

    try:
        if is_kana:
            parsed = parse_pronunciation(text)
        else:
            return build_mixed_audio_query(text).accent_phrases

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
    background_tasks: BackgroundTasks,
    speaker: int = Query(...),
):
    """Synthesize a WAV from a VOICEVOX-style AudioQuery."""

    style = _resolve_style(speaker)
    _validate_supported_query_controls(query)

    try:
        if query.voicegerSegments:
            plan = build_mixed_synthesis_plan(query)
            result = get_adapter().synthesize_mixed_audio(
                text=plan.text,
                japanese_overrides=list(plan.japanese_overrides),
                text_language=plan.text_language,
                ref_wav_path=style.reference_path(
                    get_adapter().voiceger_root
                ),
                prompt_text=style.prompt_text,
                speed=query.speedScale,
            )
        else:
            pronunciation = accent_phrases_to_pronunciation(
                query.accent_phrases,
                terminator=_query_terminator(query),
            )
            resolved_pronunciation = format_pronunciation(pronunciation)
            synthesis_text = pronunciation_to_spoken_text(pronunciation)

            result = get_adapter().synthesize_audio(
                text=synthesis_text,
                pronunciation=resolved_pronunciation,
                ref_wav_path=style.reference_path(
                    get_adapter().voiceger_root
                ),
                prompt_text=style.prompt_text,
                speed=query.speedScale,
            )

        try:
            import soundfile as sf
        except ImportError as exc:
            raise VoicegerAdapterError(
                "soundfile is required to write synthesized WAV files"
            ) from exc

        temp = NamedTemporaryFile(delete=False, suffix=".wav")
        temp_path = temp.name
        temp.close()

        sf.write(
            temp_path,
            result["audio"],
            result["sampling_rate"],
            format="WAV",
        )
        background_tasks.add_task(os.unlink, temp_path)

    except (
        ValueError,
        PronunciationSyntaxError,
        OpenJTalkConversionError,
    ) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VoicegerAdapterError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return FileResponse(
        temp_path,
        media_type="audio/wav",
        background=background_tasks,
    )
