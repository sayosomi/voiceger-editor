#!/usr/bin/env python3
"""Inspect mixed-language segmentation and AudioQuery extension."""

from __future__ import annotations

import json

from voiceger_editor.mixed_language import (
    build_mixed_audio_query,
    detect_language_segments,
)


CASES = [
    "今日はOpenAIを使うよ。",
    "ずんだもんのVoice is very cuteなのだ。",
    "Hello、今日は雨ですね。",
]


for text in CASES:
    print(f"\n=== {text} ===")
    segments = detect_language_segments(text)
    print("segments:")
    for segment in segments:
        print(f"  {segment.language}: {segment.text!r}")

    query = build_mixed_audio_query(text, segments=segments)
    print("audio_query:")
    print(
        json.dumps(
            query.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
    )
