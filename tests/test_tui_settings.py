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

    def test_synthesis_change_stops_before_session_replacement_and_clears_after(self):
        events = []
        controller, session, operations, _save, status, _batch = (
            self.make_controller(events=events)
        )

        controller.change(speed=0.9)

        self.assertEqual(events, ["stop", "settings", "clear"])
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


if __name__ == "__main__":
    unittest.main()
