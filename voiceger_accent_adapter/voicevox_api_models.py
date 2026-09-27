"""VOICEVOX-like API models used by voiceger-accent-adapter."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Mora(BaseModel):
    text: str
    consonant: Optional[str] = None
    consonant_length: Optional[float] = None
    vowel: str
    vowel_length: float = 0
    pitch: float = 0


class AccentPhrase(BaseModel):
    moras: List[Mora]
    accent: int = Field(ge=1)
    pause_mora: Optional[Mora] = None
    is_interrogative: bool = False


class AudioQuery(BaseModel):
    """VOICEVOX-like synthesis query."""

    accent_phrases: List[AccentPhrase]
    speedScale: float = Field(default=1, gt=0)
    pitchScale: float = 0
    intonationScale: float = 1
    volumeScale: float = Field(default=1, ge=0)
    prePhonemeLength: float = Field(default=0.1, ge=0)
    postPhonemeLength: float = Field(default=0.1, ge=0)
    pauseLength: Optional[float] = Field(default=None, ge=0)
    pauseLengthScale: float = Field(default=1, ge=0)
    outputSamplingRate: int = Field(default=32000, gt=0)
    outputStereo: bool = False
    kana: Optional[str] = None

    # Adapter extension: original display text for readable output filenames.
    text: str
