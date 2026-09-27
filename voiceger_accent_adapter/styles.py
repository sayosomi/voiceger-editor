"""Voiceger reference-audio styles exposed as VOICEVOX speaker styles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


PRESET_PROMPT_TEXT = "私はいつもミネラルウォーターを持ち歩いています。"


@dataclass(frozen=True)
class VoicegerStyle:
    id: int
    name: str
    filename: str
    prompt_text: str = PRESET_PROMPT_TEXT

    def reference_path(self, voiceger_root: Path) -> Path:
        return voiceger_root / "reference" / self.filename


KNOWN_STYLES: Tuple[VoicegerStyle, ...] = (
    VoicegerStyle(1, "Neutral", "01_ref_emoNormal026.wav"),
    VoicegerStyle(2, "Sweet", "02_ref_emoAma026.wav"),
    VoicegerStyle(3, "Snippy", "03_ref_emoTsun026.wav"),
    VoicegerStyle(4, "Sexy", "04_ref_emoSexy026.wav"),
    VoicegerStyle(5, "Whispering", "05_ref_emoSasa026.wav"),
    VoicegerStyle(6, "Murmuring", "06_ref_emoMurmur026.wav"),
    VoicegerStyle(7, "Exhausted", "07_ref_emoHero026.wav"),
    VoicegerStyle(8, "Sobbing", "08_ref_emoSobbing026.wav"),
)


def available_styles(voiceger_root: Path) -> Tuple[VoicegerStyle, ...]:
    """Return known styles whose reference WAV exists locally."""

    return tuple(
        style
        for style in KNOWN_STYLES
        if style.reference_path(voiceger_root).is_file()
    )


def get_style(voiceger_root: Path, style_id: int) -> VoicegerStyle:
    """Resolve a VOICEVOX-style speaker/style id to a local reference WAV."""

    for style in available_styles(voiceger_root):
        if style.id == style_id:
            return style

    available = ", ".join(str(style.id) for style in available_styles(voiceger_root))
    if not available:
        available = "none"
    raise ValueError(
        f"unsupported speaker/style id {style_id}; available style ids: {available}"
    )
