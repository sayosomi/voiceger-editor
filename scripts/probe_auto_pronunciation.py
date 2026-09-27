#!/usr/bin/env python3
"""Inspect OpenJTalk frontend features and automatic editable pronunciation."""

from __future__ import annotations

import pprint
import sys
from pathlib import Path


VOICEGER_ROOT = Path.home() / "voiceger_v2"
REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(VOICEGER_ROOT / "GPT-SoVITS" / "GPT_SoVITS"))

import pyopenjtalk  # noqa: E402

from voiceger_accent_adapter.openjtalk_converter import (  # noqa: E402
    text_to_pronunciation_string,
)


CASES = [
    "雨",
    "飴",
    "今日は雨ですね。",
    "明日の天気は晴れ。",
    "私は思う。",
]


for text in CASES:
    print(f"\n=== {text} ===")
    features = pyopenjtalk.run_frontend(text)
    for feature in features:
        pprint.pprint(
            {
                key: feature.get(key)
                for key in (
                    "string",
                    "pos",
                    "pron",
                    "acc",
                    "mora_size",
                    "chain_flag",
                )
            },
            sort_dicts=False,
        )
    print("=>", text_to_pronunciation_string(text))
