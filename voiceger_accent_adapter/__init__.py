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
from .voiceger_tokens import (
    VoicegerTokenConversionError,
    accent_phrase_to_voiceger_tokens,
    pronunciation_to_voiceger_tokens,
)
from .user_dictionary import (
    EnglishUserDictionaryEntry,
    JapaneseWordType,
    UserDictWord,
    UserDictionaryCore,
)

__all__ = [
    "AccentPhrase",
    "OpenJTalkConversionError",
    "Pronunciation",
    "PronunciationSyntaxError",
    "VoicegerTokenConversionError",
    "EnglishUserDictionaryEntry",
    "JapaneseWordType",
    "UserDictWord",
    "UserDictionaryCore",
    "accent_phrase_to_voiceger_tokens",
    "format_pronunciation",
    "frontend_features_to_pronunciation",
    "parse_pronunciation",
    "pronunciation_to_voiceger_tokens",
    "text_to_pronunciation",
    "text_to_pronunciation_string",
]
