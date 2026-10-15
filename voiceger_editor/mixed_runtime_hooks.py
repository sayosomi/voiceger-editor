"""Exception-safe installation of per-utterance Voiceger mixed runtime hooks."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Sequence
from typing import Any, Iterator

from .mixed_lab_capture import MixedLabCapture
from .mixed_pronunciation_overrides import MixedPronunciationOverrides


@contextmanager
def scoped_mixed_runtime_hooks(
    *,
    japanese: Any,
    inference_webui: Any,
    overrides: MixedPronunciationOverrides,
    capture: MixedLabCapture,
    language_segments: Sequence[tuple[str, str]] | None = None,
) -> Iterator[None]:
    """Restore all patched surfaces before the adapter releases its lock.

    The caller owns runtime serialization; this scope must remain inside
    VoicegerAdapter._lock. LAB decode capture is optional and non-fatal.
    """
    original_clean = inference_webui.clean_text_inf
    original_japanese = japanese.g2p
    langsegment = None
    original_get_texts = None

    if language_segments is not None:
        langsegment = getattr(inference_webui, "LangSegment", None)
        if langsegment is None:
            raise RuntimeError("Voiceger's LangSegment runtime is unavailable")
        expected = tuple(language_segments)
        source = "".join(value for _, value in expected)
        if not expected or any(lang not in {"ja", "en"} or not value for lang, value in expected):
            raise ValueError("Invalid JA/EN runtime segments")

        original_get_texts = langsegment.getTexts

        def matching_segments(value: str):
            # Voiceger may append a Japanese period immediately before G2P.
            if value == source:
                resolved = expected
            elif value == source + "。":
                resolved = (*expected[:-1], (expected[-1][0], expected[-1][1] + "。"))
            else:
                raise ValueError(
                    "Voiceger altered the mixed Caption before pronunciation "
                    f"segmentation: {value!r}"
                )
            return [{"lang": lang, "text": text} for lang, text in resolved]

    with capture.installed_decode_hook():
        try:
            inference_webui.clean_text_inf = overrides.clean_text_inf
            japanese.g2p = overrides.japanese_g2p
            if langsegment is not None:
                langsegment.getTexts = matching_segments
            yield
        finally:
            try:
                if langsegment is not None:
                    langsegment.getTexts = original_get_texts
            finally:
                try:
                    inference_webui.clean_text_inf = original_clean
                finally:
                    japanese.g2p = original_japanese
