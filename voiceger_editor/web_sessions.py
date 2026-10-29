"""Server-owned, bounded Web sessions and one asynchronous operation worker.

Never persist these sessions as Take recovery records. Work callbacks are
selected by the server, never provided by an HTTP client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import secrets
import threading
import time
from typing import Any, Callable

from .caption_batch import CaptionBatch
from .web_batch import WebBatchMixin
from .web_takes import WebTakeMixin
from .web_pronunciation import WebPronunciationMixin
from .voiceger_environment import check_voiceger_environment


class WebSessionNotFound(LookupError):
    """Unknown, expired, or closed session/operation."""


class WebSessionConflict(RuntimeError):
    """A typed, safe conflict; never expose arbitrary exception text."""

    CODES = frozenset({
        "conflict", "revision_conflict", "worker_busy",
        "terms_required", "accepted_take_protected", "already_accepted",
    })

    def __init__(self, message: str, *, code: str = "conflict") -> None:
        if code not in self.CODES:
            raise ValueError("Unknown Web conflict code")
        super().__init__(message)
        self.code = code


class WebSessionCapacity(RuntimeError):
    """Bounded session registry has reached its limit."""


class WebSessionClosed(RuntimeError):
    """The host application has shut down."""


@dataclass
class _Operation:
    identifier: str
    kind: str
    status: str = "running"
    completed: int = 0
    total: int = 1
    result: dict[str, Any] | None = None
    cancellable: bool = True
    error: str | None = None
    cancellation: threading.Event = field(default_factory=threading.Event)

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "kind": self.kind,
            "cancellable": self.cancellable,
            "status": self.status,
            "completed": self.completed,
            "total": self.total,
            "result": None if self.result is None else dict(self.result),
            "error": self.error,
        }


@dataclass
class _WebSession:
    identifier: str
    touched: float
    revision: int = 0
    batch: CaptionBatch = field(default_factory=lambda: CaptionBatch(default_take_count=4))
    operations: dict[str, _Operation] = field(default_factory=dict)
    preview_audio: tuple[str, str, bytes] | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "ephemeral": True,
            "restart_recovery": False,
            "item_count": len(self.batch),
            "default_take_count": self.batch.default_take_count,
        }


class WebSessionOperations(WebBatchMixin, WebPronunciationMixin, WebTakeMixin):
    """Thread-safe, in-process session registry with one worker across sessions."""

    def __init__(
        self,
        *,
        runtime_checker: Callable[[], Any] = check_voiceger_environment,
        clock: Callable[[], float] = time.monotonic,
        max_sessions: int = 8,
        idle_seconds: float = 3600,
        history_limit: int = 8,
        caption_factory: Callable[[str], Any] | None = None,
    ) -> None:
        if max_sessions < 1 or idle_seconds <= 0 or history_limit < 1:
            raise ValueError("session limits must be positive")
        self._runtime_checker = runtime_checker
        self._clock = clock
        self._max_sessions = max_sessions
        self._idle_seconds = idle_seconds
        self._history_limit = history_limit
        self._caption_factory = caption_factory
        self._batch_adapter = None
        self._batch_settings = None
        self._lock = threading.RLock()
        self._sessions: dict[str, _WebSession] = {}
        self._active: tuple[str, str] | None = None
        self._stopped = False

    def _ensure_running(self) -> None:
        if self._stopped:
            raise WebSessionClosed("Web session service has stopped")

    @staticmethod
    def _dispose(session: _WebSession) -> None:
        session.preview_audio = None
        # Dispose temporary Takes only; never delete accepted output files.
        for item in session.batch.items:
            item.session.discard_takes()

    def _reap(self) -> None:
        now = self._clock()
        expired = [
            identifier for identifier, session in self._sessions.items()
            if (now - session.touched >= self._idle_seconds)
            and not (self._active is not None and self._active[0] == identifier)
        ]
        for identifier in expired:
            self._dispose(self._sessions.pop(identifier))

    def _session(self, identifier: str) -> _WebSession:
        self._ensure_running()
        self._reap()
        session = self._sessions.get(identifier)
        if session is None:
            raise WebSessionNotFound("Web session not found")
        session.touched = self._clock()
        return session

    def create(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_running()
            self._reap()
            if len(self._sessions) >= self._max_sessions:
                raise WebSessionCapacity("Too many active Web sessions")
            identifier = secrets.token_urlsafe(24)
            while identifier in self._sessions:
                identifier = secrets.token_urlsafe(24)
            session = _WebSession(identifier=identifier, touched=self._clock())
            self._sessions[identifier] = session
            return session.snapshot()

    def get(self, identifier: str) -> dict[str, Any]:
        with self._lock:
            return self._session(identifier).snapshot()

    def delete(self, identifier: str) -> None:
        with self._lock:
            session = self._session(identifier)
            if self._active is not None and self._active[0] == identifier:
                raise WebSessionConflict("Cancel the active operation before closing")
            self._dispose(session)
            del self._sessions[identifier]

    def _get_operation(self, identifier: str, operation_id: str) -> _Operation:
        session = self._session(identifier)
        operation = session.operations.get(operation_id)
        if operation is None:
            raise WebSessionNotFound("Web operation not found")
        return operation

    def get_operation(self, identifier: str, operation_id: str) -> dict[str, Any]:
        with self._lock:
            return self._get_operation(identifier, operation_id).snapshot()

    def cancel(self, identifier: str, operation_id: str) -> dict[str, Any]:
        with self._lock:
            operation = self._get_operation(identifier, operation_id)
            if operation.status in ("running", "cancelling"):
                if not operation.cancellable:
                    raise WebSessionConflict("This operation cannot be cancelled")
                operation.cancellation.set()
                operation.status = "cancelling"
            return operation.snapshot()

    def submit_runtime_check(self, identifier: str) -> dict[str, Any]:
        with self._lock:
            session = self._session(identifier)
            if self._active is not None:
                raise WebSessionConflict("One Web operation is already running")
            operation_id = secrets.token_urlsafe(24)
            operation = _Operation(identifier=operation_id, kind="runtime-check")
            session.operations[operation_id] = operation
            while len(session.operations) > self._history_limit:
                session.operations.pop(next(iter(session.operations)))
            self._active = (identifier, operation_id)
            worker = threading.Thread(
                target=self._run_runtime_check,
                args=(identifier, operation),
                daemon=True,
                name="voiceger-web-runtime-check",
            )
            try:
                worker.start()
            except RuntimeError:
                self._active = None
                del session.operations[operation_id]
                raise WebSessionConflict("Web worker could not start") from None
            return operation.snapshot()

    def _run_runtime_check(self, session_id: str, operation: _Operation) -> None:
        try:
            if operation.cancellation.is_set():
                ready = None
            else:
                # This is the existing read-only environment inspection owner.
                # Never send the detailed report (which contains local paths).
                report = self._runtime_checker()
                ready = bool(report.ready)
            with self._lock:
                if operation.cancellation.is_set():
                    operation.status = "cancelled"
                else:
                    operation.status = "succeeded"
                    operation.result = {"ready": ready}
                    operation.completed = 1
        except Exception:
            with self._lock:
                if operation.cancellation.is_set():
                    operation.status = "cancelled"
                else:
                    operation.status = "failed"
                    operation.error = "Runtime inspection failed"
        finally:
            with self._lock:
                if self._active == (session_id, operation.identifier):
                    self._active = None
                session = self._sessions.get(session_id)
                if session is not None:
                    session.touched = self._clock()
                if self._stopped:
                    self._clear_sessions()

    def _clear_sessions(self) -> None:
        for session in self._sessions.values():
            self._dispose(session)
        self._sessions.clear()

    def shutdown(self) -> None:
        """Reject new requests and cancel active work without blocking shutdown."""
        with self._lock:
            self._stopped = True
            if self._active is not None:
                session_id, operation_id = self._active
                operation = self._sessions[session_id].operations[operation_id]
                if operation.cancellable:
                    operation.cancellation.set()
            else:
                self._clear_sessions()
