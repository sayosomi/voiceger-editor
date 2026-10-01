import unittest

from voiceger_accent_adapter import __version__
from voiceger_accent_adapter.api import app, root, version


class VersionTests(unittest.TestCase):
    def test_v1_version_source_drives_runtime_surfaces(self):
        self.assertEqual(__version__, "1.0.0")
        self.assertEqual(app.version, __version__)
        self.assertEqual(root()["version"], __version__)
        self.assertEqual(version(), __version__)


if __name__ == "__main__":
    unittest.main()
