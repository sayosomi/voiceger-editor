from pathlib import Path
import unittest
from unittest.mock import Mock

from voiceger_editor.settings import Settings
from voiceger_editor.tui_settings import TuiSettingsController


class FakeSession:
    def __init__(self, settings, *, error=None, events=None):
        self.settings = settings
        self.error = error
        self.events = events
        self.replace_settings_calls = []

    def replace_settings(self, settings):
        if self.events is not None:
            self.events.append("settings")
        if self.error is not None:
            raise self.error
        self.replace_settings_calls.append(settings)
        self.settings = settings


class TuiSettingsControllerTests(unittest.TestCase):
    def make_controller(
        self,
        *,
        settings=None,
        persisted_settings=None,
        session=None,
        save=None,
        events=None,
    ):
        runtime = settings or Settings()
        owned = session or FakeSession(runtime, events=events)
        status = {"value": ""}
        batch_take_count = {"value": runtime.take_count}
        operations = Mock()
        operations.settings_change_conflict_status.return_value = None
        if events is not None:
            operations.stop_playback.side_effect = lambda: events.append("stop")
            operations.clear_current_take.side_effect = lambda: events.append("clear")
        saver = save or Mock()
        controller = TuiSettingsController(
            settings=runtime,
            persisted_settings=persisted_settings,
            config_path=Path("/tmp/config.json"),
            operations=operations,
            sessions=lambda: (owned,),
            active_session=lambda: owned,
            set_batch_take_count=lambda value: batch_take_count.__setitem__(
                "value", value
            ),
            set_status=lambda value: status.__setitem__("value", value),
            save=saver,
            clear_generation_outcomes=(
                (lambda: events.append("outcomes"))
                if events is not None
                else (lambda: None)
            ),
        )
        return controller, owned, operations, saver, status, batch_take_count

    def test_partial_change_persists_only_changed_fields_over_persisted_baseline(self):
        runtime = Settings(take_count=8)
        persisted = Settings()
        controller, session, _operations, save, _status, batch = (
            self.make_controller(
                settings=runtime,
                persisted_settings=persisted,
            )
        )

        self.assertTrue(controller.change(save_text=True))

        expected_runtime = Settings(take_count=8, save_text=True)
        expected_persisted = Settings(save_text=True)
        self.assertEqual(controller.settings, expected_runtime)
        self.assertEqual(controller.persisted_settings, expected_persisted)
        self.assertEqual(session.replace_settings_calls, [expected_runtime])
        self.assertEqual(batch["value"], 8)
        save.assert_called_once_with(
            expected_persisted,
            Path("/tmp/config.json"),
        )

    def test_operation_policy_can_allow_future_run_settings_during_generation(self):
        controller, session, operations, save, _status, batch = self.make_controller()
        operations.settings_change_conflict_status.return_value = None

        self.assertTrue(controller.change(take_count=7, output_dir=Path("/tmp/next")))

        self.assertEqual(batch["value"], 7)
        self.assertEqual(session.settings.take_count, 7)
        self.assertEqual(session.settings.output_dir, Path("/tmp/next"))
        operations.settings_change_conflict_status.assert_called_once()
        save.assert_called_once()

    def test_audio_output_changes_are_operation_relevant_without_being_synthesis_changes(self):
        events = []
        controller, session, operations, save, _status, _batch = (
            self.make_controller(events=events)
        )

        self.assertTrue(
            controller.change(output_format="flac", flac_encoding="pcm24")
        )

        operations.settings_change_conflict_status.assert_called_once_with(
            ("output_format", "flac_encoding")
        )
        self.assertEqual(session.settings.output_format, "flac")
        self.assertEqual(session.settings.flac_encoding, "pcm24")
        self.assertEqual(events, ["settings"])
        operations.stop_playback.assert_not_called()
        operations.clear_current_take.assert_not_called()
        save.assert_called_once()

    def test_operation_policy_blocks_conflicting_synthesis_setting_before_mutation(self):
        controller, session, operations, save, status, _batch = self.make_controller()
        conflict = "Synthesis settings cannot change while the current operation is active."
        operations.settings_change_conflict_status.return_value = conflict

        self.assertFalse(controller.change(speed=0.9))

        self.assertEqual(session.replace_settings_calls, [])
        save.assert_not_called()
        self.assertEqual(status["value"], conflict)

    def test_synthesis_change_stops_before_session_replacement_and_clears_after(self):
        events = []
        controller, session, operations, _save, status, _batch = (
            self.make_controller(events=events)
        )

        controller.change(speed=0.9)

        self.assertEqual(events, ["stop", "settings", "outcomes", "clear"])
        self.assertEqual(session.settings.speed, 0.9)
        operations.stop_playback.assert_called_once_with()
        operations.clear_current_take.assert_called_once_with()
        self.assertEqual(
            status["value"],
            "Settings saved. Existing temporary takes were cleared.",
        )

    def test_apply_save_failure_retry_does_not_reapply_runtime_or_clear_twice(self):
        opening = Settings()
        target = Settings(speed=1.25)
        attempts = []

        def save(_settings, _path):
            attempts.append("save")
            if len(attempts) == 1:
                raise OSError("disk full")

        controller, session, operations, _save, status, _batch = (
            self.make_controller(
                settings=opening,
                persisted_settings=opening,
                save=save,
            )
        )

        first = controller.apply_target(target)

        self.assertIn("could not be saved", first.error_status)
        self.assertEqual(controller.settings, target)
        self.assertEqual(controller.persisted_settings, opening)
        self.assertEqual(session.replace_settings_calls, [target])
        operations.stop_playback.assert_called_once_with()
        operations.clear_current_take.assert_called_once_with()

        second = controller.apply_target(target)

        self.assertIsNone(second.error_status)
        self.assertEqual(attempts, ["save", "save"])
        self.assertEqual(session.replace_settings_calls, [target])
        operations.stop_playback.assert_called_once_with()
        operations.clear_current_take.assert_called_once_with()
        self.assertEqual(controller.persisted_settings, target)
        self.assertEqual(status["value"], "Settings saved.")

    def test_identical_target_saves_without_runtime_reapplication(self):
        opening = Settings()
        controller, session, operations, save, status, _batch = (
            self.make_controller(
                settings=opening,
                persisted_settings=Settings(take_count=7),
            )
        )

        result = controller.apply_target(opening)

        self.assertIsNone(result.error_status)
        self.assertEqual(session.replace_settings_calls, [])
        operations.stop_playback.assert_not_called()
        operations.clear_current_take.assert_not_called()
        save.assert_called_once_with(opening, Path("/tmp/config.json"))
        self.assertEqual(controller.persisted_settings, opening)
        self.assertEqual(status["value"], "Settings saved.")

    def test_runtime_failure_keeps_controller_state_and_skips_persistence(self):
        opening = Settings()
        session = FakeSession(opening, error=ValueError("unsupported style"))
        controller, _session, operations, save, status, batch = (
            self.make_controller(
                settings=opening,
                persisted_settings=opening,
                session=session,
            )
        )
        target = Settings(style_id=9)

        result = controller.apply_target(target)

        self.assertIn("Settings were not changed", result.error_status)
        self.assertEqual(controller.settings, opening)
        self.assertEqual(controller.persisted_settings, opening)
        self.assertEqual(batch["value"], opening.take_count)
        operations.stop_playback.assert_called_once_with()
        operations.clear_current_take.assert_not_called()
        save.assert_not_called()
        self.assertIn("unsupported style", status["value"])


