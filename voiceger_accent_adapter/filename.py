"""Helpers for user-facing synthesized audio filenames."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Optional


_INVALID_FILENAME_CHARS = re.compile(r'[\x00-\x1f"*/:<>?\\|\x7f]')


def sanitize_filename_part(value: str) -> str:
    """Mirror VOICEVOX's filename sanitization for user-facing fields."""

    return _INVALID_FILENAME_CHARS.sub("", value)


def shorten_text_for_filename(text: str) -> str:
    """Mirror VOICEVOX: keep up to 10 chars, or 9 chars plus ellipsis."""

    cleaned = sanitize_filename_part(text)
    if len(cleaned) > 10:
        return cleaned[:9] + "…"
    return cleaned


def build_output_filename(
    *,
    text: str,
    timestamp: Optional[datetime] = None,
) -> str:
    """Build a timestamped WAV filename using local time."""

    local_time = timestamp if timestamp is not None else datetime.now()
    snippet = shorten_text_for_filename(text)
    return f"{local_time:%Y%m%d_%H%M%S}_{snippet}.wav"
