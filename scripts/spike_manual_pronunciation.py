#!/usr/bin/env python3
"""End-to-end spike: editable pronunciation -> Voiceger synthesis.

This does not modify Voiceger files. It:
1. derives the default editable pronunciation from normal Japanese text;
2. parses either that pronunciation or a manually edited alternative;
3. converts it to Voiceger v2 Japanese phone/prosody tokens;
4. injects those tokens only for the running synthesis call.

Run:
  ~/voiceger_v2/.venv/bin/python scripts/spike_manual_pronunciation.py
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
REPO_ROOT = Path(__file__).resolve().parent.parent
SOVITS_DIR = VOICEGER_ROOT / "GPT-SoVITS"
GPT_SOVITS_DIR = SOVITS_DIR / "GPT_SoVITS"

GPT_MODEL = VOICEGER_ROOT / "GPT_weights_v2" / "zudamon_style_1-e15.ckpt"
SOVITS_MODEL = VOICEGER_ROOT / "SoVITS_weights_v2" / "zudamon_style_1_e8_s96.pth"
REF_WAV = VOICEGER_ROOT / "reference" / "reference.wav"
REF_TEXT = VOICEGER_ROOT / "reference" / "ref_text.txt"

TARGET_TEXT = "今日は雨ですね。"

# This manual variant moves the second accent phrase's accent position to its
# final mora. It therefore yields the same phrase-internal prosody shape as the
# successful earlier "[" spike, but now entirely through editable notation.
MANUAL_PRONUNCIATION = "キョ'ーワ/アメデスネ'。"

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

os.environ.setdefault(
    "LOCALAPPDATA", str(Path.home() / "Library" / "Application Support")
)
os.environ["gpt_path"] = str(GPT_MODEL)
os.environ["sovits_path"] = str(SOVITS_MODEL)

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SOVITS_DIR))
sys.path.insert(0, str(GPT_SOVITS_DIR))
os.chdir(SOVITS_DIR)

from AR.modules.activation import MhaPatched  # noqa: E402
import text.japanese as japanese  # noqa: E402
from GPT_SoVITS.inference_webui import (  # noqa: E402
    change_gpt_weights,
    change_sovits_weights,
    get_tts_wav,
)

from voiceger_editor.openjtalk_converter import (  # noqa: E402
    text_to_pronunciation,
)
from voiceger_editor.pronunciation import (  # noqa: E402
    format_pronunciation,
    parse_pronunciation,
)
from voiceger_editor.voiceger_tokens import (  # noqa: E402
    pronunciation_to_voiceger_tokens,
)


ORIGINAL_G2P = japanese.g2p


def reset_seed(seed: int = 12345) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def synthesize(
    label: str,
    pronunciation_text: str,
    output_dir: Path,
) -> Path:
    pronunciation = parse_pronunciation(pronunciation_text)
    tokens = pronunciation_to_voiceger_tokens(pronunciation)

    def controlled_g2p(norm_text: str, with_prosody: bool = True):
        if norm_text == TARGET_TEXT:
            print(f"[{label}] pronunciation: {pronunciation_text}")
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
    out = output_dir / f"{label}.wav"
    sf.write(out, audio, sample_rate)
    print(f"[{label}] wrote {out} ({duration:.2f}s)")
    return out


def main() -> None:
    output_dir = REPO_ROOT / "spike-output"
    output_dir.mkdir(parents=True, exist_ok=True)

    automatic = format_pronunciation(text_to_pronunciation(TARGET_TEXT))

    print("Voiceger:", VOICEGER_ROOT)
    print("Python:", sys.executable)
    print("Target text:", TARGET_TEXT)
    print("Automatic pronunciation:", automatic)
    print("Manual pronunciation:   ", MANUAL_PRONUNCIATION)

    try:
        with MhaPatched():
            change_gpt_weights(gpt_path=str(GPT_MODEL))
            change_sovits_weights(sovits_path=str(SOVITS_MODEL))
            automatic_wav = synthesize(
                "automatic-pronunciation",
                automatic,
                output_dir,
            )
            manual_wav = synthesize(
                "manual-pronunciation",
                MANUAL_PRONUNCIATION,
                output_dir,
            )
    finally:
        japanese.g2p = ORIGINAL_G2P

    print("\nCompare these two files:")
    print(automatic_wav)
    print(manual_wav)
    print(
        "\nThe visible text is identical. The second WAV differs only because "
        "the editable pronunciation string moved the second phrase accent."
    )


if __name__ == "__main__":
    main()
