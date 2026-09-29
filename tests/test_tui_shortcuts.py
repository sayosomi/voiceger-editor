import curses
from types import SimpleNamespace
import unittest

from voiceger_accent_adapter.settings import Settings
from voiceger_accent_adapter.tui_editors import (
    EditorState,
    OpenHelpIntent,
    QuitIntent,
    TuiEditorController,
)
from voiceger_accent_adapter.tui_shortcuts import (
    menu_definitions,
    menu_items,
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
                "p": "preview", "a": "apply", "e": "edit_text",
                "c": "clear", "r": "reset", "b": "back",
            },
            "english_word": {
                "p": "preview", "a": "apply", "e": "edit_text",
                "c": "clear", "r": "reset", "b": "back",
            },
            "section_text": {
                "p": "preview", "a": "apply", "r": "reset",
                "d": "delete_section", "b": "back",
            },
            "add_section": {"a": "add", "c": "clear", "r": "reset", "b": "back"},
            "settings": {
                "s": "style_id", "v": "speed", "n": "take_count",
                "o": "output_dir", "x": "save_text",
                "a": "apply", "r": "reset", "b": "back",
            },
            "delete_confirmation": {"d": "delete", "b": "cancel"},
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
                if item.kind == "action":
                    self.assertIsNotNone(
                        item.shortcut,
                        f"{screen_kind}:{item.key} ordinary action requires a shortcut",
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
