from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from voiceger_editor.batch_recipe import (
    BatchRecipeError,
    read_batch_recipe,
    serialize_batch_recipe,
    write_batch_recipe,
)
from voiceger_editor.caption_batch import CaptionBatch, CaptionBatchItem
from voiceger_editor.session import UtteranceSession
from voiceger_editor.settings import Settings
from voiceger_editor.styles import PRESET_PROMPT_TEXT
from voiceger_editor.voicevox_api_models import (
    AccentPhrase,
    AudioQuery,
    Mora,
    PronunciationPunctuation,
    VoicegerSegment,
)


class FakeAdapter:
    def __init__(self, voiceger_root: Path) -> None:
        self.voiceger_root = voiceger_root


def _mora(text: str, vowel: str = "a") -> Mora:
    return Mora(
        text=text,
        consonant=None,
        consonant_length=None,
        vowel=vowel,
        vowel_length=0,
        pitch=0,
    )


def _japanese_query(
    text: str = "ズンダ",
    *,
    accent: int = 2,
    punctuation: str = "。",
) -> AudioQuery:
    phrase = AccentPhrase(
        moras=[_mora(char) for char in text],
        accent=accent,
        pause_mora=None,
        is_interrogative=False,
    )
    return AudioQuery(
        accent_phrases=[phrase],
        speedScale=1,
        pitchScale=0,
        intonationScale=1,
        volumeScale=1,
        prePhonemeLength=0.1,
        postPhonemeLength=0.1,
        pauseLength=None,
        pauseLengthScale=1,
        outputSamplingRate=32000,
        outputStereo=False,
        kana=None,
        pronunciationPunctuation=[
            PronunciationPunctuation(
                afterAccentPhrase=0,
                mark=punctuation,
            )
        ],
    )


def _english_query(
    text: str = "hello",
    phonemes: list[str] | None = None,
) -> AudioQuery:
    return AudioQuery(
        accent_phrases=[],
        speedScale=1,
        pitchScale=0,
        intonationScale=1,
        volumeScale=1,
        prePhonemeLength=0.1,
        postPhonemeLength=0.1,
        pauseLength=None,
        pauseLengthScale=1,
        outputSamplingRate=32000,
        outputStereo=False,
        kana=None,
        voicegerSegments=[
            VoicegerSegment(
                language="en",
                text=text,
                phonemes=phonemes or ["HH", "EH1", "L", "OW0"],
            )
        ],
    )


def _mixed_query() -> AudioQuery:
    first_phrase = AccentPhrase(
        moras=[_mora("ズ"), _mora("ン"), _mora("ダ")],
        accent=2,
        pause_mora=None,
        is_interrogative=False,
    )
    second_phrase = AccentPhrase(
        moras=[_mora("ナ"), _mora("ノ"), _mora("ダ")],
        accent=2,
        pause_mora=None,
        is_interrogative=False,
    )
    return AudioQuery(
        accent_phrases=[first_phrase, second_phrase],
        speedScale=1,
        pitchScale=0,
        intonationScale=1,
        volumeScale=1,
        prePhonemeLength=0.1,
        postPhonemeLength=0.1,
        pauseLength=None,
        pauseLengthScale=1,
        outputSamplingRate=32000,
        outputStereo=False,
        kana=None,
        voicegerSegments=[
            VoicegerSegment(
                language="ja",
                text="ずんだは",
                accentPhraseStart=0,
                accentPhraseCount=1,
                pronunciationTerminator="",
                pronunciationPunctuation=[],
            ),
            VoicegerSegment(
                language="en",
                text="very sweet",
                phonemes=["V", "EH1", "R", "IY0", "S", "W", "IY1", "T"],
            ),
            VoicegerSegment(
                language="ja",
                text="なのだ",
                accentPhraseStart=1,
                accentPhraseCount=1,
                pronunciationTerminator="。",
                pronunciationPunctuation=[
                    PronunciationPunctuation(
                        afterAccentPhrase=0,
                        mark="。",
                    )
                ],
            ),
        ],
    )


class BatchRecipeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        reference_dir = self.root / "reference"
        reference_dir.mkdir()
        (reference_dir / "01_ref_emoNormal026.wav").write_bytes(b"neutral")
        (reference_dir / "02_ref_emoAma026.wav").write_bytes(b"sweet")
        self.adapter = FakeAdapter(self.root)
        self.runtime_settings = Settings(
            output_dir=self.root / "runtime-output",
            take_count=4,
            style_id=3,
            speed=1.0,
            top_k=20,
            top_p=1.0,
            temperature=1.0,
            save_text=True,
            save_lab=True,
        )

    def _session(
        self,
        *,
        caption: str,
        query: AudioQuery,
        style_id: int = 3,
        speed: float = 1.0,
        top_k: int = 20,
        top_p: float = 1.0,
        temperature: float = 1.0,
        pure_japanese_utterance_text: str | None = None,
    ) -> UtteranceSession:
        return UtteranceSession(
            adapter=self.adapter,
            caption=caption,
            query=query,
            settings=Settings(
                output_dir=self.root / "not-persisted",
                take_count=99,
                style_id=style_id,
                speed=speed,
                top_k=top_k,
                top_p=top_p,
                temperature=temperature,
                save_text=False,
                save_lab=False,
            ),
            pure_japanese_utterance_text=pure_japanese_utterance_text,
        )

    def _roundtrip_batch(self) -> CaptionBatch:
        japanese = CaptionBatchItem(
            self._session(
                caption="ずんだ。",
                query=_japanese_query(),
                speed=1.1,
                top_k=31,
                top_p=0.7,
                temperature=0.8,
                pure_japanese_utterance_text="ずんだ。",
            ),
            item_id="jp-id",
            take_count_override=None,
        )
        english = CaptionBatchItem(
            self._session(
                caption="hello",
                query=_english_query(),
                style_id=1,
                speed=0.9,
                top_k=17,
                top_p=0.6,
                temperature=0.5,
            ),
            item_id="en-id",
            included_for_generation=False,
            take_count_override=2,
        )
        mixed = CaptionBatchItem(
            self._session(
                caption="ずんだはvery sweetなのだ",
                query=_mixed_query(),
                speed=1.25,
                top_k=40,
                top_p=0.5,
                temperature=0.4,
            ),
            item_id="mixed-id",
            take_count_override=5,
        )
        return CaptionBatch(
            default_take_count=7,
            items=(japanese, english, mixed),
        )

    @staticmethod
    def _fake_mora_phones(
        text: str,
        previous_vowel: str | None,
    ) -> tuple[None, str]:
        return None, previous_vowel or "a"

    def test_write_read_round_trip_preserves_prepared_logical_recipe(self):
        batch = self._roundtrip_batch()
        target = self.root / "batch.voiceger.json"

        with patch(
            "voiceger_editor.voicevox_query._mora_phones",
            side_effect=self._fake_mora_phones,
        ):
            write_batch_recipe(target, batch)
            loaded = read_batch_recipe(
                target,
                adapter=self.adapter,
                runtime_settings=self.runtime_settings,
            )

        self.assertEqual(
            [item.item_id for item in loaded],
            ["jp-id", "en-id", "mixed-id"],
        )
        self.assertEqual(
            [item.included_for_generation for item in loaded],
            [True, False, True],
        )
        self.assertEqual(
            [item.take_count_override for item in loaded],
            [None, 2, 5],
        )
        self.assertEqual(loaded.default_take_count, 7)
        self.assertEqual(
            [loaded.effective_take_count(item) for item in loaded],
            [7, 2, 5],
        )
        self.assertEqual(
            [
                (
                    item.session.settings.style_id,
                    item.session.settings.speed,
                    item.session.settings.top_k,
                    item.session.settings.top_p,
                    item.session.settings.temperature,
                )
                for item in loaded
            ],
            [
                (3, 1.1, 31, 0.7, 0.8),
                (1, 0.9, 17, 0.6, 0.5),
                (3, 1.25, 40, 0.5, 0.4),
            ],
        )
        for item in loaded:
            self.assertTrue(item.session.is_prepared)
            self.assertFalse(item.session.has_active_batch)
            self.assertEqual(item.session.candidates, ())
            self.assertEqual(
                item.session.settings.output_dir,
                self.runtime_settings.output_dir,
            )
            self.assertTrue(item.session.settings.save_text)
            self.assertTrue(item.session.settings.save_lab)

        self.assertEqual(
            json.loads(serialize_batch_recipe(loaded)),
            json.loads(serialize_batch_recipe(batch)),
        )

    def test_write_uses_readable_japanese_and_excludes_runtime_preferences(self):
        batch = self._roundtrip_batch()
        serialized = serialize_batch_recipe(batch)

        self.assertIn("ずんだ", serialized)
        self.assertIn("ズン'ダ。", serialized)
        self.assertNotIn("\\u305a", serialized)
        for forbidden in (
            "output_dir",
            "save_text",
            "save_lab",
            "candidate",
            "accepted_take",
            "progress",
            "output_path",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_mixed_language_section_order_and_explicit_english_phonemes_round_trip(self):
        batch = self._roundtrip_batch()
        document = json.loads(serialize_batch_recipe(batch))
        sections = document["items"][2]["sections"]

        self.assertEqual(
            [section["language"] for section in sections],
            ["ja", "en", "ja"],
        )
        self.assertEqual(
            sections[1]["phonemes"],
            ["V", "EH1", "R", "IY0", "S", "W", "IY1", "T"],
        )

    def test_read_uses_saved_english_phonemes_without_g2p(self):
        batch = CaptionBatch(
            default_take_count=4,
            items=(
                CaptionBatchItem(
                    self._session(
                        caption="hello",
                        query=_english_query(
                            phonemes=["HH", "AH0", "L", "OW1"]
                        ),
                    ),
                    item_id="english",
                ),
            ),
        )
        target = self.root / "english.voiceger.json"
        write_batch_recipe(target, batch)

        loaded = read_batch_recipe(
            target,
            adapter=self.adapter,
            runtime_settings=self.runtime_settings,
        )

        self.assertEqual(
            loaded.items[0].session.query.voicegerSegments[0].phonemes,
            ["HH", "AH0", "L", "OW1"],
        )
        self.assertFalse(hasattr(self.adapter, "english_phonemes"))

    def test_write_rejects_unprepared_item(self):
        session = UtteranceSession.from_caption(
            adapter=self.adapter,
            caption="まだ",
            settings=self.runtime_settings,
        )
        batch = CaptionBatch(
            default_take_count=4,
            items=(CaptionBatchItem(session, item_id="unprepared"),),
        )

        with self.assertRaisesRegex(
            BatchRecipeError,
            "no prepared pronunciation",
        ):
            serialize_batch_recipe(batch)

    def _valid_document(self) -> dict:
        batch = self._roundtrip_batch()
        return json.loads(serialize_batch_recipe(batch))

    def _write_document(self, document: object, name: str = "input.voiceger.json") -> Path:
        path = self.root / name
        path.write_text(
            json.dumps(document, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_read_rejects_malformed_json(self):
        path = self.root / "bad.voiceger.json"
        path.write_text('{"schema_version": 1,', encoding="utf-8")

        with self.assertRaisesRegex(BatchRecipeError, "malformed JSON"):
            read_batch_recipe(
                path,
                adapter=self.adapter,
                runtime_settings=self.runtime_settings,
            )

    def test_read_rejects_duplicate_json_object_keys(self):
        path = self.root / "duplicate.voiceger.json"
        path.write_text(
            '{"schema_version":1,"schema_version":1,"take_count":4,"items":[]}',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            BatchRecipeError,
            "duplicate JSON object key",
        ):
            read_batch_recipe(
                path,
                adapter=self.adapter,
                runtime_settings=self.runtime_settings,
            )

    def test_read_rejects_unsupported_schema_version(self):
        document = self._valid_document()
        document["schema_version"] = 2
        path = self._write_document(document)

        with self.assertRaisesRegex(
            BatchRecipeError,
            "unsupported schema version",
        ):
            read_batch_recipe(
                path,
                adapter=self.adapter,
                runtime_settings=self.runtime_settings,
            )

    def test_read_rejects_duplicate_item_ids(self):
        document = self._valid_document()
        document["items"][1]["id"] = document["items"][0]["id"]
        path = self._write_document(document)

        with self.assertRaisesRegex(BatchRecipeError, "duplicate item id"):
            read_batch_recipe(
                path,
                adapter=self.adapter,
                runtime_settings=self.runtime_settings,
            )

    def test_read_rejects_invalid_take_counts(self):
        for field, value in (
            (("take_count",), 0),
            (("items", 0, "take_count"), True),
            (("items", 0, "take_count"), 101),
        ):
            with self.subTest(field=field, value=value):
                document = self._valid_document()
                target = document
                for key in field[:-1]:
                    target = target[key]
                target[field[-1]] = value
                path = self._write_document(
                    document,
                    name=f"take-{value}.voiceger.json",
                )
                with self.assertRaisesRegex(BatchRecipeError, "1 through 100"):
                    read_batch_recipe(
                        path,
                        adapter=self.adapter,
                        runtime_settings=self.runtime_settings,
                    )

    def test_read_rejects_invalid_japanese_pronunciation(self):
        document = self._valid_document()
        document["items"][0]["sections"][0]["pronunciation"] = "ズンダ"
        path = self._write_document(document)

        with self.assertRaisesRegex(
            BatchRecipeError,
            "accent phrase must contain exactly one accent marker",
        ):
            read_batch_recipe(
                path,
                adapter=self.adapter,
                runtime_settings=self.runtime_settings,
            )

    def test_read_rejects_invalid_english_phonemes(self):
        document = self._valid_document()
        document["items"][1]["sections"][0]["phonemes"] = ["NOPE9"]
        path = self._write_document(document)

        with self.assertRaisesRegex(
            BatchRecipeError,
            "unsupported English phoneme",
        ):
            read_batch_recipe(
                path,
                adapter=self.adapter,
                runtime_settings=self.runtime_settings,
            )

    def test_read_rejects_invalid_synthesis_settings(self):
        for field, value in (
            ("speed", 0),
            ("top_k", 0),
            ("top_p", 1.1),
            ("temperature", -0.1),
        ):
            with self.subTest(field=field):
                document = self._valid_document()
                document["items"][0]["synthesis"][field] = value
                path = self._write_document(
                    document,
                    name=f"setting-{field}.voiceger.json",
                )
                with self.assertRaises(BatchRecipeError):
                    read_batch_recipe(
                        path,
                        adapter=self.adapter,
                        runtime_settings=self.runtime_settings,
                    )

    def test_read_rejects_unavailable_style_reference(self):
        document = self._valid_document()
        document["items"][0]["synthesis"]["style"]["id"] = 75
        document["items"][0]["synthesis"]["style"]["name"] = "Exhausted"
        document["items"][0]["synthesis"]["style"][
            "reference_filename"
        ] = "07_ref_emoHero026.wav"
        path = self._write_document(document)

        with self.assertRaisesRegex(
            BatchRecipeError,
            "required style/reference is unavailable",
        ):
            read_batch_recipe(
                path,
                adapter=self.adapter,
                runtime_settings=self.runtime_settings,
            )

    def test_read_rejects_mismatched_style_reference_identity(self):
        document = self._valid_document()
        document["items"][0]["synthesis"]["style"][
            "reference_filename"
        ] = "different.wav"
        path = self._write_document(document)

        with self.assertRaisesRegex(
            BatchRecipeError,
            "style/reference identity does not match",
        ):
            read_batch_recipe(
                path,
                adapter=self.adapter,
                runtime_settings=self.runtime_settings,
            )

    def test_failed_read_does_not_mutate_existing_batch(self):
        existing = CaptionBatch(
            default_take_count=9,
            items=(
                CaptionBatchItem(
                    self._session(
                        caption="existing",
                        query=_english_query(text="existing"),
                    ),
                    item_id="existing-id",
                    included_for_generation=False,
                    take_count_override=6,
                ),
            ),
        )
        before = (
            existing.default_take_count,
            existing.items[0].item_id,
            existing.items[0].caption,
            existing.items[0].included_for_generation,
            existing.items[0].take_count_override,
        )
        document = self._valid_document()
        document["items"][0]["sections"][0]["pronunciation"] = "invalid"
        path = self._write_document(document)

        with self.assertRaises(BatchRecipeError):
            read_batch_recipe(
                path,
                adapter=self.adapter,
                runtime_settings=self.runtime_settings,
            )

        after = (
            existing.default_take_count,
            existing.items[0].item_id,
            existing.items[0].caption,
            existing.items[0].included_for_generation,
            existing.items[0].take_count_override,
        )
        self.assertEqual(after, before)

    def test_failed_atomic_write_preserves_existing_target_and_removes_temp_file(self):
        batch = self._roundtrip_batch()
        target = self.root / "atomic.voiceger.json"
        target.write_text("existing contents\n", encoding="utf-8")

        with patch(
            "voiceger_editor.batch_recipe.os.replace",
            side_effect=OSError("replace failed"),
        ):
            with self.assertRaisesRegex(BatchRecipeError, "replace failed"):
                write_batch_recipe(target, batch)

        self.assertEqual(
            target.read_text(encoding="utf-8"),
            "existing contents\n",
        )
        self.assertEqual(
            list(self.root.glob(f".{target.name}.*.tmp")),
            [],
        )

    def test_exact_schema_rejects_unknown_structural_fields(self):
        document = self._valid_document()
        document["items"][0]["runtime_state"] = {"progress": 1}
        path = self._write_document(document)

        with self.assertRaisesRegex(BatchRecipeError, "unknown field"):
            read_batch_recipe(
                path,
                adapter=self.adapter,
                runtime_settings=self.runtime_settings,
            )

    def test_style_payload_includes_reference_identity(self):
        document = self._valid_document()
        style = document["items"][0]["synthesis"]["style"]

        self.assertEqual(
            style,
            {
                "id": 3,
                "name": "Neutral",
                "reference_filename": "01_ref_emoNormal026.wav",
                "prompt_text": PRESET_PROMPT_TEXT,
            },
        )


if __name__ == "__main__":
    unittest.main()
