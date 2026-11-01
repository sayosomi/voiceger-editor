"""Execute production Web session lifecycle handlers in the Node DOM harness."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


class WebSessionLifecycleBrowserTests(unittest.TestCase):
    def test_reload_reauthentication_expiry_retry_and_stale_response(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for Web lifecycle browser tests")
        root = Path(__file__).resolve().parents[1]
        fixture = root / "tests" / "fixtures" / "web_session_lifecycle.js"
        assets = root / "voiceger_editor" / "web_assets"
        result = subprocess.run(
            [node, str(fixture), str(assets / "app.js"), str(assets / "index.html")],
            capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WEB_SESSION_LIFECYCLE_BROWSER_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
