"""Keyboard-first TUI state and policy for user dictionary management."""

from __future__ import annotations

import curses
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Literal, Sequence, Union

from .english_stress import (
    editor_state_to_english_phonemes,
    english_phonemes_to_editor_state,
    move_primary_stress,
    normalize_english_phonemes,
)
from .openjtalk_dictionary import expand_word_type, normalize_surface
from .pronunciation import parse_pronunciation
from .tui_display import _display_width, _move_wrapped_cursor
from .tui_editors import (
    ClearAdjustmentFeedbackIntent,
    EditorIntent,
    EditorState,
    OpenHelpIntent,
    PreviewIntent,
    QuitIntent,
    UpdateStatusIntent,
)
from .tui_shortcuts import menu_items, resolve_shortcut
from .tui_status import EMPTY_STATUS, Status, error_status, info_status
from .user_dictionary import JapaneseWordType, UserDictionaryCore
from .voicevox_api_models import AccentPhrase, AudioQuery, Mora, VoicegerSegment


_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"
_WORD_TYPES = tuple(JapaneseWordType)

DictionaryOperationIdentity = Literal[
    "generate_japanese_pronunciation",
    "generate_english_pronunciation",
    "save_japanese",
    "save_english",
    "delete_japanese",
    "delete_english",
]
DictionaryLanguage = Literal["ja", "en"]


@dataclass(frozen=True)
class DictionaryOperationRequest:
    """Snapshot the requested work and retain the originating UI editor identity."""

    operation: DictionaryOperationIdentity
    language: DictionaryLanguage
    editor_snapshot: EditorState
    originating_editor: EditorState


@dataclass(frozen=True)
class DictionaryOperationIntent:
    request: DictionaryOperationRequest
    status: Status
    work: Callable[[], Any]


DictionaryControllerIntent = Union[EditorIntent, DictionaryOperationIntent]


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


