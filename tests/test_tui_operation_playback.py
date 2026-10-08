"""Playback command, process and Preview temp-WAV ownership regression tests."""

from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

from voiceger_editor.tui_operations import TuiOperations, UpdateStatusEffect
from voiceger_editor.tui_status import error_status
from tests.tui_operation_test_support import FakeSession, candidate


class TuiPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.operations = TuiOperations()

    def playback_session(self):
        return FakeSession((candidate(3),))

    def assert_playback_command(self, expected):
        session = self.playback_session()
        process = Mock()
        with patch("voiceger_editor.tui_operations.subprocess.Popen", return_value=process) as popen:
            effects = self.operations.play_take(session, 3)
        self.assertEqual(effects, (UpdateStatusEffect("Playing take 3."),))
        self.assertEqual(popen.call_args.args[0], expected)
        self.assertEqual(
            popen.call_args.kwargs,
            {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            },
        )
        self.assertIs(self.operations.playback_process, process)
        self.assertEqual(self.operations.current_take, 3)

    def test_macos_prefers_afplay(self):
        with patch("voiceger_editor.tui_operations.sys.platform", "darwin"):
            with patch(
                "voiceger_editor.tui_operations.shutil.which",
                side_effect=lambda name: f"/usr/bin/{name}",
            ):
                self.assert_playback_command(["/usr/bin/afplay", "/tmp/take-3.wav"])

    def test_macos_falls_back_to_ffplay(self):
        with patch("voiceger_editor.tui_operations.sys.platform", "darwin"):
            with patch(
                "voiceger_editor.tui_operations.shutil.which",
                side_effect=[None, "/usr/bin/ffplay"],
            ):
                self.assert_playback_command(
                    [
                        "/usr/bin/ffplay",
                        "-nodisp",
                        "-autoexit",
                        "-loglevel",
                        "error",
                        "/tmp/take-3.wav",
                    ]
                )

    def test_non_macos_uses_ffplay(self):
        with patch("voiceger_editor.tui_operations.sys.platform", "linux"):
            with patch(
                "voiceger_editor.tui_operations.shutil.which",
                return_value="/usr/bin/ffplay",
            ):
                self.assert_playback_command(
                    [
                        "/usr/bin/ffplay",
                        "-nodisp",
                        "-autoexit",
                        "-loglevel",
                        "error",
                        "/tmp/take-3.wav",
                    ]
                )

    def test_windows_uses_ffplay_executable(self):
        player = r"C:\ffmpeg\bin\ffplay.exe"
        with patch("voiceger_editor.tui_operations.sys.platform", "win32"):
            with patch(
                "voiceger_editor.tui_operations.shutil.which",
                return_value=player,
            ):
                self.assert_playback_command(
                    [
                        player,
                        "-nodisp",
                        "-autoexit",
                        "-loglevel",
                        "error",
                        "/tmp/take-3.wav",
                    ]
                )

    def test_preview_playback_temp_wav_is_replaced_stopped_and_keeps_take_selection(self):
        first_process = Mock()
        first_process.poll.return_value = None
        second_process = Mock()
        second_process.poll.return_value = None
        third_process = Mock()
        third_process.poll.return_value = None
        popen = Mock(side_effect=[first_process, second_process, third_process])
        operations = TuiOperations(
            platform=lambda: "linux",
            which=lambda _name: "/usr/bin/ffplay",
            popen=popen,
        )
        session_candidate = candidate(3)
        session = FakeSession((session_candidate,))
        operations.current_take = 3

        first_effects = operations.play_preview([0.0] * 80, 32000)
        first_path = Path(popen.call_args_list[0].args[0][-1])
        first_directory = first_path.parent
        self.assertTrue(first_path.is_file())
        self.assertEqual(
            first_effects,
            (UpdateStatusEffect("Playing pronunciation Preview."),),
        )
        self.assertEqual(operations.current_take, 3)

        operations.play_preview([0.0] * 80, 32000)
        second_path = Path(popen.call_args_list[1].args[0][-1])
        second_directory = second_path.parent
        self.assertFalse(first_directory.exists())
        self.assertTrue(second_path.is_file())
        self.assertEqual(operations.current_take, 3)

        replay = operations.play_take(session, 3)
        self.assertEqual(replay, (UpdateStatusEffect("Playing take 3."),))
        self.assertFalse(second_directory.exists())
        self.assertEqual(operations.current_take, 3)
        self.assertEqual(session.candidates, [session_candidate])
        operations.stop_playback()

    def test_missing_player_and_playback_oserror_preserve_status_text(self):
        with patch("voiceger_editor.tui_operations.sys.platform", "win32"):
            with patch("voiceger_editor.tui_operations.shutil.which", return_value=None):
                self.assertEqual(
                    self.operations.play_take(self.playback_session(), 3),
                    (
                        UpdateStatusEffect(
                            error_status(
                                "Playback on Windows requires ffplay.exe in PATH. "
                                "Install an FFmpeg build that includes ffplay.exe and add its "
                                "bin directory to PATH."
                            )
                        ),
                    ),
                )

        with patch("voiceger_editor.tui_operations.sys.platform", "linux"):
            with patch("voiceger_editor.tui_operations.shutil.which", return_value=None):
                self.assertEqual(
                    self.operations.play_take(self.playback_session(), 3),
                    (
                        UpdateStatusEffect(
                            error_status(
                                "Playback needs afplay (macOS) or ffplay (other systems)."
                            )
                        ),
                    ),
                )
        with patch("voiceger_editor.tui_operations.sys.platform", "linux"):
            with patch(
                "voiceger_editor.tui_operations.shutil.which",
                return_value="/usr/bin/ffplay",
            ):
                with patch(
                    "voiceger_editor.tui_operations.subprocess.Popen",
                    side_effect=OSError("spawn failed"),
                ):
                    self.assertEqual(
                        self.operations.play_take(self.playback_session(), 3),
                        (
                            UpdateStatusEffect(
                                error_status("Could not play take 3: spawn failed")
                            ),
                        ),
                    )

    def test_unavailable_candidate_does_not_stop_current_playback(self):
        process = Mock()
        self.operations.playback_process = process
        effects = self.operations.play_take(FakeSession(), 4)
        self.assertEqual(effects, (UpdateStatusEffect("Take 4 is not available yet."),))
        process.terminate.assert_not_called()

    def test_starting_playback_stops_and_reaps_existing_process_first(self):
        session = self.playback_session()
        old = Mock()
        old.poll.return_value = None
        self.operations.playback_process = old
        with patch("voiceger_editor.tui_operations.sys.platform", "linux"):
            with patch(
                "voiceger_editor.tui_operations.shutil.which",
                return_value="/usr/bin/ffplay",
            ):
                with patch(
                    "voiceger_editor.tui_operations.subprocess.Popen",
                    return_value=Mock(),
                ):
                    self.operations.play_take(session, 3)
        old.terminate.assert_called_once_with()
        old.wait.assert_called_once_with(timeout=0.25)

    def test_stop_playback_clears_reference_terminates_and_reaps(self):
        process = Mock()
        process.poll.return_value = None
        self.operations.playback_process = process

        def wait(*, timeout=None):
            self.assertIsNone(self.operations.playback_process)
            return None

        process.wait.side_effect = wait
        self.operations.stop_playback()
        self.assertIsNone(self.operations.playback_process)
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=0.25)

    def test_stop_playback_kills_and_reaps_after_timeout(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [
            subprocess.TimeoutExpired("ffplay", 0.25),
            None,
        ]
        self.operations.playback_process = process
        self.operations.stop_playback()
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.call_args_list[0].kwargs, {"timeout": 0.25})
        self.assertEqual(process.wait.call_args_list[1].args, ())


if __name__ == "__main__":
    unittest.main()
