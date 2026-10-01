from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from voiceger_accent_adapter import __version__
from voiceger_accent_adapter.api import app, root, version
from voiceger_accent_adapter.entrypoint import main
from voiceger_accent_adapter.tui_cli import build_argument_parser


class VersionTests(unittest.TestCase):
    def test_v1_version_source_drives_runtime_surfaces(self):
        self.assertEqual(__version__, "1.0.0")
        self.assertEqual(app.version, __version__)
        self.assertEqual(root()["version"], __version__)
        self.assertEqual(version(), __version__)

    def test_cli_version_prints_canonical_version_and_skips_voiceger_gates(self):
        output = StringIO()
        with patch(
            "voiceger_accent_adapter.entrypoint.check_voiceger_environment"
        ) as check_environment, patch(
            "voiceger_accent_adapter.entrypoint._require_tui_terms_acceptance"
        ) as require_terms, redirect_stdout(output):
            with self.assertRaises(SystemExit) as caught:
                main(["--version"])

        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(
            output.getvalue(),
            f"voiceger-accent-adapter {__version__}\n",
        )
        check_environment.assert_not_called()
        require_terms.assert_not_called()

    def test_help_includes_version_option(self):
        self.assertIn("--version", build_argument_parser().format_help())


if __name__ == "__main__":
    unittest.main()
