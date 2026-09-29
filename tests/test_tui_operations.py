import io
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from voiceger_accent_adapter.tui_operations import (
    DiscardInitialBatchEffect,
    FocusEffect,
    PlayPreviewEffect,
    PlayTakeEffect,
    PreviewFailedEvent,
    PreviewReadyEvent,
    StopPlaybackEffect,
    TuiOperations,
    UpdateStatusEffect,
)
from voiceger_accent_adapter.voicevox_api_models import AudioQuery


def candidate(number):
    return SimpleNamespace(number=number, wav_path=Path(f"/tmp/take-{number}.wav"))


class FakeSession:
    def __init__(self, candidates=()):
        self.candidates = list(candidates)
        self.has_active_batch = bool(candidates)
        self.generated = ()
        self.generate_error = None
        self.regenerate_all_error = None
        self.regenerate_error = None
        self.accept_error = None
        self.discard_calls = 0
        self.accept_calls = []
        self.regenerate_calls = []
        self.regenerate_all_calls = 0
        self.preview_calls = []
        self.preview_error = None
        self.preview_result = {"audio": "preview", "sampling_rate": 22050}
        self.accepted = SimpleNamespace(
            wav_path=Path("/tmp/saved.wav"),
            text_path=Path("/tmp/saved.txt"),
        )

    def generate_takes(self):
        if self.generate_error is not None:
            raise self.generate_error

        def values():
            for item in self.generated:
                self.candidates.append(item)
                yield item

        return values()

    def regenerate_take(self, number):
        self.regenerate_calls.append(number)
        if self.regenerate_error is not None:
            raise self.regenerate_error
        return next(item for item in self.candidates if item.number == number)

    def regenerate_all_takes(self):
        self.regenerate_all_calls += 1
        if self.regenerate_all_error is not None:
            raise self.regenerate_all_error

        def values():
            for item in self.candidates:
                yield item

        return values()

    def preview_synthesis(self, query):
        self.preview_calls.append(query)
        print("preview stdout")
        print("preview stderr", file=sys.stderr)
        if self.preview_error is not None:
            raise self.preview_error
        return self.preview_result

    def discard_takes(self):
        self.discard_calls += 1
        self.candidates = []

    def accept_take(self, number):
        self.accept_calls.append(number)
        if self.accept_error is not None:
            raise self.accept_error
        self.candidates = [item for item in self.candidates if item.number != number]
        return self.accepted


