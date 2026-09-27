"""UI-neutral state and lifecycle for one editable utterance."""

from __future__ import annotations

from copy import deepcopy
from typing import Iterator

from .mixed_language import (
    build_mixed_audio_query,
    detect_language_segments,
    is_pure_japanese,
)
from .output import SavedOutput
from .settings import Settings
from .styles import VoicegerStyle, get_style
from .synthesis import synthesize_audio_query
from .takes import TakeBatch, TakeCandidate
from .voiceger_adapter import VoicegerAdapter
from .voicevox_api_models import AudioQuery


def _validate_source_text(source_text: str) -> None:
    if not isinstance(source_text, str):
        raise TypeError("source_text must be a string")
    if not source_text or not source_text.strip():
        raise ValueError("source_text must not be empty")
    if "\n" in source_text or "\r" in source_text:
        raise ValueError(
            "v1 supports one utterance per request; newlines are not supported"
        )


def _validate_settings(settings: Settings) -> None:
    if not isinstance(settings, Settings):
        raise TypeError("settings must be a Settings instance")


def _validate_query(query: AudioQuery) -> None:
    if not isinstance(query, AudioQuery):
        raise TypeError("query must be an AudioQuery instance")


def _query_language_signature(query: AudioQuery) -> tuple[str, ...]:
    if query.voicegerSegments is None:
        return ("ja",)
    return tuple(segment.language for segment in query.voicegerSegments)


class UtteranceSession:
    """Own one source utterance, its editable query, settings, and take batch."""

    def __init__(
        self,
        *,
        adapter: VoicegerAdapter,
        source_text: str,
        query: AudioQuery,
        settings: Settings,
    ) -> None:
        _validate_source_text(source_text)
        _validate_query(query)
        _validate_settings(settings)

        owned_query = deepcopy(query)
        owned_query.speedScale = settings.speed
        style = get_style(adapter.voiceger_root, settings.style_id)

        self._adapter = adapter
        self._source_text = source_text
        self._query = owned_query
        self._settings = settings
        self._style = style
        self._active_batch: TakeBatch | None = None
        self._pronunciation_needs_rebuild = False

    @classmethod
    def from_text(
        cls,
        *,
        adapter: VoicegerAdapter,
        source_text: str,
        settings: Settings,
    ) -> UtteranceSession:
        """Build an editable mixed-language query and own it in a session."""

        _validate_source_text(source_text)
        query = build_mixed_audio_query(
            source_text,
            english_g2p=adapter.english_phonemes,
            output_sampling_rate=32000,
        )
        return cls(
            adapter=adapter,
            source_text=source_text,
            query=query,
            settings=settings,
        )

    @property
    def source_text(self) -> str:
        return self._source_text

    @property
    def pronunciation_needs_rebuild(self) -> bool:
        return self._pronunciation_needs_rebuild

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def style(self) -> VoicegerStyle:
        return self._style

    @property
    def has_active_batch(self) -> bool:
        return self._active_batch is not None

    @property
    def candidates(self) -> tuple[TakeCandidate, ...]:
        if self._active_batch is None:
            return ()
        return self._active_batch.candidates

    @property
    def query(self) -> AudioQuery:
        """Return a copy so callers cannot mutate session-owned query state."""

        return deepcopy(self._query)

    def replace_query(self, query: AudioQuery) -> None:
        """Install an edited query and invalidate candidates from the old one."""

        _validate_query(query)
        replacement = deepcopy(query)
        replacement.speedScale = self._settings.speed

        self.discard_takes()
        self._query = replacement

    def replace_source_text(self, source_text: str) -> None:
        """Replace source text while retaining pronunciation for matching runs."""

        if source_text == self._source_text:
            return

        _validate_source_text(source_text)
        detected = detect_language_segments(source_text)
        detected_signature = (
            ("ja",)
            if is_pure_japanese(detected)
            else tuple(segment.language for segment in detected)
        )
        same_signature = detected_signature == _query_language_signature(
            self._query
        )

        replacement_query = deepcopy(self._query)
        if same_signature and replacement_query.voicegerSegments is not None:
            for segment, detected_segment in zip(
                replacement_query.voicegerSegments,
                detected,
            ):
                segment.text = detected_segment.text

        self.discard_takes()
        self._source_text = source_text
        if same_signature:
            self._query = replacement_query
            self._pronunciation_needs_rebuild = False
        else:
            self._pronunciation_needs_rebuild = True

    def rebuild_pronunciation(self) -> None:
        """Replace current pronunciation data with fresh automatic analysis."""

        replacement_query = deepcopy(
            build_mixed_audio_query(
                self._source_text,
                english_g2p=self._adapter.english_phonemes,
                output_sampling_rate=32000,
            )
        )
        _validate_query(replacement_query)
        replacement_query.speedScale = self._settings.speed

        self.discard_takes()
        self._query = replacement_query
        self._pronunciation_needs_rebuild = False

    def replace_settings(self, settings: Settings) -> None:
        """Resolve new settings before invalidating the current take batch."""

        _validate_settings(settings)
        style = get_style(self._adapter.voiceger_root, settings.style_id)
        replacement_query = deepcopy(self._query)
        replacement_query.speedScale = settings.speed

        self.discard_takes()
        self._settings = settings
        self._style = style
        self._query = replacement_query

    def generate_takes(
        self,
        *,
        top_k: int = 20,
        top_p: float = 0.6,
        temperature: float = 0.6,
    ) -> Iterator[TakeCandidate]:
        """Start a take batch using a fixed snapshot of synthesis conditions."""

        if self._pronunciation_needs_rebuild:
            raise RuntimeError(
                "pronunciation must be rebuilt after the source-text structure changed"
            )
        if self._active_batch is not None:
            raise RuntimeError("a take batch is already active")

        query_snapshot = deepcopy(self._query)
        style_snapshot = self._style
        settings_snapshot = deepcopy(self._settings)
        adapter = self._adapter

        def synthesize_one():
            return synthesize_audio_query(
                adapter=adapter,
                query=deepcopy(query_snapshot),
                style=style_snapshot,
                top_k=top_k,
                top_p=top_p,
                temperature=temperature,
            )

        batch = TakeBatch(
            take_count=settings_snapshot.take_count,
            synthesize_one=synthesize_one,
            source_text=self._source_text,
            output_dir=settings_snapshot.output_dir,
            save_text=settings_snapshot.save_text,
            filename_text=self._source_text,
        )
        try:
            iterator = batch.generate_all()
        except BaseException:
            batch.close()
            raise

        self._active_batch = batch
        return iterator

    def regenerate_take(self, take_number: int) -> TakeCandidate:
        return self._require_active_batch().regenerate(take_number)

    def regenerate_all_takes(self) -> Iterator[TakeCandidate]:
        return self._require_active_batch().regenerate_all()

    def accept_take(self, take_number: int) -> SavedOutput:
        batch = self._require_active_batch()
        saved = batch.accept(take_number)
        self._active_batch = None
        return saved

    def discard_takes(self) -> None:
        batch = self._active_batch
        if batch is None:
            return
        batch.close()
        self._active_batch = None

    def close(self) -> None:
        self.discard_takes()

    def __enter__(self) -> UtteranceSession:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _require_active_batch(self) -> TakeBatch:
        if self._active_batch is None:
            raise RuntimeError("no take batch is active")
        return self._active_batch
