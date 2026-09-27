"""FastAPI surface for voiceger-accent-adapter."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .openjtalk_converter import OpenJTalkConversionError
from .pronunciation import PronunciationSyntaxError
from .voiceger_adapter import (
    VoicegerAdapter,
    VoicegerAdapterError,
    resolve_pronunciation,
)


app = FastAPI(
    title="voiceger-accent-adapter",
    version="0.1.0-dev",
)


class PronunciationRequest(BaseModel):
    text: str


class PronunciationResponse(BaseModel):
    text: str
    pronunciation: str
    source: str = "openjtalk"


class TtsRequest(BaseModel):
    text: str
    pronunciation: Optional[str] = None
    top_k: int = Field(default=20, ge=1)
    top_p: float = Field(default=0.6, gt=0, le=1)
    temperature: float = Field(default=0.6, gt=0)


class TtsResponse(BaseModel):
    message: str = "success"
    resolved_pronunciation: str
    file_path: str
    sampling_rate: int


@lru_cache(maxsize=1)
def get_adapter() -> VoicegerAdapter:
    return VoicegerAdapter()


@app.get("/")
def root():
    return {
        "name": "voiceger-accent-adapter",
        "version": "0.1.0-dev",
        "endpoints": ["/pronunciation", "/tts"],
    }


@app.post("/pronunciation", response_model=PronunciationResponse)
def pronunciation(req: PronunciationRequest):
    try:
        _, _, value = resolve_pronunciation(req.text)
    except (ValueError, OpenJTalkConversionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PronunciationResponse(
        text=req.text,
        pronunciation=value,
    )


@app.post("/tts", response_model=TtsResponse)
def tts(req: TtsRequest):
    try:
        result = get_adapter().synthesize(
            text=req.text,
            pronunciation=req.pronunciation,
            top_k=req.top_k,
            top_p=req.top_p,
            temperature=req.temperature,
        )
    except (ValueError, PronunciationSyntaxError, OpenJTalkConversionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VoicegerAdapterError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return TtsResponse(**result)
