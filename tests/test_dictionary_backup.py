"""Native ZIP dictionary backup hostile parsing and all-language atomicity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from voiceger_editor.dictionary_backup import (
    load_dictionary_backup,
    prepare_dictionary_backup,
)
from voiceger_editor.dictionary_export import export_voiceger_editor_dictionaries
from voiceger_editor.dictionary_import import DictionaryImportError, DictionaryImportFormat
from voiceger_editor.pronunciation import PitchEvent
from voiceger_editor.user_dictionary import (
    UserDictionaryCore, UserDictionaryInputError, UserDictionaryStorageError,
)
from voiceger_editor import user_dictionary


class _State:
    def __init__(self, entries):
        self.entries = dict(entries)
        self.compilation = None


class FakeBackend:
    def __init__(self):
        self.active = {}

    def ensure_active(self, entries, *, force=False):
        if force:
            self.active = dict(entries)

    def activate_entries(self, entries):
        previous = _State(self.active)
        self.active = dict(entries)
        return previous

    def snapshot(self):
        return _State(self.active)

    def restore(self, previous):
        self.active = dict(previous.entries)

    def commit(self, previous):
        pass


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.voiceger = self.root / "voiceger"
        self.voiceger.mkdir()
        self.source_backend = FakeBackend()
        self.target_backend = FakeBackend()
        self.source = UserDictionaryCore(
            self.voiceger, data_directory=self.root / "source",
            openjtalk_dictionary=self.source_backend,
        )
        self.target = UserDictionaryCore(
            self.voiceger, data_directory=self.root / "target",
            openjtalk_dictionary=self.target_backend,
        )
        self.source_uuid = self.source.add_japanese_word(
            surface="スタックチャン",
            pronunciation="スタックチャン",
            accent_type=2,
            pitch_events=(
                PitchEvent(1, "["), PitchEvent(2, "]"),
                PitchEvent(4, "["), PitchEvent(5, "]"),
            ),
        )
        self.source.add_japanese_word(
            surface="ずんだもん", pronunciation="ズンダモン", accent_type=3
        )
        self.source.add_english_entry("Alpha", ["AE1", "L", "F", "AH0"])
        self.source.add_english_entry("Beta", ["B", "EY1", "T", "AH0"])
        self.archive = export_voiceger_editor_dictionaries(
            self.source, self.root / "output"
        ).paths[0]

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_restore_preserves_original_ids_order_and_pitch(self):
        local_uuid = self.target.add_japanese_word(
            surface="ローカル", pronunciation="ローカル", accent_type=0
        )
        self.target.add_english_entry("OnlyLocal", ["OW1", "N", "L", "IY0"])
        review = prepare_dictionary_backup(self.archive, self.target, restore=True)
        self.assertIs(review.format, DictionaryImportFormat.RESTORE)
        self.assertIn("ローカル", review.deleted_japanese)
        self.assertIn("OnlyLocal", review.deleted_english)
        with self.assertRaisesRegex(DictionaryImportError, "confirmation"):
            review.commit(self.target)
        self.assertIn(local_uuid, self.target.list_japanese_entries())
        review.commit(self.target, confirmed=True)
        self.assertEqual(
            list(self.target.list_japanese_entries()),
            list(self.source.list_japanese_entries()),
        )
        self.assertEqual(
            list(self.target.list_english_entries()),
            list(self.source.list_english_entries()),
        )
        self.assertEqual(
            self.target.list_japanese_pitch_events(),
            self.source.list_japanese_pitch_events(),
        )
        self.assertNotIn(local_uuid, self.target.list_japanese_entries())
        self.assertFalse(self.target.backup_journal_path.exists())

    def test_full_restore_does_not_reject_an_unrelated_local_uuid_collision(self):
        unrelated = self.target._create_word(
            surface="異なる", pronunciation="コトナル", accent_type=0,
            word_type=None, priority=5,
        )
        self.target.import_japanese({self.source_uuid: unrelated}, override=True)
        review = prepare_dictionary_backup(self.archive, self.target, restore=True)
        collision = next(
            item for item in review.items
            if getattr(item, "source_uuid", None) == self.source_uuid
        )
        self.assertEqual(collision.relation.value, "conflict")
        self.assertEqual(collision.existing.surface, "異なる")
        review.commit(self.target, confirmed=True)
        self.assertEqual(
            self.target.list_japanese_entries()[self.source_uuid].surface,
            "スタックチャン",
        )

    def test_merge_keeps_local_words_and_accepts_selected_cross_language_conflicts(self):
        local_uuid = self.target.add_japanese_word(
            surface="ローカル", pronunciation="ローカル", accent_type=0
        )
        old_uuid = self.target.add_japanese_word(
            surface="ずんだもん", pronunciation="ズンダモン", accent_type=0
        )
        self.target.add_english_entry("Alpha", ["AE1", "L", "F"])
        self.target.add_english_entry("Local", ["L", "OW1", "K", "AH0", "L"])
        review = prepare_dictionary_backup(self.archive, self.target)
        self.assertIs(review.format, DictionaryImportFormat.BACKUP)
        self.assertEqual(review.language_counts, (2, 2))
        self.assertTrue(any(not item.selected for item in review.items))
        jp = next(item for item in review.items if item.incoming.surface == "ずんだもん")
        en = next(item for item in review.items if item.incoming.surface == "Alpha")
        review.set_selected(jp.source_uuid, True, language="ja")
        review.set_selected(en.incoming.surface, True, language="en")
        review.commit(self.target)
        japanese = self.target.list_japanese_entries()
        english = self.target.list_english_entries()
        self.assertIn(local_uuid, japanese)
        self.assertEqual(japanese[old_uuid].accent_type, 3)
        self.assertIn(self.source_uuid, japanese)
        self.assertEqual(self.target.list_japanese_pitch_events()[self.source_uuid],
                         self.source.list_japanese_pitch_events()[self.source_uuid])
        self.assertEqual(english["Alpha"].phonemes, ["AE1", "L", "F", "AH0"])
        self.assertIn("Local", english)

    def test_failed_late_write_restores_both_dictionaries_pitch_files_and_backend(self):
        self.target.add_japanese_word(
            surface="残す", pronunciation="ノコス", accent_type=0
        )
        self.target.add_english_entry("Local", ["L", "OW1", "K", "AH0", "L"])
        review = prepare_dictionary_backup(self.archive, self.target, restore=True)
        before_japanese = self.target.list_japanese_entries()
        before_english = self.target.list_english_entries()
        before_pitch = self.target.list_japanese_pitch_events()
        before_backend = dict(self.target_backend.active)
        files = (self.target.japanese_path, self.target.english_path,
                 self.target.japanese_pitch_path)
        old_bytes = {
            path: path.read_bytes() if path.exists() else None for path in files
        }
        original = user_dictionary._atomic_write
        injected = False

        def fail_once(path, data):
            nonlocal injected
            if path == self.target.english_path and not injected:
                injected = True
                raise OSError("simulated full disk")
            return original(path, data)

        with patch("voiceger_editor.user_dictionary._atomic_write", side_effect=fail_once):
            with self.assertRaises(UserDictionaryStorageError):
                review.commit(self.target, confirmed=True)

        self.assertTrue(injected)
        self.assertEqual(self.target.list_japanese_entries(), before_japanese)
        self.assertEqual(self.target.list_english_entries(), before_english)
        self.assertEqual(self.target.list_japanese_pitch_events(), before_pitch)
        self.assertEqual(self.target_backend.active, before_backend)
        for path, contents in old_bytes.items():
            self.assertEqual(path.read_bytes() if path.exists() else None, contents)
        self.assertFalse(self.target.backup_journal_path.exists())

    def test_mutation_between_review_and_apply_is_rejected(self):
        review = prepare_dictionary_backup(self.archive, self.target)
        self.target.add_english_entry("Later", ["L", "EY1", "T", "ER0"])
        with self.assertRaisesRegex(UserDictionaryInputError, "changed"):
            review.commit(self.target)
        self.assertEqual(list(self.target.list_english_entries()), ["Later"])

    def _rewrite(self, members, *, manifest=None):
        path = self.root / "mutated.zip"
        if manifest is None:
            manifest = {
                "version": 1,
                "members": {
                    name: hashlib.sha256(data).hexdigest() for name, data in members.items()
                },
            }
        with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest).encode())
            for name, data in members.items():
                archive.writestr(name, data)
        return path

    def test_manifest_version_checksum_and_member_rejection_never_change_state(self):
        with ZipFile(self.archive) as archive:
            members = {
                name: archive.read(name)
                for name in archive.namelist() if name != "manifest.json"
            }
        invalid_manifest = {"version": 2, "members": {
            name: hashlib.sha256(data).hexdigest() for name, data in members.items()
        }}
        version_path = self.root / "version.zip"
        version_path.write_bytes(self._rewrite(members, manifest=invalid_manifest).read_bytes())
        cases = [version_path]
        for name, change in [
            ("missing", {"user_dict.json": members["user_dict.json"]}),
            ("traversal", {**members, "../x": b"bad"}),
        ]:
            path = self.root / (name + ".zip")
            malformed = self._rewrite(change)
            path.write_bytes(malformed.read_bytes())
            cases.append(path)
        wrong_digest = {
            "version": 1,
            "members": {
                name: hashlib.sha256(data).hexdigest() for name, data in members.items()
            },
        }
        wrong_digest["members"]["english_user_dict.json"] = "0" * 64
        wrong_path = self.root / "wrong_hash.zip"
        wrong_path.write_bytes(
            self._rewrite(members, manifest=wrong_digest).read_bytes()
        )
        cases.append(wrong_path)
        before = self.target.list_japanese_entries()
        for path in cases:
            with self.subTest(name=path.name):
                with self.assertRaises(DictionaryImportError):
                    prepare_dictionary_backup(path, self.target)
                self.assertEqual(self.target.list_japanese_entries(), before)

    def test_duplicate_archive_members_are_rejected(self):
        with ZipFile(self.archive) as original:
            entries = {name: original.read(name) for name in original.namelist()}
        path = self.root / "duplicates.zip"
        from warnings import catch_warnings, simplefilter
        with catch_warnings():
            simplefilter("ignore", UserWarning)
            with ZipFile(path, "w") as archive:
                for name, data in entries.items():
                    archive.writestr(name, data)
                archive.writestr("user_dict.json", entries["user_dict.json"])
        with self.assertRaises(DictionaryImportError):
            load_dictionary_backup(path)


if __name__ == "__main__":
    unittest.main()
