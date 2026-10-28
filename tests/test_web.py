"""Web foundation contract: packaged read-only shell and isolated endpoints."""

import unittest

from fastapi.testclient import TestClient

from voiceger_editor._version import __version__
from voiceger_editor.web import app


class WebFoundationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_health_is_read_only_and_minimal(self):
        response = self.client.get("/api/web/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"name": "voiceger-editor-web", "version": __version__, "status": "ok"},
        )
        self.assertEqual(response.headers["cache-control"], "no-store")
        for method in (self.client.post, self.client.put, self.client.delete):
            self.assertEqual(method("/api/web/health").status_code, 405)

    def test_mobile_shell_has_no_working_feature_controls(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertIn('<html lang="ja">', response.text)
        self.assertIn('name="viewport"', response.text)
        for title in ("Batch", "Dictionary", "Settings"):
            self.assertIn(title, response.text)
        self.assertIn("未実装", response.text)
        self.assertIn('aria-disabled="true"', response.text)
        self.assertIn('src="/assets/app.js"', response.text)
        self.assertIn('href="/assets/app.css"', response.text)
        self.assertIn('id="auth-form"', response.text)
        self.assertIn('id="caption-list"', response.text)

    def test_static_assets_have_correct_types(self):
        css = self.client.get("/assets/app.css")
        js = self.client.get("/assets/app.js")
        self.assertEqual(css.status_code, 200)
        self.assertEqual(js.status_code, 200)
        self.assertTrue(css.headers["content-type"].startswith("text/css"))
        self.assertIn("javascript", js.headers["content-type"])
        self.assertIn("@media (max-width: 350px)", css.text)
        self.assertIn('fetch("/api/web/health"', js.text)

    def test_no_other_api_or_schema_surface(self):
        for path in ("/docs", "/redoc", "/openapi.json", "/synthesis", "/api/web/synthesis"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.post("/").status_code, 405)

    def test_assets_reject_unknown_paths_and_traversal(self):
        self.assertEqual(self.client.get("/assets/unknown.css").status_code, 404)
        for path in (
            "/assets/%2e%2e/settings.py",
            "/assets/%2e%2e/%2e%2e/pyproject.toml",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertIn(response.status_code, (400, 403, 404))
                self.assertNotIn("requires-python", response.text)

    def test_restrictive_browser_headers(self):
        for path in ("/", "/assets/app.css", "/api/web/health", "/not-here"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.headers["x-content-type-options"], "nosniff")
                self.assertEqual(response.headers["x-frame-options"], "DENY")
                self.assertEqual(response.headers["referrer-policy"], "no-referrer")
                self.assertIn("default-src 'none'", response.headers["content-security-policy"])
                self.assertNotIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()
