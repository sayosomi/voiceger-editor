"""UI-neutral state and lifecycle for one editable utterance."""

from __future__ import annotations

from copy import deepcopy
import json
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
            "0.1 supports one utterance per request; newlines are not supported"
        )


def _validate_settings(settings: Settings) -> None:
    if not isinstance(settings, Settings):
        raise TypeError("settings must be a Settings instance")


def _validate_query(query: AudioQuery) -> None:
    if not isinstance(query, AudioQuery):
        raise TypeError("query must be an AudioQuery instance")


_PREVIEW_TOP_K = 1
_PREVIEW_TOP_P = 1.0
_PREVIEW_TEMPERATURE = 1.0


def _preview_cache_key(
    *,
    adapter: VoicegerAdapter,
    query: AudioQuery,
    style: VoicegerStyle,
) -> tuple[str, int, str, str, str, str]:
    serialized_query = json.dumps(
        query.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return (
        serialized_query,
        style.id,
        style.name,
        style.filename,
        style.prompt_text,
        str(style.reference_path(adapter.voiceger_root)),
    )


class UtteranceSession:
    """Own one user-facing Caption, its synthesized query, settings, and takes."""

    def __init__(
        self,
        *,
        adapter: VoicegerAdapter,
        caption: str,
        query: AudioQuery | None,
        settings: Settings,
        pure_japanese_utterance_text: str | None = None,
    ) -> None:
        _validate_caption(caption)
        if query is not None:
            _validate_query(query)
        _validate_settings(settings)

        style = get_style(adapter.voiceger_root, settings.style_id)

        self._adapter = adapter
        self._caption = caption
        self._query: AudioQuery | None = None
        self._pure_japanese_utterance_text = None
        if query is not None:
            owned_query = deepcopy(query)
            owned_query.speedScale = settings.speed
            self._query = owned_query
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
        self._preview_cache: dict[
            tuple[str, int, str, str, str, str],
            dict[str, Any],
        ] = {}
        self._utterance_manually_edited = False

    @classmethod
    def from_caption(
        cls,
        *,
        adapter: VoicegerAdapter,
        caption: str,
        settings: Settings,
    ) -> UtteranceSession:
        """Create a lightweight Caption session without preparing its query."""

        _validate_caption(caption)
        _validate_settings(settings)
        return cls(
            adapter=adapter,
            caption=caption,
            query=None,
            settings=settings,
        )

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
    def is_prepared(self) -> bool:
        """Whether pronunciation/query preparation has completed successfully."""

        return self._query is not None

    @property
    def caption(self) -> str:
        """The current editable Caption, which may differ from the query."""

        return self._caption

    @property
    def pure_japanese_utterance_text(self) -> str | None:
        """Actual source text for a pure-Japanese query, when applicable."""

        if self._query is None or self._query.voicegerSegments is not None:
            return None
        return self._pure_japanese_utterance_text

    @property
    def synthesis_source_text(self) -> str:
        """Return the source text represented by the current synthesis query."""

        query = self._require_prepared_query()
        if query.voicegerSegments is not None:
            return "".join(
                segment.text for segment in query.voicegerSegments
            )
        return self._pure_japanese_utterance_text or ""

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
    def active_candidate_count(self) -> int:
        """Return the number of generated slots in the active batch."""

        return len(self.candidates)

    @property
    def query(self) -> AudioQuery:
        """Return a copy so callers cannot mutate session-owned query state."""

        return deepcopy(self._require_prepared_query())

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

    def prepare_from_caption(self) -> None:
        """Prepare and atomically install a fresh complete query from Caption."""

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

    def build_pronunciation_from_caption(self) -> None:
        """Rebuild pronunciation/query from the current Caption."""

        self.prepare_from_caption()

    def replace_settings(self, settings: Settings) -> None:
        """Resolve new settings before invalidating the current take batch."""

        _validate_settings(settings)
        style = get_style(self._adapter.voiceger_root, settings.style_id)
        replacement_query = (
            deepcopy(self._query) if self._query is not None else None
        )
        if replacement_query is not None:
            replacement_query.speedScale = settings.speed

        synthesis_fields = ("style_id", "speed", "top_k", "top_p", "temperature")
        if any(
            getattr(settings, name) != getattr(self._settings, name)
            for name in synthesis_fields
        ):
            self.discard_takes()
        self._settings = settings
        self._style = style
        self._query = replacement_query

    def preview_synthesis(self, query: AudioQuery) -> dict[str, Any]:
        """Synthesize or reuse a transient deterministic Preview result."""

        _validate_query(query)
        self._require_prepared_query()
        query_snapshot = AudioQuery.model_validate(query.model_dump())
        style_snapshot = deepcopy(self._style)
        adapter = self._adapter
        query_snapshot.speedScale = self._settings.speed
        cache_key = _preview_cache_key(
            adapter=adapter,
            query=query_snapshot,
            style=style_snapshot,
        )
        cached = self._preview_cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        result = synthesize_audio_query(
            adapter=adapter,
            query=query_snapshot,
            style=style_snapshot,
            top_k=_PREVIEW_TOP_K,
            top_p=_PREVIEW_TOP_P,
            temperature=_PREVIEW_TEMPERATURE,
        )
        self._preview_cache[cache_key] = dict(result)
        return dict(result)

    def generate_takes(
        self,
        *,
        take_count: int | None = None,
        top_k: int | None = None,
        top_p: float | None = None,
        temperature: float | None = None,
    ) -> Iterator[TakeCandidate]:
        """Start a take batch using a fixed snapshot of synthesis conditions."""

        if self._active_batch is not None:
            raise RuntimeError("a take batch is already active")

        query_snapshot = deepcopy(self._require_prepared_query())
        style_snapshot = self._style
        settings_snapshot = deepcopy(self._settings)
        source_text_snapshot = self.synthesis_source_text
        adapter = self._adapter
        resolved_take_count = (
            settings_snapshot.take_count if take_count is None else take_count
        )
        resolved_top_k = settings_snapshot.top_k if top_k is None else top_k
        resolved_top_p = settings_snapshot.top_p if top_p is None else top_p
        resolved_temperature = (
            settings_snapshot.temperature if temperature is None else temperature
        )

        def synthesize_one():
            synthesis_kwargs = {
                "adapter": adapter,
                "query": deepcopy(query_snapshot),
                "style": style_snapshot,
                "top_k": resolved_top_k,
                "top_p": resolved_top_p,
                "temperature": resolved_temperature,
            }
            if (
                query_snapshot.voicegerSegments
                and {
                    segment.language
                    for segment in query_snapshot.voicegerSegments
                }
                == {"ja", "en"}
            ):
                synthesis_kwargs["capture_mixed_lab_provenance"] = True
            return synthesize_audio_query(**synthesis_kwargs)

        batch = TakeBatch(
            take_count=resolved_take_count,
            synthesize_one=synthesize_one,
            style_name=style_snapshot.name,
            source_text=source_text_snapshot,
            query=query_snapshot,
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

    def regenerate_all_takes(
        self,
        *,
        take_count: int | None = None,
    ) -> Iterator[TakeCandidate]:
        resolved_take_count = (
            self._settings.take_count if take_count is None else take_count
        )
        return self._require_active_batch().regenerate_all(resolved_take_count)

    def accept_take(self, take_number: int) -> SavedOutput:
        batch = self._require_active_batch()
        accept_kwargs = {
            "output_dir": self._settings.output_dir,
            "save_text": self._settings.save_text,
        }
        if self._settings.save_lab:
            accept_kwargs["save_lab"] = True
        return batch.accept(
            take_number,
            **accept_kwargs,
        )

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

    def _require_prepared_query(self) -> AudioQuery:
        if self._query is None:
            raise RuntimeError("pronunciation/query is not prepared")
        return self._query

    def _require_active_batch(self) -> TakeBatch:
        if self._active_batch is None:
            raise RuntimeError("no take batch is active")
        return self._active_batch
