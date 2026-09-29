"""UI-neutral state and lifecycle for one editable utterance."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterator

from .mixed_language import build_mixed_audio_query
from .output import SavedOutput
from .settings import Settings
from .styles import VoicegerStyle, get_style
from .synthesis import synthesize_audio_query
from .takes import TakeBatch, TakeCandidate
from .voiceger_adapter import VoicegerAdapter
from .voicevox_api_models import AudioQuery


def _validate_caption(caption: str) -> None:
    if not isinstance(caption, str):
        raise TypeError("caption must be a string")
    if not caption or not caption.strip():
        raise ValueError("caption must not be empty")
    if "\n" in caption or "\r" in caption:
        raise ValueError(
            "v1 supports one utterance per request; newlines are not supported"
        )


def _validate_settings(settings: Settings) -> None:
    if not isinstance(settings, Settings):
        raise TypeError("settings must be a Settings instance")


def _validate_query(query: AudioQuery) -> None:
    if not isinstance(query, AudioQuery):
        raise TypeError("query must be an AudioQuery instance")


class UtteranceSession:
    """Own one user-facing Caption, its synthesized query, settings, and takes."""

    def __init__(
        self,
        *,
        adapter: VoicegerAdapter,
        caption: str,
        query: AudioQuery,
        settings: Settings,
        pure_japanese_utterance_text: str | None = None,
    ) -> None:
        _validate_caption(caption)
        _validate_query(query)
        _validate_settings(settings)

        owned_query = deepcopy(query)
        owned_query.speedScale = settings.speed
        style = get_style(adapter.voiceger_root, settings.style_id)

        self._adapter = adapter
        self._caption = caption
        self._query = owned_query
        self._pure_japanese_utterance_text = None
        if owned_query.voicegerSegments is None:
            actual_text = (
                pure_japanese_utterance_text
                if pure_japanese_utterance_text is not None
                else caption
            )
            _validate_caption(actual_text)
            self._pure_japanese_utterance_text = actual_text
        self._settings = settings
        self._style = style
        self._active_batch: TakeBatch | None = None
        self._utterance_manually_edited = False

    @classmethod
    def from_text(
        cls,
        *,
        adapter: VoicegerAdapter,
        caption: str,
        settings: Settings,
    ) -> UtteranceSession:
        """Create the initial query from the supplied Caption."""

        _validate_caption(caption)
        adapter.ensure_japanese_dictionary_active()
        query = build_mixed_audio_query(
            caption,
            english_g2p=adapter.english_phonemes,
            output_sampling_rate=32000,
        )
        _validate_query(query)
        return cls(
            adapter=adapter,
            caption=caption,
            query=query,
            settings=settings,
            pure_japanese_utterance_text=(
                caption if query.voicegerSegments is None else None
            ),
        )

    @property
    def caption(self) -> str:
        """The current user-facing Caption used for accepted output text."""

        return self._caption

    @property
    def pure_japanese_utterance_text(self) -> str | None:
        """Actual source text for a pure-Japanese query, when applicable."""

        if self._query.voicegerSegments is not None:
            return None
        return self._pure_japanese_utterance_text

    @property
    def utterance_manually_edited(self) -> bool:
        return self._utterance_manually_edited

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

    def replace_caption(self, caption: str) -> None:
        """Replace only Caption, leaving query state and active takes untouched."""

        _validate_caption(caption)
        self._caption = caption

    def replace_query(
        self,
        query: AudioQuery,
        *,
        pure_japanese_utterance_text: str | None = None,
    ) -> None:
        """Install a committed query edit and invalidate takes from the old one."""

        _validate_query(query)
        replacement = deepcopy(query)
        replacement.speedScale = self._settings.speed
        actual_pure_japanese_text = self._pure_japanese_utterance_text
        if replacement.voicegerSegments is None:
            if pure_japanese_utterance_text is not None:
                _validate_caption(pure_japanese_utterance_text)
                actual_pure_japanese_text = pure_japanese_utterance_text
        else:
            actual_pure_japanese_text = None

        self.discard_takes()
        self._query = replacement
        self._pure_japanese_utterance_text = actual_pure_japanese_text
        self._utterance_manually_edited = True

    def build_pronunciation_from_caption(self) -> None:
        """Build and atomically install a fresh complete query from Caption."""

        self._adapter.ensure_japanese_dictionary_active()
        replacement_query = build_mixed_audio_query(
            self._caption,
            english_g2p=self._adapter.english_phonemes,
            output_sampling_rate=32000,
        )
        _validate_query(replacement_query)
        replacement_query = deepcopy(replacement_query)
        replacement_query.speedScale = self._settings.speed
        pure_japanese_text = (
            self._caption if replacement_query.voicegerSegments is None else None
        )

        self.discard_takes()
        self._query = replacement_query
        self._pure_japanese_utterance_text = pure_japanese_text
        self._utterance_manually_edited = False

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

    def preview_synthesis(self, query: AudioQuery) -> dict[str, Any]:
        """Synthesize a transient query without changing utterance or take state."""

        _validate_query(query)
        query_snapshot = AudioQuery.model_validate(query.model_dump())
        settings_snapshot = deepcopy(self._settings)
        style_snapshot = deepcopy(self._style)
        adapter = self._adapter
        query_snapshot.speedScale = settings_snapshot.speed
        return synthesize_audio_query(
            adapter=adapter,
            query=query_snapshot,
            style=style_snapshot,
            top_k=20,
            top_p=0.6,
            temperature=0.6,
        )

    def generate_takes(
        self,
        *,
        top_k: int = 20,
        top_p: float = 0.6,
        temperature: float = 0.6,
    ) -> Iterator[TakeCandidate]:
        """Start a take batch using a fixed snapshot of synthesis conditions."""

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
            style_name=style_snapshot.name,
            output_dir=settings_snapshot.output_dir,
            save_text=settings_snapshot.save_text,
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
        saved = batch.accept(
            take_number,
            source_text=self._caption,
            filename_text=self._caption,
        )
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
