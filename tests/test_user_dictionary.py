import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import patch

from voiceger_accent_adapter import openjtalk_dictionary
from voiceger_accent_adapter.openjtalk_dictionary import (
    OpenJTalkDictionary,
    OpenJTalkDictionaryError,
    WORD_TYPE_DATA,
    normalize_surface,
    priority_to_cost,
    render_word_csv,
)
from voiceger_accent_adapter.runtime_locks import OPENJTALK_LOCK
from voiceger_accent_adapter.user_dictionary import (
    JapaneseWordType,
    UserDictWord,
    UserDictionaryCore,
    UserDictionaryInputError,
)


class _BackendState:
    def __init__(self, entries):
        self.entries = dict(entries)
        self.compilation = None
        self.signature = None


class FakeBackend:
    def __init__(self):
        self.active = {}
        self.fail_compile = False
        self.fail_apply = False
        self.events = []

    def ensure_active(self, entries, *, force=False):
        self.events.append(("ensure", dict(entries), force))
        if force:
            self.active = dict(entries)

    def snapshot(self):
        return _BackendState(self.active)

    def activate_entries(self, entries):
        if self.fail_compile:
            self.fail_compile = False
            self.events.append(("compile-failed", dict(entries)))
            raise OpenJTalkDictionaryError("compile failed")
        previous = self.snapshot()
        if self.fail_apply:
            self.fail_apply = False
            self.active = dict(entries)
            self.events.append(("apply-failed", dict(entries)))
            self.restore(previous)
            raise OpenJTalkDictionaryError("apply failed")
        self.active = dict(entries)
        self.events.append(("apply", dict(entries)))
        return previous

    def restore(self, state):
        self.active = dict(state.entries)
        self.events.append(("restore", dict(self.active)))

    def commit(self, previous):
        self.events.append(("commit", dict(self.active)))


class UserDictionaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.voiceger_root = self.root / "voiceger"
        self.voiceger_root.mkdir()
        self.data_dir = self.root / "adapter-state"
        self.backend = FakeBackend()
        self.core = UserDictionaryCore(
            self.voiceger_root,
            data_directory=self.data_dir,
            openjtalk_dictionary=self.backend,
        )

    def tearDown(self):
        self.temp.cleanup()

    def add_word(self, **kwargs):
        values = {
            "surface": "ずんだもん",
            "pronunciation": "ズンダモン",
            "accent_type": 3,
        }
        values.update(kwargs)
        return self.core.add_japanese_word(**values)

    def test_create_list_update_delete_and_defaults(self):
        word_uuid = self.add_word()
        listed = self.core.list_japanese_entries()
        word = listed[word_uuid]
        self.assertEqual(word.surface, "ずんだもん")
        self.assertEqual(word.priority, 5)
        self.assertEqual(word.context_id, 1348)
        self.assertEqual(word.part_of_speech, "名詞")
        self.assertEqual(word.part_of_speech_detail_1, "固有名詞")
        self.assertEqual(word.inflectional_type, "*")
        self.assertEqual(word.inflectional_form, "*")
        self.assertEqual(word.stem, "*")
        self.assertEqual(word.accent_associative_rule, "*")
        self.assertEqual(word.mora_count, 5)

        self.core.update_japanese_word(
            word_uuid,
            surface="ずんだもん",
            pronunciation="ズンダモン",
            accent_type=1,
        )
        updated = self.core.list_japanese_entries()[word_uuid]
        self.assertEqual(updated.accent_type, 1)
        self.assertEqual(updated.priority, 5)
        self.assertEqual(updated.context_id, 1348)

        self.core.delete_japanese_word(word_uuid)
        self.assertEqual(self.core.list_japanese_entries(), {})

    def test_canonical_json_shape_has_no_word_type(self):
        self.add_word()
        stored = json.loads(self.core.japanese_path.read_text(encoding="utf-8"))
        word = next(iter(stored.values()))
        self.assertEqual(
            set(word),
            {
                "surface",
                "priority",
                "context_id",
                "part_of_speech",
                "part_of_speech_detail_1",
                "part_of_speech_detail_2",
                "part_of_speech_detail_3",
                "inflectional_type",
                "inflectional_form",
                "stem",
                "yomi",
                "pronunciation",
                "accent_type",
                "mora_count",
                "accent_associative_rule",
            },
        )

    def test_all_supported_word_types_and_voicevox_cost_candidates(self):
        for word_type, data in WORD_TYPE_DATA.items():
            with self.subTest(word_type=word_type):
                word_uuid = self.add_word(
                    surface="語彙" + str(len(self.core.list_japanese_entries())),
                    word_type=JapaneseWordType(word_type),
                    priority=0,
                )
                word = self.core.list_japanese_entries()[word_uuid]
                self.assertEqual(word.context_id, data.context_id)
                self.assertEqual(word.part_of_speech, data.part_of_speech)
                self.assertEqual(
                    word.part_of_speech_detail_1,
                    data.part_of_speech_detail_1,
                )
                self.assertEqual(priority_to_cost(data.context_id, 0), data.cost_candidates[10])
                self.assertEqual(priority_to_cost(data.context_id, 10), data.cost_candidates[0])

    def test_default_word_type_priority_and_surface_normalization(self):
        word_uuid = self.add_word(surface="ABC!", priority=10)
        word = self.core.list_japanese_entries()[word_uuid]
        self.assertEqual(word.surface, "ＡＢＣ！")
        self.assertEqual(word.context_id, 1348)
        self.assertEqual(word.priority, 10)
        self.assertEqual(normalize_surface("A!~"), "Ａ！～")

    def test_invalid_japanese_fields_are_rejected(self):
        bad_cases = (
            {"pronunciation": "ズンだ"},
            {"pronunciation": "カャ"},
            {"pronunciation": "ヮカ"},
            {"accent_type": 6},
            {"priority": 11},
            {"priority": -1},
            {"word_type": "ADVERB"},
            {"surface": "line\nbreak"},
            {"pronunciation": "ズン,ダ"},
        )
        for values in bad_cases:
            with self.subTest(values=values):
                with self.assertRaises(UserDictionaryInputError):
                    self.add_word(**values)
        self.assertEqual(self.core.list_japanese_entries(), {})

    def test_import_respects_override_and_voicevox_shape(self):
        existing_uuid = self.add_word(surface="既存", pronunciation="キソン", accent_type=2)
        incoming = UserDictWord.model_validate(
            {
                "surface": "全角Ａ",
                "priority": 4,
                "context_id": 1348,
                "part_of_speech": "名詞",
                "part_of_speech_detail_1": "固有名詞",
                "part_of_speech_detail_2": "一般",
                "part_of_speech_detail_3": "*",
                "inflectional_type": "*",
                "inflectional_form": "*",
                "stem": "*",
                "yomi": "アメ",
                "pronunciation": "アメ",
                "accent_type": 1,
                "mora_count": 2,
                "accent_associative_rule": "*",
            }
        )
        self.core.import_japanese({existing_uuid: incoming}, override=False)
        self.assertEqual(
            self.core.list_japanese_entries()[existing_uuid].surface,
            "既存",
        )
        self.core.import_japanese({existing_uuid: incoming}, override=True)
        imported = self.core.list_japanese_entries()[existing_uuid]
        self.assertEqual(imported.surface, "全角Ａ")
        self.assertEqual(imported.priority, 4)

    def test_import_rejects_bad_uuid_pos_and_adapter_fields(self):
        entry = UserDictWord.model_validate(
            {
                "surface": "語",
                "priority": 5,
                "context_id": 1348,
                "part_of_speech": "名詞",
                "part_of_speech_detail_1": "固有名詞",
                "part_of_speech_detail_2": "一般",
                "part_of_speech_detail_3": "*",
                "inflectional_type": "*",
                "inflectional_form": "*",
                "stem": "*",
                "yomi": "ゴ",
                "pronunciation": "ゴ",
                "accent_type": 1,
                "accent_associative_rule": "*",
            }
        )
        with self.assertRaises(UserDictionaryInputError):
            self.core.import_japanese({"bad-uuid": entry})
        bad_pos = entry.model_copy(update={"context_id": 1345})
        with self.assertRaises(UserDictionaryInputError):
            self.core.import_japanese({"ee6e615d-a37a-4d0e-b1c2-55f514f8f47d": bad_pos})
        with self.assertRaises(Exception):
            UserDictWord.model_validate({**entry.model_dump(), "word_type": "PROPER_NOUN"})

    def test_missing_and_malformed_uuid_operations_fail_deterministically(self):
        for invalid in ("not-a-uuid", "00000000-0000-0000-0000-000000000001"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(UserDictionaryInputError):
                    self.core.delete_japanese_word(invalid)
        with self.assertRaisesRegex(UserDictionaryInputError, "invalid word UUID"):
            self.core.update_japanese_word(
                "bad",
                surface="語",
                pronunciation="ゴ",
                accent_type=1,
            )

    def test_persistence_round_trip_and_voiceger_is_read_only(self):
        word_uuid = self.add_word(surface="ＡＢＣ", pronunciation="エービーシー", accent_type=0)
        reloaded = UserDictionaryCore(
            self.voiceger_root,
            data_directory=self.data_dir,
            openjtalk_dictionary=FakeBackend(),
        )
        self.assertEqual(reloaded.list_japanese_entries()[word_uuid].surface, "ＡＢＣ")
        self.assertEqual(self.core.japanese_path.parent, self.data_dir.resolve())
        self.assertFalse((self.voiceger_root / "user_dict.json").exists())

    def test_default_files_are_next_to_settings_and_voiceger_path_is_rejected(self):
        config_path = self.root / "platform-config" / "config.json"
        with patch(
            "voiceger_accent_adapter.user_dictionary.default_config_path",
            return_value=config_path,
        ):
            default_core = UserDictionaryCore(self.voiceger_root)
        self.assertEqual(default_core.japanese_path, config_path.with_name("user_dict.json"))
        self.assertEqual(
            default_core.english_path,
            config_path.with_name("english_user_dict.json"),
        )
        with self.assertRaisesRegex(ValueError, "outside Voiceger"):
            UserDictionaryCore(
                self.voiceger_root,
                data_directory=self.voiceger_root / "adapter-state",
                openjtalk_dictionary=FakeBackend(),
            )

    def test_failed_compile_and_apply_leave_previous_state_and_file(self):
        first_uuid = self.add_word(surface="一語", pronunciation="イチゴ", accent_type=2)
        old_file = self.core.japanese_path.read_bytes()
        old_active = dict(self.backend.active)

        self.backend.fail_compile = True
        with self.assertRaises(OpenJTalkDictionaryError):
            self.add_word(surface="二語", pronunciation="ニゴ", accent_type=2)
        self.assertEqual(self.core.japanese_path.read_bytes(), old_file)
        self.assertEqual(self.backend.active, old_active)

        self.backend.fail_apply = True
        with self.assertRaises(OpenJTalkDictionaryError):
            self.add_word(surface="三語", pronunciation="サンゴ", accent_type=2)
        self.assertEqual(self.core.japanese_path.read_bytes(), old_file)
        self.assertEqual(self.backend.active, old_active)
        self.assertIn(first_uuid, self.core.list_japanese_entries())

    def test_failed_persistence_restores_active_dictionary(self):
        word_uuid = self.add_word(surface="一語", pronunciation="イチゴ", accent_type=2)
        old_file = self.core.japanese_path.read_bytes()
        old_active = dict(self.backend.active)
        with patch(
            "voiceger_accent_adapter.user_dictionary._atomic_write",
            side_effect=OSError("disk full"),
        ):
            with self.assertRaisesRegex(Exception, "could not be persisted"):
                self.core.update_japanese_word(
                    word_uuid,
                    surface="二語",
                    pronunciation="ニゴ",
                    accent_type=2,
                )
        self.assertEqual(self.core.japanese_path.read_bytes(), old_file)
        self.assertEqual(self.backend.active, old_active)

    def test_failed_persistence_restores_merged_state_after_voiceger_replaces_global(self):
        word_uuid = self.add_word(surface="一語", pronunciation="イチゴ", accent_type=2)
        old_file = self.core.japanese_path.read_bytes()
        old_active = dict(self.core.list_japanese_entries())
        self.backend.active = {"voiceger": "replaced global manager"}

        with patch(
            "voiceger_accent_adapter.user_dictionary._atomic_write",
            side_effect=OSError("disk full"),
        ):
            with self.assertRaisesRegex(Exception, "could not be persisted"):
                self.core.update_japanese_word(
                    word_uuid,
                    surface="二語",
                    pronunciation="ニゴ",
                    accent_type=2,
                )

        self.assertEqual(self.core.japanese_path.read_bytes(), old_file)
        self.assertEqual(self.backend.active, old_active)
        self.assertIn(word_uuid, self.core.list_japanese_entries())
        ensure_events = [event for event in self.backend.events if event[0] == "ensure"]
        self.assertTrue(ensure_events[-1][2])

    def test_voiceger_runtime_transition_and_mutation_do_not_deadlock(self):
        entered = Event()
        mutation_started = Event()
        release = Event()
        errors = []

        def runtime_transition():
            try:
                with self.core.voiceger_japanese_runtime_transition():
                    entered.set()
                    if not release.wait(2):
                        raise AssertionError("runtime transition release timed out")
            except BaseException as exc:
                errors.append(exc)

        def mutate():
            try:
                if not entered.wait(2):
                    raise AssertionError("runtime transition did not start")
                mutation_started.set()
                self.add_word(
                    surface="並行更新",
                    pronunciation="ヘイコウコウシン",
                    accent_type=0,
                )
            except BaseException as exc:
                errors.append(exc)

        runtime_thread = Thread(target=runtime_transition)
        mutation_thread = Thread(target=mutate)
        runtime_thread.start()
        mutation_thread.start()
        self.assertTrue(entered.wait(2))
        self.assertTrue(mutation_started.wait(2))
        release.set()
        runtime_thread.join(2)
        mutation_thread.join(2)

        self.assertFalse(runtime_thread.is_alive())
        self.assertFalse(mutation_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.backend.active, self.core.list_japanese_entries())

    def test_mutation_activates_candidate_for_subsequent_queries(self):
        word_uuid = self.add_word(surface="新語", pronunciation="シンゴ", accent_type=2)
        self.core.ensure_japanese_active()
        self.assertEqual(self.backend.active, self.core.list_japanese_entries())
        self.assertIn(word_uuid, self.backend.active)

    def test_voiceger_csv_is_preserved_and_adapter_collision_wins(self):
        dictionary_dir = (
            self.voiceger_root
            / "GPT-SoVITS"
            / "GPT_SoVITS"
            / "text"
            / "ja_userdic"
        )
        dictionary_dir.mkdir(parents=True)
        source = dictionary_dir / "userdict.csv"
        source.write_text(
            "abc,1348,1348,10,名詞,固有名詞,一般,*,*,*,*,エービーシー,エービーシー,0/6,*\n"
            "既存語,1348,1348,20,名詞,固有名詞,一般,*,*,*,*,キソンゴ,キソンゴ,1/4,*\n",
            encoding="utf-8",
        )
        before = source.read_bytes()
        word_uuid = self.add_word(surface="abc", pronunciation="アブク", accent_type=2)
        word = self.core.list_japanese_entries()[word_uuid]
        renderer = OpenJTalkDictionary(self.voiceger_root)
        merged = renderer._merged_csv({word_uuid: word})
        self.assertIn("既存語,1348,1348", merged)
        self.assertNotIn(",エービーシー,エービーシー,", merged)
        self.assertIn("ａｂｃ,1348,1348", merged)
        self.assertIn("アブク,アブク,2/3,*", merged)
        self.assertEqual(source.read_bytes(), before)

    def test_priority_csv_uses_voicevox_cost_and_shape(self):
        word_uuid = self.add_word(priority=5)
        word = self.core.list_japanese_entries()[word_uuid]
        row = render_word_csv(word).rstrip("\n").split(",")
        self.assertEqual(row[1:4], ["1348", "1348", str(WORD_TYPE_DATA["PROPER_NOUN"].cost_candidates[5])])
        self.assertEqual(row[13], "3/5")

    def test_openjtalk_compile_apply_uses_shared_lock_and_restores_on_failure(self):
        class FakePyOpenJTalk:
            def __init__(self):
                self._global_jtalk = object()
                self.previous = self._global_jtalk
                self.calls = []

            def mecab_dict_index(self, source, target):
                self.assert_lock()
                Path(target).write_bytes(b"compiled")

            def update_global_jtalk_with_user_dict(self, path):
                self.assert_lock()
                self.calls.append(path)
                self._global_jtalk = object()
                if len(self.calls) == 1:
                    raise RuntimeError("native apply failed")

            @staticmethod
            def assert_lock():
                if not OPENJTALK_LOCK._is_owned():
                    raise AssertionError("OpenJTalk operation was not locked")

        engine = FakePyOpenJTalk()
        manager = engine._global_jtalk
        backend = OpenJTalkDictionary(self.voiceger_root, pyopenjtalk_module=engine)
        word_uuid = self.add_word(surface="声", pronunciation="コエ", accent_type=1)
        word = self.core.list_japanese_entries()[word_uuid]
        # Use the real compiler/application boundary in a fresh backend; the
        # injected core backend above is deliberately not involved here.
        with patch.object(openjtalk_dictionary, "_ACTIVE_COMPILATION", None), patch.object(
            openjtalk_dictionary, "_ACTIVE_SIGNATURE", None
        ), patch.object(
            openjtalk_dictionary, "_ACTIVE_MANAGER", None
        ), patch.object(openjtalk_dictionary, "_BASELINE_JTALK_MANAGER", manager):
            with self.assertRaises(OpenJTalkDictionaryError):
                backend.activate_entries({word_uuid: word})
        self.assertIs(engine._global_jtalk, manager)
        self.assertEqual(len(engine.calls), 1)

    def test_force_reapply_failure_restores_last_known_good_manager(self):
        class FakePyOpenJTalk:
            def __init__(self):
                self._global_jtalk = object()
                self.fail_update = False

            def mecab_dict_index(self, source, target):
                Path(target).write_bytes(b"compiled")

            def update_global_jtalk_with_user_dict(self, _path):
                if self.fail_update:
                    raise RuntimeError("runtime reapply failed")
                self._global_jtalk = object()

        engine = FakePyOpenJTalk()
        backend = OpenJTalkDictionary(self.voiceger_root, pyopenjtalk_module=engine)
        word_uuid = self.add_word(surface="再適用", pronunciation="サイテキヨウ", accent_type=0)
        word = self.core.list_japanese_entries()[word_uuid]
        with patch.object(openjtalk_dictionary, "_ACTIVE_COMPILATION", None), patch.object(
            openjtalk_dictionary, "_ACTIVE_SIGNATURE", None
        ), patch.object(openjtalk_dictionary, "_ACTIVE_MANAGER", None), patch.object(
            openjtalk_dictionary, "_BASELINE_JTALK_MANAGER", None
        ):
            compiled = backend.ensure_active({word_uuid: word})
            last_known_good = engine._global_jtalk
            engine._global_jtalk = object()  # Voiceger overwrote the global manager.
            engine.fail_update = True
            with self.assertRaises(OpenJTalkDictionaryError):
                backend.ensure_active({word_uuid: word}, force=True)
            self.assertIs(engine._global_jtalk, last_known_good)
            self.assertIs(openjtalk_dictionary._ACTIVE_COMPILATION, compiled)
            compiled.close()

    def test_english_persistence_lookup_and_validation(self):
        entry = self.core.set_english_entry(
            "Voiceger",
            ["V", "OY1", "AH0", "JH", "ER0"],
        )
        self.assertEqual(entry.phonemes, ["V", "OY1", "AH0", "JH", "ER0"])
        self.assertEqual(
            self.core.lookup_english_entry("  vOiCeGeR "),
            ["V", "OY1", "AH0", "JH", "ER0"],
        )
        reloaded = UserDictionaryCore(
            self.voiceger_root,
            data_directory=self.data_dir,
            openjtalk_dictionary=FakeBackend(),
        )
        self.assertEqual(len(reloaded.list_english_entries()), 1)
        self.assertIsNone(reloaded.lookup_english_entry("unknown"))
        with self.assertRaises(UserDictionaryInputError):
            self.core.set_english_entry("bad", ["NOT_A_PHONE"])
        with self.assertRaises(UserDictionaryInputError):
            self.core.set_english_entry(" ", ["HH", "AH1"])
        with self.assertRaises(UserDictionaryInputError):
            self.core.set_english_entry("bad\nword", ["HH", "AH1"])
        self.core.delete_english_entry("VOICEGER")
        self.assertEqual(self.core.list_english_entries(), {})


if __name__ == "__main__":
    unittest.main()
