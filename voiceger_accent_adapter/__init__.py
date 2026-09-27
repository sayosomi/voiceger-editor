"""Core package for voiceger-accent-adapter."""

from .pronunciation import (
    AccentPhrase,
    Pronunciation,
    PronunciationSyntaxError,
    format_pronunciation,
    parse_pronunciation,
)

__all__ = [
    "AccentPhrase",
    "Pronunciation",
    "PronunciationSyntaxError",
    "format_pronunciation",
    "parse_pronunciation",
]