class TuiDictionaryController:
    """Own dictionary modal state while leaving the caller editor untouched."""

    def __init__(
        self,
        core: UserDictionaryCore,
        *,
        input_prefix,
        japanese_pronunciation: Callable[[str], Any] | None = None,
        english_word_groups: Callable[[str], Sequence[tuple[str, Sequence[str]]]] | None = None,
    ) -> None:
        self.core = core
        self.editor: EditorState | None = None
        self._stack: list[EditorState] = []
        self._input_prefix = input_prefix
        self._japanese_pronunciation = japanese_pronunciation
        self._english_word_groups = english_word_groups

    @staticmethod
    def _operation_request(
        editor: EditorState,
        *,
        operation: DictionaryOperationIdentity,
        language: DictionaryLanguage,
    ) -> DictionaryOperationRequest:
        return DictionaryOperationRequest(
            operation=operation,
            language=language,
            editor_snapshot=deepcopy(editor),
            originating_editor=editor,
        )

    @property
    def active(self) -> bool:
        return self.editor is not None

    def open_menu(
        self,
        *,
        preserve_current: bool = False,
    ) -> tuple[EditorIntent, ...]:
        if preserve_current and self.editor is not None:
            self._stack.append(deepcopy(self.editor))
        else:
            self._stack.clear()
        self.editor = self._menu_state()
        return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())

    def _menu_state(self) -> EditorState:
        return EditorState(
            kind="dictionary_menu",
            title="DICTIONARY",
            origin=("dictionary", None),
            selection="japanese",
            payload={
                "japanese_count": len(self.core.list_japanese_entries()),
                "english_count": len(self.core.list_english_entries()),
            },
        )

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
            return (UpdateStatusIntent(error_status(f"Dictionary draft could not be opened: {exc}")),)

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
            return (UpdateStatusIntent(error_status(f"Dictionary draft could not be opened: {exc}")),)

        self._stack.clear()
        self.editor = self._english_entry_state(
            surface=surface,
            phonemes=normalized,
            original_surface=(existing.surface if existing is not None else None),
            quick_save=True,
        )
        return (UpdateStatusIntent(""),)

    def _restore_parent(self) -> None:
        if not self._stack:
            self.editor = None
            return
        parent = self._stack.pop()
        if parent.kind == "dictionary_menu":
            refreshed = self._menu_state()
            refreshed.selection = parent.selection
            self.editor = refreshed
        else:
            self.editor = parent

    def _japanese_list_state(self) -> EditorState:
        entries = tuple(
            sorted(
                self.core.list_japanese_entries().items(),
                key=lambda item: (item[1].surface, item[0]),
            )
        )
        return EditorState(
            kind="dictionary_japanese_list",
            title="JAPANESE DICTIONARY",
            origin=("dictionary", None),
            selection=("entry", 0) if entries else "add",
            payload={"entries": entries, "entry_index": 0 if entries else None},
        )

    def _english_list_state(self) -> EditorState:
        entries = tuple(
            sorted(
                self.core.list_english_entries().values(),
                key=lambda entry: (entry.surface, entry.surface.casefold()),
            )
        )
        return EditorState(
            kind="dictionary_english_list",
            title="ENGLISH DICTIONARY",
            origin=("dictionary", None),
            selection=("entry", 0) if entries else "add",
            payload={"entries": entries, "entry_index": 0 if entries else None},
        )

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
                "priority": priority,
                "opening": opening,
                "quick_save": quick_save,
            },
        )

    def _english_entry_state(
        self,
        *,
        surface: str = "",
        phonemes: Sequence[str] = (),
        original_surface: str | None = None,
        quick_save: bool = False,
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
            },
        )

    def _begin_field(self, name: str, value: str) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        editor.selection = name
        editor.active_field = name
        editor.input_value = value
        editor.input_original = value
        editor.input_cursor = len(value)
        editor.error = EMPTY_STATUS
        return (ClearAdjustmentFeedbackIntent(),)

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

    def _move_dynamic_selection(self, delta: int) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if editor.kind == "dictionary_menu":
            keys = ["japanese", "english", "back"]
            try:
                index = keys.index(editor.selection)
            except ValueError:
                index = 0
            editor.selection = keys[min(max(index + delta, 0), len(keys) - 1)]
            return ()
        if editor.kind in {
            "dictionary_japanese_list",
            "dictionary_english_list",
        }:
            entries = editor.payload["entries"]
            entry_keys = [("entry", index) for index in range(len(entries))]
            action_keys = ["add"]
            if entries:
                action_keys.append("delete")
            action_keys.append("back")
            keys = [*entry_keys, *action_keys]
            try:
                index = keys.index(editor.selection)
            except ValueError:
                index = 0
            editor.selection = keys[min(max(index + delta, 0), len(keys) - 1)]
            if (
                isinstance(editor.selection, tuple)
                and editor.selection[0] == "entry"
                and editor.selection[1] is not None
            ):
                editor.payload["entry_index"] = editor.selection[1]
            return ()
        if editor.kind == "dictionary_japanese_duplicates":
            entries = editor.payload["matches"]
            if not entries:
                return ()
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
            return ()
        if editor.kind == "dictionary_delete_confirmation":
            keys = [
                item.key
                for item in menu_items(editor.kind, editor.payload)
            ]
            try:
                index = keys.index(editor.selection)
            except ValueError:
                index = 0
            editor.selection = keys[min(max(index + delta, 0), len(keys) - 1)]
            return ()
        return ()

    def _move_entry_selection(self, delta: int) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if editor.kind == "dictionary_japanese_entry":
            keys = [
                "surface",
                "pronunciation",
                "word_type",
                "priority",
                "generate_pronunciation",
                "preview",
                "save",
                "dictionary",
                "back",
            ]
        elif editor.kind == "dictionary_english_entry":
            keys = [
                "surface",
                "phonemes",
                "generate_pronunciation",
                "preview",
                "save",
                "dictionary",
                "back",
            ]
        else:
            return ()
        try:
            index = keys.index(editor.selection)
        except ValueError:
            index = 0
        editor.selection = keys[min(max(index + delta, 0), len(keys) - 1)]
        editor.error = EMPTY_STATUS
        return (ClearAdjustmentFeedbackIntent(),)

    def _finish_field(self) -> tuple[DictionaryControllerIntent, ...]:
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
            current = _WORD_TYPES.index(editor.payload["word_type"])
            target = (current + direction) % len(_WORD_TYPES)
            editor.payload["word_type"] = _WORD_TYPES[target]
            return ()
        if editor.selection == "priority":
            current = editor.payload["priority"]
            editor.payload["priority"] = min(10, max(0, current + direction))
            return ()
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
            editor.payload["phonemes"] = tuple(
                editor_state_to_english_phonemes(moved)
            )
        except Exception as exc:
            editor.error = error_status(f"Stress was not changed: {exc}")
        return ()

    def _generate_pronunciation(self) -> tuple[DictionaryControllerIntent, ...]:
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
            analyze = self._japanese_pronunciation

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
            analyze_groups = self._english_word_groups

            def work(
                *,
                surface: str = surface,
                analyze_groups: Callable[
                    [str], Sequence[tuple[str, Sequence[str]]]
                ] | None = analyze_groups,
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

        request = self._operation_request(
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

    def _save(self) -> tuple[DictionaryControllerIntent, ...]:
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

        request = self._operation_request(
            editor,
            operation=operation,
            language=language,
        )
        return (DictionaryOperationIntent(request, info_status(status), work),)

    def _open_discard_confirmation(self, editor: EditorState) -> tuple[EditorIntent, ...]:
        self.editor = EditorState(
            kind="dictionary_discard_confirmation",
            title="DISCARD DICTIONARY CHANGES?",
            origin=("dictionary", None),
            selection="discard",
            payload={"parent_editor": deepcopy(editor)},
        )
        return (UpdateStatusIntent(""),)

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
        if (
            isinstance(editor.selection, tuple)
            and editor.selection[0] == "entry"
            and editor.selection[1] is not None
        ):
            index = editor.selection[1]
            editor.payload["entry_index"] = index
        else:
            index = editor.payload.get("entry_index")
        if index is None:
            return (UpdateStatusIntent("Select a dictionary word to delete."),)
        if editor.kind == "dictionary_japanese_list":
            entries = editor.payload["entries"]
            if not 0 <= index < len(entries):
                return ()
            identifier, word = entries[index]
            payload = {
                "language": "ja",
                "identifier": identifier,
                "surface": word.surface,
                "pronunciation": word.pronunciation,
                "accent": word.accent_type,
                "moras": _reading_morae(word.pronunciation),
                "parent_editor": deepcopy(editor),
            }
        else:
            entries = editor.payload["entries"]
            if not 0 <= index < len(entries):
                return ()
            entry = entries[index]
            payload = {
                "language": "en",
                "identifier": entry.surface,
                "surface": entry.surface,
                "phonemes": tuple(entry.phonemes),
                "parent_editor": deepcopy(editor),
            }
        self.editor = EditorState(
            kind="dictionary_delete_confirmation",
            title="DELETE DICTIONARY WORD?",
            origin=("dictionary", None),
            selection="delete",
            payload=payload,
        )
        return (UpdateStatusIntent(""),)

    def _delete_confirmed(self) -> tuple[DictionaryControllerIntent, ...]:
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
        request = self._operation_request(
            editor,
            operation=operation,
            language=language,
        )
        return (DictionaryOperationIntent(request, info_status(status), work),)

    def complete_operation(
        self,
        request: DictionaryOperationRequest,
        value: Any = None,
        error: BaseException | None = None,
    ) -> tuple[EditorIntent, ...]:
        """Apply a worker result to its originating Dictionary surface on the UI thread."""

        editor = self.editor
        if editor is not request.originating_editor:
            # The operation has finished, so clear its footer Status even if
            # the originating surface was replaced before the event arrived.
            return (UpdateStatusIntent(""),)

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

    def _activate(self) -> tuple[DictionaryControllerIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        selected = editor.selection
        if editor.kind == "dictionary_menu":
            if selected == "japanese":
                self._stack.append(deepcopy(editor))
                self.editor = self._japanese_list_state()
            elif selected == "english":
                self._stack.append(deepcopy(editor))
                self.editor = self._english_list_state()
            elif selected == "back":
                self._restore_parent()
            return (UpdateStatusIntent(""),)
        if editor.kind == "dictionary_japanese_list":
            if selected == "add":
                self._stack.append(deepcopy(editor))
                self.editor = self._japanese_entry_state(word_uuid=None, word=None)
                return self._begin_field("surface", "")
            if selected == "delete":
                return self._open_delete_confirmation()
            if selected == "back":
                self._restore_parent()
                return (UpdateStatusIntent(""),)
            if isinstance(selected, tuple) and selected[0] == "entry":
                index = selected[1]
                entries = editor.payload["entries"]
                if index is not None and 0 <= index < len(entries):
                    word_uuid, word = entries[index]
                    self._stack.append(deepcopy(editor))
                    self.editor = self._japanese_entry_state(
                        word_uuid=word_uuid,
                        word=word,
                    )
                return ()
        if editor.kind == "dictionary_english_list":
            if selected == "add":
                self._stack.append(deepcopy(editor))
                self.editor = self._english_entry_state()
                return self._begin_field("surface", "")
            if selected == "delete":
                return self._open_delete_confirmation()
            if selected == "back":
                self._restore_parent()
                return (UpdateStatusIntent(""),)
            if isinstance(selected, tuple) and selected[0] == "entry":
                index = selected[1]
                entries = editor.payload["entries"]
                if index is not None and 0 <= index < len(entries):
                    entry = entries[index]
                    self._stack.append(deepcopy(editor))
                    self.editor = self._english_entry_state(
                        surface=entry.surface,
                        phonemes=entry.phonemes,
                        original_surface=entry.surface,
                    )
                return ()
        if editor.kind == "dictionary_japanese_duplicates":
            if isinstance(selected, tuple) and selected[0] == "entry":
                index = selected[1]
                matches = editor.payload["matches"]
                if index is not None and 0 <= index < len(matches):
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
                return ()
        if editor.kind == "dictionary_japanese_entry":
            if selected == "surface":
                return self._begin_field("surface", editor.payload["surface"])
            if selected == "pronunciation":
                return self._begin_field(
                    "pronunciation", editor.payload["pronunciation"]
                )
            if selected == "generate_pronunciation":
                return self._generate_pronunciation()
            if selected == "preview":
                return self._preview()
            if selected == "save":
                return self._save()
            if selected == "dictionary":
                return self.open_menu(preserve_current=True)
            if selected == "back":
                return self._back_from_entry()
        if editor.kind == "dictionary_english_entry":
            if selected == "surface":
                return self._begin_field("surface", editor.payload["surface"])
            if selected == "phonemes":
                return self._begin_field(
                    "phonemes", " ".join(editor.payload["phonemes"])
                )
            if selected == "generate_pronunciation":
                return self._generate_pronunciation()
            if selected == "preview":
                return self._preview()
            if selected == "save":
                return self._save()
            if selected == "dictionary":
                return self.open_menu(preserve_current=True)
            if selected == "back":
                return self._back_from_entry()
        if editor.kind == "dictionary_delete_confirmation":
            if selected == "delete":
                return self._delete_confirmed()
            if selected == "cancel":
                self.editor = editor.payload["parent_editor"]
                return (UpdateStatusIntent(""),)
        if editor.kind == "dictionary_discard_confirmation":
            if selected == "discard":
                return self._discard_entry(editor.payload["parent_editor"])
            if selected == "cancel":
                self.editor = editor.payload["parent_editor"]
                return (UpdateStatusIntent(""),)
        return ()

    def handle_key(
        self,
        key: Any,
        *,
        screen_width: int = 80,
        preview_busy: bool = False,
        dictionary_operation_busy: bool = False,
    ) -> tuple[DictionaryControllerIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if dictionary_operation_busy:
            if key in ("q", "Q", "\x03"):
                return (QuitIntent(),)
            if key == "?":
                return (OpenHelpIntent(),)
            return ()
        if preview_busy and editor.kind in {
            "dictionary_japanese_entry",
            "dictionary_english_entry",
        }:
            return (UpdateStatusIntent("Wait for Preview to finish before editing the dictionary."),)

        if editor.active_field is not None:
            if key in _ENTER_KEYS:
                return self._finish_field()
            if key == _ESCAPE:
                return self._back_from_entry()
            if key == curses.KEY_LEFT:
                editor.input_cursor = max(0, editor.input_cursor - 1)
                return ()
            if key == curses.KEY_RIGHT:
                editor.input_cursor = min(len(editor.input_value), editor.input_cursor + 1)
                return ()
            if key == curses.KEY_HOME or key == "\x01":
                editor.input_cursor = 0
                return ()
            if key == curses.KEY_END or key == "\x05":
                editor.input_cursor = len(editor.input_value)
                return ()
            if key in (curses.KEY_UP, curses.KEY_DOWN):
                prefix = self._input_prefix(editor)
                input_width = max(1, screen_width - 1 - _display_width(prefix))
                editor.input_cursor = _move_wrapped_cursor(
                    editor.input_value,
                    editor.input_cursor,
                    -1 if key == curses.KEY_UP else 1,
                    input_width,
                )
                return ()
            if key in (curses.KEY_BACKSPACE, "\x7f", "\x08"):
                if editor.input_cursor:
                    editor.input_value = (
                        editor.input_value[: editor.input_cursor - 1]
                        + editor.input_value[editor.input_cursor :]
                    )
                    editor.input_cursor -= 1
                editor.error = EMPTY_STATUS
                return ()
            if key == curses.KEY_DC:
                if editor.input_cursor < len(editor.input_value):
                    editor.input_value = (
                        editor.input_value[: editor.input_cursor]
                        + editor.input_value[editor.input_cursor + 1 :]
                    )
                editor.error = EMPTY_STATUS
                return ()
            if isinstance(key, str) and key and all(
                char.isprintable() or char == "　" for char in key
            ):
                editor.input_value = (
                    editor.input_value[: editor.input_cursor]
                    + key
                    + editor.input_value[editor.input_cursor :]
                )
                editor.input_cursor += len(key)
                editor.error = EMPTY_STATUS
            return ()

        if key in ("q", "Q", "\x03"):
            return (QuitIntent(),)
        if key == "?":
            return (OpenHelpIntent(),)

        if editor.kind in {
            "dictionary_japanese_entry",
            "dictionary_english_entry",
            "dictionary_menu",
            "dictionary_delete_confirmation",
            "dictionary_discard_confirmation",
        }:
            shortcut = resolve_shortcut(editor.kind, key, editor.payload)
            if shortcut is not None:
                editor.selection = shortcut.key
                editor.error = EMPTY_STATUS
                return self._activate()

        if editor.kind in {
            "dictionary_japanese_list",
            "dictionary_english_list",
        }:
            shortcut = resolve_shortcut(editor.kind, key, editor.payload)
            if shortcut is not None:
                if (
                    isinstance(editor.selection, tuple)
                    and editor.selection[0] == "entry"
                    and editor.selection[1] is not None
                ):
                    editor.payload["entry_index"] = editor.selection[1]
                editor.selection = shortcut.key
                editor.error = EMPTY_STATUS
                return self._activate()
        if editor.kind == "dictionary_japanese_duplicates":
            shortcut = resolve_shortcut(editor.kind, key, editor.payload)
            if shortcut is not None and shortcut.key == "back":
                self.editor = None
                return (UpdateStatusIntent(""),)

        if key == _ESCAPE:
            if editor.kind in {
                "dictionary_japanese_entry",
                "dictionary_english_entry",
            }:
                return self._back_from_entry()
            if editor.kind in {
                "dictionary_delete_confirmation",
                "dictionary_discard_confirmation",
            }:
                self.editor = editor.payload["parent_editor"]
                return (UpdateStatusIntent(""),)
            self._restore_parent()
            return (UpdateStatusIntent(""),)

        if key == curses.KEY_UP:
            if editor.kind in {
                "dictionary_japanese_entry",
                "dictionary_english_entry",
            }:
                return self._move_entry_selection(-1)
            return self._move_dynamic_selection(-1)
        if key == curses.KEY_DOWN:
            if editor.kind in {
                "dictionary_japanese_entry",
                "dictionary_english_entry",
            }:
                return self._move_entry_selection(1)
            return self._move_dynamic_selection(1)

        if key in (curses.KEY_LEFT, curses.KEY_RIGHT):
            direction = -1 if key == curses.KEY_LEFT else 1
            if editor.kind == "dictionary_japanese_entry":
                return self._adjust_japanese(direction)
            if editor.kind == "dictionary_english_entry":
                return self._adjust_english(direction)

        if key in _ENTER_KEYS:
            return self._activate()
        return ()
