"""Multi-peak dictionary persistence and native/VOICEVOX transfer regressions."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from voiceger_editor.dictionary_export import (
    export_voiceger_editor_dictionaries, export_voicevox_dictionary,
)
from voiceger_editor.dictionary_import import (
    DictionaryImportError, DictionaryImportRelation, prepare_dictionary_import,
)
from voiceger_editor.openjtalk_dictionary import render_word_csv
from voiceger_editor.pronunciation import AccentPhrase, PitchEvent, Pronunciation, format_pronunciation, parse_pronunciation
from voiceger_editor.user_dictionary import (
    UserDictionaryCore, UserDictionaryInputError, UserDictionaryStorageError,
)


EVENTS = (
    PitchEvent(1, "["), PitchEvent(2, "]"),
    PitchEvent(4, "["), PitchEvent(5, "]"),
)


class FakeBackend:
    def __init__(self):
        self.active = {}
        self.fail_compile = False

    def ensure_active(self, entries, *, force=False):
        if force:
            self.active = dict(entries)

    def activate_entries(self, entries):
        if self.fail_compile:
            from voiceger_editor.openjtalk_dictionary import OpenJTalkDictionaryError
            raise OpenJTalkDictionaryError("compile failure")
        previous = self.snapshot()
        self.active = dict(entries)
        return previous

    def snapshot(self):
        class State:
            compilation = None
            def __init__(self, entries):
                self.entries = entries
        return State(dict(self.active))

    def restore(self, previous):
        self.active = dict(previous.entries)

    def commit(self, previous):
        pass


class JapaneseMultiPeakDictionaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.voiceger = self.root / "voiceger"
        self.voiceger.mkdir()
        self.backend = FakeBackend()
        self.core = UserDictionaryCore(
            self.voiceger, data_directory=self.root / "data",
            openjtalk_dictionary=self.backend,
        )

    def restart(self):
        return UserDictionaryCore(
            self.voiceger, data_directory=self.root / "data",
            openjtalk_dictionary=FakeBackend(),
        )

    def add_multi(self):
        return self.core.add_japanese_word(
            surface="スタックチャン", pronunciation="スタックチャン",
            accent_type=2, pitch_events=EVENTS,
        )

    def test_legacy_save_load_and_priority_default_have_no_sidecar(self):
        word_uuid = self.core.add_japanese_word(
            surface="雨", pronunciation="アメ", accent_type=1,
        )
        self.assertFalse(self.core.japanese_pitch_path.exists())
        word = self.restart().list_japanese_entries()[word_uuid]
        self.assertEqual(word.priority, 5)
        self.assertEqual(word.accent_type, 1)
        self.assertEqual(self.core.list_japanese_pitch_events(), {})

    def test_multi_events_survive_restart_and_base_json_stays_voicevox_compatible(self):
        word_uuid = self.add_multi()
        self.assertEqual(self.restart().get_japanese_pitch_events(word_uuid), EVENTS)
        word = self.core.list_japanese_entries()[word_uuid]
        self.assertEqual(word.priority, 5)
        payload = json.loads(self.core.japanese_path.read_text(encoding="utf-8"))
        self.assertEqual(list(payload), [word_uuid])
        self.assertEqual(payload[word_uuid]["accent_type"], 2)
        self.assertEqual(payload[word_uuid]["pronunciation"], "スタックチャン")
        self.assertNotIn("pitch_events", payload[word_uuid])
        self.assertNotIn("events", payload[word_uuid])
        self.assertIn("2/6", render_word_csv(word))
        sidecar = json.loads(self.core.japanese_pitch_path.read_text(encoding="utf-8"))
        self.assertEqual(sidecar["version"], 1)
        self.assertEqual(list(sidecar["entries"]), [word_uuid])

    def test_boundary_brackets_survive_dictionary_restart_without_fake_falls(self):
        phrase = parse_pronunciation("[シ]コク[メタン]").phrases[0]
        identity = self.core.add_japanese_word(
            surface="四国めたん", pronunciation=phrase.reading,
            accent_type=phrase.accent,
            pitch_events=phrase.pitch_events,
        )
        loaded = self.restart()
        restored = loaded.get_japanese_pitch_events(identity)
        self.assertEqual(restored, phrase.pitch_events)
        word = loaded.list_japanese_entries()[identity]
        self.assertEqual(word.accent_type, 1)
        self.assertEqual(
            format_pronunciation(Pronunciation(phrases=(
                AccentPhrase(
                    tuple(phrase.morae), word.accent_type, tuple(restored),
                ),
            ))),
            "[シ]コク[メタン]",
        )

    def test_crud_validation_accent_edit_and_deletion(self):
        word_uuid = self.add_multi()
        with self.assertRaises(UserDictionaryInputError):
            self.core.update_japanese_pitch_events(
                word_uuid, [PitchEvent(1, "["), PitchEvent(2, "]")]
            )
        self.assertEqual(self.core.get_japanese_pitch_events(word_uuid), EVENTS)
        self.core.update_japanese_accents({word_uuid: 3})
        expected = (
            PitchEvent(1, "["), PitchEvent(3, "]"),
            PitchEvent(4, "["), PitchEvent(5, "]"),
        )
        self.assertEqual(self.restart().get_japanese_pitch_events(word_uuid), expected)
        with self.assertRaises(UserDictionaryInputError):
            self.core.update_japanese_accents({word_uuid: 4})
        self.assertEqual(self.core.get_japanese_pitch_events(word_uuid), expected)
        self.core.update_japanese_accents({word_uuid: 2})
        self.core.update_japanese_pitch_events(word_uuid, EVENTS)
        self.core.delete_japanese_pitch_events(word_uuid)
        self.assertEqual(self.core.get_japanese_pitch_events(word_uuid), ())
        self.assertFalse(self.core.japanese_pitch_path.exists())
        self.core.update_japanese_pitch_events(word_uuid, EVENTS)
        self.core.delete_japanese_word(word_uuid)
        self.assertFalse(self.core.japanese_pitch_path.exists())
        self.assertEqual(self.restart().list_japanese_entries(), {})

    def test_compilation_and_second_file_failure_restore_dictionary_and_events(self):
        word_uuid = self.add_multi()
        before_base = self.core.japanese_path.read_bytes()
        before_sidecar = self.core.japanese_pitch_path.read_bytes()
        before_active = dict(self.backend.active)
        self.backend.fail_compile = True
        with self.assertRaises(Exception):
            self.core.add_japanese_word(
                surface="新語", pronunciation="シンゴ", accent_type=1,
            )
        self.assertEqual(self.core.japanese_path.read_bytes(), before_base)
        self.assertEqual(self.core.japanese_pitch_path.read_bytes(), before_sidecar)
        self.backend.fail_compile = False

        from voiceger_editor import user_dictionary
        original = user_dictionary._atomic_write
        injected = False
        def fail_sidecar_once(path, payload):
            nonlocal injected
            if path == self.core.japanese_pitch_path and not injected:
                injected = True
                raise OSError("disk full")
            return original(path, payload)
        with patch("voiceger_editor.user_dictionary._atomic_write",
                   side_effect=fail_sidecar_once):
            with self.assertRaises(UserDictionaryStorageError):
                self.core.add_japanese_word(
                    surface="新語", pronunciation="シンゴ", accent_type=1,
                )
        self.assertTrue(injected)
        self.assertEqual(self.core.japanese_path.read_bytes(), before_base)
        self.assertEqual(self.core.japanese_pitch_path.read_bytes(), before_sidecar)
        self.assertEqual(self.backend.active, before_active)
        self.assertEqual(self.restart().get_japanese_pitch_events(word_uuid), EVENTS)
        self.assertFalse(self.core.japanese_journal_path.exists())

    def test_metadata_only_persistence_failure_does_not_mutate_memory(self):
        word_uuid = self.add_multi()
        with patch("voiceger_editor.user_dictionary._atomic_write",
                   side_effect=OSError("disk full")):
            with self.assertRaises(UserDictionaryStorageError):
                self.core.update_japanese_pitch_events(word_uuid, (PitchEvent(1, "["), PitchEvent(2, "]"), PitchEvent(3, "["), PitchEvent(4, "]")))
        self.assertEqual(self.core.get_japanese_pitch_events(word_uuid), EVENTS)

    def test_native_export_import_and_missing_or_corrupt_sidecar(self):
        word_uuid = self.add_multi()
        result = export_voiceger_editor_dictionaries(
            self.core, self.root / "out",
        )
        self.assertEqual(len(result.paths), 3)
        self.assertIn("user_dict_with_pitch_events", result.paths[0].name)
        self.assertIn("user_dict_pitch_events", result.paths[2].name)
        self.assertEqual(result.paths[0].read_bytes(), self.core.japanese_path.read_bytes())
        second = export_voiceger_editor_dictionaries(
            self.core, self.root / "out",
        )
        self.assertEqual(len(second.paths), 3)
        self.assertTrue(all("-2.json" in path.name for path in second.paths))
        other = UserDictionaryCore(
            self.voiceger, data_directory=self.root / "other",
            openjtalk_dictionary=FakeBackend(),
        )
        review = prepare_dictionary_import(result.paths[0], other)
        self.assertTrue(review.items[0].selected)
        review.commit(other)
        self.assertEqual(other.get_japanese_pitch_events(word_uuid), EVENTS)
        self.assertEqual(other.list_japanese_entries()[word_uuid].priority, 5)
        self.assertEqual(other.list_japanese_entries()[word_uuid].accent_type, 2)
        self.assertEqual(other.list_japanese_entries()[word_uuid].surface, "スタックチャン")
        exact = prepare_dictionary_import(result.paths[0], other)
        self.assertEqual(exact.exact_duplicate_count, 1)

        result.paths[2].unlink()
        with self.assertRaises(DictionaryImportError):
            prepare_dictionary_import(result.paths[0], other)
        with self.assertRaises(DictionaryImportError):
            prepare_dictionary_import(result.paths[0], self.core)

    def test_metadata_changes_with_same_base_word_are_reviewable(self):
        word_uuid = self.add_multi()
        result = export_voiceger_editor_dictionaries(self.core, self.root / "out")
        self.core.delete_japanese_pitch_events(word_uuid)
        review = prepare_dictionary_import(result.paths[0], self.core)
        self.assertEqual(review.items[0].relation, DictionaryImportRelation.CONFLICT)
        review.set_selected(word_uuid, True)
        review.commit(self.core)
        self.assertEqual(self.core.get_japanese_pitch_events(word_uuid), EVENTS)

    def test_voicevox_is_single_accent_and_legacy_import_preserves_words(self):
        word_uuid = self.add_multi()
        output = export_voicevox_dictionary(self.core, self.root / "out")
        self.assertEqual(output.lossy_pitch_event_uuids, (word_uuid,))
        payload = json.loads(output.paths[0].read_text(encoding="utf-8"))
        self.assertEqual(payload[word_uuid]["accent_type"], 2)
        self.assertNotIn("pitch_events", payload[word_uuid])
        other = UserDictionaryCore(
            self.voiceger, data_directory=self.root / "other",
            openjtalk_dictionary=FakeBackend(),
        )
        legacy = prepare_dictionary_import(output.paths[0], other)
        legacy.commit(other)
        self.assertEqual(other.list_japanese_pitch_events(), {})
        self.assertEqual(other.list_japanese_entries()[word_uuid].priority, 5)


if __name__ == "__main__":
    unittest.main()
