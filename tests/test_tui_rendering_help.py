import unittest

from voiceger_editor.tui_rendering import TuiRenderer
from voiceger_editor.tui_rendering_help import help_document


class HelpRenderingDocumentTests(unittest.TestCase):
    def test_renderer_compatibility_wrapper_uses_help_document_owner(self):
        self.assertEqual(help_document(48), TuiRenderer.help_document(48))
        self.assertTrue(
            any(
                "Voiceger Editor" in segment[1]
                for row in help_document(48)
                for segment in row
            )
        )


if __name__ == "__main__":
    unittest.main()
