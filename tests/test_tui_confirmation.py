import curses
import unittest

from voiceger_editor.tui_confirmation import (
    ConfirmationDetail,
    ConfirmationInteraction,
    confirmation_lines,
    handle_confirmation_key,
)


def no_wrap(value: str, _width: int) -> tuple[str, ...]:
    return (value,)


class TuiConfirmationTests(unittest.TestCase):
    def test_navigation_shortcuts_enter_and_escape_share_declarative_order(self):
        self.assertEqual(
            handle_confirmation_key(
                "delete_confirmation",
                "delete",
                curses.KEY_DOWN,
            ),
            ConfirmationInteraction(
                "cancel",
                handled=True,
                changed=True,
            ),
        )
        self.assertEqual(
            handle_confirmation_key(
                "delete_confirmation",
                "cancel",
                curses.KEY_DOWN,
            ),
            ConfirmationInteraction(
                "cancel",
                handled=True,
                changed=False,
            ),
        )
        self.assertEqual(
            handle_confirmation_key(
                "delete_confirmation",
                "cancel",
                curses.KEY_UP,
            ),
            ConfirmationInteraction(
                "delete",
                handled=True,
                changed=True,
            ),
        )
        self.assertEqual(
            handle_confirmation_key(
                "delete_confirmation",
                "cancel",
                "d",
            ),
            ConfirmationInteraction(
                "delete",
                activation="delete",
                handled=True,
                changed=True,
            ),
        )
        self.assertEqual(
            handle_confirmation_key(
                "delete_confirmation",
                "cancel",
                "\n",
            ),
            ConfirmationInteraction(
                "cancel",
                activation="cancel",
                handled=True,
                changed=False,
            ),
        )
        self.assertEqual(
            handle_confirmation_key(
                "delete_confirmation",
                "delete",
                "\x1b",
            ),
            ConfirmationInteraction(
                "cancel",
                activation="cancel",
                handled=True,
                changed=True,
            ),
        )
        self.assertEqual(
            handle_confirmation_key(
                "delete_confirmation",
                "delete",
                "x",
            ),
            ConfirmationInteraction("delete"),
        )

    def test_document_uses_details_warning_and_declared_action_labels(self):
        self.assertEqual(
            confirmation_lines(
                "batch_delete_confirmation",
                "delete",
                warning="This Caption will be removed.",
                details=(ConfirmationDetail("Caption", "hello"),),
                width=80,
                wrap_text=no_wrap,
            ),
            (
                ("", None),
                ("Caption", None),
                ("  hello", None),
                ("", None),
                ("This Caption will be removed.", None),
                ("", None),
                ("▶ [D] Delete caption", "delete"),
                ("  [Esc] Cancel", "cancel"),
            ),
        )

    def test_cancel_focus_uses_the_same_visible_escape_row(self):
        lines = confirmation_lines(
            "dictionary_discard_confirmation",
            "cancel",
            warning="Unsaved changes will be discarded.",
            width=80,
            wrap_text=no_wrap,
        )

        self.assertEqual(
            lines[-2:],
            (
                ("  [D] Discard", "discard"),
                ("▶ [Esc] Cancel", "cancel"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
