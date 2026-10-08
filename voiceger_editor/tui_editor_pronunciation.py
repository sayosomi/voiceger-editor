"""Japanese/English pronunciation editor ownership."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from .english_stress import (
    EnglishPhonemeEditorState,
    english_phonemes_to_editor_state,
    normalize_english_phonemes,
)
from .pronunciation import (
    AccentPhrase as CoreAccentPhrase,
    PronunciationPunctuation as CorePronunciationPunctuation,
    canonicalize_punctuation,
    parse_pronunciation,
)
from .query_editing import (
    english_word_preview_query,
    japanese_pronunciation,
    japanese_preview_query,
    move_japanese_accent,
    replace_english_phoneme_groups,
    replace_japanese_pronunciation,
)
from .tui_display import _display_width
from .tui_editor_common import (
    ClearAdjustmentFeedbackIntent,
    EditorIntent,
    EditorOwnerBase,
    EditorState,
    OpenDictionaryIntent,
    PreviewIntent,
    ReplaceQueryIntent,
    SaveToDictionaryIntent,
    UpdateStatusIntent,
)
from .tui_editor_english import EnglishGroupingCache
from .tui_status import EMPTY_STATUS, error_status
from .voicevox_api_models import AudioQuery


@dataclass(frozen=True)
class PronunciationRow:
    """One selectable Japanese AccentPhrase or aligned English word group."""

    language: str
    source_text: str
    source_segment_index: int
    model_segment_index: int | None
    first_in_segment: bool
    phrase_index: int | None = None
    phrase_index_in_segment: int | None = None
    moras: tuple[str, ...] = ()
    accent: int | None = None
    group_index: int | None = None
    word: str | None = None
    phonemes: tuple[str, ...] = ()
    vowel_offset: int = 0
    word_column_width: int = 0
    grouping: EnglishGroupingCache | None = None
    punctuation_suffix: str = ""


def _punctuation_suffixes(value: str) -> tuple[str, ...]:
    """Return canonical punctuation grouped after each phrase in notation."""

    pronunciation = parse_pronunciation(value)
    suffixes: list[str] = []
    phrase_index = -1
    for item in pronunciation.items:
        if isinstance(item, CoreAccentPhrase):
            phrase_index += 1
            suffixes.append("")
        elif isinstance(item, CorePronunciationPunctuation):
            if phrase_index < 0:
                raise ValueError(
                    "pronunciation punctuation has no preceding phrase"
                )
            suffixes[phrase_index] += item.mark
        else:
            raise ValueError(f"unsupported pronunciation item: {item!r}")
    return tuple(suffixes)


class TuiPronunciationEditorOwner(EditorOwnerBase):
    """Own pronunciation rows and Japanese/English pronunciation edit policy."""

    @property
    def grouping_error(self):
        return self._host.grouping_error

    @grouping_error.setter
    def grouping_error(self, value) -> None:
        self._host.grouping_error = value


    def pronunciation_rows(
        self,
        query: AudioQuery,
        segments: Sequence[tuple[str, str, int | None]],
    ) -> tuple[PronunciationRow, ...]:
        """Build selectable phrase/word rows from current canonical query data."""

        rows: list[PronunciationRow] = []
        self.grouping_error = None
        for source_index, (language, source_text, model_index) in enumerate(segments):
            first = True
            if language == "ja":
                if query.voicegerSegments is None:
                    start, count = 0, len(query.accent_phrases)
                else:
                    if model_index is None or not 0 <= model_index < len(
                        query.voicegerSegments
                    ):
                        self.grouping_error = error_status("Japanese segment references are unavailable.")
                        continue
                    segment = query.voicegerSegments[model_index]
                    start = segment.accentPhraseStart
                    count = segment.accentPhraseCount
                    if (
                        segment.language != "ja"
                        or type(start) is not int
                        or type(count) is not int
                        or count < 1
                        or start < 0
                        or start + count > len(query.accent_phrases)
                    ):
                        self.grouping_error = error_status("Japanese segment references are invalid.")
                        continue
                try:
                    canonical = japanese_pronunciation(
                        query,
                        segment_index=(
                            model_index
                            if query.voicegerSegments is not None
                            else None
                        ),
                    )
                    punctuation_suffixes = _punctuation_suffixes(canonical)
                except Exception as exc:
                    self.grouping_error = error_status(
                        f"Cannot reconstruct Japanese pronunciation: {exc}"
                    )
                    continue
                if len(punctuation_suffixes) != count:
                    self.grouping_error = error_status(
                        "Japanese pronunciation phrases do not match "
                        "their query references."
                    )
                    continue
                for local_index in range(count):
                    phrase_index = start + local_index
                    phrase = query.accent_phrases[phrase_index]
                    rows.append(
                        PronunciationRow(
                            language="ja",
                            source_text=source_text,
                            source_segment_index=source_index,
                            model_segment_index=model_index,
                            first_in_segment=first,
                            phrase_index=phrase_index,
                            phrase_index_in_segment=local_index,
                            moras=tuple(mora.text for mora in phrase.moras),
                            accent=phrase.accent,
                            punctuation_suffix=punctuation_suffixes[local_index],
                        )
                    )
                    first = False
                continue

            if language == "en" and model_index is not None:
                try:
                    grouping = self.english_grouping(query, model_index)
                except Exception as exc:
                    self.grouping_error = (
                        error_status(f"Cannot align English word pronunciation: {exc}")
                    )
                    continue
                vowel_offset = 0
                word_width = max(
                    (_display_width(group.label) for group in grouping.groups if group.editable),
                    default=0,
                )
                group_states: list[EnglishPhonemeEditorState] = []
                invalid_word_group = False
                for group in grouping.groups:
                    try:
                        group_states.append(
                            english_phonemes_to_editor_state(group.phonemes)
                        )
                    except ValueError as exc:
                        if group.editable:
                            self.grouping_error = error_status(
                                "Cannot align English word pronunciation: "
                                f"invalid word phonemes: {exc}"
                            )
                            invalid_word_group = True
                            break
                        group_state = EnglishPhonemeEditorState((), ())
                        group_states.append(group_state)
                if invalid_word_group:
                    continue

                for group_index, (group, group_state) in enumerate(
                    zip(grouping.groups, group_states)
                ):
                    if group.editable:
                        rows.append(
                            PronunciationRow(
                                language="en",
                                source_text=source_text,
                                source_segment_index=source_index,
                                model_segment_index=model_index,
                                first_in_segment=first,
                                group_index=group_index,
                                word=group.label,
                                phonemes=group.phonemes,
                                vowel_offset=vowel_offset,
                                grouping=grouping,
                            )
                        )
                        first = False
                    vowel_offset += len(group_state.vowel_stresses)
                # Keep word-column alignment data identical for every child.
                if word_width:
                    start = len(rows)
                    while start and rows[start - 1].source_segment_index == source_index:
                        start -= 1
                    for row_index in range(start, len(rows)):
                        rows[row_index] = replace(
                            rows[row_index], word_column_width=word_width
                        )
                continue

            # Retain the existing unavailable placeholder for unsupported runs.
            rows.append(
                PronunciationRow(
                    language=language,
                    source_text=source_text,
                    source_segment_index=source_index,
                    model_segment_index=model_index,
                    first_in_segment=True,
                )
            )
        return tuple(rows)

    def open_pronunciation_item(
        self,
        query: AudioQuery,
        rows: Sequence[PronunciationRow],
        index: int,
        *,
        origin: tuple[str, int | None],
        busy: bool,
    ) -> tuple[EditorIntent, ...]:
        if busy or not 0 <= index < len(rows):
            return ()
        row = rows[index]
        if row.language == "ja" and row.phrase_index is not None:
            segment_index = (
                row.model_segment_index if query.voicegerSegments is not None else None
            )
            try:
                canonical = japanese_pronunciation(
                    query,
                    segment_index=segment_index,
                )
            except Exception as exc:
                return (
                    UpdateStatusIntent(
                        error_status(f"Cannot edit Japanese pronunciation: {exc}")
                    ),
                )
            self.editor = EditorState(
                kind="japanese",
                title="EDIT PRONUNCIATION",
                origin=origin,
                selection="pronunciation",
                payload={
                    "source_text": row.source_text,
                    "canonical_pronunciation": canonical,
                    "opening_draft": canonical.replace("/", " "),
                    "segment_index": segment_index,
                },
            )
            return (
                UpdateStatusIntent(""),
                *self.begin_field("pronunciation", canonical.replace("/", " ")),
            )
        if (
            row.language == "en"
            and row.group_index is not None
            and row.grouping is not None
            and row.model_segment_index is not None
        ):
            try:
                group = row.grouping.groups[row.group_index]
                phonemes = normalize_english_phonemes(group.phonemes)
            except Exception as exc:
                return (
                    UpdateStatusIntent(
                        error_status(f"Cannot edit English word pronunciation: {exc}")
                    ),
                )
            self.editor = EditorState(
                kind="english_word",
                title="EDIT PRONUNCIATION",
                origin=origin,
                selection="phonemes",
                payload={
                    "segment_index": row.model_segment_index,
                    "group_index": row.group_index,
                    "grouping": row.grouping,
                    "label": group.label,
                    "opening_draft": " ".join(phonemes),
                },
            )
            return (
                UpdateStatusIntent(""),
                *self.begin_field("phonemes", " ".join(phonemes)),
            )
        return (
            UpdateStatusIntent(
                error_status(f"Pronunciation editing is not available for {row.language!r}.")
            ),
        )

    def adjust_pronunciation(
        self,
        query: AudioQuery,
        row: PronunciationRow,
        direction: int,
    ) -> tuple[EditorIntent, ...]:
        """Return a query replacement for one focused Main pronunciation row."""

        clear = (ClearAdjustmentFeedbackIntent(),)
        try:
            if row.language == "ja" and row.phrase_index is not None:
                updated = move_japanese_accent(
                    query,
                    accent_phrase_index=row.phrase_index,
                    direction=direction,
                    segment_index=(
                        row.model_segment_index
                        if query.voicegerSegments is not None
                        else None
                    ),
                )
                if updated is query:
                    return clear
                return (
                    ReplaceQueryIntent(
                        query=updated,
                        editor_kind="japanese",
                        success_status="Japanese accent updated; old takes cleared.",
                        close_editor=False,
                    ),
                )
        except Exception as exc:
            return (
                *clear,
                UpdateStatusIntent(
                    error_status(f"Pronunciation was not changed: {exc}")
                ),
            )
        return self._host._english.adjust_stress(query, row, direction)

    @staticmethod
    def _set_pronunciation_draft(editor: EditorState, value: str) -> None:
        field = "pronunciation" if editor.kind == "japanese" else "phonemes"
        editor.input_value = value
        editor.input_original = value
        editor.input_cursor = len(value)
        editor.active_field = None
        editor.payload[field] = value

    def preview(self, query: AudioQuery | None) -> tuple[EditorIntent, ...]:
        """Validate a pronunciation draft and emit a transient query intent."""

        editor = self.editor
        if editor is None or editor.kind not in {"japanese", "english_word"}:
            return ()
        try:
            if query is None:
                raise ValueError("There is no active utterance")
            if editor.kind == "japanese":
                draft = editor.input_value
                if "/" in draft:
                    raise ValueError(
                        "Use spaces for phrase boundaries; '/' is not used in this editor."
                    )
                canonical = draft.replace("　", "/").replace(" ", "/")
                preview_query = japanese_preview_query(
                    query,
                    canonical,
                    segment_index=editor.payload["segment_index"],
                )
            else:
                grouping: EnglishGroupingCache = editor.payload["grouping"]
                draft_phonemes = normalize_english_phonemes(
                    editor.input_value.split()
                )
                preview_query = english_word_preview_query(
                    query,
                    segment_index=editor.payload["segment_index"],
                    group_index=editor.payload["group_index"],
                    phoneme_groups=tuple(
                        group.phonemes for group in grouping.groups
                    ),
                    draft_phonemes=draft_phonemes,
                )
        except Exception as exc:
            editor.error = error_status(f"Preview failed: {exc}")
            return ()
        editor.error = EMPTY_STATUS
        return (PreviewIntent(preview_query),)

    def apply_pronunciation(
        self,
        query: AudioQuery | None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if editor.kind == "japanese":
            try:
                if query is None:
                    raise ValueError("There is no active utterance")
                draft = editor.input_value
                if "/" in draft:
                    raise ValueError(
                        "Use spaces for phrase boundaries; '/' is not used in this editor."
                    )
                canonical = draft.replace("　", "/").replace(" ", "/")
                if canonical == editor.payload["canonical_pronunciation"]:
                    return self._close_editor(
                        "Japanese pronunciation unchanged."
                    )
                updated = replace_japanese_pronunciation(
                    query,
                    canonical,
                    segment_index=editor.payload["segment_index"],
                )
            except Exception as exc:
                editor.error = error_status(
                    f"Pronunciation was not changed: {exc}"
                )
                return ()
            return (
                ReplaceQueryIntent(
                    query=updated,
                    editor_kind="japanese",
                    success_status=(
                        "Japanese pronunciation updated; old takes cleared."
                    ),
                ),
            )

        if editor.kind == "english_word":
            index = editor.payload["segment_index"]
            group_index = editor.payload["group_index"]
            grouping: EnglishGroupingCache = editor.payload["grouping"]
            try:
                if query is None:
                    raise ValueError("There is no active utterance")
                groups = list(grouping.groups)
                edited_phones = tuple(
                    normalize_english_phonemes(editor.input_value.split())
                )
                current_phones = tuple(
                    normalize_english_phonemes(
                        groups[group_index].phonemes
                    )
                )
                if edited_phones == current_phones:
                    return self._close_editor(
                        "English phonemes unchanged."
                    )
                groups[group_index] = replace(
                    groups[group_index],
                    phonemes=edited_phones,
                )
                updated = replace_english_phoneme_groups(
                    query,
                    segment_index=index,
                    phoneme_groups=tuple(
                        group.phonemes for group in groups
                    ),
                )
            except Exception as exc:
                editor.error = error_status(
                    f"English phonemes were not changed: {exc}"
                )
                return ()
            accepted_grouping = EnglishGroupingCache(
                grouping.source_text, tuple(groups)
            )
            return (
                ReplaceQueryIntent(
                    query=updated,
                    editor_kind="english_word",
                    success_status=(
                        "English word pronunciation updated; old takes cleared."
                    ),
                    grouping_index=index,
                    accepted_grouping=accepted_grouping,
                ),
            )
        return ()

    def activate_selection(
        self,
        query: AudioQuery | None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        selected = editor.selection
        if editor.kind == "japanese":
            if selected == "pronunciation":
                return self.begin_field(
                    "pronunciation", editor.input_value
                )
            if selected == "preview":
                return self.preview(query)
            if selected == "apply":
                return self.apply_pronunciation(query)
            if selected == "save_dictionary":
                return (
                    SaveToDictionaryIntent(
                        language="ja",
                        surface=editor.payload["source_text"],
                        pronunciation=editor.input_value,
                    ),
                )
            if selected == "dictionary":
                return (OpenDictionaryIntent(),)
            if selected == "edit_text":
                return self.open_section_text(
                    query,
                    pure_japanese_utterance_text=(
                        editor.payload["source_text"]
                        if editor.payload["segment_index"] is None
                        else None
                    ),
                    busy=False,
                )
            if selected == "clear":
                self._set_pronunciation_draft(editor, "")
                editor.error = EMPTY_STATUS
                return (
                    UpdateStatusIntent(
                        "Japanese pronunciation draft cleared."
                    ),
                )
            if selected == "reset":
                self._set_pronunciation_draft(
                    editor, editor.payload["opening_draft"]
                )
                editor.error = EMPTY_STATUS
                return (
                    UpdateStatusIntent(
                        "Japanese pronunciation draft reset."
                    ),
                )
            if selected == "back":
                return self.cancel()
            return ()

        if editor.kind == "english_word":
            if selected == "phonemes":
                return self.begin_field(
                    "phonemes", editor.input_value
                )
            if selected == "preview":
                return self.preview(query)
            if selected == "apply":
                return self.apply_pronunciation(query)
            if selected == "save_dictionary":
                return (
                    SaveToDictionaryIntent(
                        language="en",
                        surface=editor.payload["label"],
                        pronunciation=editor.input_value,
                    ),
                )
            if selected == "dictionary":
                return (OpenDictionaryIntent(),)
            if selected == "edit_text":
                return self.open_section_text(
                    query,
                    pure_japanese_utterance_text=None,
                    busy=False,
                )
            if selected == "clear":
                self._set_pronunciation_draft(editor, "")
                editor.error = EMPTY_STATUS
                return (
                    UpdateStatusIntent(
                        "English phoneme draft cleared."
                    ),
                )
            if selected == "reset":
                self._set_pronunciation_draft(
                    editor, editor.payload["opening_draft"]
                )
                editor.error = EMPTY_STATUS
                return (
                    UpdateStatusIntent(
                        "English phoneme draft reset."
                    ),
                )
            if selected == "back":
                return self.cancel()
        return ()

    def finish_field(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if (
            editor is None
            or editor.active_field is None
            or editor.kind not in {"japanese", "english_word"}
        ):
            return ()
        name = editor.active_field
        value = editor.input_value
        if editor.kind == "japanese" and name == "pronunciation":
            value = "".join(
                canonicalize_punctuation(character) or character
                for character in value
            )
            editor.input_value = value
        editor.payload[name] = value
        editor.active_field = None
        editor.input_original = value
        editor.input_cursor = len(value)
        editor.error = EMPTY_STATUS
        return (UpdateStatusIntent(""),)

    def reject_active_key(self, key) -> bool:
        editor = self.editor
        if (
            editor is None
            or editor.kind != "japanese"
            or editor.active_field is None
            or not isinstance(key, str)
            or "/" not in key
        ):
            return False
        editor.error = error_status(
            "Use spaces for phrase boundaries; '/' is not used in this editor."
        )
        return True
