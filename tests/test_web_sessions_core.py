"""Thread-safe Web session ownership and bounded worker lifecycle tests."""

from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace

from voiceger_editor.caption_batch import CaptionBatchItem
from voiceger_editor.web_sessions import (
    WebSessionCapacity,
    WebSessionClosed,
    WebSessionConflict,
    WebSessionNotFound,
    WebSessionOperations,
)


class FakeUtterance:
    def __init__(self):
        self.caption = "testing"
        self.discarded = 0

    def discard_takes(self):
        self.discarded += 1


class WebSessionCoreTests(unittest.TestCase):
    def test_capacity_expiry_and_takes_disposal(self):
        clock = [100.0]
        service = WebSessionOperations(
            clock=lambda: clock[0], max_sessions=2, idle_seconds=10
        )
        first = service.create()["id"]
        fake = FakeUtterance()
        service._sessions[first].batch.add_item(CaptionBatchItem(fake))
        second = service.create()["id"]
        self.assertNotEqual(first, second)
        self.assertEqual(service.get(first)["item_count"], 1)
        with self.assertRaises(WebSessionCapacity):
            service.create()

        clock[0] += 11
        with self.assertRaises(WebSessionNotFound):
            service.get(first)
        self.assertEqual(fake.discarded, 1)
        with self.assertRaises(WebSessionNotFound):
            service.get(second)
        self.assertEqual(service.create()["item_count"], 0)
        service.shutdown()

    def test_history_is_bounded_and_old_operation_is_not_addressable(self):
        service = WebSessionOperations(
            runtime_checker=lambda: SimpleNamespace(ready=False),
            history_limit=2,
        )
        session_id = service.create()["id"]
        ids = []
        for _ in range(3):
            operation = service.submit_runtime_check(session_id)
            operation_id = operation["id"]
            ids.append(operation_id)
            until = time.monotonic() + 3
            while service.get_operation(session_id, operation_id)["status"] == "running":
                if time.monotonic() >= until:
                    self.fail("operation did not finish")
                time.sleep(0.002)

        with self.assertRaises(WebSessionNotFound):
            service.get_operation(session_id, ids[0])
        for operation_id in ids[1:]:
            self.assertEqual(
                service.get_operation(session_id, operation_id)["result"],
                {"ready": False},
            )
        service.shutdown()

    def test_shutdown_fails_closed_and_cancels_running_operation(self):
        started, release = threading.Event(), threading.Event()

        def check():
            started.set()
            release.wait(3)
            return SimpleNamespace(ready=True)

        service = WebSessionOperations(runtime_checker=check)
        sid = service.create()["id"]
        try:
            service.submit_runtime_check(sid)
            self.assertTrue(started.wait(2))
            service.shutdown()
            with self.assertRaises(WebSessionClosed):
                service.create()
            with self.assertRaises(WebSessionClosed):
                service.get(sid)
        finally:
            release.set()

    def test_explicit_close_cleans_temporary_takes_only(self):
        service = WebSessionOperations()
        session_id = service.create()["id"]
        session = service._sessions[session_id]
        fake = FakeUtterance()
        session.batch.add_item(CaptionBatchItem(fake))
        service.delete(session_id)
        self.assertEqual(fake.discarded, 1)
        with self.assertRaises(WebSessionNotFound):
            service.get(session_id)
        service.shutdown()

    def test_cannot_close_or_expire_active_worker(self):
        clock = [0.0]
        started, release = threading.Event(), threading.Event()

        def check():
            started.set()
            release.wait(3)
            return SimpleNamespace(ready=True)

        service = WebSessionOperations(
            clock=lambda: clock[0], idle_seconds=2, runtime_checker=check,
        )
        sid = service.create()["id"]
        try:
            operation = service.submit_runtime_check(sid)
            self.assertTrue(started.wait(2))
            clock[0] = 5
            self.assertEqual(service.get(sid)["id"], sid)
            with self.assertRaises(WebSessionConflict):
                service.delete(sid)
            service.cancel(sid, operation["id"])
            release.set()
            until = time.monotonic() + 3
            while service.get_operation(sid, operation["id"])["status"] == "cancelling":
                if time.monotonic() >= until:
                    self.fail("cancel did not resolve")
                time.sleep(0.002)
            self.assertEqual(
                service.get_operation(sid, operation["id"])["status"], "cancelled"
            )
        finally:
            release.set()
            service.shutdown()


if __name__ == "__main__":
    unittest.main()
