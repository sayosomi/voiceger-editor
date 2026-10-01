from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from voiceger_accent_adapter import terms_acceptance as terms


class TermsAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / terms.ACCEPTANCE_FILENAME

    def test_missing_acceptance_is_not_current_and_error_is_actionable(self):
        status = terms.current_acceptance_status(self.path)

        self.assertFalse(status.accepted)
        self.assertIn("No acceptance record", status.detail)
        with self.assertRaises(terms.VoicegerTermsAcceptanceError) as caught:
            terms.require_current_acceptance(self.path)
        self.assertIn(terms.OFFICIAL_TERMS_URL, str(caught.exception))
        self.assertIn(terms.ACCEPTANCE_COMMAND, str(caught.exception))

    def test_explicit_acceptance_persists_across_reload(self):
        record = terms.record_explicit_acceptance(self.path)

        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")),
            {
                "accepted_explicitly": True,
                "notice_version": 1,
                "terms_url": terms.OFFICIAL_TERMS_URL,
            },
        )
        self.assertTrue(record.accepted_explicitly)
        self.assertEqual(terms.load_acceptance_record(self.path), record)
        self.assertTrue(terms.current_acceptance_status(self.path).accepted)
        terms.require_current_acceptance(self.path)

    def test_default_path_is_beside_default_config_file(self):
        config_path = Path(self.temp_dir.name) / "some-config" / "config.json"
        with patch.object(terms, "default_config_path", return_value=config_path):
            self.assertEqual(
                terms.default_acceptance_path(),
                config_path.with_name(terms.ACCEPTANCE_FILENAME),
            )

    def test_strictly_rejects_malformed_duplicate_missing_unknown_and_bad_fields(self):
        invalid_records = (
            "{",
            '{"accepted_explicitly":true,"accepted_explicitly":true,'
            '"notice_version":1,"terms_url":"'
            + terms.OFFICIAL_TERMS_URL
            + '"}',
            "[]",
            json.dumps(
                {
                    "accepted_explicitly": True,
                    "notice_version": 1,
                }
            ),
            json.dumps(
                {
                    "accepted_explicitly": True,
                    "notice_version": 1,
                    "terms_url": terms.OFFICIAL_TERMS_URL,
                    "extra": "ignored fields are forbidden",
                }
            ),
            json.dumps(
                {
                    "accepted_explicitly": False,
                    "notice_version": 1,
                    "terms_url": terms.OFFICIAL_TERMS_URL,
                }
            ),
            json.dumps(
                {
                    "accepted_explicitly": 1,
                    "notice_version": 1,
                    "terms_url": terms.OFFICIAL_TERMS_URL,
                }
            ),
            json.dumps(
                {
                    "accepted_explicitly": True,
                    "notice_version": True,
                    "terms_url": terms.OFFICIAL_TERMS_URL,
                }
            ),
            json.dumps(
                {
                    "accepted_explicitly": True,
                    "notice_version": 0,
                    "terms_url": terms.OFFICIAL_TERMS_URL,
                }
            ),
            json.dumps(
                {
                    "accepted_explicitly": True,
                    "notice_version": 2,
                    "terms_url": terms.OFFICIAL_TERMS_URL,
                }
            ),
            json.dumps(
                {
                    "accepted_explicitly": True,
                    "notice_version": 1,
                    "terms_url": [terms.OFFICIAL_TERMS_URL],
                }
            ),
        )

        for contents in invalid_records:
            with self.subTest(contents=contents):
                self.path.write_text(contents, encoding="utf-8")
                status = terms.current_acceptance_status(self.path)
                self.assertFalse(status.accepted)
                with self.assertRaises(terms.TermsAcceptanceRecordError):
                    terms.load_acceptance_record(self.path)
                with self.assertRaises(terms.VoicegerTermsAcceptanceError):
                    terms.require_current_acceptance(self.path)

    def test_url_mismatch_is_not_current(self):
        self.path.write_text(
            json.dumps(
                {
                    "accepted_explicitly": True,
                    "notice_version": 1,
                    "terms_url": "https://example.invalid/terms",
                }
            ),
            encoding="utf-8",
        )

        status = terms.current_acceptance_status(self.path)

        self.assertFalse(status.accepted)
        self.assertIn("does not match", status.detail)

    def test_notice_version_bump_forces_explicit_reacceptance(self):
        terms.record_explicit_acceptance(self.path)

        with patch.object(terms, "CURRENT_NOTICE_VERSION", 2):
            status = terms.current_acceptance_status(self.path)
            self.assertFalse(status.accepted)
            self.assertIn("current notice version is 2", status.detail)
            with self.assertRaises(terms.VoicegerTermsAcceptanceError):
                terms.require_current_acceptance(self.path)

            terms.record_explicit_acceptance(self.path)
            refreshed = terms.load_acceptance_record(self.path)
            self.assertEqual(refreshed.notice_version, 2)
            self.assertTrue(terms.current_acceptance_status(self.path).accepted)


    def test_status_shows_current_version_and_official_url(self):
        formatted = terms.format_acceptance_status(
            terms.current_acceptance_status(self.path)
        )

        self.assertIn("not accepted", formatted)
        self.assertIn("notice version: 1", formatted)
        self.assertIn(terms.OFFICIAL_TERMS_URL, formatted)


if __name__ == "__main__":
    unittest.main()
