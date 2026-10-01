"""Runtime integration with a locally installed Voiceger.

The adapter does not modify Voiceger files. It imports the installed
Voiceger/GPT-SoVITS runtime, temporarily replaces the Japanese and English
G2P functions for one target utterance, then restores the original functions.
"""

from __future__ import annotations

from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import replace
import os
from pathlib import Path
import sys
from threading import RLock
from types import MethodType
from typing import Any, Optional

from .english_stress import normalize_english_phonemes
from .openjtalk_converter import text_to_pronunciation
from .output import save_output
from .pronunciation import AccentPhrase, Pronunciation, format_pronunciation, parse_pronunciation
from .runtime_locks import LANGSEGMENT_LOCK, OPENJTALK_LOCK
from .user_dictionary import UserDictionaryCore
from .voiceger_tokens import pronunciation_to_voiceger_tokens


_SENTENCE_END = {
    "。": "。",
    ".": "。",
    "！": "！",
    "!": "！",
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


def pronunciation_to_spoken_text(value: Pronunciation) -> str:
    """Build plain kana text from resolved pronunciation data."""

    text = "".join(phrase.reading for phrase in value.phrases)
    if value.terminator is not None:
        text += value.terminator
    return text


def resolve_pronunciation(
    text: str,
    pronunciation: Optional[str] = None,
) -> tuple[str, Pronunciation, str]:
    """Resolve target text and pronunciation without loading Voiceger."""

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
        voiceger_root: Optional[str | Path] = None,
        output_dir: Optional[str | Path] = None,
    ) -> None:
        self.voiceger_root = Path(
            voiceger_root
            or os.environ.get("VOICEGER_ROOT")
            or (Path.home() / "voiceger_v2")
        ).expanduser().resolve()

        self.sovits_dir = self.voiceger_root / "GPT-SoVITS"
        self.gpt_sovits_dir = self.sovits_dir / "GPT_SoVITS"
        self.gpt_model = (
            self.voiceger_root
            / "GPT_weights_v2"
            / "zudamon_style_1-e15.ckpt"
        )
        self.sovits_model = (
            self.voiceger_root
            / "SoVITS_weights_v2"
            / "zudamon_style_1_e8_s96.pth"
        )
        self.default_ref_wav = self.voiceger_root / "reference" / "reference.wav"
        self.default_ref_text = self.voiceger_root / "reference" / "ref_text.txt"

        self.output_dir = Path(
            output_dir
            or os.environ.get("VOICEGER_ACCENT_OUTPUT_DIR")
            or (Path.home() / ".voiceger-accent-adapter" / "output")
        ).expanduser().resolve()

        self.character_name = os.environ.get(
            "VOICEGER_CHARACTER_NAME",
            "ずんだもん",
        )

        self.user_dictionary = UserDictionaryCore(self.voiceger_root)

        self._lock = RLock()
        self._loaded = False
        self._runtime: dict[str, Any] = {}

    def ensure_japanese_dictionary_active(self, *, force: bool = False) -> None:
        """Activate the merged Voiceger and adapter Japanese dictionary."""

        self.user_dictionary.ensure_japanese_active(force=force)

    def japanese_dictionary_pronunciation(self, text: str) -> Pronunciation:
        """Return one editable dictionary-word pronunciation for Japanese text."""

        self.ensure_japanese_dictionary_active()
        parsed = resolve_pronunciation(text)[1]
        morae = tuple(
            mora
            for phrase in parsed.phrases
            for mora in phrase.morae
        )
        final_phrase_offset = sum(
            len(phrase.morae)
            for phrase in parsed.phrases[:-1]
        )
        accent = final_phrase_offset + parsed.phrases[-1].accent
        return Pronunciation(
            phrases=(AccentPhrase(morae=morae, accent=accent),),
            terminator=None,
        )

    def _require_paths(self) -> None:
        required = [
            self.sovits_dir,
            self.gpt_sovits_dir,
            self.gpt_model,
            self.sovits_model,
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise VoicegerAdapterError(
                "required Voiceger paths are missing: " + ", ".join(missing)
            )

    def _require_text_paths(self) -> None:
        required = [self.sovits_dir, self.gpt_sovits_dir]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise VoicegerAdapterError(
                "required Voiceger text paths are missing: " + ", ".join(missing)
            )

    def _ensure_import_paths(self) -> None:
        for path in (self.sovits_dir, self.gpt_sovits_dir):
            value = str(path)
            if value not in sys.path:
                sys.path.insert(0, value)

    def english_phonemes(self, text: str) -> list[str]:
        """Return Voiceger's editable English ARPAbet tokens for text."""

        if not text or not text.strip():
            raise ValueError("English segment text must not be empty")
        if "\n" in text or "\r" in text:
            raise ValueError("English segment text must not contain newlines")

        dictionary_hit = self.user_dictionary.lookup_english_entry(text)
        if dictionary_hit is not None:
            return dictionary_hit

        groups = self.english_word_phoneme_groups(text)
        return [phoneme for _label, group in groups for phoneme in group]

    def english_word_phoneme_groups(
        self, text: str
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Return Voiceger-tokenized groups from its whole-segment G2P pass.

        Voiceger's public ``english.g2p`` removes the separator entries that
        its internal whole-segment pass emits between tokenizer groups. Keep
        that pass, tokenizer, and post-processing behind this adapter boundary,
        then prove that flattening the groups is exactly the public result.
        """

        if not text or not text.strip():
            raise ValueError("English segment text must not be empty")
        if "\n" in text or "\r" in text:
            raise ValueError("English segment text must not contain newlines")

        dictionary_hit = self.user_dictionary.lookup_english_entry(text)
        if dictionary_hit is not None:
            return ((text, tuple(dictionary_hit)),)

        with self._lock:
            self._require_text_paths()
            self._ensure_import_paths()
            with _pushd(self.sovits_dir):
                import text.english as english

            normalized = english.text_normalize(text)
            labels = list(english.word_tokenize(normalized))
            try:
                internal = list(english._g2p(normalized))
            except Exception as exc:
                raise VoicegerAdapterError(
                    "Voiceger English whole-segment token boundaries are unavailable"
                ) from exc

            raw_groups: list[list[str]] = [[]]
            for phoneme in internal:
                if phoneme == " ":
                    if not raw_groups[-1]:
                        raise VoicegerAdapterError(
                            "Voiceger English G2P returned an empty token boundary"
                        )
                    raw_groups.append([])
                else:
                    raw_groups[-1].append(phoneme)
            if raw_groups and not raw_groups[-1]:
                raw_groups.pop()

            if len(labels) != len(raw_groups):
                raise VoicegerAdapterError(
                    "Voiceger English tokenizer and G2P token boundaries disagree"
                )

            def public_postprocess(values: list[str]) -> tuple[str, ...]:
                mapped = [
                    "UNK" if phoneme == "<unk>" else phoneme
                    for phoneme in values
                    if phoneme not in {" ", "<pad>", "UW", "</s>", "<s>"}
                ]
                return tuple(english.replace_phs(mapped))

            groups = tuple(
                (label, public_postprocess(group))
                for label, group in zip(labels, raw_groups)
            )
            flattened = [phoneme for _label, group in groups for phoneme in group]
            canonical = list(english.g2p(normalized))
            if flattened != canonical:
                raise VoicegerAdapterError(
                    "Voiceger English token grouping does not reproduce its "
                    "canonical whole-segment G2P output"
                )

            # Prove the baseline grouping reproduces Voiceger before applying
            # user-dictionary overrides. Dictionary words are then resolved
            # independently, so an exact word hit works inside a larger segment
            # without substring replacement.
            for _label, group in groups:
                if group:
                    normalize_english_phonemes(group)

            resolved: list[tuple[str, tuple[str, ...]]] = []
            for label, group in groups:
                dictionary_word = (
                    self.user_dictionary.lookup_english_entry(label)
                    if any(character.isalpha() for character in label)
                    else None
                )
                if dictionary_word is None:
                    resolved.append((label, group))
                else:
                    resolved.append(
                        (
                            label,
                            tuple(normalize_english_phonemes(dictionary_word)),
                        )
                    )
            return tuple(resolved)

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

            self._ensure_import_paths()

            with _pushd(self.sovits_dir):
                from AR.modules.activation import MhaPatched
                import text.english as english
                with self.user_dictionary.voiceger_japanese_runtime_transition():
                    import text.japanese as japanese
                    import GPT_SoVITS.inference_webui as inference_webui

                with MhaPatched():
                    inference_webui.change_gpt_weights(
                        gpt_path=str(self.gpt_model)
                    )
                    inference_webui.change_sovits_weights(
                        sovits_path=str(self.sovits_model)
                    )

            self._runtime = {
                "MhaPatched": MhaPatched,
                "english": english,
                "japanese": japanese,
                "inference_webui": inference_webui,
                "get_tts_wav": inference_webui.get_tts_wav,
            }
            self._loaded = True

    def synthesize_audio(
        self,
        *,
        text: str,
        pronunciation: Optional[str] = None,
        ref_wav_path: Optional[str | Path] = None,
        prompt_text: Optional[str] = None,
        top_k: int = 20,
        top_p: float = 1.0,
        temperature: float = 1.0,
        speed: float = 1.0,
    ) -> dict[str, Any]:
        """Synthesize one utterance and return audio in memory."""

        source_text = _ensure_single_utterance(text)
        if pronunciation is None:
            self.user_dictionary.ensure_japanese_active()
        synthesis_text, parsed, resolved = resolve_pronunciation(
            source_text,
            pronunciation,
        )
        tokens = pronunciation_to_voiceger_tokens(parsed)

        selected_ref_wav = Path(
            ref_wav_path or self.default_ref_wav
        ).expanduser().resolve()
        if not selected_ref_wav.is_file():
            raise VoicegerAdapterError(
                f"reference WAV not found: {selected_ref_wav}"
            )

        if prompt_text is None:
            if not self.default_ref_text.is_file():
                raise VoicegerAdapterError(
                    f"reference text not found: {self.default_ref_text}"
                )
            selected_prompt_text = self.default_ref_text.read_text(
                encoding="utf-8"
            ).strip()
        else:
            selected_prompt_text = prompt_text.strip()

        if not selected_prompt_text:
            raise VoicegerAdapterError("reference prompt text must not be empty")

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
                with OPENJTALK_LOCK:
                    return original_g2p(norm_text, with_prosody)

            try:
                japanese.g2p = controlled_g2p
                with _pushd(self.sovits_dir):
                    with MhaPatched():
                        results = list(
                            get_tts_wav(
                                ref_wav_path=str(selected_ref_wav),
                                prompt_text=selected_prompt_text,
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
            return {
                "audio": audio,
                "sampling_rate": int(sample_rate),
                "resolved_pronunciation": resolved,
            }

    def synthesize_mixed_audio(
        self,
        *,
        text: str,
        japanese_overrides: list[tuple[str, list[str]]],
        text_language: str,
        english_overrides: Optional[list[tuple[str, list[str]]]] = None,
        ref_wav_path: Optional[str | Path] = None,
        prompt_text: Optional[str] = None,
        top_k: int = 20,
        top_p: float = 1.0,
        temperature: float = 1.0,
        speed: float = 1.0,
        mixed_lab_query: Any | None = None,
    ) -> dict[str, Any]:
        """Synthesize mixed-language text with Japanese/English G2P overrides."""

        synthesis_text = _ensure_single_utterance(text)

        selected_ref_wav = Path(
            ref_wav_path or self.default_ref_wav
        ).expanduser().resolve()
        if not selected_ref_wav.is_file():
            raise VoicegerAdapterError(
                f"reference WAV not found: {selected_ref_wav}"
            )

        if prompt_text is None:
            if not self.default_ref_text.is_file():
                raise VoicegerAdapterError(
                    f"reference text not found: {self.default_ref_text}"
                )
            selected_prompt_text = self.default_ref_text.read_text(
                encoding="utf-8"
            ).strip()
        else:
            selected_prompt_text = prompt_text.strip()

        if not selected_prompt_text:
            raise VoicegerAdapterError("reference prompt text must not be empty")

        self._ensure_runtime()

        with self._lock:
            english = self._runtime["english"]
            japanese = self._runtime["japanese"]
            inference_webui = self._runtime["inference_webui"]
            MhaPatched = self._runtime["MhaPatched"]
            get_tts_wav = self._runtime["get_tts_wav"]
            original_clean_text_inf = inference_webui.clean_text_inf
            original_japanese_g2p = japanese.g2p

            capture_records: list[dict[str, Any]] = []
            capture_errors: list[str] = []
            capture_installed = False
            capture_missing = object()
            capture_original_instance = capture_missing
            capture_model = None
            expected_mixed_phone_ids = None
            mixed_lab_spans = None

            if mixed_lab_query is not None:
                try:
                    from .lab_mixed_attention import (
                        build_mixed_lab_segment_spans,
                        voiceger_ids_for_spans,
                    )

                    mixed_lab_spans = build_mixed_lab_segment_spans(
                        mixed_lab_query
                    )
                    expected_mixed_phone_ids = voiceger_ids_for_spans(
                        mixed_lab_spans,
                        cleaned_text_to_sequence=(
                            inference_webui.cleaned_text_to_sequence
                        ),
                        version=str(inference_webui.version),
                    )
                    capture_model = inference_webui.vq_model
                    original_decode = capture_model.decode
                    capture_original_instance = capture_model.__dict__.get(
                        "decode",
                        capture_missing,
                    )

                    def capture_decode(
                        self,
                        codes,
                        text,
                        refer,
                        noise_scale=0.5,
                        speed=1,
                    ):
                        decoded = original_decode(
                            codes,
                            text,
                            refer,
                            noise_scale=noise_scale,
                            speed=speed,
                        )
                        try:
                            attention = self.enc_p.mrte.cross_attention.attn
                            if attention is None:
                                raise RuntimeError(
                                    "MRTE cross-attention is unavailable"
                                )
                            capture_records.append(
                                {
                                    "target_phone_ids": [
                                        int(value)
                                        for value in (
                                            text.detach()
                                            .cpu()
                                            .reshape(-1)
                                            .tolist()
                                        )
                                    ],
                                    "attention": (
                                        attention.detach()
                                        .float()
                                        .cpu()
                                        .numpy()
                                        .copy()
                                    ),
                                    "raw_speech_sample_count": int(
                                        decoded.shape[-1]
                                    ),
                                    "raw_speech_sampling_rate": int(
                                        inference_webui.hps.data.sampling_rate
                                    ),
                                }
                            )
                        except Exception as exc:
                            capture_errors.append(
                                f"{type(exc).__name__}: {exc}"
                            )
                        return decoded

                except Exception as exc:
                    capture_errors.append(
                        f"{type(exc).__name__}: {exc}"
                    )

            japanese_override_queues = defaultdict(deque)
            for segment_text, tokens in japanese_overrides:
                normalized = japanese.text_normalize(segment_text)
                japanese_override_queues[normalized].append(list(tokens))

            def canonical_english_text(value: str) -> str:
                normalized = english.text_normalize(value).strip()
                return normalized.strip(" .,!?…")

            english_override_entries = []
            for segment_text, tokens in english_overrides or []:
                english_override_entries.append(
                    {
                        "canonical": canonical_english_text(segment_text),
                        "tokens": normalize_english_phonemes(tokens),
                        "consumed": False,
                    }
                )

            def controlled_japanese_g2p(
                norm_text: str,
                with_prosody: bool = True,
            ):
                if with_prosody:
                    queue = japanese_override_queues.get(norm_text)
                    if queue:
                        return queue.popleft()
                with OPENJTALK_LOCK:
                    return original_japanese_g2p(norm_text, with_prosody)

            def controlled_clean_text_inf(
                value: str,
                language: str,
                version: str,
            ):
                if language == "en":
                    actual = canonical_english_text(value)
                    for entry in english_override_entries:
                        if actual == entry["canonical"]:
                            entry["consumed"] = True
                            phones = list(entry["tokens"])
                            phone_ids = inference_webui.cleaned_text_to_sequence(
                                phones,
                                version,
                            )
                            norm_text = english.text_normalize(value)
                            return phone_ids, None, norm_text
                return original_clean_text_inf(value, language, version)

            if capture_model is not None and not capture_errors:
                try:
                    setattr(
                        capture_model,
                        "decode",
                        MethodType(capture_decode, capture_model),
                    )
                    capture_installed = True
                except Exception as exc:
                    capture_errors.append(
                        f"{type(exc).__name__}: {exc}"
                    )

            try:
                inference_webui.clean_text_inf = controlled_clean_text_inf
                japanese.g2p = controlled_japanese_g2p
                with LANGSEGMENT_LOCK:
                    with _pushd(self.sovits_dir):
                        with MhaPatched():
                            results = list(
                                get_tts_wav(
                                    ref_wav_path=str(selected_ref_wav),
                                    prompt_text=selected_prompt_text,
                                    prompt_language="Japanese",
                                    text=synthesis_text,
                                    text_language=text_language,
                                    top_k=top_k,
                                    top_p=top_p,
                                    temperature=temperature,
                                    speed=speed,
                                )
                            )
            finally:
                inference_webui.clean_text_inf = original_clean_text_inf
                japanese.g2p = original_japanese_g2p
                if capture_installed and capture_model is not None:
                    if capture_original_instance is capture_missing:
                        delattr(capture_model, "decode")
                    else:
                        setattr(
                            capture_model,
                            "decode",
                            capture_original_instance,
                        )

            remaining_japanese = sum(
                len(queue)
                for queue in japanese_override_queues.values()
            )
            if remaining_japanese:
                raise VoicegerAdapterError(
                    "Voiceger mixed-language segmentation did not consume "
                    f"{remaining_japanese} Japanese pronunciation override(s)"
                )

            remaining_english = sum(
                1
                for entry in english_override_entries
                if not entry["consumed"]
            )
            if remaining_english:
                raise VoicegerAdapterError(
                    "Voiceger mixed-language segmentation did not consume "
                    f"{remaining_english} English phoneme override(s)"
                )

            if not results:
                raise VoicegerAdapterError("Voiceger returned no audio")

            sample_rate, audio = results[-1]
            response = {
                "audio": audio,
                "sampling_rate": int(sample_rate),
            }

            if mixed_lab_query is not None:
                provenance = None
                provenance_warning = None
                if capture_errors:
                    provenance_warning = (
                        "mixed LAB timing capture failed: "
                        + "; ".join(capture_errors)
                    )
                elif len(capture_records) != 1:
                    provenance_warning = (
                        "mixed LAB timing capture requires exactly one "
                        f"Voiceger decode, got {len(capture_records)}"
                    )
                elif (
                    expected_mixed_phone_ids is None
                    or capture_records[0]["target_phone_ids"]
                    != expected_mixed_phone_ids
                ):
                    provenance_warning = (
                        "mixed LAB target phone IDs do not match the "
                        "adapter-owned pronunciation"
                    )
                elif mixed_lab_spans is None:
                    provenance_warning = (
                        "mixed LAB segment phone spans are unavailable"
                    )
                else:
                    try:
                        from .lab_mixed_attention import (
                            derive_mixed_lab_provenance,
                        )

                        provenance = derive_mixed_lab_provenance(
                            mixed_lab_spans,
                            capture_records[0]["attention"],
                            raw_speech_sample_count=(
                                capture_records[0][
                                    "raw_speech_sample_count"
                                ]
                            ),
                            raw_speech_sampling_rate=(
                                capture_records[0][
                                    "raw_speech_sampling_rate"
                                ]
                            ),
                            raw_audio=audio,
                        )
                    except Exception as exc:
                        provenance_warning = (
                            "mixed LAB timing capture failed: "
                            f"{type(exc).__name__}: {exc}"
                        )
                response["mixed_lab_provenance"] = provenance
                response["mixed_lab_provenance_warning"] = (
                    provenance_warning
                )

            return response

    def synthesize(
        self,
        *,
        text: str,
        pronunciation: Optional[str] = None,
        ref_wav_path: Optional[str | Path] = None,
        prompt_text: Optional[str] = None,
        style_name: str = "style_1",
        top_k: int = 20,
        top_p: float = 1.0,
        temperature: float = 1.0,
        speed: float = 1.0,
        save_text: bool = False,
    ) -> dict[str, Any]:
        """Synthesize and persist a WAV for local helper/CLI use."""

        source_text = _ensure_single_utterance(text)
        result = self.synthesize_audio(
            text=source_text,
            pronunciation=pronunciation,
            ref_wav_path=ref_wav_path,
            prompt_text=prompt_text,
            top_k=top_k,
            top_p=top_p,
            temperature=temperature,
            speed=speed,
        )

        try:
            saved = save_output(
                audio=result["audio"],
                sampling_rate=result["sampling_rate"],
                source_text=text,
                style_name=style_name,
                output_dir=self.output_dir,
                save_text=save_text,
                filename_text=source_text,
            )
        except ImportError as exc:
            raise VoicegerAdapterError(
                "soundfile is required to write synthesized WAV files"
            ) from exc

        return {
            "file_name": saved.wav_path.name,
            "file_path": str(saved.wav_path),
            "text_file_path": (
                str(saved.text_path) if saved.text_path is not None else None
            ),
            "sampling_rate": result["sampling_rate"],
            "resolved_pronunciation": result["resolved_pronunciation"],
        }
