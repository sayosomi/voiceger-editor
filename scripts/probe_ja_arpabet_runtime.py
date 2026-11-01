"""Read-only pinned-runtime feasibility probe for Issue #322.

This does NOT implement JA→ARPAbet conversion or change production behavior.
It deliberately supplies a Japanese-origin EN segment with an explicit
ARPAbet override so that Voiceger's actual normalization, segmentation and
synthesis contract can be checked before changing TUI/Web code.

Run only in the installed Voiceger Python environment, with the user's
already-approved Voiceger terms. All generated audio stays in memory.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from voiceger_editor.compatibility import SUPPORTED_VOICEGER_REVISION
from voiceger_editor.english_stress import normalize_english_phonemes
from voiceger_editor.mixed_language import (
    DetectedSegment,
    build_mixed_audio_query,
    build_mixed_synthesis_plan,
)
from voiceger_editor.styles import get_style
from voiceger_editor.synthesis import synthesize_audio_query
from voiceger_editor.terms_acceptance import require_current_acceptance
from voiceger_editor.voiceger_adapter import VoicegerAdapter


JAPANESE = "ずんだもんはかしこいのだ！"
# An intentionally hand-supplied baseline, not the future conversion algorithm.
# Three consecutive JA accent-phrase approximations, plus punctuation.
PHONEMES = normalize_english_phonemes((
    "Z", "UW1", "N", "D", "AA0", "M", "OW0", "N", "HH", "AA0",
    "K", "AA0", "SH", "IY0", "K", "OW1", "IY0",
    "N", "OW0", "D", "AA1", "!",
))


def _pinned_root() -> Path:
    root = Path(os.environ.get("VOICEGER_ROOT", "~/voiceger_v2")).expanduser().resolve()
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != SUPPORTED_VOICEGER_REVISION:
        raise RuntimeError(
            "Voiceger revision mismatch; expected " + SUPPORTED_VOICEGER_REVISION +
            ", actual " + revision + ". No Voiceger files were changed."
        )
    return root


def _probe(name: str, adapter: VoicegerAdapter, query) -> bool:
    plan = build_mixed_synthesis_plan(query)
    if plan.english_overrides != ((JAPANESE, PHONEMES),):
        raise AssertionError(name + ": explicit EN tokens were lost before synthesis")
    if plan.text != "".join(segment.text for segment in query.voicegerSegments):
        raise AssertionError(name + ": original Japanese section text was changed")
    try:
        result = synthesize_audio_query(
            adapter=adapter, query=query, style=get_style(adapter.voiceger_root, 3),
        )
        rate = int(result["sampling_rate"])
        sample_count = len(result["audio"])
        if rate <= 0 or sample_count <= rate // 10:
            raise AssertionError("Voiceger returned empty or very short audio")
    except Exception as exc:
        print(f"{name}=FAIL {type(exc).__name__}: {exc}", flush=True)
        return False

    print(f"{name}=PASS rate={rate} samples={sample_count}", flush=True)
    return True


def main() -> int:
    try:
        root = _pinned_root()
        require_current_acceptance()
        adapter = VoicegerAdapter(voiceger_root=root)
        pure_en = build_mixed_audio_query(
            JAPANESE,
            segments=(DetectedSegment("en", JAPANESE),),
            english_g2p=lambda _text: PHONEMES,
        )
        mixed = build_mixed_audio_query(
            "今日は" + JAPANESE,
            segments=(DetectedSegment("ja", "今日は"), DetectedSegment("en", JAPANESE)),
            english_g2p=lambda _text: PHONEMES,
        )
    except Exception as exc:
        print(f"SETUP=BLOCKED {type(exc).__name__}: {exc}", flush=True)
        return 2

    print(f"VOICEGER_REVISION={SUPPORTED_VOICEGER_REVISION}", flush=True)
    print("SOURCE_QUERY=Japanese text preserved; explicit EN phones; no disk audio", flush=True)

    successes = (
        _probe("PURE_JA_TEXT_AS_EN", adapter, pure_en),
        _probe("MIXED_JA_AND_CONVERTED_EN", adapter, mixed),
    )
    # The existing English group provider is G2P/tokenizer-derived. Its
    # suitability for Japanese-source text must be independently established
    # rather than inferred from a successful synthesis.
    try:
        groups = adapter.english_word_phoneme_groups(JAPANESE)
        flattened = [phone for _label, phones in groups for phone in phones]
        print(
            "CURRENT_EN_WORD_GROUPING="
            + ("MATCHES_OVERRIDE" if flattened == PHONEMES else "DIFFERS_FROM_OVERRIDE"),
            flush=True,
        )
    except Exception as exc:
        print(
            f"CURRENT_EN_WORD_GROUPING=UNAVAILABLE {type(exc).__name__}: {exc}",
            flush=True,
        )

    if all(successes):
        print("RUNTIME_SYNTHESIS_PROBE_PASS", flush=True)
        return 0
    print("RUNTIME_SYNTHESIS_PROBE_BLOCKED", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
