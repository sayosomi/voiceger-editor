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

TARGET_TEXT = "雨、雨、雨。"

# Same spoken phonemes, different prosody symbols.
RAIN_TOKENS = [
    "a", "]", "m", "e", ",",
    "a", "]", "m", "e", ",",
    "a", "]", "m", "e", ".",
]
CANDY_TOKENS = [
    "a", "[", "m", "e", ",",
    "a", "[", "m", "e", ",",
    "a", "[", "m", "e", ".",
]


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
            top_k=1,
            top_p=1,
            temperature=0.1,
        )
    )
    if not result_list:
        raise RuntimeError(f"No audio returned for {label}")

    sample_rate, audio = result_list[-1]
    out = output_dir / f"{label}.wav"
    sf.write(out, audio, sample_rate)
    print(f"[{label}] wrote {out}")
    return out


def main() -> None:
    output_dir = Path(__file__).resolve().parent.parent / "spike-output"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Voiceger:", VOICEGER_ROOT)
    print("Python:", sys.executable)
    print("Built-in 雨:", ORIGINAL_G2P("雨"))
    print("Built-in 飴:", ORIGINAL_G2P("飴"))
    print("Target text:", TARGET_TEXT)

    try:
        with MhaPatched():
            change_gpt_weights(gpt_path=str(GPT_MODEL))
            change_sovits_weights(sovits_path=str(SOVITS_MODEL))
            rain = synthesize("rain-accent", RAIN_TOKENS, output_dir)
            candy = synthesize("candy-accent", CANDY_TOKENS, output_dir)
    finally:
        japanese.g2p = ORIGINAL_G2P

    print("\nCompare these two files:")
    print(rain)
    print(candy)
    print(
        "\nThey use the same visible text and phonemes; only the injected "
        "prosody marker differs (] vs [)."
    )


if __name__ == "__main__":
    main()
