from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from voiceger_accent_adapter import api
from voiceger_accent_adapter.compatibility import SUPPORTED_VOICEGER_REVISION
from voiceger_accent_adapter.tui import main
from voiceger_accent_adapter.voiceger_environment import (
    CheckStatus,
    EnvironmentCheck,
    VoicegerEnvironmentError,
    VoicegerEnvironmentReport,
    VOICEGER_REPOSITORY_URL,
    check_voiceger_environment,
    format_voiceger_environment_report,
    resolve_voiceger_root,
)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"test")


def _make_valid_voiceger(root: Path) -> None:
    _touch(root / "voiceger.py")
    _touch(root / "GPT-SoVITS" / "GPT_SoVITS" / "inference_webui.py")
    _touch(root / ".venv" / "bin" / "python")
    _touch(root / "GPT_weights_v2" / "zudamon_style_1-e15.ckpt")
    _touch(root / "SoVITS_weights_v2" / "zudamon_style_1_e8_s96.pth")
    _touch(root / "reference" / "reference.wav")
    _touch(root / "reference" / "ref_text.txt")
    _touch(root / "reference" / "01_ref_emoNormal026.wav")


def _report(*checks: EnvironmentCheck, root: Path = Path("/voiceger")):
    return VoicegerEnvironmentReport(
        adapter_version="1.0.0",
        python_version="3.9.0",
        voiceger_root=root,
        root_source="explicit",
        voiceger_revision=SUPPORTED_VOICEGER_REVISION,
        checks=tuple(checks),
    )


