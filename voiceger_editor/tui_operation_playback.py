"""Focused ownership for TUI Take and pronunciation-preview playback."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
from typing import Any, Callable

from .session import UtteranceSession
from .tui_status import Status, error_status


class TuiPlaybackOwner:
    """Own the single playback process, preview temp files, and Take selection."""

    def __init__(
        self,
        *,
        platform: Callable[[], str],
        which: Callable[[str], str | None],
        popen: Callable[..., subprocess.Popen[Any]],
        update_status: Callable[[Status | str], Any],
    ) -> None:
        self._platform = platform
        self._which = which
        self._popen = popen
        self._update_status = update_status
        self.current_take: int | None = None
        self.playback_process: subprocess.Popen[Any] | None = None
        self._preview_temporary_directory: (
            tempfile.TemporaryDirectory[str] | None
        ) = None

    def play_take(
        self,
        session: UtteranceSession | None,
        number: int,
    ) -> tuple[Any, ...]:
        if session is None:
            return ()
        candidate = next(
            (item for item in session.candidates if item.number == number),
            None,
        )
        if candidate is None:
            return (self._update_status(f"Take {number} is not available yet."),)

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
    ) -> tuple[Any, ...]:
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
            return (
                self._update_status(
                    error_status(f"Could not prepare Preview: {exc}")
                ),
            )
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
    ) -> tuple[Any, ...]:
        self.stop_playback()
        try:
            command = self._player_command(wav_path)
            if command is None:
                if preview_temporary_directory is not None:
                    preview_temporary_directory.cleanup()
                return (self._update_status(self._missing_player_status()),)
            self.playback_process = self._popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._preview_temporary_directory = preview_temporary_directory
            if take_number is not None:
                self.current_take = take_number
            return (self._update_status(status),)
        except OSError as exc:
            if preview_temporary_directory is not None:
                preview_temporary_directory.cleanup()
            return (
                self._update_status(
                    error_status(f"{error_prefix}: {exc}")
                ),
            )

    def _missing_player_status(self) -> Status:
        if self._platform() == "win32":
            return error_status(
                "Playback on Windows requires ffplay.exe in PATH. "
                "Install an FFmpeg build that includes ffplay.exe and add its bin "
                "directory to PATH."
            )
        return error_status(
            "Playback needs afplay (macOS) or ffplay (other systems)."
        )

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
