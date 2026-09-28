"""Synthesis operation, candidate playback, and acceptance coordination."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
import os
import queue
import shutil
import subprocess
import sys
from threading import Thread
from typing import Any, Callable, Iterable, Union

from .session import UtteranceSession


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


OperationEffect = Union[
    UpdateStatusEffect,
    FocusEffect,
    PlayTakeEffect,
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
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker: Thread | None = None
        self.worker_operation: str | None = None
        self.worker_target: int | None = None
        self.worker_error: BaseException | None = None
        self.busy = False
        self.operation_completed = 0
        self.operation_total = 0
        self.operation_focus_revision = 0
        self.current_take: int | None = None
        self.playback_process: subprocess.Popen[Any] | None = None

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
                    "A take batch already exists; use R to regenerate all takes."
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

        def work() -> None:
            try:
                with open(os.devnull, "w", encoding="utf-8") as sink:
                    with redirect_stdout(sink), redirect_stderr(sink):
                        for candidate in make_values():
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
                kind, value = self.events.get_nowait()
            except queue.Empty:
                return tuple(effects)

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
                effects.append(UpdateStatusEffect(f"Error: Generation failed: {value}"))
                if self.worker_operation == "initial":
                    effects.append(StopPlaybackEffect())
                    effects.append(DiscardInitialBatchEffect())
                    self.current_take = None
                    effects.append(FocusEffect(("pronunciation", pronunciation_index)))

            elif kind == "done":
                operation = self.worker_operation
                self.busy = False
                if self.worker_error is not None:
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

        self.stop_playback()
        try:
            if self._platform() == "darwin":
                player = self._which("afplay")
                if player:
                    command = [player, str(candidate.wav_path)]
                else:
                    player = self._which("ffplay")
                    command = (
                        [
                            player,
                            "-nodisp",
                            "-autoexit",
                            "-loglevel",
                            "error",
                            str(candidate.wav_path),
                        ]
                        if player
                        else None
                    )
            else:
                player = self._which("ffplay")
                command = (
                    [
                        player,
                        "-nodisp",
                        "-autoexit",
                        "-loglevel",
                        "error",
                        str(candidate.wav_path),
                    ]
                    if player
                    else None
                )
            if command is None:
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
            self.current_take = number
            return (UpdateStatusEffect(f"Playing take {number}."),)
        except OSError as exc:
            return (UpdateStatusEffect(f"Error: Could not play take {number}: {exc}"),)

    def stop_playback(self) -> None:
        process = self.playback_process
        self.playback_process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

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
        sidecar = f" and {saved.text_path.name}" if saved.text_path else ""
        return (
            FocusEffect(("pronunciation", pronunciation_index)),
            UpdateStatusEffect(f"Saved {saved.wav_path.name}{sidecar}."),
        )

    def join_worker(self) -> None:
        worker = self.worker
        if worker is not None and worker.ident is not None:
            worker.join()

    def worker_is_alive(self) -> bool:
        return self.worker is not None and self.worker.is_alive()
