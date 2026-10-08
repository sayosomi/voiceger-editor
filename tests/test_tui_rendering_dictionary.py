import curses
from voiceger_editor.tui_display import _display_width
from voiceger_editor.user_dictionary import JapaneseWordType
from tests.tui_rendering_test_support import RenderingTestCase, FakeScreen, render_state

from types import SimpleNamespace
import unittest

from voiceger_editor.tui_rendering_dictionary import build_document
from voiceger_editor.tui_rendering_editor_common import EditorDocumentBuilder


class DictionaryRenderingDocumentTests(RenderingTestCase):
    def test_dictionary_menu_owner(self):
        editor = SimpleNamespace(
            kind="dictionary_menu",
            title="DICTIONARY",
            selection="japanese",
            payload={"japanese_count": 3, "english_count": 2},
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
        )
        builder = EditorDocumentBuilder(render_state(editor=editor), 80)
        self.assertTrue(build_document(builder))
        self.assertTrue(any("3 words" in line for line, _key in builder.lines))
        self.assertTrue(any("2 words" in line for line, _key in builder.lines))

    def test_dictionary_entry_action_groups_match_add_and_edit_layout(self):
        cases = (
            (
                "dictionary_japanese_entry",
                {
                    "surface": "ずんだもん",
                    "moras": ("ズ", "ン", "ダ", "モ", "ン"),
                    "accent": 3,
                    "word_type": SimpleNamespace(value="PROPER_NOUN"),
                    "word_type_label": "固有名詞",
                    "priority": 5,
                    "entry_index": 0,
                    "entry_total": 4,
                    "can_delete": True,
                },
                [
                    "surface",
                    "generate_pronunciation",
                    "pronunciation",
                    "word_type",
                    "priority",
                    "preview",
                    "save",
                    "delete",
                    "dictionary",
                    "back",
                ],
                True,
            ),
            (
                "dictionary_english_entry",
                {
                    "surface": "Voiceger",
                    "phonemes": ("V", "OY1", "AH0", "JH", "ER0"),
                    "entry_index": 0,
                    "entry_total": 4,
                    "can_delete": True,
                },
                [
                    "surface",
                    "generate_pronunciation",
                    "phonemes",
                    "preview",
                    "save",
                    "delete",
                    "dictionary",
                    "back",
                ],
                True,
            ),
            (
                "dictionary_japanese_entry",
                {
                    "surface": "",
                    "moras": (),
                    "accent": 1,
                    "word_type": SimpleNamespace(value="PROPER_NOUN"),
                    "word_type_label": "固有名詞",
                    "priority": 5,
                    "entry_index": None,
                    "entry_total": None,
                    "can_delete": False,
                },
                [
                    "surface",
                    "generate_pronunciation",
                    "pronunciation",
                    "word_type",
                    "priority",
                    "preview",
                    "save",
                    "dictionary",
                    "back",
                ],
                False,
            ),
            (
                "dictionary_english_entry",
                {
                    "surface": "",
                    "phonemes": (),
                    "entry_index": None,
                    "entry_total": None,
                    "can_delete": False,
                },
                [
                    "surface",
                    "generate_pronunciation",
                    "phonemes",
                    "preview",
                    "save",
                    "dictionary",
                    "back",
                ],
                False,
            ),
        )
        for kind, payload, expected_keys, can_delete in cases:
            with self.subTest(kind=kind, can_delete=can_delete):
                editor = SimpleNamespace(
                    kind=kind,
                    title=(
                        "EDIT DICTIONARY WORD"
                        if can_delete
                        else "ADD DICTIONARY WORD"
                    ),
                    selection="surface",
                    payload=payload,
                    active_field=None,
                    input_value="",
                    input_cursor=0,
                    error="",
                    scroll=0,
                )
                document, _cursor_line, _cursor_column = self.renderer.editor_document(
                    render_state(editor=editor), 80
                )
                keyed = [
                    (index, key)
                    for index, (_text, key) in enumerate(document)
                    if key and key != "entry_navigator"
                ]
                positions = {key: index for index, key in keyed}

                self.assertEqual([key for _index, key in keyed], expected_keys)
                if kind == "dictionary_japanese_entry":
                    visible = "\n".join(line for line, _key in document)
                    self.assertIn("Word type      < 固有名詞 >", visible)
                    self.assertNotIn("PROPER_NOUN", visible)
                self.assertEqual(
                    positions["generate_pronunciation"],
                    positions["surface"] + 1,
                )
                pronunciation_key = (
                    "pronunciation"
                    if kind == "dictionary_japanese_entry"
                    else "phonemes"
                )
                self.assertEqual(
                    positions[pronunciation_key],
                    positions["generate_pronunciation"] + 2,
                )
                last_persisted = (
                    "priority"
                    if kind == "dictionary_japanese_entry"
                    else pronunciation_key
                )
                self.assertEqual(positions["preview"], positions[last_persisted] + 2)
                self.assertEqual(positions["save"], positions["preview"] + 1)
                if can_delete:
                    self.assertEqual(positions["delete"], positions["save"] + 2)
                    self.assertEqual(
                        positions["dictionary"],
                        positions["delete"] + 2,
                    )
                else:
                    self.assertEqual(
                        positions["dictionary"],
                        positions["save"] + 2,
                    )
                self.assertEqual(positions["back"], positions["dictionary"] + 1)

    def test_dictionary_existing_entry_titles_have_right_aligned_navigator(self):
        cases = (
            SimpleNamespace(
                kind="dictionary_japanese_entry",
                title="EDIT JAPANESE DICTIONARY WORD",
                selection="entry_navigator",
                payload={
                    "surface": "あめ",
                    "moras": ("ア", "メ"),
                    "accent": 1,
                    "word_type": SimpleNamespace(value="PROPER_NOUN"),
                    "word_type_label": "固有名詞",
                    "priority": 5,
                    "entry_index": 1,
                    "entry_total": 4,
                },
                active_field=None,
                input_value="",
                input_cursor=0,
                error="",
                scroll=0,
            ),
            SimpleNamespace(
                kind="dictionary_english_entry",
                title="EDIT ENGLISH DICTIONARY WORD",
                selection="entry_navigator",
                payload={
                    "surface": "hello",
                    "phonemes": ("HH", "AH0", "L", "OW1"),
                    "entry_index": 1,
                    "entry_total": 4,
                },
                active_field=None,
                input_value="",
                input_cursor=0,
                error="",
                scroll=0,
            ),
        )
        for editor in cases:
            with self.subTest(kind=editor.kind):
                document, _cursor_line, _cursor_column = self.renderer.editor_document(
                    render_state(editor=editor), 50
                )

                self.assertEqual(document[0][1], "entry_navigator")
                self.assertTrue(document[0][0].startswith(editor.title))
                self.assertTrue(document[0][0].endswith("< 2 / 4 >"))
                self.assertLessEqual(_display_width(document[0][0]), 49)

                screen = FakeScreen(rows=24, columns=50)
                self.renderer.render_editor(
                    screen,
                    render_state(editor=editor),
                    screen.rows,
                    screen.columns,
                )
                header = next(item for item in screen.drawn if item[0] == 0)
                self.assertTrue(header[2].endswith("< 2 / 4 >"))
                self.assertTrue(header[3] & curses.A_REVERSE)

                editor.selection = "surface"
                screen = FakeScreen(rows=24, columns=50)
                self.renderer.render_editor(
                    screen,
                    render_state(editor=editor),
                    screen.rows,
                    screen.columns,
                )
                header = next(item for item in screen.drawn if item[0] == 0)
                self.assertFalse(header[3] & curses.A_REVERSE)

    def test_dictionary_add_entry_title_has_no_navigator(self):
        editor = SimpleNamespace(
            kind="dictionary_english_entry",
            title="ADD ENGLISH DICTIONARY WORD",
            selection="surface",
            payload={
                "surface": "",
                "phonemes": (),
                "entry_index": None,
                "entry_total": None,
            },
            active_field="surface",
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 50
        )

        self.assertEqual(document[0], ("ADD ENGLISH DICTIONARY WORD", None))
        self.assertNotIn("<", document[0][0])

    def test_dictionary_menu_renders_language_shortcuts(self):
        editor = SimpleNamespace(
            kind="dictionary_menu",
            title="DICTIONARY",
            selection="japanese",
            payload={"japanese_count": 2, "english_count": 1},
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )

        self.assertIn(("▶ [J] Japanese      2 words", "japanese"), document)
        self.assertIn(("  [E] English       1 words", "english"), document)
        self.assertIn(("  [Esc] Back", "back"), document)

    def test_dictionary_menu_renders_import_entry_point(self):
        editor = SimpleNamespace(
            kind="dictionary_menu",
            title="DICTIONARY",
            selection="import",
            payload={"japanese_count": 2, "english_count": 1},
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )

        self.assertIn(("▶ [I] Import dictionary", "import"), document)

    def test_dictionary_import_review_is_compact_and_marks_conflicts_after_checkbox(self):
        items = (
            SimpleNamespace(
                selected=True,
                relation=SimpleNamespace(value="new"),
                incoming=SimpleNamespace(surface="ずんだもん"),
            ),
            SimpleNamespace(
                selected=False,
                relation=SimpleNamespace(value="conflict"),
                incoming=SimpleNamespace(surface="雨"),
            ),
        )
        editor = SimpleNamespace(
            kind="dictionary_import_review",
            title="IMPORT DICTIONARY",
            selection=("import_entry", 1),
            payload={
                "items": items,
                "word_type_labels": ("固有名詞", "普通名詞"),
                "total_count": 3,
                "exact_duplicate_count": 1,
                "review_count": 2,
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        labels = [line for line, _key in document]

        self.assertIn("3 words found", labels)
        self.assertIn("1 already exist", labels)
        self.assertIn("2 to review", labels)
        self.assertIn("  [x]   ずんだもん  固有名詞", labels)
        self.assertIn("▶ [ ] ! 雨  普通名詞", labels)
        self.assertFalse(any("CONFLICT" in line or "NEW" in line for line in labels))
        self.assertIn(("  [I] Import selected", "import_selected"), document)
        self.assertIn(("  [C] Clear selection", "clear_selection"), document)
        self.assertIn(("  [Esc] Back", "back"), document)

    def test_dictionary_import_detail_renders_japanese_fields_and_english_comparison(self):
        japanese_item = SimpleNamespace(
            incoming=SimpleNamespace(
                surface="雨",
                pronunciation="アメ",
                accent_type=1,
                priority=6,
            ),
            existing=None,
        )
        japanese = SimpleNamespace(
            kind="dictionary_import_japanese_detail",
            title="IMPORT JAPANESE WORD",
            selection="word_type",
            payload={
                "item": japanese_item,
                "word_type": JapaneseWordType.COMMON_NOUN,
                "word_type_label": "普通名詞",
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=japanese), 80
        )
        labels = [line for line, _key in document]
        self.assertIn("Incoming", labels)
        self.assertIn("  Surface        雨", labels)
        self.assertIn("  Pronunciation  アメ", labels)
        self.assertIn("  Accent         1", labels)
        self.assertTrue(any("品詞" in line and "普通名詞" in line for line in labels))
        self.assertFalse(any("COMMON_NOUN" in line for line in labels))
        self.assertIn("  Priority       6", labels)

        english_item = SimpleNamespace(
            incoming=SimpleNamespace(
                surface="Voiceger",
                phonemes=["V", "OY1", "AH0", "JH", "ER0"],
            ),
            existing=SimpleNamespace(
                surface="Voiceger",
                phonemes=["V", "OY1", "JH", "ER0"],
            ),
        )
        english = SimpleNamespace(
            kind="dictionary_import_english_detail",
            title="IMPORT ENGLISH WORD",
            selection="back",
            payload={"item": english_item},
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=english), 80
        )
        labels = [line for line, _key in document]
        self.assertIn("Incoming", labels)
        self.assertIn("Existing", labels)
        self.assertTrue(any("V OY1 AH0 JH ER0" in line for line in labels))
        self.assertTrue(any("V OY1 JH ER0" in line for line in labels))
        self.assertFalse(any("Word type" in line for line in labels))

    def test_dictionary_delete_confirmation_matches_common_modal(self):
        cases = (
            (
                "ja",
                {
                    "language": "ja",
                    "surface": "ずんだもん",
                    "moras": ("ズ", "ン", "ダ", "モ", "ン"),
                    "accent": 3,
                },
                "ズ ン [ダ] モ ン",
            ),
            (
                "en",
                {
                    "language": "en",
                    "surface": "Voiceger",
                    "phonemes": ("V", "OY1", "AH0", "JH", "ER0"),
                },
                "V OY1 AH0 JH ER0",
            ),
        )
        for language, payload, pronunciation in cases:
            with self.subTest(language=language):
                editor = SimpleNamespace(
                    kind="dictionary_delete_confirmation",
                    title="DELETE DICTIONARY WORD?",
                    selection="delete",
                    payload={
                        **payload,
                        "warning": "This dictionary word will be removed.",
                    },
                    active_field=None,
                    input_value="",
                    input_cursor=0,
                    error="",
                    scroll=0,
                )

                document, _cursor_line, _cursor_column = self.renderer.editor_document(
                    render_state(editor=editor), 80
                )
                labels = [line for line, _key in document]

                self.assertEqual(labels[0], "DELETE DICTIONARY WORD?")
                self.assertIn("Surface", labels)
                self.assertIn(f"  {payload['surface']}", labels)
                self.assertIn("Pronunciation", labels)
                self.assertIn(f"  {pronunciation}", labels)
                self.assertIn("This dictionary word will be removed.", labels)
                self.assertEqual(labels[-2:], ["▶ [D] Delete", "  [Esc] Cancel"])

                editor.selection = "cancel"
                document, _cursor_line, _cursor_column = self.renderer.editor_document(
                    render_state(editor=editor), 80
                )
                labels = [line for line, _key in document]
                self.assertEqual(labels[-2:], ["  [D] Delete", "▶ [Esc] Cancel"])

    def test_empty_dictionary_list_renders_add_and_back(self):
        editor = SimpleNamespace(
            kind="dictionary_japanese_list",
            title="JAPANESE DICTIONARY",
            selection="add",
            payload={
                "entries": (),
                "sort_mode": "surface_asc",
                "text_filter": "",
                "filter_enabled": False,
                "word_type_filter": "ALL",
                "visible_count": 0,
                "total_count": 0,
                "can_delete": False,
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )

        self.assertTrue(
            any("No Japanese dictionary words." in line for line, _key in document)
        )
        self.assertIn(("▶ [A] Add", "add"), document)
        self.assertTrue(any("[S] Sort" in line for line, _key in document))
        filter_line = next(line for line, key in document if key == "filter")
        self.assertIn("[F] Filter", filter_line)
        self.assertIn("Not set", filter_line)
        self.assertNotIn("<", filter_line)
        self.assertNotIn(">", filter_line)
        self.assertIn(("  [Esc] Back", "back"), document)
        self.assertFalse(any("[X] Delete" in line for line, _key in document))

    def test_filtered_dictionary_no_match_keeps_actions_and_shown_total_count(self):
        editor = SimpleNamespace(
            kind="dictionary_english_list",
            title="ENGLISH DICTIONARY",
            selection="filter",
            payload={
                "entries": (),
                "sort_mode": "added_desc",
                "text_filter": "missing",
                "filter_enabled": True,
                "word_type_filter": None,
                "visible_count": 0,
                "total_count": 3,
                "can_delete": False,
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        visible = "\n".join(line for line, _key in document)

        self.assertIn("Showing 0 / 3 words", visible)
        self.assertIn("No matching English dictionary words.", visible)
        self.assertIn("[S] Sort", visible)
        self.assertIn("Added ↓", visible)
        self.assertIn("[F] Filter", visible)
        self.assertIn("On: missing", visible)
        self.assertIn("[A] Add", visible)
        self.assertNotIn("[X] Delete", visible)

    def test_configured_disabled_filter_keeps_angle_bracket_off_state(self):
        editor = SimpleNamespace(
            kind="dictionary_english_list",
            title="ENGLISH DICTIONARY",
            selection="filter",
            payload={
                "entries": (),
                "sort_mode": "surface_asc",
                "text_filter": "record",
                "filter_enabled": False,
                "word_type_filter": None,
                "visible_count": 0,
                "total_count": 0,
                "can_delete": False,
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )
        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        filter_line = next(line for line, key in document if key == "filter")
        self.assertIn("< Off >", filter_line)

    def test_dictionary_sort_chooser_renders_all_modes_without_angle_brackets(self):
        editor = SimpleNamespace(
            kind="dictionary_sort",
            title="SORT JAPANESE DICTIONARY",
            selection=("sort", 1),
            payload={
                "language": "ja",
                "modes": (
                    "surface_asc",
                    "surface_desc",
                    "word_type",
                    "priority_asc",
                    "priority_desc",
                    "added_asc",
                    "added_desc",
                ),
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        visible = "\n".join(line for line, _key in document)
        self.assertIn("Surface ↑", visible)
        self.assertIn("▶ Surface ↓", visible)
        self.assertIn("Word type", visible)
        self.assertIn("Priority ↓", visible)
        self.assertIn("Added ↓", visible)
        self.assertNotIn("< Surface", visible)
        self.assertIn("[Esc] Back", visible)

    def test_dictionary_filter_editors_render_focused_fields_and_actions(self):
        cases = (
            SimpleNamespace(
                kind="dictionary_japanese_filter",
                title="FILTER JAPANESE DICTIONARY",
                selection="word_type",
                payload={
                    "language": "ja",
                    "text_query": "アメ",
                    "word_type_filter": "PROPER_NOUN",
                },
                active_field=None,
                input_value="",
                input_cursor=0,
                error="",
                scroll=0,
            ),
            SimpleNamespace(
                kind="dictionary_english_filter",
                title="FILTER ENGLISH DICTIONARY",
                selection="text_query",
                payload={"language": "en", "text_query": "ER0 D"},
                active_field=None,
                input_value="",
                input_cursor=0,
                error="",
                scroll=0,
            ),
        )
        for editor in cases:
            with self.subTest(kind=editor.kind):
                document, _cursor_line, _cursor_column = self.renderer.editor_document(
                    render_state(editor=editor), 80
                )
                visible = "\n".join(line for line, _key in document)
                self.assertIn("[A] Apply", visible)
                self.assertIn("[C] Clear filter", visible)
                self.assertIn("[Esc] Back", visible)
                if editor.kind == "dictionary_japanese_filter":
                    self.assertIn("Surface / Pronunciation", visible)
                    self.assertIn("PROPER_NOUN", visible)
                else:
                    self.assertIn("Surface / ARPAbet", visible)
                    self.assertIn("ER0 D", visible)

    def test_japanese_dictionary_list_uses_main_mora_accent_display(self):
        word = SimpleNamespace(
            surface="ずんだもん",
            pronunciation="ズンダモン",
            accent_type=3,
        )
        editor = SimpleNamespace(
            kind="dictionary_japanese_list",
            title="JAPANESE DICTIONARY",
            selection=("entry", 0),
            payload={
                "entries": (("uuid", word),),
                "sort_mode": "priority_desc",
                "text_filter": "ずん",
                "filter_enabled": True,
                "word_type_filter": "PROPER_NOUN",
                "visible_count": 1,
                "total_count": 4,
                "can_delete": True,
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )

        entry = next(
            line for line, key in document if key == ("entry", 0)
        )
        self.assertIn("ずんだもん", entry)
        self.assertIn("ズ ン [ダ] モ ン", entry)
        visible = "\n".join(line for line, _key in document)
        self.assertNotIn("accent_type", visible)
        self.assertNotIn("Enter Edit", visible)
        self.assertIn("Showing 1 / 4 words", visible)
        self.assertTrue(any("[S] Sort" in line and "Priority ↓" in line for line, _key in document))
        self.assertTrue(any("[F] Filter" in line and "On: ずん" in line for line, _key in document))
        self.assertIn(("  [A] Add", "add"), document)
        self.assertIn(("  [X] Delete", "delete"), document)
        self.assertIn(("  [Esc] Back", "back"), document)

    def test_english_dictionary_list_renders_selectable_actions(self):
        entry = SimpleNamespace(
            surface="hello",
            phonemes=("HH", "AH0", "L", "OW1"),
        )
        editor = SimpleNamespace(
            kind="dictionary_english_list",
            title="ENGLISH DICTIONARY",
            selection="add",
            payload={
                "entries": (entry,),
                "entry_index": 0,
                "sort_mode": "surface_asc",
                "text_filter": "",
                "filter_enabled": False,
                "word_type_filter": None,
                "visible_count": 1,
                "total_count": 1,
                "can_delete": True,
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        visible = "\n".join(line for line, _key in document)

        self.assertIn(("▶ [A] Add", "add"), document)
        self.assertTrue(any("[S] Sort" in line and "Surface ↑" in line for line, _key in document))
        filter_line = next(line for line, key in document if key == "filter")
        self.assertIn("[F] Filter", filter_line)
        self.assertIn("Not set", filter_line)
        self.assertNotIn("<", filter_line)
        self.assertNotIn(">", filter_line)
        self.assertIn(("  [X] Delete", "delete"), document)
        self.assertIn(("  [Esc] Back", "back"), document)
        self.assertNotIn("Enter Edit", visible)

    def test_dictionary_number_tokens_mark_direct_shortcuts_and_align_content(self):
        entries = tuple(
            SimpleNamespace(
                surface=f"word-{number:02d}",
                phonemes=("W", "ER1", "D"),
            )
            for number in range(1, 13)
        )
        editor = SimpleNamespace(
            kind="dictionary_english_list",
            title="ENGLISH DICTIONARY",
            selection=("entry", 11),
            payload={
                "entries": entries,
                "sort_mode": "surface_asc",
                "text_filter": "",
                "filter_enabled": False,
                "word_type_filter": None,
                "visible_count": 12,
                "total_count": 12,
                "can_delete": True,
                "number_jump_active": False,
                "number_jump_value": "",
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor),
            80,
        )
        rows = {
            key[1] + 1: line
            for line, key in document
            if isinstance(key, tuple) and key[0] == "entry"
        }

        self.assertTrue(rows[1].startswith("  [1]  word-01"))
        self.assertTrue(rows[9].startswith("  [9]  word-09"))
        self.assertTrue(rows[10].startswith("   10  word-10"))
        self.assertTrue(rows[12].startswith("▶  12  word-12"))
        surface_columns = {
            rows[number].index(f"word-{number:02d}")
            for number in (1, 9, 10, 12)
        }
        self.assertEqual(surface_columns, {7})

    def test_english_dictionary_aligns_pronunciation_by_surface_display_width(self):
        entries = (
            SimpleNamespace(
                surface="Tohoku",
                phonemes=("T", "OW1", "HH", "OW0", "K", "UW0"),
            ),
            SimpleNamespace(
                surface="Zundamon",
                phonemes=("Z", "UW1", "N", "D", "AA0", "M", "OW0", "N"),
            ),
            SimpleNamespace(
                surface="Zunko",
                phonemes=("Z", "UW1", "NG", "K", "OW0"),
            ),
        )
        editor = SimpleNamespace(
            kind="dictionary_english_list",
            title="ENGLISH DICTIONARY",
            selection=("entry", 1),
            payload={
                "entries": entries,
                "sort_mode": "surface_asc",
                "text_filter": "",
                "filter_enabled": False,
                "word_type_filter": None,
                "visible_count": len(entries),
                "total_count": len(entries),
                "can_delete": True,
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        rows = {
            key[1]: line
            for line, key in document
            if isinstance(key, tuple) and key[0] == "entry"
        }

        def pronunciation_column(line, surface):
            surface_end = line.index(surface) + len(surface)
            suffix = line[surface_end:]
            gap = len(suffix) - len(suffix.lstrip(" "))
            return _display_width(line[:surface_end]) + gap

        columns = {
            pronunciation_column(rows[index], entry.surface)
            for index, entry in enumerate(entries)
        }
        self.assertEqual(len(columns), 1)

    def test_japanese_dictionary_aligns_pronunciation_by_terminal_display_width(self):
        entries = (
            (
                "id-1",
                SimpleNamespace(
                    surface="雨",
                    pronunciation="アメ",
                    accent_type=1,
                ),
            ),
            (
                "id-2",
                SimpleNamespace(
                    surface="ずんだもん",
                    pronunciation="ズンダモン",
                    accent_type=3,
                ),
            ),
            (
                "id-3",
                SimpleNamespace(
                    surface="東北",
                    pronunciation="トウホク",
                    accent_type=2,
                ),
            ),
        )
        editor = SimpleNamespace(
            kind="dictionary_japanese_list",
            title="JAPANESE DICTIONARY",
            selection=("entry", 1),
            payload={
                "entries": entries,
                "sort_mode": "surface_asc",
                "text_filter": "",
                "filter_enabled": False,
                "word_type_filter": "ALL",
                "visible_count": len(entries),
                "total_count": len(entries),
                "can_delete": True,
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 80
        )
        rows = {
            key[1]: line
            for line, key in document
            if isinstance(key, tuple) and key[0] == "entry"
        }

        def pronunciation_column(line, surface):
            surface_end = line.index(surface) + len(surface)
            suffix = line[surface_end:]
            gap = len(suffix) - len(suffix.lstrip(" "))
            return _display_width(line[:surface_end]) + gap

        columns = {
            pronunciation_column(rows[index], word.surface)
            for index, (_word_uuid, word) in enumerate(entries)
        }
        self.assertEqual(len(columns), 1)

    def test_dictionary_surface_column_is_bounded_by_long_visible_surface(self):
        entries = (
            SimpleNamespace(surface="short", phonemes=("SH", "AO1", "R", "T")),
            SimpleNamespace(surface="x" * 80, phonemes=("EH1", "K", "S")),
        )
        editor = SimpleNamespace(
            kind="dictionary_english_list",
            title="ENGLISH DICTIONARY",
            selection=("entry", 0),
            payload={
                "entries": entries,
                "sort_mode": "surface_asc",
                "text_filter": "",
                "filter_enabled": False,
                "word_type_filter": None,
                "visible_count": len(entries),
                "total_count": len(entries),
                "can_delete": True,
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), 100
        )
        short_row = next(line for line, key in document if key == ("entry", 0))
        phoneme_column = _display_width(short_row[: short_row.index("SH")])

        self.assertLessEqual(phoneme_column, 40)

    def test_dictionary_lists_render_visible_one_based_numbers(self):
        japanese_entries = tuple(
            (
                f"id-{number}",
                SimpleNamespace(
                    surface=f"単語{number}",
                    pronunciation="ズンダモン",
                    accent_type=3,
                ),
            )
            for number in range(1, 3)
        )
        english_entries = tuple(
            SimpleNamespace(
                surface=f"word-{number}",
                phonemes=("W", "ER1", "D"),
            )
            for number in range(1, 3)
        )
        cases = (
            SimpleNamespace(
                kind="dictionary_japanese_list",
                title="JAPANESE DICTIONARY",
                selection=("entry", 1),
                payload={
                    "entries": japanese_entries,
                    "sort_mode": "surface_asc",
                    "text_filter": "",
                    "filter_enabled": False,
                    "word_type_filter": "ALL",
                    "visible_count": 2,
                    "total_count": 2,
                    "can_delete": True,
                },
                active_field=None,
                input_value="",
                input_cursor=0,
                error="",
                scroll=0,
            ),
            SimpleNamespace(
                kind="dictionary_english_list",
                title="ENGLISH DICTIONARY",
                selection=("entry", 1),
                payload={
                    "entries": english_entries,
                    "sort_mode": "surface_asc",
                    "text_filter": "",
                    "filter_enabled": False,
                    "word_type_filter": None,
                    "visible_count": 2,
                    "total_count": 2,
                    "can_delete": True,
                },
                active_field=None,
                input_value="",
                input_cursor=0,
                error="",
                scroll=0,
            ),
        )

        for editor in cases:
            with self.subTest(kind=editor.kind):
                document, _cursor_line, _cursor_column = self.renderer.editor_document(
                    render_state(editor=editor), 80
                )
                first = next(line for line, key in document if key == ("entry", 0))
                second = next(line for line, key in document if key == ("entry", 1))
                self.assertIn("[1]  ", first)
                self.assertIn("[2]  ", second)
                self.assertTrue(second.startswith("▶ [2]  "))

    def test_dictionary_jump_row_is_pinned_only_for_ten_or_more_visible_entries(self):
        def editor_for(count, *, active=False, value="", total=None, filtered=False):
            entries = tuple(
                SimpleNamespace(
                    surface=f"word-{number:02d}",
                    phonemes=("W", "ER1", "D"),
                )
                for number in range(1, count + 1)
            )
            return SimpleNamespace(
                kind="dictionary_english_list",
                title="ENGLISH DICTIONARY",
                selection=("entry", max(0, count - 1)) if count else "add",
                payload={
                    "entries": entries,
                    "entry_index": max(0, count - 1) if count else None,
                    "sort_mode": "surface_asc",
                    "text_filter": "word" if filtered else "",
                    "filter_enabled": filtered,
                    "word_type_filter": None,
                    "visible_count": count,
                    "total_count": count if total is None else total,
                    "can_delete": bool(entries),
                    "number_jump_active": active,
                    "number_jump_value": value,
                },
                active_field=None,
                input_value="",
                input_cursor=0,
                error="",
                scroll=0,
            )

        screen = FakeScreen(rows=10, columns=80)
        self.renderer.render_editor(
            screen,
            render_state(editor=editor_for(12)),
            screen.rows,
            screen.columns,
        )
        jump_row = next(item for item in screen.drawn if item[0] == 1)
        self.assertEqual(jump_row[2], "  [0] Jump to word")

        screen = FakeScreen(rows=10, columns=80)
        self.renderer.render_editor(
            screen,
            render_state(editor=editor_for(12, active=True, value="11")),
            screen.rows,
            screen.columns,
        )
        self.assertIn(
            (1, 0, "▶ Jump to word: 11_ / 12"),
            [(row, col, text) for row, col, text, _attr in screen.drawn],
        )
        self.assertIn(
            (2, 0, "  [Enter] Open   [Esc] Cancel"),
            [(row, col, text) for row, col, text, _attr in screen.drawn],
        )

        for editor in (
            editor_for(9),
            editor_for(3, total=12, filtered=True),
        ):
            with self.subTest(count=len(editor.payload["entries"])):
                screen = FakeScreen(rows=10, columns=80)
                self.renderer.render_editor(
                    screen,
                    render_state(editor=editor),
                    screen.rows,
                    screen.columns,
                )
                self.assertFalse(
                    any(
                        "Jump to word" in text
                        for _row, _col, text, _attr in screen.drawn
                    )
                )

if __name__ == "__main__":
    unittest.main()
