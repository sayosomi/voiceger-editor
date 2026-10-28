"""Protected Web session HTTP contract; no Voiceger models required."""

from __future__ import annotations

import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from voiceger_editor.web import create_web_app
from voiceger_editor.web_sessions import WebSessionOperations


_TOKEN = "a-test-only-token-with-at-least-thirty-two-characters"


class WebSessionRouteTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": _TOKEN})
        self.environment.start()
        self.service = WebSessionOperations(
            runtime_checker=lambda: SimpleNamespace(ready=True)
        )
        self.client = TestClient(create_web_app(service=self.service))
        self.read_headers = {"Authorization": f"Bearer {_TOKEN}"}
        self.write_headers = {
            **self.read_headers,
            "X-Voiceger-Web-Request": "1",
        }

    def tearDown(self):
        self.service.shutdown()
        self.client.close()
        self.environment.stop()

    def create_session(self):
        response = self.client.post("/api/web/sessions", headers=self.write_headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def await_terminal(self, session_id, operation_id):
        url = f"/api/web/sessions/{session_id}/operations/{operation_id}"
        until = time.monotonic() + 5
        while time.monotonic() < until:
            response = self.client.get(url, headers=self.read_headers)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            if result["status"] in ("succeeded", "cancelled", "failed"):
                return result
            time.sleep(0.01)
        self.fail("Web operation did not terminate in 5 seconds")

    def test_authorization_and_fail_closed_configuration(self):
        self.assertEqual(self.client.get("/api/web/health").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.post("/api/web/sessions").status_code, 401)
        self.assertEqual(
            self.client.get("/api/web/sessions/not-a-session").status_code, 401
        )
        wrong = {"Authorization": "Bearer wrong", "X-Voiceger-Web-Request": "1"}
        self.assertEqual(
            self.client.post("/api/web/sessions", headers=wrong).status_code, 401
        )
        with patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": ""}):
            self.assertEqual(
                self.client.post("/api/web/sessions", headers=self.write_headers).status_code,
                503,
            )
        with patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": "too-short"}):
            self.assertEqual(
                self.client.post("/api/web/sessions", headers=self.write_headers).status_code,
                503,
            )

    def test_mutation_header_and_origin_protection(self):
        self.assertEqual(
            self.client.post("/api/web/sessions", headers=self.read_headers).status_code,
            403,
        )
        blocked = {**self.write_headers, "Origin": "https://evil.example"}
        self.assertEqual(
            self.client.post("/api/web/sessions", headers=blocked).status_code, 403
        )
        null_origin = {**self.write_headers, "Origin": "null"}
        self.assertEqual(
            self.client.post("/api/web/sessions", headers=null_origin).status_code, 403
        )
        accepted = {**self.write_headers, "Origin": "http://testserver"}
        self.assertEqual(
            self.client.post("/api/web/sessions", headers=accepted).status_code, 201
        )
        self.assertNotIn(
            "access-control-allow-origin",
            self.client.get("/api/web/health").headers,
        )

    def test_create_reload_read_and_close_session(self):
        session = self.create_session()
        self.assertEqual(session["item_count"], 0)
        self.assertEqual(session["default_take_count"], 4)
        self.assertTrue(session["ephemeral"])
        self.assertFalse(session["restart_recovery"])
        self.assertGreaterEqual(len(session["id"]), 24)
        url = "/api/web/sessions/" + session["id"]
        self.assertEqual(self.client.get(url, headers=self.read_headers).json(), session)
        self.assertEqual(self.client.delete(url, headers=self.write_headers).status_code, 204)
        self.assertEqual(self.client.get(url, headers=self.read_headers).status_code, 404)
        self.assertEqual(self.client.delete(url, headers=self.write_headers).status_code, 404)

    def test_restart_does_not_recover_session(self):
        session_id = self.create_session()["id"]
        other = TestClient(
            create_web_app(
                service=WebSessionOperations(
                    runtime_checker=lambda: SimpleNamespace(ready=True)
                )
            )
        )
        try:
            self.assertEqual(
                other.get("/api/web/sessions/" + session_id, headers=self.read_headers).status_code,
                404,
            )
        finally:
            other.app.state.web_sessions.shutdown()
            other.close()

    def test_runtime_operation_runs_on_worker_and_is_per_session(self):
        first = self.create_session()["id"]
        second = self.create_session()["id"]
        result = self.client.post(
            f"/api/web/sessions/{first}/operations/runtime-check",
            headers=self.write_headers,
        )
        self.assertEqual(result.status_code, 202, result.text)
        operation = result.json()
        self.assertEqual(operation["kind"], "runtime-check")
        self.assertIn(operation["status"], ("running", "succeeded"))
        self.assertNotIn("voiceger_root", str(operation))
        self.assertEqual(
            self.client.get(
                f"/api/web/sessions/{second}/operations/{operation['id']}",
                headers=self.read_headers,
            ).status_code,
            404,
        )
        completed = self.await_terminal(first, operation["id"])
        self.assertEqual(completed["status"], "succeeded")
        self.assertEqual(completed["result"], {"ready": True})
        self.assertEqual((completed["completed"], completed["total"]), (1, 1))
        self.assertIsNone(completed["error"])

    def test_worker_conflict_cancellation_close_and_recovery(self):
        began, release = threading.Event(), threading.Event()

        def slow_check():
            began.set()
            release.wait(5)
            return SimpleNamespace(ready=True)

        self.service._runtime_checker = slow_check
        first = self.create_session()["id"]
        second = self.create_session()["id"]
        url = f"/api/web/sessions/{first}/operations/runtime-check"
        try:
            started = self.client.post(url, headers=self.write_headers)
            self.assertEqual(started.status_code, 202)
            self.assertTrue(began.wait(2))
            job_id = started.json()["id"]
            self.assertEqual(
                self.client.post(
                    f"/api/web/sessions/{second}/operations/runtime-check",
                    headers=self.write_headers,
                ).status_code, 409
            )
            self.assertEqual(self.client.post(url, headers=self.write_headers).status_code, 409)
            self.assertEqual(
                self.client.delete(
                    f"/api/web/sessions/{first}", headers=self.write_headers
                ).status_code, 409
            )
            cancel_url = f"/api/web/sessions/{first}/operations/{job_id}/cancel"
            self.assertEqual(
                self.client.post(cancel_url, headers=self.write_headers).json()["status"],
                "cancelling",
            )
            release.set()
            self.assertEqual(self.await_terminal(first, job_id)["status"], "cancelled")
            self.assertEqual(
                self.client.post(
                    f"/api/web/sessions/{second}/operations/runtime-check",
                    headers=self.write_headers,
                ).status_code, 202
            )
        finally:
            release.set()

    def test_runtime_failure_redacts_exception_content(self):
        def failed():
            raise RuntimeError("/Users/private/voiceger and TOKEN=secret")

        self.service._runtime_checker = failed
        session_id = self.create_session()["id"]
        response = self.client.post(
            f"/api/web/sessions/{session_id}/operations/runtime-check",
            headers=self.write_headers,
        )
        result = self.await_terminal(session_id, response.json()["id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "Runtime inspection failed")
        self.assertNotIn("private", str(result))
        self.assertIsNone(result["result"])

    def test_wrong_routes_methods_and_untrusted_payload(self):
        session_id = self.create_session()["id"]
        self.assertEqual(
            self.client.post(
                f"/api/web/sessions/{session_id}/operations/synthesis",
                headers=self.write_headers,
            ).status_code,
            405,  # Read-only operation-detail path does not accept POST.
        )
        self.assertEqual(
            self.client.post("/api/web/health", headers=self.write_headers).status_code, 405
        )
        self.assertEqual(
            self.client.get(
                f"/api/web/sessions/{session_id}/operations/unknown",
                headers=self.read_headers,
            ).status_code, 404
        )
        self.assertEqual(
            self.client.get("/synthesis", headers=self.read_headers).status_code, 404
        )


if __name__ == "__main__":
    unittest.main()
