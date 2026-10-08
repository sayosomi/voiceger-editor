"""Exception-safe installation of per-utterance Voiceger mixed runtime hooks."""

from __future__ import annotations

from contextlib import contextmanager
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
) -> Iterator[None]:
    """Restore all patched surfaces before the adapter releases its lock.

    The caller owns runtime serialization; this scope must remain inside
    VoicegerAdapter._lock. LAB decode capture is optional and non-fatal.
    """
    original_clean = inference_webui.clean_text_inf
    original_japanese = japanese.g2p
    with capture.installed_decode_hook():
        try:
            inference_webui.clean_text_inf = overrides.clean_text_inf
            japanese.g2p = overrides.japanese_g2p
            yield
        finally:
            try:
                inference_webui.clean_text_inf = original_clean
            finally:
                japanese.g2p = original_japanese