import curses
import json
import tempfile
from unittest.mock import patch
from voiceger_editor.caption_batch import CaptionBatchItem
from voiceger_editor.tui import TuiApp
from tests.tui_app_test_support import TuiAppTestCase, FakeSession as AppFakeSession, candidate, mixed_query, navigation_items

class TuiSettingsIntegrationTests(TuiAppTestCase):
    def test_settings_are_reachable_and_editable_without_shortcuts(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query())
            app.config_path = Path(directory) / "config.json"
            for _ in range(len(navigation_items(app))):
                if app._navigation.focus_key == ("settings", None):
                    break
                app._handle_key(curses.KEY_DOWN)
            self.assertEqual(app._navigation.focus_key, ("settings", None))
            app._handle_key("\n")
            self.assertEqual(app._editor_controller.editor.kind, "settings")
            editor = app._editor_controller.editor
            editor.selection = "output_dir"
            app._handle_key("\n")
            self.assertEqual(editor.active_field, "output_dir")
            editor.input_value = "/tmp/settings-output"
            app._handle_key("\n")
            self.assertIsNotNone(editor)
            self.assertIsNone(editor.active_field)
            self.assertEqual(
                editor.payload["draft_settings"]["output_dir"],
                "/tmp/settings-output",
            )
            self.assertEqual(app.settings.output_dir, Settings().output_dir)
            self.assertEqual(app.session.replace_settings_calls, [])
            self.assertFalse(app.config_path.exists())
            editor.selection = "apply"
            app._handle_key("\n")
            self.assertIsNone(app._editor_controller.editor)
            self.assertEqual(app.settings.output_dir, Path("/tmp/settings-output"))
            self.assertEqual(
                json.loads(app.config_path.read_text())["output_dir"],
                "/tmp/settings-output",
            )

    def test_audio_output_template_and_sidecars_apply_with_parent_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
            app.config_path = Path(directory) / "config.json"
            app._open_settings_editor()
            parent = app._editor_controller.editor
            parent.selection = "audio_output"
            app._handle_key("\n")
            editor = app._editor_controller.editor
            self.assertEqual(editor.kind, "audio_output_settings")

            editor.selection = "filename_template"
            app._handle_key("\n")
            editor.input_value = "{style}_{caption}_{HHmmss}"
            app._handle_key("\n")
            editor.selection = "save_text"
            app._handle_key(curses.KEY_RIGHT)
            editor.selection = "save_lab"
            app._handle_key(curses.KEY_RIGHT)

            app._handle_key("\x1b")
            self.assertIs(app._editor_controller.editor, parent)
            parent.selection = "apply"
            app._handle_key("\n")

            self.assertIsNone(app._editor_controller.editor)
            self.assertEqual(app.settings.filename_template, "{style}_{caption}_{HHmmss}")
            self.assertTrue(app.settings.save_text)
            self.assertTrue(app.settings.save_lab)
            saved = json.loads(app.config_path.read_text())
            self.assertEqual(saved["filename_template"], "{style}_{caption}_{HHmmss}")
            self.assertTrue(saved["save_text"])
            self.assertTrue(saved["save_lab"])

    def test_sampling_draft_only_applies_and_invalidates_candidates_on_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
            app.config_path = Path(directory) / "config.json"
            app._operations.current_take = 1
            app._operations.stop_playback = Mock()
            app._open_settings_editor()
            editor = app._editor_controller.editor
            editor.selection = "top_p"

            app._handle_key(curses.KEY_LEFT)

            self.assertEqual(editor.payload["draft_settings"]["top_p"], "0.95")
            self.assertEqual(app.settings.top_p, 1.0)
            self.assertEqual(app.session.candidates, (candidate(1),))
            self.assertFalse(app.config_path.exists())

            app._handle_key("a")

            self.assertEqual(app.settings.top_p, 0.95)
            self.assertEqual(app.session.replace_settings_calls[-1].top_p, 0.95)
            self.assertEqual(app.session.candidates, ())
            self.assertIsNone(app._operations.current_take)
            self.assertEqual(
                json.loads(app.config_path.read_text())["top_p"],
                0.95,
            )
            app._operations.stop_playback.assert_called_once_with()

    def test_settings_apply_reconciles_session_state_before_candidate_invalidation(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        target = Settings(
            top_p=0.95,
            output_dir=app.settings.output_dir,
        )
        app.settings = target
        app._persisted_settings = target
        app._operations.current_take = 1
        app._operations.stop_playback = Mock()
        app._open_settings_editor()

        with patch("voiceger_editor.tui.save_settings") as save:
            app._handle_key("a")

        save.assert_called_once_with(target, app.config_path)
        self.assertEqual(app.session.replace_settings_calls, [target])
        self.assertEqual(app.session.candidates, ())
        self.assertIsNone(app._operations.current_take)
        app._operations.stop_playback.assert_called_once_with()

    def test_explicit_settings_save_persists_entire_cli_effective_target(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "settings.json"
            effective = Settings(
                style_id=22,
                speed=1.25,
                take_count=7,
                output_dir=Path("/tmp/effective-output"),
                save_text=True,
            )
            persisted = Settings(output_dir=Path("/tmp/config-output"))
            app = TuiApp(
                adapter=Mock(),
                settings=effective,
                persisted_settings=persisted,
                config_path=config_path,
            )
            app.session = AppFakeSession(query=mixed_query(), candidates=(candidate(1),))
            app.session.settings = effective
            app._batch.batch.add_item(CaptionBatchItem(app.session))
            app._batch.open_item(0)
            app._open_settings_editor()
            editor = app._editor_controller.editor
            editor.payload["draft_settings"]["output_dir"] = "/tmp/explicit-output"
            editor.selection = "apply"

            app._handle_key("\n")

            target = Settings(
                style_id=22,
                speed=1.25,
                take_count=7,
                output_dir=Path("/tmp/explicit-output"),
                save_text=True,
            )
            self.assertEqual(app.session.replace_settings_calls, [target])
            self.assertEqual(app._persisted_settings, target)
            self.assertEqual(json.loads(config_path.read_text()), {
                "output_dir": "/tmp/explicit-output",
                "filename_template": target.filename_template,
                "output_format": target.output_format,
                "wav_encoding": target.wav_encoding,
                "flac_encoding": target.flac_encoding,
                "mp3_bitrate": target.mp3_bitrate,
                "take_count": 7,
                "style_id": 22,
                "speed": 1.25,
                "top_k": 20,
                "top_p": 1.0,
                "temperature": 1.0,
                "save_text": True,
                "save_lab": False,
            })


if __name__ == "__main__":
    unittest.main()
