"""Interaction state and policy for Dictionary entry editing and CRUD."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Sequence, Union

from .english_stress import (
    editor_state_to_english_phonemes,
    english_phonemes_to_editor_state,
    move_primary_stress,
    normalize_english_phonemes,
)
from .openjtalk_dictionary import expand_word_type, normalize_surface
from .pronunciation import parse_pronunciation
from .tui_adjustments import step_bounded, step_cyclic
from .tui_dictionary_list import DictionaryListStateOwner
from .tui_dictionary_operations import (
    DictionaryLanguage,
    DictionaryOperationIdentity,
    DictionaryOperationIntent,
    DictionaryOperationRequest,
    dictionary_operation_request,
)
from .tui_dictionary_word_types import (
    JAPANESE_WORD_TYPES as _WORD_TYPES,
    japanese_word_type_label as _japanese_word_type_label,
)
from .tui_editors import (
    ClearAdjustmentFeedbackIntent,
    EditorIntent,
    EditorState,
    PreviewIntent,
    UpdateStatusIntent,
    adjustment_feedback_intents,
)
from .tui_selection import move_clamped_selection
from .tui_shortcuts import menu_items
from .tui_status import EMPTY_STATUS, error_status, info_status
from .user_dictionary import JapaneseWordType, UserDictionaryCore
from .voicevox_api_models import AccentPhrase, AudioQuery, Mora, VoicegerSegment


DictionaryEntryIntent = Union[EditorIntent, DictionaryOperationIntent]


def _reading_morae(reading: str) -> tuple[str, ...]:
    if "'" in reading or "/" in reading or any(ch in reading for ch in "。？！"):
        raise ValueError("Dictionary pronunciation must be one kana reading")
    parsed = parse_pronunciation(reading + "'")
    if len(parsed.phrases) != 1:
        raise ValueError("Dictionary pronunciation must contain one accent phrase")
    return parsed.phrases[0].morae


def _word_type_for_context(context_id: int) -> JapaneseWordType:
    for word_type in _WORD_TYPES:
        if expand_word_type(word_type.value)["context_id"] == context_id:
            return word_type
    raise ValueError(f"Unsupported Japanese dictionary word type context: {context_id}")


def _japanese_preview_query(morae: Sequence[str], accent: int) -> AudioQuery:
    if not morae:
        raise ValueError("Japanese pronunciation must not be empty")
    preview_accent = accent if accent > 0 else len(morae)
    return AudioQuery(
        accent_phrases=[
            AccentPhrase(
                moras=[Mora(text=mora, vowel="") for mora in morae],
                accent=preview_accent,
            )
        ],
        kana=None,
    )


def _english_preview_query(surface: str, phonemes: Sequence[str]) -> AudioQuery:
    if not surface.strip():
        raise ValueError("English dictionary Surface must not be empty")
    normalized = normalize_english_phonemes(phonemes)
    return AudioQuery(
        accent_phrases=[],
        voicegerSegments=[
            VoicegerSegment(
                language="en",
                text=surface,
                phonemes=normalized,
            )
        ],
    )


class DictionaryEntryOwner:
    """Own Dictionary entry drafts, persistence requests, and outcomes."""

    def __init__(
        self,
        core: UserDictionaryCore,
        *,
        get_editor: Callable[[], EditorState | None],
        set_editor: Callable[[EditorState | None], None],
        parent_stack: list[EditorState],
        get_japanese_pronunciation: Callable[[], Callable[[str], Any] | None],
        get_english_word_groups: Callable[
            [], Callable[[str], Sequence[tuple[str, Sequence[str]]]] | None
        ],
        list_state: DictionaryListStateOwner,
        remember_list_focus: Callable[[EditorState], str | None],
        japanese_list_state: Callable[[], EditorState],
        english_list_state: Callable[[], EditorState],
        menu_state: Callable[[], EditorState],
    ) -> None:
        self.core = core
        self._get_editor = get_editor
        self._set_editor = set_editor
        self._stack = parent_stack
        self._get_japanese_pronunciation = get_japanese_pronunciation
        self._get_english_word_groups = get_english_word_groups
        self._list_state = list_state
        self._remember_list_focus = remember_list_focus
        self._japanese_list_state = japanese_list_state
        self._english_list_state = english_list_state
        self._menu_state = menu_state

    @property
    def editor(self) -> EditorState | None:
        return self._get_editor()

    @editor.setter
    def editor(self, value: EditorState | None) -> None:
        self._set_editor(value)

    def open_quick_save_japanese(
        self,
        *,
        surface: str,
        pronunciation: str,
    ) -> tuple[EditorIntent, ...]:
        try:
            canonical = pronunciation.replace("　", "/").replace(" ", "/")
            parsed = parse_pronunciation(canonical)
            if len(parsed.phrases) != 1:
                raise ValueError(
                    "A Japanese dictionary word must contain exactly one accent phrase."
                )
            phrase = parsed.phrases[0]
            reading = phrase.reading
            normalized_surface = normalize_surface(surface)
            entries = self.core.list_japanese_entries()
            matches = [
                (word_uuid, word)
                for word_uuid, word in entries.items()
                if word.surface == normalized_surface
            ]
        except Exception as exc:
            return (
                UpdateStatusIntent(
                    error_status(f"Dictionary draft could not be opened: {exc}")
                ),
            )

        self._stack.clear()
        if len(matches) > 1:
            self.editor = EditorState(
                kind="dictionary_japanese_duplicates",
                title="SELECT DICTIONARY WORD",
                origin=("dictionary", None),
                selection=("entry", 0),
                payload={
                    "surface": surface,
                    "pronunciation": reading,
                    "moras": phrase.morae,
                    "accent": phrase.accent,
                    "matches": tuple(matches),
                },
            )
            return (UpdateStatusIntent("Choose the existing entry to update."),)

        word_uuid = matches[0][0] if matches else None
        word = matches[0][1] if matches else None
        self.editor = self._japanese_entry_state(
            word_uuid=word_uuid,
            word=word,
            surface=surface,
            pronunciation=reading,
            moras=phrase.morae,
            accent=phrase.accent,
            quick_save=True,
        )
        return (UpdateStatusIntent(""),)

    def open_quick_save_english(
        self,
        *,
        surface: str,
        phonemes: str,
    ) -> tuple[EditorIntent, ...]:
        try:
            normalized = normalize_english_phonemes(phonemes.split())
            entries = self.core.list_english_entries()
            existing = next(
                (
                    entry
                    for entry in entries.values()
                    if entry.surface.strip().casefold() == surface.strip().casefold()
                ),
                None,
            )
        except Exception as exc:
            return (
                UpdateStatusIntent(
                    error_status(f"Dictionary draft could not be opened: {exc}")
                ),
            )

        self._stack.clear()
        self.editor = self._english_entry_state(
            surface=surface,
            phonemes=normalized,
            original_surface=(existing.surface if existing is not None else None),
            quick_save=True,
        )
        return (UpdateStatusIntent(""),)

    def _japanese_entry_state(
        self,
        *,
        word_uuid: str | None,
        word,
        surface: str | None = None,
        pronunciation: str | None = None,
        moras: Sequence[str] | None = None,
        accent: int | None = None,
        quick_save: bool = False,
        entry_index: int | None = None,
        entry_total: int | None = None,
    ) -> EditorState:
        if word is None:
            selected_surface = surface or ""
            selected_pronunciation = pronunciation or ""
            selected_moras = tuple(moras or ())
            selected_accent = 1 if accent is None else accent
            word_type = JapaneseWordType.PROPER_NOUN
            priority = 5
        else:
            selected_surface = word.surface if surface is None else surface
            selected_pronunciation = (
                word.pronunciation if pronunciation is None else pronunciation
            )
            selected_moras = (
                _reading_morae(selected_pronunciation)
                if moras is None
                else tuple(moras)
            )
            selected_accent = word.accent_type if accent is None else accent
            word_type = _word_type_for_context(word.context_id)
            priority = word.priority

        opening = (
            selected_surface,
            selected_pronunciation,
            selected_accent,
            word_type,
            priority,
        )
        return EditorState(
            kind="dictionary_japanese_entry",
            title=(
                "ADD JAPANESE DICTIONARY WORD"
                if word_uuid is None
                else "EDIT JAPANESE DICTIONARY WORD"
            ),
            origin=("dictionary", None),
            selection="surface",
            payload={
                "word_uuid": word_uuid,
                "surface": selected_surface,
                "pronunciation": selected_pronunciation,
                "moras": selected_moras,
                "accent": selected_accent,
                "word_type": word_type,
                "word_type_label": _japanese_word_type_label(word_type),
                "priority": priority,
                "opening": opening,
                "quick_save": quick_save,
                "entry_index": entry_index,
                "entry_total": entry_total,
                "can_delete": word_uuid is not None,
            },
        )

    def _english_entry_state(
        self,
        *,
        surface: str = "",
        phonemes: Sequence[str] = (),
        original_surface: str | None = None,
        quick_save: bool = False,
        entry_index: int | None = None,
        entry_total: int | None = None,
    ) -> EditorState:
        normalized = tuple(phonemes)
        opening = (surface, normalized)
        return EditorState(
            kind="dictionary_english_entry",
            title=(
                "ADD ENGLISH DICTIONARY WORD"
                if original_surface is None
                else "EDIT ENGLISH DICTIONARY WORD"
            ),
            origin=("dictionary", None),
            selection="surface",
            payload={
                "surface": surface,
                "phonemes": normalized,
                "original_surface": original_surface,
                "opening": opening,
                "quick_save": quick_save,
                "entry_index": entry_index,
                "entry_total": entry_total,
                "can_delete": original_surface is not None,
            },
        )

    def _entry_snapshot(self, editor: EditorState) -> tuple[Any, ...]:
        if editor.kind == "dictionary_japanese_entry":
            surface = (
                editor.input_value
                if editor.active_field == "surface"
                else editor.payload["surface"]
            )
            pronunciation = (
                editor.input_value
                if editor.active_field == "pronunciation"
                else editor.payload["pronunciation"]
            )
            return (
                surface,
                pronunciation,
                editor.payload["accent"],
                editor.payload["word_type"],
                editor.payload["priority"],
            )
        surface = (
            editor.input_value
            if editor.active_field == "surface"
            else editor.payload["surface"]
        )
        phonemes = (
            tuple(editor.input_value.split())
            if editor.active_field == "phonemes"
            else tuple(editor.payload["phonemes"])
        )
        return (surface, phonemes)

    def _is_dirty(self, editor: EditorState) -> bool:
        return self._entry_snapshot(editor) != tuple(editor.payload["opening"])

    def _move_entry_selection(self, delta: int) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind not in {
            "dictionary_japanese_entry",
            "dictionary_english_entry",
        }:
            return ()
        keys = [item.key for item in menu_items(editor.kind, editor.payload)]
        if (
            editor.payload.get("entry_index") is not None
            and editor.payload.get("entry_total") is not None
        ):
            keys.insert(0, "entry_navigator")
        result = move_clamped_selection(editor.selection, keys, delta=delta)
        if result is not None:
            editor.selection = result.selection
        editor.error = EMPTY_STATUS
        return (ClearAdjustmentFeedbackIntent(),)

    def _finish_field(self) -> tuple[DictionaryEntryIntent, ...]:
        editor = self.editor
        if editor is None or editor.active_field is None:
            return ()
        name = editor.active_field
        value = editor.input_value
        auto_generate = False
        try:
            if editor.kind == "dictionary_japanese_entry":
                if name == "surface":
                    editor.payload["surface"] = value
                    auto_generate = (
                        editor.payload["word_uuid"] is None
                        and not editor.payload["quick_save"]
                        and not editor.payload["pronunciation"]
                    )
                elif name == "pronunciation":
                    moras = _reading_morae(value)
                    editor.payload["pronunciation"] = value
                    editor.payload["moras"] = moras
                    accent = editor.payload["accent"]
                    if accent > len(moras):
                        editor.payload["accent"] = len(moras)
            elif editor.kind == "dictionary_english_entry":
                if name == "surface":
                    editor.payload["surface"] = value
                    auto_generate = (
                        editor.payload["original_surface"] is None
                        and not editor.payload["quick_save"]
                        and not editor.payload["phonemes"]
                    )
                elif name == "phonemes":
                    normalized = normalize_english_phonemes(value.split())
                    editor.payload["phonemes"] = tuple(normalized)
                    editor.input_value = " ".join(normalized)
            elif (
                editor.kind
                in {
                    "dictionary_japanese_filter",
                    "dictionary_english_filter",
                }
                and name == "text_query"
            ):
                editor.payload["text_query"] = value
            elif editor.kind == "dictionary_import_path" and name == "path":
                editor.payload["path"] = value
        except Exception as exc:
            editor.error = error_status(f"{exc}")
            return ()
        editor.active_field = None
        editor.input_original = editor.input_value
        editor.error = EMPTY_STATUS
        if auto_generate:
            return self._generate_pronunciation()
        return (UpdateStatusIntent(""),)

    def _adjust_japanese(self, direction: int) -> tuple[EditorIntent, ...]:
        editor = self.editor
        assert editor is not None
        if editor.selection == "pronunciation":
            count = len(editor.payload["moras"])
            if not count:
                return ()
            accent = editor.payload["accent"]
            visual_accent = count if accent == 0 else accent
            if direction < 0:
                updated = max(1, visual_accent - 1)
            else:
                updated = min(count, visual_accent + 1)
            if updated != accent:
                editor.payload["accent"] = updated
            return ()
        if editor.selection == "word_type":
            result = step_cyclic(
                editor.payload["word_type"],
                _WORD_TYPES,
                direction=direction,
            )
            if result.changed:
                editor.payload["word_type"] = result.value
                editor.payload["word_type_label"] = _japanese_word_type_label(
                    result.value
                )
            return adjustment_feedback_intents(
                changed=result.changed,
                area="dictionary",
                control="word_type",
                direction=direction,
            )
        if editor.selection == "priority":
            result = step_bounded(
                editor.payload["priority"],
                direction=direction,
                step=1,
                minimum=0,
                maximum=10,
            )
            if result.changed:
                editor.payload["priority"] = result.value
            return adjustment_feedback_intents(
                changed=result.changed,
                area="dictionary",
                control="priority",
                direction=direction,
            )
        return ()

    def _adjust_english(self, direction: int) -> tuple[EditorIntent, ...]:
        editor = self.editor
        assert editor is not None
        if editor.selection != "phonemes":
            return ()
        try:
            state = english_phonemes_to_editor_state(editor.payload["phonemes"])
            positions = state.primary_stress_vowel_positions
            if not positions or len(state.vowel_stresses) < 2:
                return ()
            source = positions[0]
            target = min(
                max(source + direction, 0),
                len(state.vowel_stresses) - 1,
            )
            if target == source:
                return ()
            moved = move_primary_stress(state, source, target)
            editor.payload["phonemes"] = tuple(editor_state_to_english_phonemes(moved))
        except Exception as exc:
            editor.error = error_status(f"Stress was not changed: {exc}")
        return ()

    def _generate_pronunciation(self) -> tuple[DictionaryEntryIntent, ...]:
        editor = self.editor
        assert editor is not None
        surface = editor.payload["surface"]
        if not surface.strip():
            editor.error = error_status("Surface must not be empty.")
            return ()
        editor.error = EMPTY_STATUS
        if editor.kind == "dictionary_japanese_entry":
            language: DictionaryLanguage = "ja"
            operation: DictionaryOperationIdentity = "generate_japanese_pronunciation"
            analyze = self._get_japanese_pronunciation()

            def work(
                *,
                surface: str = surface,
                analyze: Callable[[str], Any] | None = analyze,
            ) -> tuple[str, tuple[str, ...], int]:
                if analyze is None:
                    raise RuntimeError("Japanese pronunciation analysis is unavailable")
                parsed = analyze(surface)
                if len(parsed.phrases) != 1:
                    raise ValueError(
                        "Japanese dictionary Surface must resolve to exactly one accent phrase"
                    )
                phrase = parsed.phrases[0]
                return phrase.reading, tuple(phrase.morae), phrase.accent

            status = "Generating Japanese pronunciation…"
        else:
            language = "en"
            operation = "generate_english_pronunciation"
            analyze_groups = self._get_english_word_groups()

            def work(
                *,
                surface: str = surface,
                analyze_groups: Callable[[str], Sequence[tuple[str, Sequence[str]]]]
                | None = analyze_groups,
            ) -> tuple[str, ...]:
                if analyze_groups is None:
                    raise RuntimeError("English pronunciation analysis is unavailable")
                groups = tuple(analyze_groups(surface))
                if len(groups) != 1:
                    raise ValueError(
                        "English dictionary Surface must resolve to exactly one word"
                    )
                _label, phonemes = groups[0]
                return tuple(normalize_english_phonemes(phonemes))

            status = "Generating English pronunciation…"

        request = dictionary_operation_request(
            editor,
            operation=operation,
            language=language,
        )
        return (
            ClearAdjustmentFeedbackIntent(),
            DictionaryOperationIntent(request, info_status(status), work),
        )

    def _preview(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        assert editor is not None
        try:
            if editor.kind == "dictionary_japanese_entry":
                query = _japanese_preview_query(
                    editor.payload["moras"],
                    editor.payload["accent"],
                )
            else:
                query = _english_preview_query(
                    editor.payload["surface"],
                    editor.payload["phonemes"],
                )
        except Exception as exc:
            editor.error = error_status(f"Preview failed: {exc}")
            return ()
        editor.error = EMPTY_STATUS
        return (PreviewIntent(query),)

    def _save(self) -> tuple[DictionaryEntryIntent, ...]:
        editor = self.editor
        assert editor is not None
        surface = str(editor.payload["surface"])
        if not surface.strip():
            editor.error = error_status("Surface must not be empty.")
            return ()

        editor.error = EMPTY_STATUS
        if editor.kind == "dictionary_japanese_entry":
            language: DictionaryLanguage = "ja"
            operation: DictionaryOperationIdentity = "save_japanese"
            word_uuid = editor.payload["word_uuid"]
            pronunciation = str(editor.payload["pronunciation"])
            accent_type = int(editor.payload["accent"])
            word_type = editor.payload["word_type"]
            priority = int(editor.payload["priority"])
            core = self.core
            if word_uuid is None:

                def work() -> Any:
                    return core.add_japanese_word(
                        surface=surface,
                        pronunciation=pronunciation,
                        accent_type=accent_type,
                        word_type=word_type,
                        priority=priority,
                    )
            else:
                word_uuid = str(word_uuid)

                def work() -> Any:
                    return core.update_japanese_word(
                        word_uuid,
                        surface=surface,
                        pronunciation=pronunciation,
                        accent_type=accent_type,
                        word_type=word_type,
                        priority=priority,
                    )

            status = "Saving Japanese dictionary word…"
        else:
            language = "en"
            operation = "save_english"
            original_surface = editor.payload["original_surface"]
            if original_surface is not None:
                original_surface = str(original_surface)
            phonemes = tuple(editor.payload["phonemes"])
            core = self.core
            if original_surface is None:

                def work() -> Any:
                    return core.set_english_entry(surface, phonemes)
            else:

                def work() -> Any:
                    return core.update_english_entry(
                        original_surface,
                        surface=surface,
                        phonemes=phonemes,
                    )

            status = "Saving English dictionary word…"

        request = dictionary_operation_request(
            editor,
            operation=operation,
            language=language,
        )
        return (DictionaryOperationIntent(request, info_status(status), work),)

    def _open_discard_confirmation(
        self,
        editor: EditorState,
        *,
        entry_navigation_target: int | None = None,
    ) -> tuple[EditorIntent, ...]:
        payload: dict[str, Any] = {
            "parent_editor": deepcopy(editor),
            "warning": "Unsaved dictionary changes will be discarded.",
        }
        if entry_navigation_target is not None:
            payload["entry_navigation_target"] = entry_navigation_target
        self.editor = EditorState(
            kind="dictionary_discard_confirmation",
            title="DISCARD DICTIONARY CHANGES?",
            origin=("dictionary", None),
            selection="cancel",
            payload=payload,
        )
        return (UpdateStatusIntent(""),)

    def _open_entry_at_index(
        self,
        source_editor: EditorState,
        target_index: int,
    ) -> tuple[EditorIntent, ...]:
        if not self._stack:
            return ()
        parent = self._stack[-1]
        if source_editor.kind == "dictionary_japanese_entry":
            if parent.kind != "dictionary_japanese_list":
                return ()
            entries = parent.payload["entries"]
            if not 0 <= target_index < len(entries):
                return ()
            word_uuid, word = entries[target_index]
            self.editor = self._japanese_entry_state(
                word_uuid=word_uuid,
                word=word,
                entry_index=target_index,
                entry_total=len(entries),
            )
        elif source_editor.kind == "dictionary_english_entry":
            if parent.kind != "dictionary_english_list":
                return ()
            entries = parent.payload["entries"]
            if not 0 <= target_index < len(entries):
                return ()
            entry = entries[target_index]
            self.editor = self._english_entry_state(
                surface=entry.surface,
                phonemes=entry.phonemes,
                original_surface=entry.surface,
                entry_index=target_index,
                entry_total=len(entries),
            )
        else:
            return ()
        parent.selection = ("entry", target_index)
        parent.payload["entry_index"] = target_index
        self._remember_list_focus(parent)
        self.editor.selection = "entry_navigator"
        return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())

    def _move_open_entry(
        self,
        direction: int,
        *,
        show_feedback: bool = False,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        assert editor is not None
        index = editor.payload.get("entry_index")
        total = editor.payload.get("entry_total")
        if not isinstance(index, int) or not isinstance(total, int) or total <= 0:
            return ()
        target = index + (-1 if direction < 0 else 1)
        if target < 0:
            return (UpdateStatusIntent(info_status("First dictionary word.")),)
        if target >= total:
            return (UpdateStatusIntent(info_status("Last dictionary word.")),)
        if self._is_dirty(editor):
            return self._open_discard_confirmation(
                editor,
                entry_navigation_target=target,
            )
        intents = self._open_entry_at_index(editor, target)
        if not intents or not show_feedback:
            return intents
        return tuple(
            intent
            for intent in intents
            if not isinstance(intent, ClearAdjustmentFeedbackIntent)
        ) + adjustment_feedback_intents(
            changed=True,
            area="dictionary",
            control="entry_navigator",
            direction=direction,
        )

    def _back_from_entry(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        assert editor is not None
        if self._is_dirty(editor):
            return self._open_discard_confirmation(editor)
        return self._discard_entry(editor)

    def _discard_entry(self, editor: EditorState) -> tuple[EditorIntent, ...]:
        if bool(editor.payload.get("quick_save")):
            self.editor = None
            self._stack.clear()
        elif self._stack:
            self.editor = self._stack.pop()
        else:
            self.editor = None
        return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())

    def _open_delete_confirmation(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        assert editor is not None
        if editor.kind in {
            "dictionary_japanese_list",
            "dictionary_english_list",
        }:
            identifier = self._remember_list_focus(editor)
            if identifier is None:
                return (UpdateStatusIntent("Select a dictionary word to delete."),)
            identities = tuple(editor.payload.get("entry_ids", ()))
            try:
                index = identities.index(identifier)
            except ValueError:
                return ()
            editor.payload["entry_index"] = index
            parent_editor = deepcopy(editor)
            parent_editor.selection = ("entry", index)
            if editor.kind == "dictionary_japanese_list":
                entries = editor.payload["entries"]
                if not 0 <= index < len(entries):
                    return ()
                _entry_identifier, word = entries[index]
                payload = {
                    "language": "ja",
                    "identifier": identifier,
                    "surface": word.surface,
                    "pronunciation": word.pronunciation,
                    "accent": word.accent_type,
                    "moras": _reading_morae(word.pronunciation),
                    "parent_editor": parent_editor,
                    "opened_from_entry": False,
                }
            else:
                entries = editor.payload["entries"]
                if not 0 <= index < len(entries):
                    return ()
                entry = entries[index]
                payload = {
                    "language": "en",
                    "identifier": identifier,
                    "surface": entry.surface,
                    "phonemes": tuple(entry.phonemes),
                    "parent_editor": parent_editor,
                    "opened_from_entry": False,
                }
        elif editor.kind == "dictionary_japanese_entry":
            identifier = editor.payload.get("word_uuid")
            if identifier is None:
                return ()
            payload = {
                "language": "ja",
                "identifier": str(identifier),
                "surface": editor.payload["surface"],
                "pronunciation": editor.payload["pronunciation"],
                "accent": editor.payload["accent"],
                "moras": tuple(editor.payload["moras"]),
                "parent_editor": deepcopy(editor),
                "opened_from_entry": True,
            }
        elif editor.kind == "dictionary_english_entry":
            identifier = editor.payload.get("original_surface")
            if identifier is None:
                return ()
            payload = {
                "language": "en",
                "identifier": str(identifier),
                "surface": editor.payload["surface"],
                "phonemes": tuple(editor.payload["phonemes"]),
                "parent_editor": deepcopy(editor),
                "opened_from_entry": True,
            }
        else:
            return ()
        payload["warning"] = "This dictionary word will be removed."
        self.editor = EditorState(
            kind="dictionary_delete_confirmation",
            title="DELETE DICTIONARY WORD?",
            origin=("dictionary", None),
            selection="cancel",
            payload=payload,
        )
        return (UpdateStatusIntent(""),)

    def _delete_confirmed(self) -> tuple[DictionaryEntryIntent, ...]:
        editor = self.editor
        assert editor is not None
        language: DictionaryLanguage = editor.payload["language"]
        identifier = str(editor.payload["identifier"])
        editor.error = EMPTY_STATUS
        core = self.core
        if language == "ja":
            operation: DictionaryOperationIdentity = "delete_japanese"

            def work() -> Any:
                return core.delete_japanese_word(identifier)

            status = "Deleting Japanese dictionary word…"
        else:
            operation = "delete_english"

            def work() -> Any:
                return core.delete_english_entry(identifier)

            status = "Deleting English dictionary word…"
        request = dictionary_operation_request(
            editor,
            operation=operation,
            language=language,
        )
        return (DictionaryOperationIntent(request, info_status(status), work),)

    def move_duplicate_selection(self, editor: EditorState, delta: int) -> None:
        if editor.kind != "dictionary_japanese_duplicates":
            return
        entries = editor.payload["matches"]
        if not entries:
            return
        index = (
            editor.selection[1]
            if isinstance(editor.selection, tuple)
            and editor.selection[0] == "entry"
            and editor.selection[1] is not None
            else 0
        )
        editor.selection = (
            "entry",
            min(max(index + delta, 0), len(entries) - 1),
        )

    def open_selected_list_entry(self, editor: EditorState) -> None:
        if editor.kind not in {
            "dictionary_japanese_list",
            "dictionary_english_list",
        }:
            return
        identifier = self._remember_list_focus(editor)
        identities = tuple(editor.payload.get("entry_ids", ()))
        entries = editor.payload["entries"]
        if identifier is None or identifier not in identities:
            return
        index = identities.index(identifier)
        if editor.kind == "dictionary_japanese_list":
            word_uuid, word = entries[index]
            entry_editor = self._japanese_entry_state(
                word_uuid=word_uuid,
                word=word,
                entry_index=index,
                entry_total=len(entries),
            )
        else:
            entry = entries[index]
            entry_editor = self._english_entry_state(
                surface=entry.surface,
                phonemes=entry.phonemes,
                original_surface=identifier,
                entry_index=index,
                entry_total=len(entries),
            )
        self._stack.append(deepcopy(editor))
        self.editor = entry_editor

    def select_duplicate_entry(self, editor: EditorState, index: int | None) -> None:
        if editor.kind != "dictionary_japanese_duplicates":
            return
        matches = editor.payload["matches"]
        if index is None or not 0 <= index < len(matches):
            return
        word_uuid, word = matches[index]
        self.editor = self._japanese_entry_state(
            word_uuid=word_uuid,
            word=word,
            surface=editor.payload["surface"],
            pronunciation=editor.payload["pronunciation"],
            moras=editor.payload["moras"],
            accent=editor.payload["accent"],
            quick_save=True,
        )

    def restore_confirmation_parent(
        self, editor: EditorState
    ) -> tuple[EditorIntent, ...]:
        self.editor = editor.payload["parent_editor"]
        return (UpdateStatusIntent(""),)

    def confirm_discard(self, editor: EditorState) -> tuple[EditorIntent, ...]:
        parent_editor = editor.payload["parent_editor"]
        target = editor.payload.get("entry_navigation_target")
        if target is not None:
            return self._open_entry_at_index(parent_editor, target)
        return self._discard_entry(parent_editor)

    def complete_operation(
        self,
        request: DictionaryOperationRequest,
        value: Any = None,
        error: BaseException | None = None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        assert editor is not None
        if error is not None:
            if request.operation in {
                "generate_japanese_pronunciation",
                "generate_english_pronunciation",
            }:
                message = f"Pronunciation was not generated: {error}"
            elif request.operation in {"save_japanese", "save_english"}:
                message = f"Dictionary word was not saved: {error}"
            else:
                message = f"Dictionary word was not deleted: {error}"
            editor.error = error_status(message)
            return (UpdateStatusIntent(editor.error),)

        editor.error = EMPTY_STATUS
        if request.operation == "generate_japanese_pronunciation":
            reading, moras, accent = value
            editor.payload["pronunciation"] = reading
            editor.payload["moras"] = tuple(moras)
            editor.payload["accent"] = accent
            message = "Pronunciation generated from Surface."
        elif request.operation == "generate_english_pronunciation":
            editor.payload["phonemes"] = tuple(value)
            message = "Pronunciation generated from Surface."
        elif request.operation in {"save_japanese", "save_english"}:
            snapshot = request.editor_snapshot
            message = (
                "Japanese dictionary word saved."
                if request.language == "ja"
                else "English dictionary word saved."
            )
            if bool(snapshot.payload["quick_save"]):
                self.editor = None
                self._stack.clear()
            else:
                if request.language == "ja":
                    saved_identity = snapshot.payload.get("word_uuid")
                    if saved_identity is None and value is not None:
                        saved_identity = str(value)
                    self._list_state.remember_focus(
                        "ja",
                        None if saved_identity is None else str(saved_identity),
                    )
                else:
                    saved_identity = getattr(value, "surface", None)
                    if saved_identity is None:
                        saved_identity = snapshot.payload.get("surface")
                    self._list_state.remember_focus(
                        "en",
                        None if saved_identity is None else str(saved_identity),
                    )
                parent = self._stack.pop() if self._stack else self._menu_state()
                self.editor = (
                    self._japanese_list_state()
                    if request.language == "ja"
                    else self._english_list_state()
                )
                if parent.kind not in {
                    "dictionary_japanese_list",
                    "dictionary_english_list",
                }:
                    self._stack.clear()
        else:
            snapshot = request.editor_snapshot
            if bool(snapshot.payload.get("opened_from_entry")):
                list_kind = (
                    "dictionary_japanese_list"
                    if request.language == "ja"
                    else "dictionary_english_list"
                )
                if self._stack and self._stack[-1].kind == list_kind:
                    self._stack.pop()
            self.editor = (
                self._japanese_list_state()
                if request.language == "ja"
                else self._english_list_state()
            )
            message = (
                "Japanese dictionary word deleted."
                if request.language == "ja"
                else "English dictionary word deleted."
            )
        return (
            UpdateStatusIntent(message),
            ClearAdjustmentFeedbackIntent(),
        )
