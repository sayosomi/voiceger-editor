import curses
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from voiceger_editor.settings import Settings
from voiceger_editor.tui_editors import (
    EditorState,
    OpenHelpIntent,
    QuitIntent,
    TuiEditorController,
)
from voiceger_editor.tui_rendering import TuiRenderer, TuiRenderState
from voiceger_editor.tui_shortcuts import (
    main_shortcut,
    main_shortcuts,
    menu_definitions,
    menu_items,
    resolve_main_shortcut,
    resolve_shortcut,
    validate_menu_definitions,
)


class TuiShortcutTests(unittest.TestCase):
    def make_controller(self):
        return TuiEditorController(
            english_word_groups=lambda _text: (),
            available_styles=lambda: (),
            input_prefix=lambda _editor: "▶ ",
        )

    @staticmethod
    def handle(controller, key):
        return controller.handle_key(
            key,
            settings=Settings(),
            query=None,
            current_caption="opening",
        )

    def test_declared_shortcuts_match_issue_47_contract(self):
        expected = {
            "caption": {"a": "apply", "c": "clear", "r": "reset", "b": "back"},
            "build_confirmation": {"r": "rebuild", "b": "cancel"},
            "japanese": {
                "p": "preview", "a": "apply", "s": "save_dictionary",
                "d": "dictionary", "e": "edit_text",
                "c": "clear", "r": "reset", "b": "back",
            },
            "english_word": {
                "p": "preview", "a": "apply", "s": "save_dictionary",
                "d": "dictionary", "e": "edit_text",
                "c": "clear", "r": "reset", "b": "back",
            },
            "section_text": {
                "p": "preview", "a": "apply", "r": "reset",
                "d": "delete_section", "b": "back",
            },
            "add_section": {"a": "add", "c": "clear", "r": "reset", "b": "back"},
            "settings": {
                "s": "style_id", "v": "speed", "n": "take_count",
                "o": "output_dir", "x": "save_text", "l": "save_lab",
                "k": "top_k", "p": "top_p", "t": "temperature",
                "d": "reset_sampling",
                "a": "apply", "r": "reset", "b": "back",
            },
            "dictionary_menu": {"j": "japanese", "e": "english", "b": "back"},
            "dictionary_japanese_list": {"a": "add", "x": "delete", "b": "back"},
            "dictionary_english_list": {"a": "add", "x": "delete", "b": "back"},
            "dictionary_japanese_duplicates": {"b": "back"},
            "dictionary_japanese_entry": {
                "g": "generate_pronunciation", "p": "preview",
                "s": "save", "d": "dictionary", "b": "back",
            },
            "dictionary_english_entry": {
                "g": "generate_pronunciation", "p": "preview",
                "s": "save", "d": "dictionary", "b": "back",
            },
            "dictionary_delete_confirmation": {"d": "delete", "b": "cancel"},
            "dictionary_discard_confirmation": {"d": "discard", "b": "cancel"},
            "delete_confirmation": {"d": "delete", "b": "cancel"},
            "clear_candidates_confirmation": {"c": "clear", "b": "cancel"},
            "help": {"b": "back"},
        }
        for screen_kind, mapping in expected.items():
            with self.subTest(screen_kind=screen_kind):
                payload = {"can_delete": True}
                actual = {
                    item.shortcut: item.key
                    for item in menu_items(screen_kind, payload)
                    if item.shortcut is not None
                }
                self.assertEqual(actual, mapping)

    def test_main_shortcuts_match_issue_49_contract_and_share_display_metadata(self):
        expected = {
            "b": "build_pronunciation",
            "a": "add_section",
            "g": "generate",
            "c": "clear_candidates",
            "s": "settings",
            "d": "dictionary",
            "?": "help",
            "q": "quit",
        }
        actual = {item.shortcut: item.navigation_key for item in main_shortcuts()}
        self.assertEqual(actual, expected)
        for shortcut, navigation_key in expected.items():
            with self.subTest(shortcut=shortcut):
                resolved = resolve_main_shortcut(shortcut)
                self.assertIsNotNone(resolved)
                self.assertEqual(resolved, main_shortcut(navigation_key))
                self.assertTrue(resolved.display_label.startswith(
                    f"[{shortcut.upper()}] "
                ))

        for removed in (curses.KEY_F5, "\x07", "R"):
            with self.subTest(removed=removed):
                self.assertIsNone(resolve_main_shortcut(removed))

    def test_metadata_architecture_is_valid_and_no_shortcut_exception_is_explicit(self):
        self.assertEqual(validate_menu_definitions(), ())
        for screen_kind, items in menu_definitions().items():
            shortcuts = [item.shortcut for item in items if item.shortcut is not None]
            self.assertEqual(
                len(shortcuts),
                len(set(shortcuts)),
                f"{screen_kind} has duplicate local shortcuts",
            )
            for item in items:
                if item.shortcut is None:
                    self.assertIsNotNone(
                        item.no_shortcut_reason,
                        f"{screen_kind}:{item.key} omitted a shortcut accidentally",
                    )
                if item.kind == "action" and item.shortcut is None:
                    self.assertIsNotNone(
                        item.no_shortcut_reason,
                        f"{screen_kind}:{item.key} action needs an explicit no-shortcut exception",
                    )

    def test_every_declared_shortcut_resolves_to_the_same_selectable_declaration(self):
        for screen_kind, definitions in menu_definitions().items():
            payload = {
                item.condition_key: True
                for item in definitions
                if item.condition_key is not None
            }
            visible = menu_items(screen_kind, payload)
            visible_keys = {item.key for item in visible}
            for item in visible:
                if item.shortcut is None:
                    continue
                with self.subTest(screen_kind=screen_kind, key=item.key):
                    resolved = resolve_shortcut(screen_kind, item.shortcut, payload)
                    self.assertEqual(resolved, item)
                    self.assertIn(resolved.key, visible_keys)
                    self.assertIn(item.shortcut.upper(), item.display_label)
                    self.assertIn(item.label, item.display_label)

    def test_activate_shortcuts_use_the_same_activation_path_as_enter(self):
        controller = self.make_controller()
        settings = Settings()
        for screen_kind, definitions in menu_definitions().items():
            if screen_kind == "help" or screen_kind.startswith("dictionary_"):
                continue
            payload = {
                item.condition_key: True
                for item in definitions
                if item.condition_key is not None
            }
            first = menu_items(screen_kind, payload)[0]
            controller.editor = EditorState(
                kind=screen_kind,
                title="",
                origin=("caption", None),
                selection=first.key,
                payload=dict(payload),
            )
            for item in menu_items(screen_kind, payload):
                if item.shortcut_mode != "activate":
                    continue
                with self.subTest(screen_kind=screen_kind, key=item.key):
                    controller.editor.selection = first.key
                    controller._activate_selection = Mock(return_value=())
                    controller.handle_key(
                        item.shortcut,
                        settings=settings,
                        query=None,
                        current_caption="opening",
                    )
                    self.assertEqual(controller.editor.selection, item.key)
                    controller._activate_selection.assert_called_once_with(
                        settings, None, "opening"
                    )

    def test_rendered_selectable_order_and_shortcut_hints_follow_declarations(self):
        renderer = TuiRenderer()
        samples = {
            "caption": ("draft", {"draft": "hello"}, "hello"),
            "build_confirmation": (
                "rebuild",
                {"warning": "warning"},
                "",
            ),
            "japanese": (
                "pronunciation",
                {"source_text": "雨"},
                "ア メ",
            ),
            "english_word": (
                "phonemes",
                {"label": "hello"},
                "HH AH1",
            ),
            "section_text": (
                "draft",
                {"language": "ja", "draft": "雨", "can_delete": True},
                "雨",
            ),
            "add_section": (
                "language",
                {"language": "ja", "draft": "雨"},
                "雨",
            ),
            "settings": (
                "style_id",
                {
                    "draft_settings": {
                        "style_id": "3",
                        "speed": "1.0",
                        "take_count": "4",
                        "output_dir": ".",
                        "save_text": False,
                    }
                },
                "",
            ),
            "delete_confirmation": (
                "delete",
                {"warning": "warning"},
                "",
            ),
        }
        for screen_kind, (selection, payload, input_value) in samples.items():
            with self.subTest(screen_kind=screen_kind):
                editor = SimpleNamespace(
                    kind=screen_kind,
                    title=screen_kind,
                    selection=selection,
                    payload=payload,
                    active_field=None,
                    input_value=input_value,
                    input_cursor=len(input_value),
                    error="",
                )
                state = TuiRenderState(
                    voiceger_root=Path("/nonexistent/voiceger"),
                    settings=Settings(),
                    session=None,
                    focus_key=("settings", None),
                    status="",
                    segments=(),
                    pronunciation_rows=(),
                    busy=False,
                    worker_operation=None,
                    worker_target=None,
                    operation_completed=0,
                    operation_total=0,
                    pressed_adjustment=None,
                    editor=editor,
                )
                document, _cursor_line, _cursor_column = renderer.editor_document(
                    state, 120
                )
                rendered_items = [
                    (text, key) for text, key in document if key is not None
                ]
                self.assertEqual(
                    [key for _text, key in rendered_items],
                    [item.key for item in menu_items(screen_kind, payload)],
                )
                text_by_key = {key: text for text, key in rendered_items}
                for item in menu_items(screen_kind, payload):
                    if item.shortcut is not None:
                        self.assertIn(
                            f"[{item.shortcut.upper()}]",
                            text_by_key[item.key],
                        )

    def test_dynamic_delete_shortcut_exists_only_when_delete_is_selectable(self):
        hidden = menu_items("section_text", {"can_delete": False})
        visible = menu_items("section_text", {"can_delete": True})
        self.assertNotIn("delete_section", [item.key for item in hidden])
        self.assertIn("delete_section", [item.key for item in visible])
        self.assertIsNone(resolve_shortcut("section_text", "d", {"can_delete": False}))
        target = resolve_shortcut("section_text", "d", {"can_delete": True})
        self.assertIsNotNone(target)
        self.assertEqual(target.key, "delete_section")

    def test_controller_selection_order_comes_from_shared_metadata(self):
        controller = self.make_controller()
        for screen_kind, payload in (
            ("caption", {"draft": "", "opening_caption": ""}),
            ("section_text", {"can_delete": True}),
            ("settings", {}),
        ):
            with self.subTest(screen_kind=screen_kind):
                controller.editor = EditorState(
                    kind=screen_kind,
                    title="",
                    origin=("caption", None),
                    selection=menu_items(screen_kind, payload)[0].key,
                    payload=dict(payload),
                )
                self.assertEqual(
                    controller.selection_keys(),
                    [item.key for item in menu_items(screen_kind, payload)],
                )

    def test_printable_shortcut_letters_are_text_while_field_is_active(self):
        controller = self.make_controller()
        controller.open_caption(
            "start",
            current_caption="start",
            origin=("caption", None),
            busy=False,
        )
        editor = controller.editor
        self.assertEqual(editor.active_field, "draft")

        for key in ("a", "b", "c", "q", "?"):
            intents = self.handle(controller, key)
            self.assertEqual(intents, ())
        self.assertEqual(editor.input_value, "startabcq?")
        self.assertEqual(editor.active_field, "draft")

        self.handle(controller, "\n")
        self.assertIsNone(editor.active_field)
        self.handle(controller, "c")
        self.assertEqual(editor.selection, "clear")
        self.assertEqual(editor.payload["draft"], "")

    def test_settings_focus_shortcuts_only_move_focus(self):
        controller = self.make_controller()
        controller.open_settings(
            Settings(),
            origin=("settings", None),
            busy=False,
        )
        editor = controller.editor
        opening = dict(editor.payload["draft_settings"])

        for key, target in (
            ("s", "style_id"),
            ("v", "speed"),
            ("n", "take_count"),
            ("o", "output_dir"),
            ("x", "save_text"),
            ("l", "save_lab"),
        ):
            with self.subTest(key=key):
                intents = self.handle(controller, key)
                self.assertEqual(editor.selection, target)
                self.assertIsNone(editor.active_field)
                self.assertEqual(editor.payload["draft_settings"], opening)
                self.assertTrue(intents)

    def test_editor_menu_global_help_and_quit_keys_emit_typed_intents(self):
        controller = self.make_controller()
        controller.open_settings(Settings(), origin=("settings", None), busy=False)

        self.assertIsInstance(self.handle(controller, "?")[0], OpenHelpIntent)
        for key in ("q", "Q", "\x03"):
            with self.subTest(key=key):
                self.assertIsInstance(self.handle(controller, key)[0], QuitIntent)

    def test_uppercase_local_shortcuts_are_not_implicitly_enabled(self):
        controller = self.make_controller()
        controller.open_settings(Settings(), origin=("settings", None), busy=False)
        editor = controller.editor
        editor.selection = "speed"
        self.assertEqual(self.handle(controller, "S"), ())
        self.assertEqual(editor.selection, "speed")


if __name__ == "__main__":
    unittest.main()
