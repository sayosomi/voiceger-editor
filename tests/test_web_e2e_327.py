"""Regression checks for Issue #327's isolated Mac terms acceptance handoff."""

from __future__ import annotations

from pathlib import Path
import json
import os
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts import run_web_e2e_327 as launcher
from voiceger_editor.terms_acceptance import (
    current_acceptance_status,
    default_acceptance_path,
    record_explicit_acceptance,
)


class WebE2ETermsIsolationTests(TestCase):
    def test_current_mac_acceptance_reused_only_inside_test_home(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            mac_record = root / "existing" / "voiceger-terms-acceptance.json"
            record_explicit_acceptance(mac_record)
            original = mac_record.read_bytes()
            test_home = root / "test-home"
            test_home.mkdir()
            # Override both native macOS HOME and Windows APPDATA so no
            # machine-wide acceptance path is used by this regression test.
            with patch.dict(os.environ, {
                "HOME": str(test_home),
                "APPDATA": str(test_home / "AppData" / "Roaming"),
            }):
                isolated_record = default_acceptance_path()
                self.assertNotEqual(mac_record, isolated_record)
                launcher._copy_current_terms_acceptance(mac_record, isolated_record)
                self.assertTrue(current_acceptance_status().accepted)
                self.assertTrue(isolated_record.is_relative_to(test_home))
                self.assertEqual(isolated_record.read_bytes(), original)
            self.assertEqual(mac_record.read_bytes(), original)

    def test_missing_mac_consent_cannot_create_test_acceptance(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            destination = root / "home" / "voiceger-terms-acceptance.json"
            with self.assertRaises(launcher.LaunchBlocked):
                launcher._copy_current_terms_acceptance(root / "missing.json", destination)
            self.assertFalse(destination.exists())

    def test_stale_mac_consent_cannot_be_copied(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "existing.json"
            record_explicit_acceptance(original)
            payload = json.loads(original.read_text(encoding="utf-8"))
            payload["notice_version"] = 0
            original.write_text(json.dumps(payload), encoding="utf-8")
            destination = root / "home" / "voiceger-terms-acceptance.json"
            with self.assertRaises(launcher.LaunchBlocked):
                launcher._copy_current_terms_acceptance(original, destination)
            self.assertFalse(destination.exists())
