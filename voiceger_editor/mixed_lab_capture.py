"""Optional, per-utterance mixed LAB MRTE decode capture and validation."""

from __future__ import annotations

from contextlib import contextmanager
from types import MethodType
from typing import Any, Iterator


class MixedLabCapture:
    """Capture Voiceger decode inputs without changing synthesis on failure."""

    def __init__(self, inference_webui: Any, query: Any | None) -> None:
        self.records: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.expected_phone_ids: list[int] | None = None
        self.spans = None
        self._model = None
        self._patched_decode = None
        self._missing = object()
        self._original_instance = self._missing

        if query is None:
            return

        try:
            from .lab_mixed_attention import (
                build_mixed_lab_segment_spans,
                voiceger_ids_for_spans,
            )

            self.spans = build_mixed_lab_segment_spans(query)
            self.expected_phone_ids = voiceger_ids_for_spans(
                self.spans,
                cleaned_text_to_sequence=(
                    inference_webui.cleaned_text_to_sequence
                ),
                version=str(inference_webui.version),
            )
            self._model = inference_webui.vq_model
            original_decode = self._model.decode
            self._original_instance = self._model.__dict__.get(
                "decode", self._missing
            )

            def capture_decode(
                model,
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
                    attention = model.enc_p.mrte.cross_attention.attn
                    if attention is None:
                        raise RuntimeError(
                            "MRTE cross-attention is unavailable"
                        )
                    self.records.append(
                        {
                            "target_phone_ids": [
                                int(value)
                                for value in (
                                    text.detach().cpu().reshape(-1).tolist()
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
                    self.errors.append(f"{type(exc).__name__}: {exc}")
                return decoded

            self._patched_decode = MethodType(capture_decode, self._model)
        except Exception as exc:
            self.errors.append(f"{type(exc).__name__}: {exc}")

    @contextmanager
    def installed_decode_hook(self) -> Iterator[None]:
        installed = False
        if self._model is not None and not self.errors:
            try:
                setattr(self._model, "decode", self._patched_decode)
                installed = True
            except Exception as exc:
                self.errors.append(f"{type(exc).__name__}: {exc}")
        try:
            yield
        finally:
            if installed:
                if self._original_instance is self._missing:
                    delattr(self._model, "decode")
                else:
                    setattr(
                        self._model, "decode", self._original_instance
                    )

    def result(self, audio: Any) -> tuple[Any | None, str | None]:
        """Preserve the existing target-ID check and warning precedence."""
        if self.errors:
            return None, (
                "mixed LAB timing capture failed: "
                + "; ".join(self.errors)
            )
        if len(self.records) != 1:
            return None, (
                "mixed LAB timing capture requires exactly one "
                f"Voiceger decode, got {len(self.records)}"
            )
        record = self.records[0]
        if (
            self.expected_phone_ids is None
            or record["target_phone_ids"] != self.expected_phone_ids
        ):
            return None, (
                "mixed LAB target phone IDs do not match the "
                "adapter-owned pronunciation"
            )
        if self.spans is None:
            return None, "mixed LAB segment phone spans are unavailable"
        try:
            from .lab_mixed_attention import derive_mixed_lab_provenance

            provenance = derive_mixed_lab_provenance(
                self.spans,
                record["attention"],
                raw_speech_sample_count=record["raw_speech_sample_count"],
                raw_speech_sampling_rate=record["raw_speech_sampling_rate"],
                raw_audio=audio,
            )
        except Exception as exc:
            return None, (
                "mixed LAB timing capture failed: "
                f"{type(exc).__name__}: {exc}"
            )
        return provenance, None
