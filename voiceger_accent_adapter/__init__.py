"""Core package for voiceger-accent-adapter."""

from .openjtalk_converter import (
    OpenJTalkConversionError,
    frontend_features_to_pronunciation,
    text_to_pronunciation,
    text_to_pronunciation_string,
)
from .pronunciation import (
    AccentPhrase,
    Pronunciation,
    PronunciationSyntaxError,
    format_pronunciation,
    parse_pronunciation,
)

__all__ = [
    "AccentPhrase",
    "OpenJTalkConversionError",
    "Pronunciation",
    "PronunciationSyntaxError",
    "format_pronunciation",
    "frontend_features_to_pronunciation",
    "parse_pronunciation",
    "text_to_pronunciation",
    "text_to_pronunciation_string",
]
