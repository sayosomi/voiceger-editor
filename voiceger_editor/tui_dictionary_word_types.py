"""Shared Japanese word-type choices and labels for Dictionary TUI flows."""

from __future__ import annotations

from .user_dictionary import JapaneseWordType


JAPANESE_WORD_TYPES = tuple(JapaneseWordType)
_JAPANESE_WORD_TYPE_LABELS = {
    JapaneseWordType.PROPER_NOUN: "固有名詞",
    JapaneseWordType.COMMON_NOUN: "普通名詞",
    JapaneseWordType.VERB: "動詞",
    JapaneseWordType.ADJECTIVE: "形容詞",
    JapaneseWordType.SUFFIX: "接尾辞",
}


def japanese_word_type_label(word_type: JapaneseWordType) -> str:
    return _JAPANESE_WORD_TYPE_LABELS[word_type]
