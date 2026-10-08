import unittest

from voiceger_editor.tui_rendering_navigation import navigation_document

from tests.tui_rendering_test_support import render_state


class NavigationRenderingDocumentTests(unittest.TestCase):
    def test_navigation_owner_builds_top_level_actions_without_session(self):
        labels = [
            line.text
            for line in navigation_document(
                render_state(focus_key=("settings", None)),
                80,
            )
        ]

        self.assertEqual(
            labels[-4:],
            ["▶ [S] Settings", "  [D] Dictionary", "  [?] Help", "  [Q] Quit"],
        )


if __name__ == "__main__":
    unittest.main()