class TuiOperationsTests(unittest.TestCase):
    def setUp(self):
        self.operations = TuiOperations()

    def consume(self, session=None, *, revision=0, segment=0, exiting=False):
        return self.operations.consume_pending_events(
            session,
            navigation_revision=revision,
            pronunciation_index=segment,
            exit_requested=exiting,
        )

    def test_initial_generation_guards_and_startup_errors(self):
        self.assertEqual(self.operations.start_generation(
            None, take_count=4, navigation_revision=0
        ), ())

        self.operations.busy = True
        self.assertEqual(
            self.operations.start_generation(
                FakeSession(), take_count=4, navigation_revision=0
            ),
            (UpdateStatusEffect("A sequential take operation is already running."),),
        )
        self.operations.busy = False

        existing = FakeSession((candidate(1),))
        self.assertEqual(
            self.operations.start_generation(existing, take_count=4, navigation_revision=0),
            (
                UpdateStatusEffect(
                    "A take batch already exists; use g to regenerate all takes."
                ),
            ),
        )

        failing = FakeSession()
        failing.generate_error = RuntimeError("generator setup failed")
        self.assertEqual(
            self.operations.start_generation(failing, take_count=4, navigation_revision=0),
            (
                UpdateStatusEffect(
                    "Error: Could not start take generation: generator setup failed"
                ),
            ),
        )

    def test_preview_worker_emits_ready_playback_effect_without_candidate_focus(self):
        session_candidate = candidate(3)
        session = FakeSession((session_candidate,))
        query = AudioQuery(accent_phrases=[])
        self.operations.current_take = 3
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            effects = self.operations.start_preview(session, query)
            self.operations.join_worker()

        self.assertEqual(
            effects,
            (UpdateStatusEffect("Synthesizing pronunciation Preview…"),),
        )
        self.assertTrue(self.operations.busy)
        self.assertEqual(self.operations.worker_operation, "preview")
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        event = self.operations.events.get_nowait()
        self.assertIsInstance(event, PreviewReadyEvent)
        self.assertEqual(event.audio, "preview")
        self.assertEqual(event.sampling_rate, 22050)
        done_event = self.operations.events.get_nowait()
        self.assertEqual(done_event, ("done", None))
        self.operations.events.put(event)
        self.operations.events.put(done_event)

        effects = self.consume(session)

        self.assertEqual(effects, (PlayPreviewEffect("preview", 22050),))
        self.assertFalse(self.operations.busy)
        self.assertIsNone(self.operations.worker_operation)
        self.assertEqual(self.operations.current_take, 3)
        self.assertEqual(session.candidates, [session_candidate])
        self.assertEqual(session.preview_calls[0].model_dump(), query.model_dump())
        self.assertFalse(any(isinstance(item, FocusEffect) for item in effects))
        self.assertFalse(any(isinstance(item, PlayTakeEffect) for item in effects))

    def test_preview_worker_failure_is_preview_specific_and_keeps_candidates(self):
        session_candidate = candidate(2)
        session = FakeSession((session_candidate,))
        session.preview_error = RuntimeError("model unavailable")
        self.operations.current_take = 2

        self.operations.start_preview(session, AudioQuery(accent_phrases=[]))
        self.assertTrue(self.operations.busy)
        self.operations.join_worker()
        event = self.operations.events.get_nowait()
        self.assertIsInstance(event, PreviewFailedEvent)
        self.assertEqual(str(event.error), "model unavailable")
        done_event = self.operations.events.get_nowait()
        self.assertEqual(done_event, ("done", None))
        self.operations.events.put(event)
        self.operations.events.put(done_event)

        effects = self.consume(session)

        self.assertEqual(
            effects,
            (UpdateStatusEffect("Error: Preview failed: model unavailable"),),
        )
        self.assertFalse(self.operations.busy)
        self.assertEqual(self.operations.current_take, 2)
        self.assertEqual(session.candidates, [session_candidate])
        self.assertFalse(any(isinstance(item, FocusEffect) for item in effects))
        self.assertFalse(any(isinstance(item, DiscardInitialBatchEffect) for item in effects))

    def test_initial_generation_initializes_progress_and_clears_current_take(self):
        session = FakeSession()
        session.generated = (candidate(1),)
        self.operations.current_take = 3
        effects = self.operations.start_generation(
            session,
            take_count=4,
            navigation_revision=8,
        )
        self.assertEqual(effects, (UpdateStatusEffect("Generating 1/4"),))
        self.assertTrue(self.operations.busy)
        self.assertEqual(self.operations.worker_operation, "initial")
        self.assertIsNone(self.operations.worker_target)
        self.assertEqual(self.operations.operation_focus_revision, 8)
        self.assertEqual(self.operations.operation_total, 4)
        self.assertEqual(self.operations.operation_completed, 0)
        self.assertIsNone(self.operations.current_take)
        self.operations.join_worker()

    def test_worker_suppresses_output_and_posts_candidate_then_done(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        def values():
            print("synthesis stdout")
            print("synthesis stderr", file=sys.stderr)
            yield candidate(1)
            print("more stdout")
            print("more stderr", file=sys.stderr)

        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            self.operations.run_worker(
                values,
                "Generating 1/1",
                operation="initial",
                take_count=1,
                navigation_revision=0,
            )
            worker = self.operations.worker
            self.operations.join_worker()

        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(worker.name, "voiceger-tui-synthesis")
        self.assertTrue(worker.daemon)
        self.assertEqual(self.operations.events.get_nowait()[0], "candidate")
        self.assertEqual(self.operations.events.get_nowait(), ("done", None))

    def test_worker_posts_error_and_always_posts_done(self):
        error = RuntimeError("iterator failed")

        def values():
            yield candidate(1)
            raise error

        self.operations.run_worker(
            values,
            "Generating 1/2",
            operation="initial",
            take_count=2,
            navigation_revision=0,
        )
        self.operations.join_worker()
        self.assertEqual(self.operations.events.get_nowait()[0], "candidate")
        self.assertEqual(self.operations.events.get_nowait(), ("error", error))
        self.assertEqual(self.operations.events.get_nowait(), ("done", None))

    def test_first_initial_candidate_returns_progress_focus_and_play_effects(self):
        first = candidate(1)
        self.operations.worker_operation = "initial"
        self.operations.operation_total = 2
        self.operations.operation_focus_revision = 4
        self.operations.busy = True
        self.operations.events.put(("candidate", first))
        effects = self.consume(FakeSession((first,)), revision=4, segment=1)
        self.assertEqual(
            effects,
            (
                UpdateStatusEffect("Generating 2/2 · 1 ready"),
                FocusEffect(("candidate", 1)),
                PlayTakeEffect(1),
            ),
        )
        self.assertEqual(self.operations.operation_completed, 1)
        self.assertEqual(self.operations.current_take, 1)

    def test_first_candidate_does_not_steal_focus_after_navigation_moves(self):
        first = candidate(1)
        self.operations.worker_operation = "initial"
        self.operations.operation_total = 3
        self.operations.operation_focus_revision = 4
        self.operations.busy = True
        self.operations.events.put(("candidate", first))
        effects = self.consume(FakeSession((first,)), revision=5)
        self.assertEqual(effects, (UpdateStatusEffect("Generating 2/3 · 1 ready"),))
        self.assertIsNone(self.operations.current_take)

    def test_later_initial_candidates_only_update_progress(self):
        second = candidate(2)
        self.operations.worker_operation = "initial"
        self.operations.operation_total = 3
        self.operations.operation_completed = 1
        self.operations.current_take = 1
        self.operations.busy = True
        self.operations.events.put(("candidate", second))
        self.assertEqual(
            self.consume(FakeSession((candidate(1), second))),
            (UpdateStatusEffect("Generating 3/3 · 2 ready"),),
        )
        self.assertEqual(self.operations.current_take, 1)

    def test_single_regeneration_replays_only_current_target_replacement(self):
        replacement = candidate(2)
        self.operations.worker_operation = "regenerate_one"
        self.operations.worker_target = 2
        self.operations.current_take = 2
        self.operations.operation_total = 1
        self.operations.busy = True
        self.operations.events.put(("candidate", replacement))
        self.assertEqual(
            self.consume(FakeSession((candidate(1), replacement))),
            (
                UpdateStatusEffect("Take 2 replacement ready."),
                PlayTakeEffect(2),
            ),
        )

    def test_manual_selection_during_single_regeneration_is_retained(self):
        replacement = candidate(2)
        self.operations.worker_operation = "regenerate_one"
        self.operations.worker_target = 2
        self.operations.current_take = 1
        self.operations.operation_total = 1
        self.operations.busy = True
        self.operations.events.put(("candidate", replacement))
        effects = self.consume(FakeSession((candidate(1), replacement)))
        self.assertEqual(effects, (UpdateStatusEffect("Take 2 replacement ready."),))
        self.assertEqual(self.operations.current_take, 1)

    def test_regenerate_all_preserves_selection_and_plays_only_its_replacement(self):
        one, two, three = candidate(1), candidate(2), candidate(3)
        self.operations.worker_operation = "regenerate_all"
        self.operations.operation_total = 3
        self.operations.current_take = 2
        self.operations.busy = True
        self.operations.events.put(("candidate", one))
        self.operations.events.put(("candidate", three))
        self.assertEqual(
            self.consume(FakeSession((one, two, three))),
            (
                UpdateStatusEffect("Regenerating 2/3 · 1 ready"),
                UpdateStatusEffect("Regenerating 3/3 · 2 ready"),
            ),
        )
        self.assertEqual(self.operations.current_take, 2)
        self.operations.events.put(("candidate", two))
        self.assertEqual(
            self.consume(FakeSession((one, two, three))),
            (
                UpdateStatusEffect("Regenerating 3/3 · 3 ready"),
                PlayTakeEffect(2),
            ),
        )

    def test_initial_failure_requests_playback_stop_batch_discard_and_focus_restore(self):
        first = candidate(1)
        error = RuntimeError("second synthesis failed")
        session = FakeSession((first,))
        self.operations.worker_operation = "initial"
        self.operations.operation_total = 2
        self.operations.current_take = 1
        self.operations.busy = True
        self.operations.events.put(("candidate", first))
        self.operations.events.put(("error", error))
        self.operations.events.put(("done", None))

        effects = self.consume(session, segment=3)
        self.assertEqual(
            effects,
            (
                UpdateStatusEffect("Generating 2/2 · 1 ready"),
                FocusEffect(("candidate", 1)),
                PlayTakeEffect(1),
                UpdateStatusEffect("Error: Generation failed: second synthesis failed"),
                StopPlaybackEffect(),
                DiscardInitialBatchEffect(),
                FocusEffect(("pronunciation", 3)),
                UpdateStatusEffect("Error: Generation failed: second synthesis failed"),
            ),
        )
        self.assertFalse(self.operations.busy)
        self.assertIsNone(self.operations.current_take)
        self.assertEqual(self.operations.worker_error, error)
        self.assertIsNone(self.operations.worker_operation)
        self.assertIsNone(self.operations.worker_target)

    def test_regeneration_failure_preserves_batch_and_status(self):
        existing = candidate(1)
        error = RuntimeError("replacement failed")
        session = FakeSession((existing,))
        self.operations.worker_operation = "regenerate_one"
        self.operations.worker_target = 1
        self.operations.current_take = 1
        self.operations.busy = True
        self.operations.events.put(("error", error))
        self.operations.events.put(("done", None))
        self.assertEqual(
            self.consume(session),
            (
                UpdateStatusEffect("Error: Generation failed: replacement failed"),
                UpdateStatusEffect("Error: Generation failed: replacement failed"),
            ),
        )
        self.assertEqual(session.candidates, [existing])
        self.assertEqual(session.discard_calls, 0)
        self.assertEqual(self.operations.current_take, 1)

    def test_done_statuses_cover_successful_regeneration_empty_and_exit(self):
        self.operations.worker_operation = "initial"
        self.operations.busy = True
        self.operations.events.put(("done", None))
        self.assertEqual(
            self.consume(FakeSession((candidate(1), candidate(2)))),
            (UpdateStatusEffect("2 take(s) ready."),),
        )
        self.assertFalse(self.operations.busy)
        self.assertIsNone(self.operations.worker_operation)

        self.operations.worker_operation = "regenerate_all"
        self.operations.busy = True
        self.operations.events.put(("done", None))
        self.assertEqual(
            self.consume(FakeSession()),
            (UpdateStatusEffect("Take regeneration finished."),),
        )

        self.operations.worker_operation = "initial"
        self.operations.busy = True
        self.operations.events.put(("done", None))
        self.assertEqual(
            self.consume(FakeSession()),
            (UpdateStatusEffect("No takes were generated. Select Generate to try again."),),
        )

        self.operations.worker_operation = "initial"
        self.operations.busy = True
        self.operations.events.put(("done", None))
        self.assertEqual(self.consume(FakeSession(), exiting=True), ())

    def test_regenerate_all_startup_failure_keeps_existing_state(self):
        session = FakeSession((candidate(1),))
        session.regenerate_all_error = RuntimeError("regeneration unavailable")
        self.operations.current_take = 1
        self.assertEqual(
            self.operations.start_regenerate_all(
                session,
                take_count=4,
                navigation_revision=2,
            ),
            (
                UpdateStatusEffect(
                    "Error: Could not regenerate all takes: regeneration unavailable"
                ),
            ),
        )
        self.assertEqual(self.operations.current_take, 1)
        self.assertFalse(self.operations.busy)

    def playback_session(self):
        return FakeSession((candidate(3),))

    def assert_playback_command(self, expected):
        session = self.playback_session()
        process = Mock()
        with patch("voiceger_accent_adapter.tui_operations.subprocess.Popen", return_value=process) as popen:
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
        with patch("voiceger_accent_adapter.tui_operations.sys.platform", "darwin"):
            with patch(
                "voiceger_accent_adapter.tui_operations.shutil.which",
                side_effect=lambda name: f"/usr/bin/{name}",
            ):
                self.assert_playback_command(["/usr/bin/afplay", "/tmp/take-3.wav"])

    def test_macos_falls_back_to_ffplay(self):
        with patch("voiceger_accent_adapter.tui_operations.sys.platform", "darwin"):
            with patch(
                "voiceger_accent_adapter.tui_operations.shutil.which",
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
        with patch("voiceger_accent_adapter.tui_operations.sys.platform", "linux"):
            with patch(
                "voiceger_accent_adapter.tui_operations.shutil.which",
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
        with patch("voiceger_accent_adapter.tui_operations.sys.platform", "linux"):
            with patch("voiceger_accent_adapter.tui_operations.shutil.which", return_value=None):
                self.assertEqual(
                    self.operations.play_take(self.playback_session(), 3),
                    (
                        UpdateStatusEffect(
                            "Error: Playback needs afplay (macOS) or ffplay (other systems)."
                        ),
                    ),
                )
        with patch("voiceger_accent_adapter.tui_operations.sys.platform", "linux"):
            with patch(
                "voiceger_accent_adapter.tui_operations.shutil.which",
                return_value="/usr/bin/ffplay",
            ):
                with patch(
                    "voiceger_accent_adapter.tui_operations.subprocess.Popen",
                    side_effect=OSError("spawn failed"),
                ):
                    self.assertEqual(
                        self.operations.play_take(self.playback_session(), 3),
                        (UpdateStatusEffect("Error: Could not play take 3: spawn failed"),),
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
        with patch("voiceger_accent_adapter.tui_operations.sys.platform", "linux"):
            with patch(
                "voiceger_accent_adapter.tui_operations.shutil.which",
                return_value="/usr/bin/ffplay",
            ):
                with patch(
                    "voiceger_accent_adapter.tui_operations.subprocess.Popen",
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

    def test_candidate_acceptance_stops_playback_clears_current_and_requests_focus(self):
        session = FakeSession((candidate(3),))
        process = Mock()
        process.poll.return_value = None
        self.operations.playback_process = process
        self.operations.current_take = 3
        effects = self.operations.accept_take(
            session,
            3,
            busy=False,
            pronunciation_index=2,
        )
        self.assertEqual(session.accept_calls, [3])
        self.assertEqual(self.operations.current_take, None)
        self.assertIsNone(self.operations.playback_process)
        self.assertEqual(
            effects,
            (
                FocusEffect(("pronunciation", 2)),
                UpdateStatusEffect("Saved saved.wav and saved.txt."),
            ),
        )
        process.terminate.assert_called_once_with()

    def test_candidate_acceptance_failure_and_busy_guard(self):
        original = candidate(3)
        session = FakeSession((original,))
        session.accept_error = RuntimeError("save failed")
        self.operations.current_take = 3
        self.assertEqual(
            self.operations.accept_take(
                session,
                3,
                busy=False,
                pronunciation_index=0,
            ),
            (UpdateStatusEffect("Error: Could not save take 3: save failed"),),
        )
        self.assertEqual(self.operations.current_take, 3)
        self.assertEqual(session.candidates, [original])
        session.accept_calls.clear()
        self.assertEqual(
            self.operations.accept_take(
                session,
                3,
                busy=True,
                pronunciation_index=0,
            ),
            (),
        )
        self.assertEqual(session.accept_calls, [])


if __name__ == "__main__":
    unittest.main()
