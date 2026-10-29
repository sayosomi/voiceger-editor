"""Actual browser-side pronunciation handlers: IME, Back/reload and stale state."""

from pathlib import Path
import shutil
import subprocess
import unittest


class PronunciationBrowserReviewTests(unittest.TestCase):
    def test_browser_event_contracts(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node needed to run production Web event handlers")
        root = Path(__file__).resolve().parents[1]
        script = root / "tests" / "fixtures" / "web_pronunciation_browser_review.js"
        app = root / "voiceger_editor" / "web_assets" / "app.js"
        result = subprocess.run(
            [node, str(script), str(app)],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn("WEB_PRONUNCIATION_BROWSER_REVIEW_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