class VoicegerEnvironmentTests(unittest.TestCase):
    def test_root_resolution_distinguishes_explicit_environment_and_default(self):
        explicit, explicit_source = resolve_voiceger_root("/explicit/voiceger")
        self.assertEqual(explicit, Path("/explicit/voiceger"))
        self.assertEqual(explicit_source, "explicit")

        with patch.dict(os.environ, {"VOICEGER_ROOT": "/env/voiceger"}):
            configured, configured_source = resolve_voiceger_root()
        self.assertEqual(configured, Path("/env/voiceger"))
        self.assertEqual(configured_source, "environment")

        with patch.dict(os.environ, {"VOICEGER_ROOT": ""}), patch(
            "voiceger_accent_adapter.voiceger_environment.Path.home",
            return_value=Path("/home/tester"),
        ):
            default, default_source = resolve_voiceger_root()
        self.assertEqual(default, Path("/home/tester/voiceger_v2").resolve())
        self.assertEqual(default_source, "default")

    def test_missing_root_reports_major_setup_failures(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "missing"
            with patch(
                "voiceger_accent_adapter.voiceger_environment._read_voiceger_revision",
                return_value=None,
            ):
                report = check_voiceger_environment(root)

        statuses = {check.key: check.status for check in report.checks}
        self.assertEqual(statuses["voiceger-root"], CheckStatus.ERROR)
        self.assertEqual(statuses["voiceger-layout"], CheckStatus.ERROR)
        self.assertEqual(statuses["voiceger-python"], CheckStatus.ERROR)
        self.assertEqual(statuses["voiceger-models"], CheckStatus.ERROR)
        self.assertEqual(statuses["voiceger-reference-assets"], CheckStatus.ERROR)
        self.assertFalse(report.ready)

    def test_existing_non_voiceger_path_is_reported_as_layout_error(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch(
                "voiceger_accent_adapter.voiceger_environment._read_voiceger_revision",
                return_value=None,
            ):
                report = check_voiceger_environment(root)

        statuses = {check.key: check.status for check in report.checks}
        self.assertEqual(statuses["voiceger-root"], CheckStatus.OK)
        self.assertEqual(statuses["voiceger-layout"], CheckStatus.ERROR)

    def test_missing_models_and_reference_assets_are_fatal(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _touch(root / "voiceger.py")
            _touch(root / "GPT-SoVITS" / "GPT_SoVITS" / "inference_webui.py")
            _touch(root / ".venv" / "bin" / "python")
            with patch(
                "voiceger_accent_adapter.voiceger_environment._read_voiceger_revision",
                return_value=SUPPORTED_VOICEGER_REVISION,
            ), patch(
                "voiceger_accent_adapter.voiceger_environment.sys.prefix",
                str(root / ".venv"),
            ):
                report = check_voiceger_environment(root)

        statuses = {check.key: check.status for check in report.checks}
        self.assertEqual(statuses["voiceger-layout"], CheckStatus.OK)
        self.assertEqual(statuses["voiceger-python"], CheckStatus.OK)
        self.assertEqual(statuses["voiceger-models"], CheckStatus.ERROR)
        self.assertEqual(statuses["voiceger-reference-assets"], CheckStatus.ERROR)
        self.assertFalse(report.ready)

    def test_revision_mismatch_is_warning_and_not_fatal(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _make_valid_voiceger(root)
            with patch(
                "voiceger_accent_adapter.voiceger_environment._read_voiceger_revision",
                return_value="0123456789abcdef0123456789abcdef01234567",
            ), patch(
                "voiceger_accent_adapter.voiceger_environment.sys.prefix",
                str(root / ".venv"),
            ):
                report = check_voiceger_environment(root)

        revision = next(
            check for check in report.checks if check.key == "voiceger-revision"
        )
        self.assertEqual(revision.status, CheckStatus.WARN)
        self.assertIn("compatibility is unverified", revision.message)
        self.assertTrue(report.ready)

    def test_unset_voiceger_root_is_warning_when_default_install_is_ready(self):
        with TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            root = home / "voiceger_v2"
            _make_valid_voiceger(root)
            with patch.dict(os.environ, {"VOICEGER_ROOT": ""}), patch(
                "voiceger_accent_adapter.voiceger_environment.Path.home",
                return_value=home,
            ), patch(
                "voiceger_accent_adapter.voiceger_environment._read_voiceger_revision",
                return_value=SUPPORTED_VOICEGER_REVISION,
            ), patch(
                "voiceger_accent_adapter.voiceger_environment.sys.prefix",
                str(root / ".venv"),
            ):
                report = check_voiceger_environment()

        root_config = next(
            check for check in report.checks if check.key == "voiceger-root-config"
        )
        self.assertEqual(root_config.status, CheckStatus.WARN)
        self.assertIn("VOICEGER_ROOT is not set", root_config.message)
        self.assertTrue(report.ready)

    def test_actionable_error_and_report_include_setup_guidance(self):
        report = _report(
            EnvironmentCheck(
                "voiceger-root", CheckStatus.ERROR, "Voiceger root does not exist.",
            )
        )
        message = str(VoicegerEnvironmentError(report))
        rendered = format_voiceger_environment_report(report)

        self.assertIn(VOICEGER_REPOSITORY_URL, message)
        self.assertIn("VOICEGER_ROOT", message)
        self.assertIn(SUPPORTED_VOICEGER_REVISION, message)
        self.assertIn("--check", message)
        self.assertIn("[ERROR]", rendered)
        self.assertIn("READY: NO", rendered)


class VoicegerEnvironmentFrontendTests(unittest.TestCase):
    def tearDown(self):
        api.get_adapter.cache_clear()

    def test_diagnostic_cli_prints_report_and_returns_readiness_status(self):
        ready = _report(
            EnvironmentCheck("voiceger-root", CheckStatus.OK, "Voiceger root exists.")
        )
        output = StringIO()
        with patch(
            "voiceger_accent_adapter.tui.check_voiceger_environment",
            return_value=ready,
        ), redirect_stdout(output):
            result = main(["--check"])

        self.assertEqual(result, 0)
        self.assertIn("voiceger-accent-adapter 1.0.0", output.getvalue())
        self.assertIn("READY: YES", output.getvalue())

    def test_normal_tui_stops_before_curses_on_setup_error(self):
        failed = _report(
            EnvironmentCheck(
                "voiceger-root", CheckStatus.ERROR, "Voiceger root does not exist.",
            )
        )
        error = StringIO()
        with patch(
            "voiceger_accent_adapter.tui.check_voiceger_environment",
            return_value=failed,
        ), patch(
            "voiceger_accent_adapter.tui.curses.wrapper"
        ) as wrapper, redirect_stderr(error):
            result = main([])

        self.assertEqual(result, 2)
        wrapper.assert_not_called()
        self.assertIn("Voiceger setup is not ready.", error.getvalue())
        self.assertIn(VOICEGER_REPOSITORY_URL, error.getvalue())

    def test_api_maps_shared_setup_error_to_503(self):
        failed = _report(
            EnvironmentCheck(
                "voiceger-root", CheckStatus.ERROR, "Voiceger root does not exist.",
            )
        )
        api.get_adapter.cache_clear()
        with patch(
            "voiceger_accent_adapter.api.require_voiceger_environment",
            side_effect=VoicegerEnvironmentError(failed),
        ):
            with TestClient(api.app) as client:
                response = client.get("/speakers")

        self.assertEqual(response.status_code, 503)
        self.assertIn("Voiceger setup is not ready.", response.json()["detail"])
        self.assertIn(VOICEGER_REPOSITORY_URL, response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
