#!/usr/bin/env python3
"""Spike: inject Japanese prosody tokens into Voiceger at runtime.

This does not modify Voiceger files. It temporarily replaces text.japanese.g2p
inside the running Python process and synthesizes the same visible text with
two different pitch-accent token sequences.

Expected local layout by default:
  ~/voiceger_v2/
  ~/Code/voiceger-accent-adapter/   (this repository)

Run with Voiceger's virtualenv:
  ~/voiceger_v2/.venv/bin/python scripts/spike_inject_prosody.py
"""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch


VOICEGER_ROOT = Path(
    os.environ.get("VOICEGER_ROOT", str(Path.home() / "voiceger_v2"))
).expanduser().resolve()
SOVITS_DIR = VOICEGER_ROOT / "GPT-SoVITS"
GPT_SOVITS_DIR = SOVITS_DIR / "GPT_SoVITS"

GPT_MODEL = VOICEGER_ROOT / "GPT_weights_v2" / "zudamon_style_1-e15.ckpt"
SOVITS_MODEL = VOICEGER_ROOT / "SoVITS_weights_v2" / "zudamon_style_1_e8_s96.pth"
REF_WAV = VOICEGER_ROOT / "reference" / "reference.wav"
REF_TEXT = VOICEGER_ROOT / "reference" / "ref_text.txt"

# A natural sentence is deliberately used here. Very short/repetitive text can
# make the autoregressive semantic decoder unstable and obscure the actual
# prosody experiment.
TARGET_TEXT = "今日は雨ですね。"

# Use Voiceger's own normal inference defaults. The first version of this spike
# intentionally used near-greedy decoding (top_k=1, temperature=0.1) for
# repeatability, but that caused semantic-token runaway on this model.
TOP_K = 20
TOP_P = 0.6
TEMPERATURE = 0.6


def require(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"Required path not found: {path}")


for required in [
    SOVITS_DIR,
    GPT_SOVITS_DIR,
    GPT_MODEL,
    SOVITS_MODEL,
    REF_WAV,
    REF_TEXT,
]:
    require(required)

# Match Voiceger's normal launch environment as closely as possible.
os.environ.setdefault(
    "LOCALAPPDATA", str(Path.home() / "Library" / "Application Support")
)
os.environ["gpt_path"] = str(GPT_MODEL)
os.environ["sovits_path"] = str(SOVITS_MODEL)

sys.path.insert(0, str(SOVITS_DIR))
sys.path.insert(0, str(GPT_SOVITS_DIR))

# Some GPT-SoVITS internals resolve resources relative to this directory.
os.chdir(SOVITS_DIR)

from AR.modules.activation import MhaPatched  # noqa: E402
import text.japanese as japanese  # noqa: E402
from GPT_SoVITS.inference_webui import (  # noqa: E402
    change_gpt_weights,
    change_sovits_weights,
    get_tts_wav,
)


ORIGINAL_G2P = japanese.g2p


def reset_seed(seed: int = 12345) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def replace_once(tokens: list[str], old: list[str], new: list[str]) -> list[str]:
    """Replace exactly one token subsequence, or fail loudly."""
    matches = [
        i
        for i in range(len(tokens) - len(old) + 1)
        if tokens[i : i + len(old)] == old
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one {old!r} in {tokens!r}, found {len(matches)}"
        )
    i = matches[0]
    return tokens[:i] + new + tokens[i + len(old) :]


def synthesize(label: str, tokens: list[str], output_dir: Path) -> Path:
    def controlled_g2p(norm_text: str, with_prosody: bool = True):
        if norm_text == TARGET_TEXT:
            print(f"[{label}] injected g2p: {tokens}")
            return list(tokens)
        return ORIGINAL_G2P(norm_text, with_prosody)

    japanese.g2p = controlled_g2p
    reset_seed()

    prompt_text = REF_TEXT.read_text(encoding="utf-8").strip()

    result_list = list(
        get_tts_wav(
            ref_wav_path=str(REF_WAV),
            prompt_text=prompt_text,
            prompt_language="Japanese",
            text=TARGET_TEXT,
            text_language="Japanese",
            top_k=TOP_K,
            top_p=TOP_P,
            temperature=TEMPERATURE,
        )
    )
    if not result_list:
        raise RuntimeError(f"No audio returned for {label}")

    sample_rate, audio = result_list[-1]
    duration = len(audio) / sample_rate
    if duration > 15:
        print(
            f"WARNING: {label} is {duration:.1f}s long for a short sentence; "
            "semantic decoding may have run away."
        )

    out = output_dir / f"{label}.wav"
    sf.write(out, audio, sample_rate)
    print(f"[{label}] wrote {out} ({duration:.2f}s)")
    return out


def main() -> None:
    output_dir = Path(__file__).resolve().parent.parent / "spike-output"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Voiceger:", VOICEGER_ROOT)
    print("Python:", sys.executable)
    print("Built-in 雨:", ORIGINAL_G2P("雨"))
    print("Built-in 飴:", ORIGINAL_G2P("飴"))
    print("Target text:", TARGET_TEXT)

    baseline_tokens = ORIGINAL_G2P(TARGET_TEXT)
    print("Built-in target g2p:", baseline_tokens)

    # Keep the full natural sentence exactly as Voiceger/OpenJTalk generated it,
    # then change only the minimal-pair sequence for 雨:
    #   雨: a ] m e
    #   飴: a [ m e
    rain_tokens = list(baseline_tokens)
    candy_tokens = replace_once(
        baseline_tokens,
        ["a", "]", "m", "e"],
        ["a", "[", "m", "e"],
    )

    print("Rain tokens: ", rain_tokens)
    print("Candy tokens:", candy_tokens)

    try:
        with MhaPatched():
            change_gpt_weights(gpt_path=str(GPT_MODEL))
            change_sovits_weights(sovits_path=str(SOVITS_MODEL))
            rain = synthesize("rain-accent", rain_tokens, output_dir)
            candy = synthesize("candy-accent", candy_tokens, output_dir)
    finally:
        japanese.g2p = ORIGINAL_G2P

    print("\nCompare these two files:")
    print(rain)
    print(candy)
    print(
        "\nThey use the same visible sentence and the same Voiceger settings. "
        "Only the 雨/飴 pitch-accent marker is changed (] vs [)."
    )


if __name__ == "__main__":
    main()
