"""Per-utterance Japanese and English override preparation and consumption."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from .english_stress import normalize_english_phonemes
from .runtime_locks import OPENJTALK_LOCK


class MixedPronunciationOverrides:
    """Track exact override consumption without owning runtime patch lifetime."""

    def __init__(
        self,
        *,
        japanese: Any,
        english: Any,
        inference_webui: Any,
        japanese_overrides: list[tuple[str, list[str]]],
        english_overrides: list[tuple[str, list[str]]] | None,
    ) -> None:
        self._japanese = japanese
        self._english = english
        self._inference_webui = inference_webui
        self._original_japanese_g2p = japanese.g2p
        self._original_clean_text_inf = inference_webui.clean_text_inf

        self._japanese_queues: dict[str, deque[list[str]]] = defaultdict(deque)
        for segment_text, tokens in japanese_overrides:
            canonical = self._canonical_japanese(segment_text)
            self._japanese_queues[canonical].append(list(tokens))

        self._english_entries: list[dict[str, Any]] = []
        for segment_text, tokens in english_overrides or []:
            self._english_entries.append(
                {
                    "canonical": self._canonical_english(segment_text),
                    "tokens": normalize_english_phonemes(tokens),
                    "consumed": False,
                }
            )

    def _canonical_japanese(self, value: str) -> str:
        normalized = self._japanese.text_normalize(value).strip()
        return normalized.rstrip(" .,!?。！？…、，：；·")

    def _canonical_english(self, value: str) -> str:
        normalized = self._english.text_normalize(value).strip()
        return normalized.strip(" .,!?…")

    def japanese_g2p(
        self,
        norm_text: str,
        with_prosody: bool = True,
    ):
        if with_prosody:
            queue = self._japanese_queues.get(
                self._canonical_japanese(norm_text)
            )
            if queue:
                return queue.popleft()
        with OPENJTALK_LOCK:
            return self._original_japanese_g2p(norm_text, with_prosody)

    def clean_text_inf(
        self,
        value: str,
        language: str,
        version: str,
    ):
        if language == "en":
            actual = self._canonical_english(value)
            for entry in self._english_entries:
                if actual == entry["canonical"]:
                    entry["consumed"] = True
                    phones = list(entry["tokens"])
                    phone_ids = self._inference_webui.cleaned_text_to_sequence(
                        phones, version
                    )
                    norm_text = self._english.text_normalize(value)
                    return phone_ids, None, norm_text
        return self._original_clean_text_inf(value, language, version)

    @property
    def remaining_japanese(self) -> int:
        return sum(len(queue) for queue in self._japanese_queues.values())

    @property
    def remaining_english(self) -> int:
        return sum(1 for entry in self._english_entries if not entry["consumed"])
