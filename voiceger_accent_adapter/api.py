"""VOICEVOX-style FastAPI surface for voiceger-accent-adapter."""

from __future__ import annotations

from functools import lru_cache
import os
import warnings
from tempfile import NamedTemporaryFile
from typing import List

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from ._version import __version__
from .mixed_language import build_mixed_audio_query
from .openjtalk_converter import OpenJTalkConversionError
from .openjtalk_dictionary import OpenJTalkDictionaryError
from .pronunciation import (
    PronunciationSyntaxError,
    parse_pronunciation,
)
from .synthesis import synthesize_audio_query
from .styles import available_styles, get_style
from .voiceger_environment import (
    VoicegerEnvironmentError,
    require_voiceger_environment,
)
from .voiceger_adapter import (
    VoicegerAdapter,
    VoicegerAdapterError,
)
from .voicevox_api_models import AccentPhrase, AudioQuery
from .user_dictionary import (
    JapaneseWordType,
    UserDictWord,
    UserDictionaryInputError,
)
from .voicevox_query import (
    build_audio_query,
    pronunciation_to_accent_phrases,
)


app = FastAPI(
    title="voiceger-accent-adapter",
    version=__version__,
)


@lru_cache(maxsize=1)
def get_adapter() -> VoicegerAdapter:
    environment = require_voiceger_environment()
    for warning in environment.warnings:
        warnings.warn(
            f"Voiceger setup warning: {warning.message}",
            RuntimeWarning,
            stacklevel=2,
        )
    return VoicegerAdapter(voiceger_root=environment.voiceger_root)


@app.exception_handler(VoicegerEnvironmentError)
async def _voiceger_environment_error(_request, exc: VoicegerEnvironmentError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _resolve_style(speaker: int):
    adapter = get_adapter()
    try:
        return get_style(adapter.voiceger_root, speaker)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/")
def root():
    return {
        "name": "voiceger-accent-adapter",
        "version": __version__,
        "endpoints": [
            "/version",
            "/speakers",
            "/audio_query",
            "/accent_phrases",
            "/synthesis",
            "GET /user_dict",
            "POST /user_dict_word",
            "PUT /user_dict_word/{word_uuid}",
            "DELETE /user_dict_word/{word_uuid}",
            "POST /import_user_dict",
        ],
    }


@app.get("/version")
def version():
    """Return an engine-style version string."""

    return __version__


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
    """Create a VOICEVOX-style synthesis query from ordinary text."""

    _resolve_style(speaker)

    try:
        adapter = get_adapter()
        adapter.ensure_japanese_dictionary_active()
        return build_mixed_audio_query(
            text,
            english_g2p=adapter.english_phonemes,
            output_sampling_rate=32000,
        )
    except OpenJTalkDictionaryError as exc:
        raise HTTPException(
            status_code=500,
            detail="Japanese user dictionary could not be activated.",
        ) from exc
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
            get_adapter().ensure_japanese_dictionary_active()
            return build_mixed_audio_query(text).accent_phrases

        return pronunciation_to_accent_phrases(parsed)
    except (
        ValueError,
        PronunciationSyntaxError,
        OpenJTalkConversionError,
    ) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OpenJTalkDictionaryError as exc:
        raise HTTPException(
            status_code=500,
            detail="Japanese user dictionary could not be activated.",
        ) from exc


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

    try:
        result = synthesize_audio_query(
            adapter=get_adapter(),
            query=query,
            style=style,
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


@app.get("/user_dict", response_model=dict[str, UserDictWord])
def user_dict():
    """Return the persistent UUID-keyed Japanese dictionary."""

    try:
        return get_adapter().user_dictionary.list_japanese_entries()
    except VoicegerEnvironmentError:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Japanese user dictionary could not be loaded.",
        ) from exc


@app.post("/user_dict_word")
def add_user_dict_word(
    surface: str,
    pronunciation: str,
    accent_type: int,
    word_type: JapaneseWordType = Query(JapaneseWordType.PROPER_NOUN),
    priority: int = Query(5, ge=0, le=10),
):
    """Add one VOICEVOX-compatible Japanese dictionary word."""

    try:
        return get_adapter().user_dictionary.add_japanese_word(
            surface=surface,
            pronunciation=pronunciation,
            accent_type=accent_type,
            word_type=word_type,
            priority=priority,
        )
    except UserDictionaryInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except VoicegerEnvironmentError:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Japanese user dictionary could not be updated.",
        ) from exc


@app.put("/user_dict_word/{word_uuid}", status_code=204)
def update_user_dict_word(
    word_uuid: str,
    surface: str,
    pronunciation: str,
    accent_type: int,
    word_type: JapaneseWordType = Query(JapaneseWordType.PROPER_NOUN),
    priority: int = Query(5, ge=0, le=10),
):
    """Replace one existing word, applying VOICEVOX add/update defaults."""

    try:
        get_adapter().user_dictionary.update_japanese_word(
            word_uuid,
            surface=surface,
            pronunciation=pronunciation,
            accent_type=accent_type,
            word_type=word_type,
            priority=priority,
        )
    except UserDictionaryInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except VoicegerEnvironmentError:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Japanese user dictionary could not be updated.",
        ) from exc


@app.delete("/user_dict_word/{word_uuid}", status_code=204)
def delete_user_dict_word(word_uuid: str):
    """Delete one existing Japanese dictionary word."""

    try:
        get_adapter().user_dictionary.delete_japanese_word(word_uuid)
    except UserDictionaryInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except VoicegerEnvironmentError:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Japanese user dictionary could not be updated.",
        ) from exc


@app.post("/import_user_dict", status_code=204)
def import_user_dict(
    entries: dict[str, UserDictWord],
    override: bool = Query(...),
):
    """Import the UUID-keyed expanded VOICEVOX UserDictWord format."""

    try:
        get_adapter().user_dictionary.import_japanese(entries, override=override)
    except UserDictionaryInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except VoicegerEnvironmentError:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Japanese user dictionary could not be imported.",
        ) from exc
