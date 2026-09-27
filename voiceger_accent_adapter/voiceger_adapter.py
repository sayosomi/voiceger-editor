"""Runtime integration with a locally installed Voiceger.

The adapter does not modify Voiceger files. It imports the installed
Voiceger/GPT-SoVITS runtime, temporarily replaces the Japanese G2P function
for one target utterance, then restores the original function.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import os
from pathlib import Path
import sys
from threading import RLock
from typing import Any

from .filename import build_output_filename, next_output_index
from .openjtalk_converter import text_to_pronunciation
from .pronunciation import Pronunciation, format_pronunciation, parse_pronunciation
from .voiceger_tokens import pronunciation_to_voiceger_tokens


_SENTENCE_END = {
    "。": "。",
    "！": "。",
    "!": "。",
    "？": "？",
    "?": "？",
}

class VoicegerAdapterError(RuntimeError):
    """Raised when the local Voiceger runtime cannot be used safely."""


def _ensure_single_utterance(text: str) -> str:
    if not text or not text.strip():
        raise ValueError("text must not be empty")
    if "\n" in text or "\r" in text:
        raise ValueError(
            "v1 supports one utterance per request; newlines are not supported"
        )
    return text.strip()


def _text_terminator(text: str) -> str:
    return _SENTENCE_END.get(text[-1], "。")


def resolve_pronunciation(
    text: str,
    pronunciation: str | None = None,
) -> tuple[str, Pronunciation, str]:
    """Resolve target text and pronunciation without loading Voiceger.

    Returns:
        synthesis_text: text that will be passed to Voiceger
        parsed pronunciation
        canonical editable pronunciation string
    """

    source = _ensure_single_utterance(text)
    terminator = _text_terminator(source)

    if source[-1] not in _SENTENCE_END:
        synthesis_text = source + terminator
    else:
        synthesis_text = source

    if pronunciation is None:
        parsed = text_to_pronunciation(synthesis_text)
    else:
        parsed = parse_pronunciation(pronunciation)
        if parsed.terminator is None:
            parsed = replace(parsed, terminator=terminator)

    return synthesis_text, parsed, format_pronunciation(parsed)


@contextmanager
def _pushd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class VoicegerAdapter:
    """Lazy, serialized Voiceger runtime adapter."""

    def __init__(
        self,
        voiceger_root: str | Path | None = None,
        output_dir: str | Path | None = None,
    ) -> None:
        self.voiceger_root = Path(
            voiceger_root
            or os.environ.get("VOICEGER_ROOT")
            or (Path.home() / "voiceger_v2")
        ).expanduser().resolve()

        self.sovits_dir = self.voiceger_root / "GPT-SoVITS"
        self.gpt_sovits_dir = self.sovits_dir / "GPT_SoVITS"
        self.gpt_model = self.voiceger_root / "GPT_weights_v2" / "zudamon_style_1-e15.ckpt"
        self.sovits_model = self.voiceger_root / "SoVITS_weights_v2" / "zudamon_style_1_e8_s96.pth"
        self.ref_wav = self.voiceger_root / "reference" / "reference.wav"
        self.ref_text = self.voiceger_root / "reference" / "ref_text.txt"

        self.output_dir = Path(
            output_dir
            or os.environ.get("VOICEGER_ACCENT_OUTPUT_DIR")
            or (Path.home() / ".voiceger-accent-adapter" / "output")
        ).expanduser().resolve()

        self.character_name = os.environ.get(
            "VOICEGER_CHARACTER_NAME",
            "ずんだもん",
        )
        self.style_name = os.environ.get(
            "VOICEGER_STYLE_NAME",
            "style_1",
        )

        self._lock = RLock()
        self._loaded = False
        self._runtime: dict[str, Any] = {}

    def _require_paths(self) -> None:
        required = [
            self.sovits_dir,
            self.gpt_sovits_dir,
            self.gpt_model,
            self.sovits_model,
            self.ref_wav,
            self.ref_text,
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise VoicegerAdapterError(
                "required Voiceger paths are missing: " + ", ".join(missing)
            )

    def _ensure_runtime(self) -> None:
        if self._loaded:
            return

        with self._lock:
            if self._loaded:
                return

            self._require_paths()

            if sys.platform == "darwin":
                os.environ.setdefault(
                    "LOCALAPPDATA",
                    str(Path.home() / "Library" / "Application Support"),
                )
            os.environ["gpt_path"] = str(self.gpt_model)
            os.environ["sovits_path"] = str(self.sovits_model)

            for path in (self.sovits_dir, self.gpt_sovits_dir):
                value = str(path)
                if value not in sys.path:
                    sys.path.insert(0, value)

            with _pushd(self.sovits_dir):
                from AR.modules.activation import MhaPatched
                import text.japanese as japanese
                from GPT_SoVITS.inference_webui import (
                    change_gpt_weights,
                    change_sovits_weights,
                    get_tts_wav,
                )

                with MhaPatched():
                    change_gpt_weights(gpt_path=str(self.gpt_model))
                    change_sovits_weights(sovits_path=str(self.sovits_model))

            self._runtime = {
                "MhaPatched": MhaPatched,
                "japanese": japanese,
                "get_tts_wav": get_tts_wav,
            }
            self._loaded = True

    def synthesize(
        self,
        *,
        text: str,
        pronunciation: str | None = None,
        top_k: int = 20,
        top_p: float = 0.6,
        temperature: float = 0.6,
        speed: float = 1.0,
    ) -> dict[str, Any]:
        """Synthesize one Japanese utterance with optional pronunciation override."""

        source_text = _ensure_single_utterance(text)
        synthesis_text, parsed, resolved = resolve_pronunciation(
            source_text,
            pronunciation,
        )
        tokens = pronunciation_to_voiceger_tokens(parsed)

        self._ensure_runtime()

        with self._lock:
            japanese = self._runtime["japanese"]
            MhaPatched = self._runtime["MhaPatched"]
            get_tts_wav = self._runtime["get_tts_wav"]
            original_g2p = japanese.g2p

            normalized_target = japanese.text_normalize(synthesis_text)

            def controlled_g2p(norm_text: str, with_prosody: bool = True):
                if norm_text == normalized_target and with_prosody:
                    return list(tokens)
                return original_g2p(norm_text, with_prosody)

            prompt_text = self.ref_text.read_text(encoding="utf-8").strip()
            self.output_dir.mkdir(parents=True, exist_ok=True)

            try:
                japanese.g2p = controlled_g2p
                with _pushd(self.sovits_dir):
                    with MhaPatched():
                        results = list(
                            get_tts_wav(
                                ref_wav_path=str(self.ref_wav),
                                prompt_text=prompt_text,
                                prompt_language="Japanese",
                                text=synthesis_text,
                                text_language="Japanese",
                                top_k=top_k,
                                top_p=top_p,
                                temperature=temperature,
                                speed=speed,
                            )
                        )
            finally:
                japanese.g2p = original_g2p

            if not results:
                raise VoicegerAdapterError("Voiceger returned no audio")

            sample_rate, audio = results[-1]

            try:
                import soundfile as sf
            except ImportError as exc:
                raise VoicegerAdapterError(
                    "soundfile is required to write synthesized WAV files"
                ) from exc

            output_index = next_output_index(self.output_dir)
            file_name = build_output_filename(
                index=output_index,
                character_name=self.character_name,
                style_name=self.style_name,
                text=source_text,
            )
            output_path = self.output_dir / file_name
            sf.write(output_path, audio, sample_rate)

            return {
                "file_name": file_name,
                "file_path": str(output_path),
                "sampling_rate": int(sample_rate),
                "resolved_pronunciation": resolved,
            }
