"""Derived sorting, filtering, and stable-focus state for dictionary lists."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .openjtalk_dictionary import normalize_surface
from .user_dictionary import JapaneseWordType, UserDictionaryCore


JapaneseDictionarySort = Literal[
    "surface_asc",
    "surface_desc",
    "word_type",
    "priority_asc",
    "priority_desc",
    "added_asc",
    "added_desc",
]
EnglishDictionarySort = Literal[
    "surface_asc",
    "surface_desc",
    "added_asc",
    "added_desc",
]
JapaneseWordTypeFilter = Literal[
    "ALL",
    "PROPER_NOUN",
    "COMMON_NOUN",
    "VERB",
    "ADJECTIVE",
    "SUFFIX",
]

JAPANESE_SORT_MODES: tuple[JapaneseDictionarySort, ...] = (
    "surface_asc",
    "surface_desc",
    "word_type",
    "priority_asc",
    "priority_desc",
    "added_asc",
    "added_desc",
)
ENGLISH_SORT_MODES: tuple[EnglishDictionarySort, ...] = (
    "surface_asc",
    "surface_desc",
    "added_asc",
    "added_desc",
)
JAPANESE_WORD_TYPE_FILTERS: tuple[JapaneseWordTypeFilter, ...] = (
    "ALL",
    "PROPER_NOUN",
    "COMMON_NOUN",
    "VERB",
    "ADJECTIVE",
    "SUFFIX",
)

_WORD_TYPE_ORDER = {
    word_type.value: index
    for index, word_type in enumerate(JapaneseWordType)
}
_CONTEXT_TO_WORD_TYPE = {
    1348: JapaneseWordType.PROPER_NOUN.value,
    1345: JapaneseWordType.COMMON_NOUN.value,
    642: JapaneseWordType.VERB.value,
    20: JapaneseWordType.ADJECTIVE.value,
    1358: JapaneseWordType.SUFFIX.value,
}


@dataclass
class _ListPreferences:
    sort_mode: str
    text_query: str = ""
    word_type_filter: str = "ALL"
    filter_enabled: bool = False
    focused_identity: str | None = None


@dataclass(frozen=True)
class DictionaryListView:
    """One derived dictionary list plus stable identity and presentation metadata."""

    entries: tuple[Any, ...]
    identities: tuple[str, ...]
    total_count: int
    shown_count: int
    focused_identity: str | None
    focused_index: int | None
    sort_mode: str
    text_query: str
    filter_enabled: bool
    word_type_filter: str | None = None


class DictionaryListStateOwner:
    """Retain list preferences and derive views without mutating persistence order."""

    def __init__(self, core: UserDictionaryCore) -> None:
        self.core = core
        self._japanese = _ListPreferences(sort_mode="surface_asc")
        self._english = _ListPreferences(sort_mode="surface_asc")

    def set_japanese_sort(self, sort_mode: JapaneseDictionarySort) -> None:
        if sort_mode not in JAPANESE_SORT_MODES:
            raise ValueError(f"Unsupported Japanese dictionary sort mode: {sort_mode}")
        self._japanese.sort_mode = sort_mode

    def set_english_sort(self, sort_mode: EnglishDictionarySort) -> None:
        if sort_mode not in ENGLISH_SORT_MODES:
            raise ValueError(f"Unsupported English dictionary sort mode: {sort_mode}")
        self._english.sort_mode = sort_mode

    def set_japanese_filter(
        self,
        *,
        text_query: str,
        word_type_filter: JapaneseWordTypeFilter,
    ) -> None:
        if word_type_filter not in JAPANESE_WORD_TYPE_FILTERS:
            raise ValueError(
                f"Unsupported Japanese dictionary word type filter: {word_type_filter}"
            )
        self._japanese.text_query = str(text_query)
        self._japanese.word_type_filter = word_type_filter
        self._japanese.filter_enabled = (
            bool(self._japanese.text_query.strip()) or word_type_filter != "ALL"
        )

    def set_japanese_filter_enabled(self, enabled: bool) -> None:
        self._japanese.filter_enabled = bool(enabled)

    def set_english_filter(self, *, text_query: str) -> None:
        self._english.text_query = str(text_query)
        self._english.filter_enabled = bool(self._english.text_query.strip())

    def set_english_filter_enabled(self, enabled: bool) -> None:
        self._english.filter_enabled = bool(enabled)

    def remember_focus(self, language: Literal["ja", "en"], identity: str | None) -> None:
        preferences = self._japanese if language == "ja" else self._english
        preferences.focused_identity = None if identity is None else str(identity)

    @staticmethod
    def _restore_focus(
        preferences: _ListPreferences,
        identities: tuple[str, ...],
    ) -> tuple[str | None, int | None]:
        focused = preferences.focused_identity
        if focused in identities:
            index = identities.index(focused)
        elif identities:
            focused = identities[0]
            index = 0
        else:
            focused = None
            index = None
        preferences.focused_identity = focused
        return focused, index

    @staticmethod
    def _surface_sort(
        items: list[Any],
        *,
        surface,
        secondary,
        descending: bool,
    ) -> None:
        items.sort(key=secondary)
        items.sort(key=lambda item: surface(item).casefold(), reverse=descending)

    def japanese_view(self) -> DictionaryListView:
        entries = self.core.list_japanese_entries()
        items = [
            (identity, word, canonical_index)
            for canonical_index, (identity, word) in enumerate(entries.items())
        ]
        total_count = len(items)
        query = self._japanese.text_query.strip()
        if self._japanese.filter_enabled and query:
            surface_query = normalize_surface(query).casefold()
            pronunciation_query = query.casefold()
            items = [
                item
                for item in items
                if (
                    surface_query in item[1].surface.casefold()
                    or pronunciation_query in item[1].pronunciation.casefold()
                )
            ]

        word_type_filter = self._japanese.word_type_filter
        if self._japanese.filter_enabled and word_type_filter != "ALL":
            items = [
                item
                for item in items
                if _CONTEXT_TO_WORD_TYPE.get(item[1].context_id) == word_type_filter
            ]

        sort_mode = self._japanese.sort_mode
        if sort_mode == "surface_asc":
            self._surface_sort(
                items,
                surface=lambda item: item[1].surface,
                secondary=lambda item: (item[1].surface, item[0]),
                descending=False,
            )
        elif sort_mode == "surface_desc":
            self._surface_sort(
                items,
                surface=lambda item: item[1].surface,
                secondary=lambda item: (item[1].surface, item[0]),
                descending=True,
            )
        elif sort_mode == "word_type":
            items.sort(
                key=lambda item: (
                    _WORD_TYPE_ORDER.get(
                        _CONTEXT_TO_WORD_TYPE.get(item[1].context_id, ""),
                        len(_WORD_TYPE_ORDER),
                    ),
                    item[1].surface.casefold(),
                    item[1].surface,
                    item[0],
                )
            )
        elif sort_mode in {"priority_asc", "priority_desc"}:
            items.sort(
                key=lambda item: (
                    item[1].surface.casefold(),
                    item[1].surface,
                    item[0],
                )
            )
            items.sort(
                key=lambda item: item[1].priority,
                reverse=sort_mode == "priority_desc",
            )
        elif sort_mode == "added_desc":
            items.reverse()

        visible_entries = tuple((identity, word) for identity, word, _index in items)
        identities = tuple(identity for identity, _word, _index in items)
        focused_identity, focused_index = self._restore_focus(
            self._japanese,
            identities,
        )
        return DictionaryListView(
            entries=visible_entries,
            identities=identities,
            total_count=total_count,
            shown_count=len(visible_entries),
            focused_identity=focused_identity,
            focused_index=focused_index,
            sort_mode=sort_mode,
            text_query=self._japanese.text_query,
            filter_enabled=self._japanese.filter_enabled,
            word_type_filter=word_type_filter,
        )

    def english_view(self) -> DictionaryListView:
        entries = self.core.list_english_entries()
        items = [
            (identity, entry, canonical_index)
            for canonical_index, (identity, entry) in enumerate(entries.items())
        ]
        total_count = len(items)
        query = self._english.text_query.strip().casefold()
        if self._english.filter_enabled and query:
            items = [
                item
                for item in items
                if (
                    query in item[1].surface.casefold()
                    or query in " ".join(item[1].phonemes).casefold()
                )
            ]

        sort_mode = self._english.sort_mode
        if sort_mode == "surface_asc":
            self._surface_sort(
                items,
                surface=lambda item: item[1].surface,
                secondary=lambda item: (item[1].surface, item[0]),
                descending=False,
            )
        elif sort_mode == "surface_desc":
            self._surface_sort(
                items,
                surface=lambda item: item[1].surface,
                secondary=lambda item: (item[1].surface, item[0]),
                descending=True,
            )
        elif sort_mode == "added_desc":
            items.reverse()

        visible_entries = tuple(entry for _identity, entry, _index in items)
        identities = tuple(identity for identity, _entry, _index in items)
        focused_identity, focused_index = self._restore_focus(
            self._english,
            identities,
        )
        return DictionaryListView(
            entries=visible_entries,
            identities=identities,
            total_count=total_count,
            shown_count=len(visible_entries),
            focused_identity=focused_identity,
            focused_index=focused_index,
            sort_mode=sort_mode,
            text_query=self._english.text_query,
            filter_enabled=self._english.filter_enabled,
        )
