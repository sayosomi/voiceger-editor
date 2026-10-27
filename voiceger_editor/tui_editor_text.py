"""Caption, section-text, and Add Section editor ownership."""

from __future__ import annotations

from copy import deepcopy
from typing import Sequence

from .query_editing import (
    append_english_section,
    append_japanese_section,
    delete_utterance_section,
    english_section_text_preview_query,
    merge_english_section_text_groups,
    replace_english_section_text,
    replace_japanese_section_text,
    japanese_section_text_preview_query,
)
from .tui_editor_common import (
    ApplyCaptionIntent,
    CaptionApplicationResult,
    ClearAdjustmentFeedbackIntent,
    EditorIntent,
    EditorOwnerBase,
    EditorState,
    PreviewIntent,
    ReplaceQueryIntent,
    UpdateStatusIntent,
    adjustment_feedback_intents,
)
from .tui_editor_english import EnglishGroupingCache, EnglishWordGroup
from .tui_input import PasteText
from .tui_status import EMPTY_STATUS, error_status
from .voicevox_api_models import AudioQuery


class TuiTextEditorOwner(EditorOwnerBase):
    """Own Caption, section-text, and Add Section draft/application policy."""

    def open_caption(
        self,
        initial: str | None,
        *,
        current_caption: str | None,
        origin: tuple[str, int | None],
        busy: bool,
        multiline: bool = False,
    ) -> tuple[EditorIntent, ...]:
        if busy and not multiline:
            return (UpdateStatusIntent("Wait for synthesis to finish before editing Caption."),)
        current = initial if initial is not None else current_caption or ""
        self.editor = EditorState(
            kind="caption",
            title="ADD CAPTIONS" if multiline else "EDIT CAPTION TEXT",
            origin=origin,
            selection="draft",
            payload={
                "draft": current,
                "opening_caption": current,
                "multiline": multiline,
            },
        )
        return (
            UpdateStatusIntent(""),
            *self.begin_field("draft", current),
        )

    def open_add_section(
        self,
        query: AudioQuery | None,
        *,
        pure_japanese_utterance_text: str | None,
        origin: tuple[str, int | None],
        busy: bool,
    ) -> tuple[EditorIntent, ...]:
        if busy:
            return (
                UpdateStatusIntent(
                    "Wait for synthesis to finish before adding a section."
                ),
            )
        if query is None:
            return (UpdateStatusIntent(error_status("There is no active utterance.")),)
        self.editor = EditorState(
            kind="add_section",
            title="ADD SECTION",
            origin=origin,
            selection="draft",
            payload={
                "language": "ja",
                "opening_language": "ja",
                "draft": "",
                "opening_draft": "",
                "pure_japanese_utterance_text": pure_japanese_utterance_text,
            },
        )
        return (UpdateStatusIntent(""), *self.begin_field("draft", ""))

    def open_section_text(
        self,
        query: AudioQuery | None,
        *,
        pure_japanese_utterance_text: str | None,
        busy: bool,
    ) -> tuple[EditorIntent, ...]:
        parent = self.editor
        if busy or parent is None or parent.kind not in {"japanese", "english_word"}:
            return ()
        if query is None:
            return (UpdateStatusIntent(error_status("There is no active utterance.")),)

        segment_index = parent.payload["segment_index"]
        language = "ja" if parent.kind == "japanese" else "en"
        if language == "ja" and segment_index is None:
            if query.voicegerSegments is not None or pure_japanese_utterance_text is None:
                return (
                    UpdateStatusIntent(
                        error_status("The pure Japanese section text is unavailable.")
                    ),
                )
            source_text = pure_japanese_utterance_text
        else:
            if query.voicegerSegments is None or type(segment_index) is not int:
                return (UpdateStatusIntent(error_status("The selected section is unavailable.")),)
            if not 0 <= segment_index < len(query.voicegerSegments):
                return (UpdateStatusIntent(error_status("The selected section is unavailable.")),)
            segment = query.voicegerSegments[segment_index]
            if segment.language != language:
                return (UpdateStatusIntent(error_status("The selected section changed.")),)
            source_text = segment.text

        can_delete = (
            query.voicegerSegments is not None
            and len(query.voicegerSegments) > 1
        )
        payload: dict[str, Any] = {
            "language": language,
            "segment_index": segment_index,
            "opening_text": source_text,
            "draft": source_text,
            "parent_editor": deepcopy(parent),
            "can_delete": can_delete,
        }
        if language == "en":
            payload["grouping"] = parent.payload["grouping"]

        self.editor = EditorState(
            kind="section_text",
            title="EDIT SECTION TEXT",
            origin=parent.origin,
            selection="draft",
            payload=payload,
        )
        return (UpdateStatusIntent(""), *self.begin_field("draft", source_text))

    @staticmethod
    def _set_caption_draft(editor: EditorState, caption: str) -> None:
        editor.payload["draft"] = caption
        editor.input_value = caption
        editor.input_original = caption
        editor.input_cursor = len(caption)

    @staticmethod
    def _set_text_draft(editor: EditorState, value: str) -> None:
        editor.payload["draft"] = value
        editor.input_value = value
        editor.input_original = value
        editor.input_cursor = len(value)
        editor.active_field = None

    @staticmethod
    def _word_group_values(
        grouping: EnglishGroupingCache,
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return tuple((group.label, group.phonemes) for group in grouping.groups)

    @staticmethod
    def _grouping_cache(
        source_text: str,
        groups: Sequence[tuple[str, Sequence[str]]],
    ) -> EnglishGroupingCache:
        return EnglishGroupingCache(
            source_text,
            tuple(
                EnglishWordGroup(
                    label=label,
                    phonemes=tuple(phonemes),
                    editable=any(character.isalpha() for character in label),
                )
                for label, phonemes in groups
            ),
        )

    @staticmethod
    def _validated_text(editor: EditorState) -> str:
        text = editor.payload["draft"]
        language = "Japanese" if editor.payload["language"] == "ja" else "English"
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{language} section text must not be empty")
        if "\n" in text or "\r" in text:
            raise ValueError(f"{language} section text must not contain newlines")
        return text

    def preview_section_text(
        self,
        query: AudioQuery | None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind != "section_text":
            return ()
        try:
            if query is None:
                raise ValueError("There is no active utterance")
            text = self._validated_text(editor)
            if editor.payload["language"] == "ja":
                preview_query = japanese_section_text_preview_query(
                    query,
                    text,
                    segment_index=editor.payload["segment_index"],
                )
            else:
                grouping: EnglishGroupingCache = editor.payload["grouping"]
                preview_query = english_section_text_preview_query(
                    query,
                    segment_index=editor.payload["segment_index"],
                    text=text,
                    old_groups=self._word_group_values(grouping),
                    new_groups=self._english_word_groups(text),
                )
        except Exception as exc:
            editor.error = error_status(f"Preview failed: {exc}")
            return ()
        editor.error = EMPTY_STATUS
        return (PreviewIntent(preview_query),)

    def apply_section_text(
        self,
        query: AudioQuery | None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind != "section_text":
            return ()
        try:
            if query is None:
                raise ValueError("There is no active utterance")
            text = self._validated_text(editor)
            if text == editor.payload["opening_text"]:
                return self._close_editor("Section text unchanged.")
            segment_index = editor.payload["segment_index"]
            accepted_grouping = None
            if editor.payload["language"] == "ja":
                updated = replace_japanese_section_text(
                    query,
                    text,
                    segment_index=segment_index,
                )
                pure_text = text if segment_index is None else None
            else:
                grouping: EnglishGroupingCache = editor.payload["grouping"]
                merged = merge_english_section_text_groups(
                    query,
                    segment_index=segment_index,
                    old_groups=self._word_group_values(grouping),
                    new_groups=self._english_word_groups(text),
                )
                updated = replace_english_section_text(
                    query,
                    segment_index=segment_index,
                    text=text,
                    phoneme_groups=merged,
                )
                accepted_grouping = self._grouping_cache(text, merged)
                pure_text = None
        except Exception as exc:
            editor.error = error_status(f"Section text was not changed: {exc}")
            return ()
        return (
            ReplaceQueryIntent(
                query=updated,
                editor_kind="section_text",
                success_status="Section text updated; old takes cleared.",
                grouping_index=(
                    segment_index if accepted_grouping is not None else None
                ),
                accepted_grouping=accepted_grouping,
                pure_japanese_utterance_text=pure_text,
            ),
        )

    def open_delete_confirmation(
        self, query: AudioQuery | None
    ) -> tuple[EditorIntent, ...]:
        """Confirm deletion of the whole section behind either editor kind."""
        editor = self.editor
        if (
            editor is None
            or editor.kind not in {"section_text", "japanese", "english_word"}
            or not editor.payload.get("can_delete", False)
        ):
            return ()
        segment_index = editor.payload["segment_index"]
        language = (
            editor.payload["language"]
            if editor.kind == "section_text"
            else ("ja" if editor.kind == "japanese" else "en")
        )
        opening_text = (
            editor.payload["opening_text"]
            if editor.kind == "section_text"
            else editor.payload["section_text"]
        )
        segments = query.voicegerSegments if query is not None else None
        if (
            segments is None
            or len(segments) <= 1
            or type(segment_index) is not int
            or not 0 <= segment_index < len(segments)
            or segments[segment_index].language != language
            or segments[segment_index].text != opening_text
        ):
            editor.error = error_status(
                "Selected section changed; reopen the editor before deleting."
            )
            return ()

        self.editor = EditorState(
            kind="delete_confirmation",
            title="DELETE SECTION?",
            origin=editor.origin,
            selection="cancel",
            payload={
                "warning": "This section will be removed from the synthesized utterance.",
                "target_segment_index": segment_index,
                "target_language": language,
                "target_text": opening_text,
                "parent_editor": deepcopy(editor),
            },
        )
        return (ClearAdjustmentFeedbackIntent(), UpdateStatusIntent(""))

    def delete_section(
        self,
        query: AudioQuery | None,
    ) -> tuple[EditorIntent, ...]:
        confirmation = self.editor
        if confirmation is None or confirmation.kind != "delete_confirmation":
            return ()
        section_editor: EditorState = confirmation.payload["parent_editor"]
        self.editor = section_editor
        try:
            if query is None:
                raise ValueError("There is no active utterance")
            segment_index = confirmation.payload["target_segment_index"]
            segments = query.voicegerSegments
            if (
                segments is None
                or len(segments) <= 1
                or type(segment_index) is not int
                or not 0 <= segment_index < len(segments)
                or segments[segment_index].language != confirmation.payload["target_language"]
                or segments[segment_index].text != confirmation.payload["target_text"]
            ):
                raise ValueError("selected section changed; reopen the editor")
            updated, pure_text = delete_utterance_section(
                query,
                segment_index=segment_index,
            )
        except Exception as exc:
            section_editor.error = error_status(f"Section was not deleted: {exc}")
            return ()
        return (
            ReplaceQueryIntent(
                query=updated,
                editor_kind="delete_section",
                success_status="Section deleted; old takes cleared.",
                deleted_segment_index=segment_index,
                pure_japanese_utterance_text=pure_text,
            ),
        )

    def add_section(
        self,
        query: AudioQuery | None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind != "add_section":
            return ()
        try:
            if query is None:
                raise ValueError("There is no active utterance")
            text = self._validated_text(editor)
            language = editor.payload["language"]
            pure_text = editor.payload["pure_japanese_utterance_text"]
            if language == "ja":
                updated = append_japanese_section(
                    query,
                    text,
                    pure_japanese_utterance_text=pure_text,
                )
                accepted_grouping = None
                grouping_index = None
            else:
                generated = self._english_word_groups(text)
                updated = append_english_section(
                    query,
                    text,
                    phoneme_groups=generated,
                    pure_japanese_utterance_text=pure_text,
                )
                assert updated.voicegerSegments is not None
                grouping_index = len(updated.voicegerSegments) - 1
                accepted_grouping = self._grouping_cache(text, generated)
        except Exception as exc:
            editor.error = error_status(f"Section was not added: {exc}")
            return ()
        language_name = "Japanese" if language == "ja" else "English"
        return (
            ReplaceQueryIntent(
                query=updated,
                editor_kind="add_section",
                success_status=f"{language_name} section added; old takes cleared.",
                grouping_index=grouping_index,
                accepted_grouping=accepted_grouping,
            ),
        )

    def apply_caption(
        self,
        current_caption: str | None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind != "caption":
            return ()
        source = editor.payload["draft"]
        if current_caption is not None and source == current_caption:
            return self._close_editor("Caption unchanged.")
        return (ApplyCaptionIntent(source),)

    def activate_selection(
        self,
        query: AudioQuery | None,
        current_caption: str | None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        selected = editor.selection
        if editor.kind == "caption":
            if selected == "draft":
                return self.begin_field("draft", editor.payload["draft"])
            if selected == "apply":
                return self.apply_caption(current_caption)
            if selected == "clear":
                self._set_caption_draft(editor, "")
                editor.error = EMPTY_STATUS
                return (UpdateStatusIntent("Caption draft cleared."),)
            if selected == "reset":
                self._set_caption_draft(
                    editor, editor.payload["opening_caption"]
                )
                editor.error = EMPTY_STATUS
                return (UpdateStatusIntent("Caption draft reset."),)
            if selected == "back":
                return self.cancel()
            return ()

        if editor.kind == "section_text":
            if selected == "draft":
                return self.begin_field("draft", editor.input_value)
            if selected == "preview":
                return self.preview_section_text(query)
            if selected == "apply":
                return self.apply_section_text(query)
            if selected == "reset":
                self._set_text_draft(editor, editor.payload["opening_text"])
                editor.error = EMPTY_STATUS
                return (UpdateStatusIntent("Section text draft reset."),)
            if selected == "delete_section":
                return self.open_delete_confirmation(query)
            if selected == "back":
                return self.cancel()
            return ()

        if editor.kind == "add_section":
            if selected == "draft":
                return self.begin_field("draft", editor.input_value)
            if selected == "add":
                return self.add_section(query)
            if selected == "clear":
                self._set_text_draft(editor, "")
                editor.error = EMPTY_STATUS
                return (UpdateStatusIntent("New section draft cleared."),)
            if selected == "reset":
                editor.payload["language"] = editor.payload["opening_language"]
                self._set_text_draft(editor, editor.payload["opening_draft"])
                editor.error = EMPTY_STATUS
                return (UpdateStatusIntent("New section draft reset."),)
            if selected == "back":
                return self.cancel()
        return ()

    def handle_active_field_key(self, key) -> bool:
        editor = self.editor
        if (
            editor is None
            or editor.kind != "caption"
            or not editor.payload.get("multiline", False)
            or editor.active_field is None
        ):
            return False
        if isinstance(key, PasteText):
            editor.input_value = (
                editor.input_value[: editor.input_cursor]
                + key.text
                + editor.input_value[editor.input_cursor :]
            )
            editor.input_cursor += len(key.text)
            editor.error = EMPTY_STATUS
            return True
        if key == "\x0e":
            editor.input_value = (
                editor.input_value[: editor.input_cursor]
                + "\n"
                + editor.input_value[editor.input_cursor :]
            )
            editor.input_cursor += 1
            editor.error = EMPTY_STATUS
            return True
        return False

    def adjust_add_section_language(
        self,
        direction: int,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if (
            editor is None
            or editor.kind != "add_section"
            or editor.selection != "language"
        ):
            return ()
        language = editor.payload["language"]
        changed = (
            (direction > 0 and language == "ja")
            or (direction < 0 and language == "en")
        )
        if changed:
            editor.payload["language"] = "en" if language == "ja" else "ja"
            editor.error = EMPTY_STATUS
            return (
                *adjustment_feedback_intents(
                    changed=True,
                    area="editor",
                    control="language",
                    direction=direction,
                ),
                UpdateStatusIntent(""),
            )
        return adjustment_feedback_intents(
            changed=False,
            area="editor",
            control="language",
            direction=direction,
        )

    def complete_caption_application(
        self,
        result: CaptionApplicationResult,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if result.error is not None:
            editor.error = error_status(f"Caption was not changed: {result.error}")
            return ()
        if result.unchanged:
            return self._close_editor("Caption unchanged.")
        if result.added_caption_count:
            count = result.added_caption_count
            status = (
                "Caption added."
                if count == 1
                else f"{count} Captions added."
            )
        else:
            status = (
                "Caption set."
                if result.initial_session_created
                else "Caption updated."
            )
        return self._close_editor(status)
