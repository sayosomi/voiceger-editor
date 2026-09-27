#!/usr/bin/env python3
"""Compare adapter-generated tokens with Voiceger's built-in Japanese G2P."""

from __future__ import annotations

import sys
from pathlib import Path


VOICEGER_ROOT = Path.home() / "voiceger_v2"
REPO_ROOT = Path(__file__).resolve().parent.parent
GPT_SOVITS = VOICEGER_ROOT / "GPT-SoVITS" / "GPT_SoVITS"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(GPT_SOVITS))

from text.cleaner import clean_text  # noqa: E402
from text.japanese import g2p as voiceger_g2p  # noqa: E402

from voiceger_accent_adapter.openjtalk_converter import (  # noqa: E402
    text_to_pronunciation,
)
from voiceger_accent_adapter.pronunciation import format_pronunciation  # noqa: E402
from voiceger_accent_adapter.voiceger_tokens import (  # noqa: E402
    pronunciation_to_voiceger_tokens,
)


CASES = [
    "雨",
    "飴",
    "今日は雨ですね。",
    "明日の天気は晴れ。",
    "私は思う。",
]


for text in CASES:
    pronunciation = text_to_pronunciation(text)
    adapter_tokens = pronunciation_to_voiceger_tokens(pronunciation)
    original_tokens = voiceger_g2p(text)
    cleaned_tokens = clean_text(text, "ja", "v2")[0]

    print(f"\n=== {text} ===")
    print("pronunciation:", format_pronunciation(pronunciation))
    print("voiceger g2p:  ", original_tokens)
    print("adapter g2p:   ", adapter_tokens)
    print("g2p match:", adapter_tokens == original_tokens)
    print("cleaned v2:    ", cleaned_tokens)
