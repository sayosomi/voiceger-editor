"""Protected, single-worker Web audio operations backed by shared Take owners.

The client provides only item/Take IDs; it never supplies filesystem paths or
synthesis callbacks. All persistent audio saving belongs to UtteranceSession.
"""

from __future__ import annotations

from io import BytesIO
import secrets
import threading
from typing import Any, Callable

from .terms_acceptance import VoicegerTermsAcceptanceError, require_current_acceptance

MAX_AUDIO_BYTES = 32 * 1024 * 1024


class WebTakeValidation(ValueError):
    """Invalid item/Take or unsupported action."""


def _wav_bytes(audio: Any, rate: int) -> bytes:
    import soundfile as sf

    sink = BytesIO()
    sf.write(sink, audio, rate, format="WAV", subtype="PCM_16")
    value = sink.getvalue()
    if len(value) > MAX_AUDIO_BYTES:
        raise WebTakeValidation("Audio is too large for browser playback")
    return value


class WebTakeMixin:
    """Audio operations using WebSessionOperations' lock and worker registry."""

    def _take_item(self, session_id: str, item_id: str):
        from .web_sessions import WebSessionNotFound

        session = self._session(session_id)
        try:
            item = session.batch.get_item(item_id)
        except KeyError:
            raise WebSessionNotFound("Batch item not found") from None
        return session, item

    def _take_guard(self, session_id: str, item_id: str, revision: int):
        from .web_sessions import WebSessionConflict

        session, item = self._take_item(session_id, item_id)
        if revision != session.revision:
            raise WebSessionConflict("Batch was changed in another tab; reload it", code="revision_conflict")
        if self._active is not None:
            raise WebSessionConflict("One Web operation is already running", code="worker_busy")
        return session, item

    @staticmethod
    def _require_terms() -> None:
        from .web_sessions import WebSessionConflict

        try:
            require_current_acceptance()
        except VoicegerTermsAcceptanceError:
            raise WebSessionConflict(
                "Accept the current Voiceger terms on the Mac before generating audio",
                code="terms_required",
            ) from None

    def _start_take_work(
        self,
        session_id: str,
        session: Any,
        *,
        kind: str,
        total: int,
        run: Callable[[Any], dict[str, Any] | None],
        cancellable: bool = True,
        on_terminal: Callable[[str], None] | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from .web_sessions import _Operation, WebSessionConflict

        identifier = secrets.token_urlsafe(24)
        operation = _Operation(
            identifier=identifier, kind=kind, total=total, cancellable=cancellable,
            detail=detail,
        )
        session.operations[identifier] = operation
        while len(session.operations) > self._history_limit:
            session.operations.pop(next(iter(session.operations)))
        self._active = (session_id, identifier)
        worker = threading.Thread(
            target=self._run_take_work,
            args=(session_id, operation, run, on_terminal),
            daemon=True,
            name="voiceger-web-audio",
        )
        try:
            worker.start()
        except RuntimeError:
            del session.operations[identifier]
            self._active = None
            raise WebSessionConflict("Audio worker could not start") from None
        return operation.snapshot()

    def _run_take_work(
        self, session_id: str, operation: Any,
        run: Callable[[Any], dict[str, Any] | None],
        on_terminal: Callable[[str], None] | None = None,
    ) -> None:
        result = None
        failed = False
        try:
            result = run(operation)
        except BaseException:
            failed = True
        finally:
            # Publish terminal state and release the single-worker gate atomically.
            with self._lock:
                if failed:
                    operation.status = "failed"
                    # Never disclose raw Voiceger exceptions or Mac paths.
                    operation.error = "Audio operation failed on the Mac"
                elif operation.cancellation.is_set():
                    operation.status = "cancelled"
                else:
                    operation.result = result or {}
                    operation.status = "succeeded"
                try:
                    # The operation status and Batch outcome become visible
                    # together: cancel() and readers use this same lock.
                    if on_terminal is not None:
                        on_terminal(operation.status)
                finally:
                    if self._active == (session_id, operation.identifier):
                        self._active = None
                    session = self._sessions.get(session_id)
                    if session is not None:
                        session.touched = self._clock()
                    if self._stopped:
                        self._clear_sessions()

    def _progress(self, session: Any, operation: Any) -> None:
        with self._lock:
            session.revision += 1
            operation.completed += 1

    def _generate_values(self, session: Any, operation: Any, values: Any) -> dict[str, Any]:
        iterator = iter(values)
        try:
            while not operation.cancellation.is_set():
                try:
                    next(iterator)
                except StopIteration:
                    break
                self._progress(session, operation)
        finally:
            close = getattr(iterator, "close", None)
            if callable(close):
                close()
        return {"generated": operation.completed}

    def start_prepare(
        self, session_id: str, item_id: str, revision: int, *, rebuild: bool,
    ) -> dict[str, Any]:
        from .web_sessions import WebSessionConflict

        with self._lock:
            session, item = self._take_guard(session_id, item_id, revision)
            self._require_terms()
            if item.session.is_prepared and not rebuild:
                raise WebSessionConflict("Pronunciation is already prepared")
            if not item.session.is_prepared and rebuild:
                raise WebTakeValidation("Nothing to rebuild")

            def work(op):
                if op.cancellation.is_set():
                    return {}
                item.session.prepare_from_caption()
                with self._lock:
                    session.preview_audio = None
                    # Rebuilt pronunciation invalidates word boundaries from the
                    # former query even when its flat phonemes happen to match.
                    for key in tuple(session.english_groupings):
                        if key[0] == item_id:
                            session.english_groupings.pop(key, None)
                    item.clear_acceptance()
                    item.clear_generation_outcome()
                    session.revision += 1
                    op.completed = 1
                return {"prepared": True}

            return self._start_take_work(
                session_id, session, kind="prepare", total=1, run=work,
                cancellable=False,
            )

    def start_preview(self, session_id: str, item_id: str, revision: int) -> dict[str, Any]:
        from .web_sessions import WebSessionConflict

        with self._lock:
            session, item = self._take_guard(session_id, item_id, revision)
            self._require_terms()
            if not item.session.is_prepared:
                raise WebSessionConflict("Prepare pronunciation before Preview")

            def work(op):
                if op.cancellation.is_set():
                    return {}
                result = item.session.preview_synthesis(item.session.query)
                audio = _wav_bytes(result["audio"], int(result["sampling_rate"]))
                handle = secrets.token_urlsafe(18)
                with self._lock:
                    if not op.cancellation.is_set():
                        session.preview_audio = (item_id, handle, audio)
                        op.completed = 1
                return {"preview_id": handle}

            return self._start_take_work(
                session_id, session, kind="preview", total=1, run=work,
            )

    def start_generate(self, session_id: str, item_id: str, revision: int) -> dict[str, Any]:
        from .web_sessions import WebSessionConflict

        with self._lock:
            session, item = self._take_guard(session_id, item_id, revision)
            self._require_terms()
            if not item.session.is_prepared:
                raise WebSessionConflict("Prepare pronunciation before generation")
            if item.session.has_active_batch:
                raise WebSessionConflict("Clear candidates before initial generation")
            count = session.batch.effective_take_count(item)

            def work(op):
                try:
                    if op.cancellation.is_set():
                        return {}
                    return self._generate_values(
                        session, op, item.session.generate_takes(take_count=count),
                    )
                finally:
                    with self._lock:
                        if item.session.has_active_batch and not item.session.candidates:
                            item.session.discard_takes()
                        session.revision += 1

            def record_terminal(status: str) -> None:
                item.set_generation_outcome({
                    "succeeded": "completed",
                    "cancelled": "cancelled",
                    "failed": "failed",
                }[status])

            return self._start_take_work(
                session_id, session, kind="generate", total=count, run=work,
                on_terminal=record_terminal,
            )

    def start_regenerate(
        self, session_id: str, item_id: str, revision: int, *,
        number: int | None = None,
    ) -> dict[str, Any]:
        from .web_sessions import WebSessionConflict

        with self._lock:
            session, item = self._take_guard(session_id, item_id, revision)
            self._require_terms()
            candidates = {c.number for c in item.session.candidates}
            protected = item.accepted_take_numbers
            if not candidates:
                raise WebSessionConflict("Generate Takes before regeneration")
            if number is not None:
                if isinstance(number, bool) or not isinstance(number, int) or number not in candidates:
                    raise WebTakeValidation("Take does not exist")
                if number in protected:
                    raise WebSessionConflict("Accepted Takes cannot be regenerated", code="accepted_take_protected")
                count = 1

                def work(op):
                    if op.cancellation.is_set():
                        return {}
                    item.session.regenerate_take(number, protected_numbers=protected)
                    self._progress(session, op)
                    return {"generated": 1}

                kind = "regenerate-one"
            else:
                target = session.batch.effective_take_count(item)
                if any(n > target for n in protected):
                    raise WebSessionConflict("Take count would discard an accepted Take", code="accepted_take_protected")
                count = len(set(range(1, target + 1)) - protected)

                def work(op):
                    if op.cancellation.is_set():
                        return {}
                    previous_numbers = {c.number for c in item.session.candidates}
                    result = self._generate_values(
                        session, op, item.session.regenerate_all_takes(
                            take_count=target, protected_numbers=protected,
                        ),
                    )
                    if op.completed == 0 and previous_numbers != {
                        c.number for c in item.session.candidates
                    }:
                        with self._lock:
                            session.revision += 1
                    return result

                kind = "regenerate-all"
            return self._start_take_work(
                session_id, session, kind=kind, total=count, run=work,
            )

    def start_accept(
        self, session_id: str, item_id: str, revision: int, number: int,
    ) -> dict[str, Any]:
        from .web_sessions import WebSessionConflict

        with self._lock:
            session, item = self._take_guard(session_id, item_id, revision)
            self._require_terms()
            if isinstance(number, bool) or not isinstance(number, int) or number not in {
                c.number for c in item.session.candidates
            }:
                raise WebTakeValidation("Take does not exist")
            if item.is_take_accepted(number):
                raise WebSessionConflict("Take is already accepted", code="already_accepted")

            def work(op):
                saved = item.session.accept_take(number)
                with self._lock:
                    item.mark_accepted(number)
                    session.revision += 1
                    op.completed = 1
                return {
                    "audio_name": saved.audio_path.name,
                    "text_name": saved.text_path.name if saved.text_path else None,
                    "lab_name": saved.lab_path.name if saved.lab_path else None,
                    "lab_warning": bool(saved.lab_warning),
                }

            return self._start_take_work(
                session_id, session, kind="accept", total=1, run=work,
                cancellable=False,
            )

    def clear_candidates(self, session_id: str, item_id: str, revision: int):
        with self._lock:
            session, item = self._take_guard(session_id, item_id, revision)
            item.session.discard_takes()
            item.clear_acceptance()
            item.clear_generation_outcome()
            session.preview_audio = None
            session.revision += 1
            return self._batch_snapshot(session)

    def candidate_audio(self, session_id: str, item_id: str, number: int) -> bytes:
        from .web_sessions import WebSessionNotFound

        # Regeneration publishes a replacement candidate before removing its
        # old temporary WAV. Retry a disappearing path by candidate identity.
        for _ in range(2):
            with self._lock:
                _, item = self._take_item(session_id, item_id)
                candidate = next(
                    (c for c in item.session.candidates if c.number == number), None
                )
                if candidate is None:
                    raise WebSessionNotFound("Take audio not found")
                path = candidate.wav_path
                try:
                    if path.stat().st_size > MAX_AUDIO_BYTES:
                        raise WebTakeValidation("Audio is too large for browser playback")
                    return path.read_bytes()
                except FileNotFoundError:
                    continue
        raise WebSessionNotFound("Take audio temporarily unavailable")

    def preview_bytes(self, session_id: str, item_id: str, handle: str) -> bytes:
        from .web_sessions import WebSessionNotFound

        with self._lock:
            session, _ = self._take_item(session_id, item_id)
            stored = session.preview_audio
            if stored is None or stored[0] != item_id or stored[1] != handle:
                raise WebSessionNotFound("Preview audio not found")
            return stored[2]
