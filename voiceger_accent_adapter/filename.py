"""Helpers for user-facing synthesized audio filenames."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Optional


_INVALID_FILENAME_CHARS = re.compile(r'[\x00-\x1f"*/:<>?\\|\x7f]')


def sanitize_filename_part(value: str) -> str:
    """Mirror VOICEVOX's filename sanitization for user-facing fields."""

    return _INVALID_FILENAME_CHARS.sub("", value)


def build_output_filename(
    *,
    text: str,
    timestamp: Optional[datetime] = None,
) -> str:
    """Build a minute-resolution timestamped WAV filename from source text."""

    local_time = timestamp if timestamp is not None else datetime.now()
    source = sanitize_filename_part(text)
    return f"{local_time:%Y%m%d%H%M}_{source}.wav"
