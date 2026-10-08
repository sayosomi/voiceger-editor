from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from voiceger_editor import entrypoint
from voiceger_editor.settings import Settings
from voiceger_editor.terms_acceptance import (
    ACCEPTANCE_COMMAND,
    OFFICIAL_TERMS_URL,
    TermsAcceptanceStatus,
    VoicegerTermsAcceptanceError,
)


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


class EntrypointTermsAndStartupTests(unittest.TestCase):
    def test_main_sweeps_stale_take_directories_before_starting_tui(self):
        environment = SimpleNamespace(
            ready=True,
            warnings=(),
            voiceger_root=Path("/voiceger"),
        )
        with patch(
            "voiceger_editor.entrypoint.check_voiceger_environment",
            return_value=environment,
        ), patch(
            "voiceger_editor.entrypoint.current_acceptance_status",
            return_value=SimpleNamespace(accepted=True),
        ), patch(
            "voiceger_editor.entrypoint.require_current_acceptance",
        ), patch(
            "voiceger_editor.entrypoint.cleanup_stale_take_directories"
        ) as cleanup, patch(
            "voiceger_editor.entrypoint.load_settings",
            return_value=Settings(),
        ), patch(
            "voiceger_editor.entrypoint.VoicegerAdapter",
        ), patch(
            "curses.wrapper",
        ):
            self.assertEqual(entrypoint.main([]), 0)

        cleanup.assert_called_once_with()

    def test_first_use_japanese_menu_accepts_and_persists_before_tui(self):
        environment = SimpleNamespace(
            ready=True,
            warnings=(),
            voiceger_root=Path("/voiceger"),
        )
        order = []
        status = TermsAcceptanceStatus(
            accepted=False,
            path=Path("/terms.json"),
            notice_version=1,
            terms_url=OFFICIAL_TERMS_URL,
            detail="No acceptance record exists.",
        )
        with patch(
            "voiceger_editor.entrypoint.check_voiceger_environment",
            return_value=environment,
        ), patch(
            "voiceger_editor.entrypoint.current_acceptance_status",
            return_value=status,
        ), patch(
            "voiceger_editor.entrypoint.preferred_notice_language",
            return_value="ja",
        ), patch(
            "voiceger_editor.entrypoint.record_explicit_acceptance",
            side_effect=lambda: order.append("accepted"),
        ) as record_acceptance, patch(
            "voiceger_editor.entrypoint.require_current_acceptance",
            side_effect=lambda: order.append("required"),
        ), patch(
            "voiceger_editor.entrypoint.sys.stdin",
            SimpleNamespace(isatty=lambda: True),
        ), patch(
            "builtins.input",
            return_value="A",
        ) as prompt, patch(
            "voiceger_editor.entrypoint.cleanup_stale_take_directories",
            side_effect=lambda: order.append("cleanup"),
        ), patch(
            "voiceger_editor.entrypoint.load_settings",
            return_value=Settings(),
        ), patch(
            "voiceger_editor.entrypoint.VoicegerAdapter",
            side_effect=lambda **_kwargs: order.append("adapter") or Mock(),
        ), patch(
            "curses.wrapper",
            side_effect=lambda _run: order.append("tui"),
        ), redirect_stdout(StringIO()) as stdout:
            result = entrypoint.main([])

        self.assertEqual(result, 0)
        self.assertIn("必ずお読みください", stdout.getvalue())
        self.assertIn("[E] English", stdout.getvalue())
        self.assertIn(OFFICIAL_TERMS_URL, stdout.getvalue())
        prompt.assert_called_once_with("選択: ")
        record_acceptance.assert_called_once_with()
        self.assertEqual(order, ["accepted", "required", "cleanup", "adapter", "tui"])

    def test_first_use_language_switching_and_quit_never_accepts(self):
        environment = SimpleNamespace(
            ready=True,
            warnings=(),
            voiceger_root=Path("/voiceger"),
        )
        status = TermsAcceptanceStatus(
            accepted=False,
            path=Path("/terms.json"),
            notice_version=1,
            terms_url=OFFICIAL_TERMS_URL,
            detail="No acceptance record exists.",
        )
        cases = (
            ("ja", ["E", "Q"], "必ずお読みください", "Please read before continuing"),
            ("en", ["J", "Q"], "Please read before continuing", "必ずお読みください"),
        )
        for initial, answers, first_notice, switched_notice in cases:
            with self.subTest(initial=initial):
                with patch(
                    "voiceger_editor.entrypoint.check_voiceger_environment",
                    return_value=environment,
                ), patch(
                    "voiceger_editor.entrypoint.current_acceptance_status",
                    return_value=status,
                ), patch(
                    "voiceger_editor.entrypoint.preferred_notice_language",
                    return_value=initial,
                ), patch(
                    "voiceger_editor.entrypoint.sys.stdin",
                    SimpleNamespace(isatty=lambda: True),
                ), patch(
                    "builtins.input",
                    side_effect=answers,
                ), patch(
                    "voiceger_editor.entrypoint.record_explicit_acceptance",
                ) as record_acceptance, patch(
                    "voiceger_editor.entrypoint.VoicegerAdapter",
                ) as adapter, patch(
                    "curses.wrapper",
                ) as wrapper, redirect_stdout(StringIO()) as stdout:
                    self.assertEqual(entrypoint.main([]), 2)

                self.assertIn(first_notice, stdout.getvalue())
                self.assertIn(switched_notice, stdout.getvalue())
                record_acceptance.assert_not_called()
                adapter.assert_not_called()
                wrapper.assert_not_called()

    def test_blank_invalid_and_open_never_accept_before_quit(self):
        environment = SimpleNamespace(
            ready=True,
            warnings=(),
            voiceger_root=Path("/voiceger"),
        )
        status = TermsAcceptanceStatus(
            accepted=False,
            path=Path("/terms.json"),
            notice_version=1,
            terms_url=OFFICIAL_TERMS_URL,
            detail="No acceptance record exists.",
        )
        with patch(
            "voiceger_editor.entrypoint.check_voiceger_environment",
            return_value=environment,
        ), patch(
            "voiceger_editor.entrypoint.current_acceptance_status",
            return_value=status,
        ), patch(
            "voiceger_editor.entrypoint.preferred_notice_language",
            return_value="ja",
        ), patch(
            "voiceger_editor.entrypoint.sys.stdin",
            SimpleNamespace(isatty=lambda: True),
        ), patch(
            "builtins.input",
            side_effect=["", "x", "O", "Q"],
        ), patch(
            "voiceger_editor.entrypoint.webbrowser.open",
            return_value=True,
        ) as open_browser, patch(
            "voiceger_editor.entrypoint.record_explicit_acceptance",
        ) as record_acceptance, patch(
            "voiceger_editor.entrypoint.VoicegerAdapter",
        ) as adapter, patch(
            "curses.wrapper",
        ) as wrapper, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(entrypoint.main([]), 2)

        open_browser.assert_called_once_with(OFFICIAL_TERMS_URL)
        record_acceptance.assert_not_called()
        adapter.assert_not_called()
        wrapper.assert_not_called()

    def test_first_use_eof_exits_without_accepting(self):
        environment = SimpleNamespace(
            ready=True,
            warnings=(),
            voiceger_root=Path("/voiceger"),
        )
        status = TermsAcceptanceStatus(
            accepted=False,
            path=Path("/terms.json"),
            notice_version=1,
            terms_url=OFFICIAL_TERMS_URL,
            detail="No acceptance record exists.",
        )
        with patch(
            "voiceger_editor.entrypoint.check_voiceger_environment",
            return_value=environment,
        ), patch(
            "voiceger_editor.entrypoint.current_acceptance_status",
            return_value=status,
        ), patch(
            "voiceger_editor.entrypoint.preferred_notice_language",
            return_value="en",
        ), patch(
            "voiceger_editor.entrypoint.sys.stdin",
            SimpleNamespace(isatty=lambda: True),
        ), patch(
            "builtins.input",
            side_effect=EOFError,
        ), patch(
            "voiceger_editor.entrypoint.record_explicit_acceptance",
        ) as record_acceptance, patch(
            "voiceger_editor.entrypoint.VoicegerAdapter",
        ) as adapter, patch(
            "curses.wrapper",
        ) as wrapper:
            self.assertEqual(entrypoint.main([]), 2)

        record_acceptance.assert_not_called()
        adapter.assert_not_called()
        wrapper.assert_not_called()

    def test_persisted_acceptance_skips_first_use_prompt(self):
        environment = SimpleNamespace(
            ready=True,
            warnings=(),
            voiceger_root=Path("/voiceger"),
        )
        with patch(
            "voiceger_editor.entrypoint.check_voiceger_environment",
            return_value=environment,
        ), patch(
            "voiceger_editor.entrypoint.current_acceptance_status",
            return_value=SimpleNamespace(accepted=True),
        ), patch(
            "voiceger_editor.entrypoint.require_current_acceptance",
        ), patch(
            "builtins.input",
            side_effect=AssertionError("accepted state must not prompt"),
        ) as prompt, patch(
            "voiceger_editor.entrypoint.cleanup_stale_take_directories"
        ), patch(
            "voiceger_editor.entrypoint.load_settings",
            return_value=Settings(),
        ), patch(
            "voiceger_editor.entrypoint.VoicegerAdapter",
        ), patch(
            "curses.wrapper",
        ):
            self.assertEqual(entrypoint.main([]), 0)

        prompt.assert_not_called()

    def test_noninteractive_missing_acceptance_fails_with_setup_command(self):
        environment = SimpleNamespace(
            ready=True,
            warnings=(),
            voiceger_root=Path("/voiceger"),
        )
        error = VoicegerTermsAcceptanceError(
            f"Read {OFFICIAL_TERMS_URL} and run {ACCEPTANCE_COMMAND}."
        )
        with patch(
            "voiceger_editor.entrypoint.check_voiceger_environment",
            return_value=environment,
        ), patch(
            "voiceger_editor.entrypoint.current_acceptance_status",
            return_value=SimpleNamespace(accepted=False, detail="missing"),
        ), patch(
            "voiceger_editor.entrypoint.require_current_acceptance",
            side_effect=error,
        ), patch(
            "voiceger_editor.entrypoint.sys.stdin",
            SimpleNamespace(isatty=lambda: False),
        ), patch(
            "builtins.input",
            side_effect=AssertionError("non-interactive startup must not prompt"),
        ) as prompt, patch(
            "voiceger_editor.entrypoint.VoicegerAdapter",
        ) as adapter, patch(
            "curses.wrapper",
        ) as wrapper, redirect_stderr(StringIO()) as stderr:
            self.assertEqual(entrypoint.main([]), 2)

        self.assertIn(OFFICIAL_TERMS_URL, stderr.getvalue())
        self.assertIn(ACCEPTANCE_COMMAND, stderr.getvalue())
        prompt.assert_not_called()
        adapter.assert_not_called()
        wrapper.assert_not_called()

    def test_terms_management_actions_skip_voiceger_preflight(self):
        accepted_status = SimpleNamespace(
            accepted=True,
            path=Path("/terms.json"),
            notice_version=1,
            terms_url=OFFICIAL_TERMS_URL,
            detail="accepted",
        )
        rejected_status = SimpleNamespace(
            accepted=False,
            path=Path("/terms.json"),
            notice_version=1,
            terms_url=OFFICIAL_TERMS_URL,
            detail="No acceptance record exists.",
        )
        output = StringIO()

        def verify_notice_was_printed_before_recording():
            self.assertIn(OFFICIAL_TERMS_URL, output.getvalue())

        with patch(
            "voiceger_editor.entrypoint.check_voiceger_environment",
        ) as environment_check, patch(
            "voiceger_editor.entrypoint.record_explicit_acceptance",
            side_effect=verify_notice_was_printed_before_recording,
        ) as record_acceptance, patch(
            "voiceger_editor.entrypoint.current_acceptance_status",
            side_effect=[rejected_status, accepted_status],
        ), patch(
            "voiceger_editor.entrypoint.webbrowser.open",
            return_value=True,
        ) as open_browser, redirect_stdout(output):
            self.assertEqual(entrypoint.main(["--accept-voiceger-terms"]), 0)
            self.assertEqual(entrypoint.main(["--voiceger-terms-status"]), 2)
            self.assertEqual(entrypoint.main(["--voiceger-terms-status"]), 0)
            self.assertEqual(entrypoint.main(["--open-voiceger-terms"]), 0)

        environment_check.assert_not_called()
        record_acceptance.assert_called_once_with()
        open_browser.assert_called_once_with(OFFICIAL_TERMS_URL)
        self.assertIn("not accepted", output.getvalue())

    def test_acceptance_write_failure_does_not_start_tui(self):
        environment = SimpleNamespace(
            ready=True,
            warnings=(),
            voiceger_root=Path("/voiceger"),
        )
        status = TermsAcceptanceStatus(
            accepted=False,
            path=Path("/terms.json"),
            notice_version=1,
            terms_url=OFFICIAL_TERMS_URL,
            detail="No acceptance record exists.",
        )
        with patch(
            "voiceger_editor.entrypoint.check_voiceger_environment",
            return_value=environment,
        ), patch(
            "voiceger_editor.entrypoint.current_acceptance_status",
            return_value=status,
        ), patch(
            "voiceger_editor.entrypoint.record_explicit_acceptance",
            side_effect=OSError("read-only directory"),
        ), patch(
            "voiceger_editor.entrypoint.sys.stdin",
            SimpleNamespace(isatty=lambda: True),
        ), patch(
            "builtins.input",
            return_value="A",
        ), patch(
            "voiceger_editor.entrypoint.VoicegerAdapter",
        ) as adapter, patch(
            "curses.wrapper",
        ) as wrapper, redirect_stdout(StringIO()), redirect_stderr(StringIO()) as stderr:
            self.assertEqual(entrypoint.main([]), 2)

        self.assertIn("Cannot continue", stderr.getvalue())
        adapter.assert_not_called()
        wrapper.assert_not_called()

    def test_open_terms_reports_browser_failure_with_printed_url(self):
        with patch(
            "voiceger_editor.entrypoint.webbrowser.open",
            return_value=False,
        ), redirect_stdout(StringIO()) as stdout, redirect_stderr(
            StringIO()
        ) as stderr:
            result = entrypoint.main(["--open-voiceger-terms"])

        self.assertEqual(result, 2)
        self.assertIn(OFFICIAL_TERMS_URL, stdout.getvalue())
        self.assertIn(OFFICIAL_TERMS_URL, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
