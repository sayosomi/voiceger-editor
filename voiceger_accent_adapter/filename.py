"""VOICEVOX-style output filename helpers."""

from __future__ import annotations

import re
from pathlib import Path


_INVALID_FILENAME_CHARS = re.compile(r'[\x00-\x1f"*/:<>?\\|\x7f]')
_INDEX_PREFIX = re.compile(r"^(\d+)_")


def sanitize_filename_part(value: str) -> str:
    """Mirror VOICEVOX's filename sanitization for user-facing fields."""

    return _INVALID_FILENAME_CHARS.sub("", value)


def shorten_text_for_filename(text: str) -> str:
    """Mirror VOICEVOX: keep up to 10 chars, or 9 chars plus ellipsis."""

    cleaned = sanitize_filename_part(text)
    if len(cleaned) > 10:
        return cleaned[:9] + "…"
    return cleaned


def next_output_index(output_dir: Path) -> int:
    """Return the next persistent 1-based index for an output directory."""

    highest = 0
    if output_dir.exists():
        for path in output_dir.iterdir():
            if not path.is_file():
                continue
            match = _INDEX_PREFIX.match(path.name)
            if match is not None:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def build_output_filename(
    *,
    index: int,
    character_name: str,
    style_name: str,
    text: str,
) -> str:
    """Build the default VOICEVOX-style WAV filename.

    Format:
      001_キャラ（スタイル）_テキスト.wav
    """

    if index < 1:
        raise ValueError("index must be 1 or greater")

    character = sanitize_filename_part(character_name)
    style = sanitize_filename_part(style_name)
    snippet = shorten_text_for_filename(text)

    return f"{index:03d}_{character}（{style}）_{snippet}.wav"
