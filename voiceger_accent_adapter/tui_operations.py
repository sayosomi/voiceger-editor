"""Synthesis operation, candidate playback, and acceptance coordination."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
import os
import queue
import shutil
import subprocess
import sys
import tempfile
from threading import Event, Thread
from typing import Any, Callable, Iterable, Union

from .session import UtteranceSession
from .voicevox_api_models import AudioQuery


@dataclass(frozen=True)
class UpdateStatusEffect:
    status: str


@dataclass(frozen=True)
class FocusEffect:
    focus_key: tuple[str, int | None]


@dataclass(frozen=True)
class PlayTakeEffect:
    number: int


@dataclass(frozen=True)
class StopPlaybackEffect:
    pass


@dataclass(frozen=True)
class DiscardInitialBatchEffect:
    pass


@dataclass(frozen=True)
class PlayPreviewEffect:
    audio: Any
    sampling_rate: int


@dataclass(frozen=True)
class PreviewReadyEvent:
    audio: Any
    sampling_rate: int


@dataclass(frozen=True)
class PreviewFailedEvent:
    error: BaseException


OperationEffect = Union[
    UpdateStatusEffect,
    FocusEffect,
    PlayTakeEffect,
    PlayPreviewEffect,
    StopPlaybackEffect,
    DiscardInitialBatchEffect,
]


class TuiOperations:
    """Own operation state and return typed effects for app-owned actions."""

    def __init__(
        self,
        *,
        platform: Callable[[], str] | None = None,
        which: Callable[[str], str | None] | None = None,
        popen: Callable[..., subprocess.Popen[Any]] | None = None,
    ) -> None:
        self._platform = platform or (lambda: sys.platform)
        self._which = which or (lambda name: shutil.which(name))
        self._popen = popen or (
            lambda *args, **kwargs: subprocess.Popen(*args, **kwargs)
        )
        self.events: queue.Queue[Any] = queue.Queue()
        self.worker: Thread | None = None
        self.worker_operation: str | None = None
        self.worker_target: int | None = None
        self.worker_error: BaseException | None = None
        self.busy = False
        self.operation_completed = 0
        self.operation_total = 0
        self.operation_focus_revision = 0
        self._cancellation_event: Event | None = None
        self.cancellation_requested = False
        self.current_take: int | None = None
        self.playback_process: subprocess.Popen[Any] | None = None
        self._preview_temporary_directory: (
            tempfile.TemporaryDirectory[str] | None
        ) = None

    def start_generation(
        self,
        session: UtteranceSession | None,
        *,
        take_count: int,
        navigation_revision: int,
    ) -> tuple[OperationEffect, ...]:
        if self.busy:
            return (
                UpdateStatusEffect("A sequential take operation is already running."),
            )
        if session is None:
            return ()
        if session.has_active_batch:
            return (
                UpdateStatusEffect(
                    "A take batch already exists; use g to regenerate all takes."
                ),
            )
        try:
            values = session.generate_takes()
        except Exception as exc:
            return (
                UpdateStatusEffect(f"Error: Could not start take generation: {exc}"),
            )
        self.current_take = None
        return self.run_worker(
            lambda: values,
            f"Generating 1/{take_count}",
            operation="initial",
            take_count=take_count,
            navigation_revision=navigation_revision,
        )

    def start_regeneration(
        self,
        session: UtteranceSession | None,
        number: int,
        *,
        take_count: int,
        navigation_revision: int,
    ) -> tuple[OperationEffect, ...]:
        if session is None:
            return ()
        self.stop_playback()
        self.current_take = number
        return self.run_worker(
            lambda: (session.regenerate_take(number),),
            f"Regenerating take {number}…",
            operation="regenerate_one",
            target=number,
            take_count=take_count,
            navigation_revision=navigation_revision,
        )

    def start_regenerate_all(
        self,
        session: UtteranceSession | None,
        *,
        take_count: int,
        navigation_revision: int,
    ) -> tuple[OperationEffect, ...]:
        if session is None:
            return ()
        take_count = session.active_candidate_count
        try:
            values = session.regenerate_all_takes()
        except Exception as exc:
            return (
                UpdateStatusEffect(f"Error: Could not regenerate all takes: {exc}"),
            )
        return self.run_worker(
            lambda: values,
            f"Regenerating 1/{take_count}",
            operation="regenerate_all",
            take_count=take_count,
            navigation_revision=navigation_revision,
        )

    def start_preview(
        self,
        session: UtteranceSession | None,
        query: AudioQuery,
    ) -> tuple[OperationEffect, ...]:
        """Synthesize one fixed transient query on the background worker."""

        if self.busy:
            return (
                UpdateStatusEffect("Wait for the current operation to finish."),
            )
        if session is None:
            return ()
        try:
            query_snapshot = query.model_copy(deep=True)
        except Exception as exc:
            return (UpdateStatusEffect(f"Error: Could not start Preview: {exc}"),)

        # A single owned player is reused for takes and previews. Stopping it
        # does not clear the user's selected candidate.
        self.stop_playback()
        self.busy = True
        self.worker_operation = "preview"
        self.worker_target = None
        self.worker_error = None
        self.operation_completed = 0
        self.operation_total = 1

        def work() -> None:
            try:
                with open(os.devnull, "w", encoding="utf-8") as sink:
                    with redirect_stdout(sink), redirect_stderr(sink):
                        result = session.preview_synthesis(query_snapshot)
                self.events.put(
                    PreviewReadyEvent(
                        audio=result["audio"],
                        sampling_rate=int(result["sampling_rate"]),
                    )
                )
            except BaseException as exc:
                self.events.put(PreviewFailedEvent(exc))
            finally:
                self.events.put(("done", None))

        self.worker = Thread(
            target=work,
            name="voiceger-tui-preview",
            daemon=True,
        )
        self.worker.start()
        return (UpdateStatusEffect("Synthesizing pronunciation Preview…"),)

    def run_worker(
        self,
        make_values: Callable[[], Iterable[Any]],
        status: str,
        *,
        operation: str,
        take_count: int,
        navigation_revision: int,
        target: int | None = None,
    ) -> tuple[OperationEffect, ...]:
        self.busy = True
        self.worker_operation = operation
        self.worker_target = target
        self.worker_error = None
        self.operation_focus_revision = navigation_revision
        self.operation_completed = 0
        self.operation_total = 1 if operation == "regenerate_one" else take_count
        cancellation_event = Event()
        self._cancellation_event = cancellation_event
        self.cancellation_requested = False

        def work() -> None:
            try:
                with open(os.devnull, "w", encoding="utf-8") as sink:
                    with redirect_stdout(sink), redirect_stderr(sink):
                        values = iter(make_values())
                        while not cancellation_event.is_set():
                            try:
                                candidate = next(values)
                            except StopIteration:
                                break
                            self.events.put(("candidate", candidate))
            except BaseException as exc:
                self.events.put(("error", exc))
            finally:
                self.events.put(("done", None))

        self.worker = Thread(
            target=work,
            name="voiceger-tui-synthesis",
            daemon=True,
        )
        self.worker.start()
        return (UpdateStatusEffect(status),)

    @property
    def can_cancel_batch(self) -> bool:
        """Whether the active worker is an initial or all-takes operation."""

        return self.busy and self.worker_operation in {"initial", "regenerate_all"}

    def request_batch_cancellation(self) -> tuple[OperationEffect, ...]:
        """Request cancellation at the next take boundary."""

        if not self.can_cancel_batch:
            return ()
        cancellation_event = self._cancellation_event
        if cancellation_event is not None:
            cancellation_event.set()
        self.cancellation_requested = True
        return (UpdateStatusEffect("Cancelling…"),)

    def request_shutdown(self) -> tuple[OperationEffect, ...]:
        """Prepare a safe shutdown without forcibly terminating Voiceger."""

        if self.can_cancel_batch:
            self.request_batch_cancellation()
            return (UpdateStatusEffect("Cancelling current batch before cleanup…"),)
        if self.busy:
            return (UpdateStatusEffect("Finishing the current synthesis before cleanup…"),)
        return ()

    def consume_pending_events(
        self,
        session: UtteranceSession | None,
        *,
        navigation_revision: int,
        pronunciation_index: int,
        exit_requested: bool,
    ) -> tuple[OperationEffect, ...]:
        effects: list[OperationEffect] = []
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return tuple(effects)

            if isinstance(event, PreviewReadyEvent):
                self.operation_completed = 1
                effects.append(PlayPreviewEffect(event.audio, event.sampling_rate))
                continue
            if isinstance(event, PreviewFailedEvent):
                self.worker_error = event.error
                effects.append(
                    UpdateStatusEffect(f"Error: Preview failed: {event.error}")
                )
                continue

            kind, value = event

            if kind == "candidate":
                operation = self.worker_operation
                self.operation_completed += 1
                if operation == "initial":
                    status = (
                        f"Generating {min(self.operation_completed + 1, self.operation_total)}"
                        f"/{self.operation_total} · {self.operation_completed} ready"
                    )
                elif operation == "regenerate_all":
                    status = (
                        f"Regenerating {min(self.operation_completed + 1, self.operation_total)}"
                        f"/{self.operation_total} · {self.operation_completed} ready"
                    )
                else:
                    status = f"Take {value.number} replacement ready."
                effects.append(UpdateStatusEffect(status))

                if operation == "initial":
                    if (
                        self.operation_completed == 1
                        and navigation_revision == self.operation_focus_revision
                    ):
                        self.current_take = value.number
                        effects.append(FocusEffect(("candidate", value.number)))
                        effects.append(PlayTakeEffect(value.number))
                elif operation == "regenerate_one":
                    if (
                        value.number == self.worker_target
                        and self.current_take == value.number
                    ):
                        effects.append(PlayTakeEffect(value.number))
                elif operation == "regenerate_all":
                    if value.number == self.current_take:
                        effects.append(PlayTakeEffect(value.number))

            elif kind == "error":
                self.worker_error = value
                if self.worker_operation == "preview":
                    effects.append(
                        UpdateStatusEffect(f"Error: Preview failed: {value}")
                    )
                else:
                    effects.append(
                        UpdateStatusEffect(f"Error: Generation failed: {value}")
                    )
                if (
                    self.worker_operation == "initial"
                    and not self.cancellation_requested
                ):
                    effects.append(StopPlaybackEffect())
                    effects.append(DiscardInitialBatchEffect())
                    self.current_take = None
                    effects.append(FocusEffect(("pronunciation", pronunciation_index)))

            elif kind == "done":
                operation = self.worker_operation
                cancelled = self.cancellation_requested
                self.busy = False
                if operation == "preview":
                    status = None
                elif cancelled and operation == "initial":
                    ready = len(session.candidates) if session is not None else 0
                    status = f"Generation cancelled. {ready} take(s) ready."
                    if ready == 0:
                        effects.append(StopPlaybackEffect())
                        effects.append(DiscardInitialBatchEffect())
                        self.current_take = None
                        effects.append(
                            FocusEffect(("pronunciation", pronunciation_index))
                        )
                elif cancelled and operation == "regenerate_all":
                    status = (
                        "Regeneration cancelled after "
                        f"{self.operation_completed} replacement(s)."
                    )
                elif self.worker_error is not None:
                    status = f"Error: Generation failed: {self.worker_error}"
                elif (
                    operation == "initial"
                    and session is not None
                    and session.candidates
                ):
                    status = f"{len(session.candidates)} take(s) ready."
                elif operation in {"regenerate_one", "regenerate_all"}:
                    status = "Take regeneration finished."
                elif not exit_requested:
                    status = "No takes were generated. Select Generate to try again."
                else:
                    status = None
                if status is not None:
                    effects.append(UpdateStatusEffect(status))
                self.worker_operation = None
                self.worker_target = None
                self._cancellation_event = None
                self.cancellation_requested = False

    def play_take(
        self,
        session: UtteranceSession | None,
        number: int,
    ) -> tuple[OperationEffect, ...]:
        if session is None:
            return ()
        candidate = next(
            (item for item in session.candidates if item.number == number),
            None,
        )
        if candidate is None:
            return (UpdateStatusEffect(f"Take {number} is not available yet."),)

        return self._play_path(
            candidate.wav_path,
            status=f"Playing take {number}.",
            error_prefix=f"Could not play take {number}",
            take_number=number,
        )

    def play_preview(
        self,
        audio: Any,
        sampling_rate: int,
    ) -> tuple[OperationEffect, ...]:
        """Write and play preview audio from a temporary runtime directory."""

        self.stop_playback()
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="voiceger-preview-"
        )
        wav_path = Path(temporary_directory.name) / "preview.wav"
        try:
            import soundfile as sf

            sf.write(wav_path, audio, sampling_rate)
        except Exception as exc:
            temporary_directory.cleanup()
            return (UpdateStatusEffect(f"Error: Could not prepare Preview: {exc}"),)
        return self._play_path(
            wav_path,
            status="Playing pronunciation Preview.",
            error_prefix="Could not play Preview",
            preview_temporary_directory=temporary_directory,
        )

    def _play_path(
        self,
        wav_path: Path,
        *,
        status: str,
        error_prefix: str,
        take_number: int | None = None,
        preview_temporary_directory: tempfile.TemporaryDirectory[str] | None = None,
    ) -> tuple[OperationEffect, ...]:
        self.stop_playback()
        try:
            command = self._player_command(wav_path)
            if command is None:
                if preview_temporary_directory is not None:
                    preview_temporary_directory.cleanup()
                return (
                    UpdateStatusEffect(
                        "Error: Playback needs afplay (macOS) or ffplay (other systems)."
                    ),
                )
            self.playback_process = self._popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._preview_temporary_directory = preview_temporary_directory
            if take_number is not None:
                self.current_take = take_number
            return (UpdateStatusEffect(status),)
        except OSError as exc:
            if preview_temporary_directory is not None:
                preview_temporary_directory.cleanup()
            return (UpdateStatusEffect(f"Error: {error_prefix}: {exc}"),)

    def _player_command(self, wav_path: Path) -> list[str] | None:
        if self._platform() == "darwin":
            player = self._which("afplay")
            if player:
                return [player, str(wav_path)]
        player = self._which("ffplay")
        if not player:
            return None
        return [
            player,
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "error",
            str(wav_path),
        ]

    def stop_playback(self) -> None:
        process = self.playback_process
        self.playback_process = None
        if process is None:
            self._cleanup_preview_temporary_directory()
            return
        try:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        finally:
            self._cleanup_preview_temporary_directory()

    def _cleanup_preview_temporary_directory(self) -> None:
        temporary_directory = self._preview_temporary_directory
        self._preview_temporary_directory = None
        if temporary_directory is not None:
            temporary_directory.cleanup()

    def clear_current_take(self) -> None:
        self.current_take = None

    def accept_take(
        self,
        session: UtteranceSession | None,
        number: int,
        *,
        busy: bool,
        pronunciation_index: int,
    ) -> tuple[OperationEffect, ...]:
        if session is None or busy:
            return ()
        self.stop_playback()
        try:
            saved = session.accept_take(number)
        except Exception as exc:
            return (
                UpdateStatusEffect(f"Error: Could not save take {number}: {exc}"),
            )
        self.current_take = None
        sidecars = []
        if saved.text_path is not None:
            sidecars.append(saved.text_path.name)
        lab_path = getattr(saved, "lab_path", None)
        if lab_path is not None:
            sidecars.append(lab_path.name)
        names = [saved.wav_path.name, *sidecars]
        status = f"Saved {' and '.join(names)}."
        lab_warning = getattr(saved, "lab_warning", None)
        if lab_warning:
            status += f" {lab_warning}"
        return (
            FocusEffect(("pronunciation", pronunciation_index)),
            UpdateStatusEffect(status),
        )

    def join_worker(self) -> None:
        worker = self.worker
        if worker is None or worker.ident is None:
            return
        while worker.is_alive():
            try:
                worker.join(timeout=0.1)
            except KeyboardInterrupt:
                self.request_batch_cancellation()

    def worker_is_alive(self) -> bool:
        return self.worker is not None and self.worker.is_alive()
