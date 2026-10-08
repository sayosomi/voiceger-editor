"""Focused contracts for mixed Voiceger override, hook, and capture owners."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from voiceger_editor.mixed_lab_capture import MixedLabCapture
from voiceger_editor.mixed_pronunciation_overrides import (
    MixedPronunciationOverrides,
)
from voiceger_editor.mixed_runtime_hooks import scoped_mixed_runtime_hooks


def runtime():
    japanese = SimpleNamespace(
        text_normalize=lambda text: text,
        g2p=lambda text, with_prosody=True: ["NATIVE", text],
    )
    english = SimpleNamespace(text_normalize=lambda text: text)
    inference = SimpleNamespace(
        clean_text_inf=lambda value, language, version: (
            [value], None, value
        ),
        cleaned_text_to_sequence=lambda phones, version: list(phones),
    )
    return japanese, english, inference


class MixedPronunciationOverridesTests(unittest.TestCase):
    def test_japanese_duplicate_canonical_queue_and_fallback(self):
        japanese, english, inference = runtime()
        overrides = MixedPronunciationOverrides(
            japanese=japanese,
            english=english,
            inference_webui=inference,
            japanese_overrides=[
                ("雨", ["FIRST"]),
                ("雨。", ["SECOND"]),
            ],
            english_overrides=None,
        )
        self.assertEqual(overrides.japanese_g2p("雨。"), ["FIRST"])
        self.assertEqual(overrides.japanese_g2p("雨"), ["SECOND"])
        self.assertEqual(overrides.remaining_japanese, 0)
        self.assertEqual(
            overrides.japanese_g2p("雨", with_prosody=False),
            ["NATIVE", "雨"],
        )

    def test_english_exact_match_consumption_and_native_fallback(self):
        japanese, english, inference = runtime()
        overrides = MixedPronunciationOverrides(
            japanese=japanese,
            english=english,
            inference_webui=inference,
            japanese_overrides=[],
            english_overrides=[
                ("hello", ["HH", "AH0"]),
                ("hello", ["HH", "EH1"]),
            ],
        )
        self.assertEqual(
            overrides.clean_text_inf("hello!", "en", "v2"),
            (["HH", "AH0"], None, "hello!"),
        )
        self.assertEqual(overrides.remaining_english, 1)
        self.assertEqual(
            overrides.clean_text_inf("hello", "ja", "v2"),
            (["hello"], None, "hello"),
        )


class MixedRuntimeHooksTests(unittest.TestCase):
    def test_restores_both_hooks_after_synthesis_exception(self):
        japanese, english, inference = runtime()
        original_japanese = japanese.g2p
        original_clean = inference.clean_text_inf
        overrides = MixedPronunciationOverrides(
            japanese=japanese,
            english=english,
            inference_webui=inference,
            japanese_overrides=[("雨", ["CUSTOM"])],
            english_overrides=[("hi", ["HH", "AY1"])],
        )
        with self.assertRaisesRegex(RuntimeError, "synthesis failed"):
            with scoped_mixed_runtime_hooks(
                japanese=japanese,
                inference_webui=inference,
                overrides=overrides,
                capture=MixedLabCapture(inference, None),
            ):
                self.assertEqual(japanese.g2p("雨"), ["CUSTOM"])
                self.assertEqual(
                    inference.clean_text_inf("hi", "en", "v2")[0],
                    ["HH", "AY1"],
                )
                raise RuntimeError("synthesis failed")
        self.assertIs(japanese.g2p, original_japanese)
        self.assertIs(inference.clean_text_inf, original_clean)


class FakeTensor:
    def __init__(self, values):
        self.values = values

    def detach(self):
        return self

    def cpu(self):
        return self

    def float(self):
        return self

    def reshape(self, *_shape):
        return self

    def tolist(self):
        return self.values

    def numpy(self):
        return np.asarray(self.values)


class MixedLabCaptureTests(unittest.TestCase):
    def test_preparation_failure_is_nonfatal_and_reports_existing_warning(self):
        _, _, inference = runtime()
        capture = MixedLabCapture(inference, object())
        with capture.installed_decode_hook():
            pass
        provenance, warning = capture.result([0])
        self.assertIsNone(provenance)
        self.assertTrue(warning.startswith("mixed LAB timing capture failed: "))

    def test_decode_capture_restores_inherited_method_and_validates_ids(self):
        class Model:
            def __init__(self):
                self.enc_p = SimpleNamespace(
                    mrte=SimpleNamespace(
                        cross_attention=SimpleNamespace(
                            attn=FakeTensor([[[[0.5]]]])
                        )
                    )
                )

            def decode(
                self, codes, text, refer, noise_scale=0.5, speed=1
            ):
                return SimpleNamespace(shape=(1, 200))

        model = Model()
        inference = SimpleNamespace(
            vq_model=model,
            version="v2",
            cleaned_text_to_sequence=lambda phones, version: [7],
            hps=SimpleNamespace(data=SimpleNamespace(sampling_rate=32000)),
        )
        spans = (object(),)
        sentinel = object()
        with patch(
            "voiceger_editor.lab_mixed_attention.build_mixed_lab_segment_spans",
            return_value=spans,
        ), patch(
            "voiceger_editor.lab_mixed_attention.voiceger_ids_for_spans",
            return_value=[7],
        ), patch(
            "voiceger_editor.lab_mixed_attention.derive_mixed_lab_provenance",
            return_value=sentinel,
        ):
            capture = MixedLabCapture(inference, object())
            with capture.installed_decode_hook():
                model.decode(None, FakeTensor([7]), None)
            self.assertNotIn("decode", model.__dict__)
            provenance, warning = capture.result([1, 2])
            self.assertIs(provenance, sentinel)
            self.assertIsNone(warning)

            mismatch = MixedLabCapture(inference, object())
            with mismatch.installed_decode_hook():
                model.decode(None, FakeTensor([8]), None)
            provenance, warning = mismatch.result([1, 2])
            self.assertIsNone(provenance)
            self.assertIn("target phone IDs do not match", warning)


if __name__ == "__main__":
    unittest.main()
