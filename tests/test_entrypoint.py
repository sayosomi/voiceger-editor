from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from voiceger_editor import entrypoint
from voiceger_editor.settings import Settings


class EntrypointStartupTests(unittest.TestCase):
    def _patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def _patch_ready_tui_prerequisites(self):
        environment = SimpleNamespace(
            ready=True,
            warnings=(),
            voiceger_root=Path("/voiceger"),
        )
        self._patch(
            "voiceger_editor.entrypoint.check_voiceger_environment",
            return_value=environment,
        )
        self._patch(
            "voiceger_editor.entrypoint.current_acceptance_status",
            return_value=SimpleNamespace(accepted=True),
        )
        self._patch("voiceger_editor.entrypoint.require_current_acceptance")
        self._patch("voiceger_editor.entrypoint.cleanup_stale_take_directories")
        self._patch(
            "voiceger_editor.entrypoint.load_settings",
            return_value=Settings(),
        )
        self._patch("voiceger_editor.entrypoint.VoicegerAdapter")

    def test_management_actions_do_not_load_the_tui_runtime(self):
        load_curses = self._patch("voiceger_editor.entrypoint._load_curses")
        environment = SimpleNamespace(ready=True)
        self._patch(
            "voiceger_editor.entrypoint.check_voiceger_environment",
            return_value=environment,
        )
        self._patch(
            "voiceger_editor.entrypoint.format_voiceger_environment_report",
            return_value="READY: YES",
        )

        with redirect_stdout(StringIO()):
            with self.assertRaises(SystemExit) as help_exit:
                entrypoint.main(["--help"])
            with self.assertRaises(SystemExit) as version_exit:
                entrypoint.main(["--version"])
            check_result = entrypoint.main(["--check"])

        self.assertEqual(help_exit.exception.code, 0)
        self.assertEqual(version_exit.exception.code, 0)
        self.assertEqual(check_result, 0)
        load_curses.assert_not_called()

    def test_missing_curses_on_tui_path_has_actionable_install_message(self):
        self._patch_ready_tui_prerequisites()
        load_curses = self._patch(
            "voiceger_editor.entrypoint._load_curses",
            side_effect=ModuleNotFoundError(
                "No module named 'curses'",
                name="curses",
            ),
        )
        error = StringIO()

        with redirect_stderr(error):
            result = entrypoint.main([])

        self.assertEqual(result, 2)
        self.assertIn(
            "python -m pip install 'voiceger-editor[tui]'",
            error.getvalue(),
        )
        load_curses.assert_called_once_with()

    def test_unrelated_missing_module_on_tui_path_is_not_rewritten(self):
        self._patch_ready_tui_prerequisites()
        missing_dependency = ModuleNotFoundError(
            "No module named 'other_dependency'",
            name="other_dependency",
        )
        self._patch(
            "voiceger_editor.entrypoint._load_curses",
            side_effect=missing_dependency,
        )

        with self.assertRaises(ModuleNotFoundError) as caught:
            entrypoint.main([])

        self.assertIs(caught.exception, missing_dependency)
        self.assertEqual(caught.exception.name, "other_dependency")

    def test_tui_import_failure_is_not_reported_as_missing_curses(self):
        self._patch_ready_tui_prerequisites()
        self._patch(
            "voiceger_editor.entrypoint._load_curses",
            return_value=SimpleNamespace(wrapper=Mock(), error=Exception),
        )
        error = StringIO()

        with patch.dict(
            sys.modules,
            {"voiceger_editor.tui": None},
        ), redirect_stderr(error):
            with self.assertRaises(ModuleNotFoundError) as caught:
                entrypoint.main([])

        self.assertEqual(caught.exception.name, "voiceger_editor.tui")
        self.assertNotIn("voiceger-editor[tui]", error.getvalue())

    def test_curses_wrapper_error_keeps_terminal_guidance(self):
        self._patch_ready_tui_prerequisites()

        class FakeCursesError(Exception):
            pass

        wrapper = Mock(side_effect=FakeCursesError("terminal unavailable"))
        backend = SimpleNamespace(wrapper=wrapper, error=FakeCursesError)
        self._patch(
            "voiceger_editor.entrypoint._load_curses",
            return_value=backend,
        )
        tui_module = ModuleType("voiceger_editor.tui")
        app = SimpleNamespace(run=Mock())
        tui_module.TuiApp = Mock(return_value=app)
        error = StringIO()

        with patch.dict(
            sys.modules,
            {"voiceger_editor.tui": tui_module},
        ), redirect_stderr(error):
            result = entrypoint.main([])

        self.assertEqual(result, 2)
        wrapper.assert_called_once_with(app.run)
        self.assertIn(
            "The terminal UI could not start: terminal unavailable. "
            "Run this command in a real terminal.",
            error.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
