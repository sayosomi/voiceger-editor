import unittest

from voiceger_accent_adapter.openjtalk_converter import (
    OpenJTalkConversionError,
    frontend_features_to_pronunciation,
    text_to_pronunciation_string,
)
from voiceger_accent_adapter.runtime_locks import OPENJTALK_LOCK


def node(
    pron,
    *,
    acc,
    mora_size,
    chain_flag=-1,
    string=None,
    pos="名詞",
):
    return {
        "string": string or pron,
        "pos": pos,
        "pron": pron,
        "acc": acc,
        "mora_size": mora_size,
        "chain_flag": chain_flag,
    }


class OpenJTalkConverterTests(unittest.TestCase):
    def test_rain(self):
        features = [node("アメ", acc=1, mora_size=2)]
        self.assertEqual(
            text_to_pronunciation_string(
                "雨", run_frontend=lambda _: features
            ),
            "ア'メ",
        )

    def test_heiban_is_canonicalized_to_final_accent_position(self):
        features = [node("アメ", acc=0, mora_size=2)]
        self.assertEqual(
            text_to_pronunciation_string(
                "飴", run_frontend=lambda _: features
            ),
            "アメ'",
        )

    def test_chain_flag_joins_nodes_into_one_accent_phrase(self):
        features = [
            node("キョー", acc=2, mora_size=2),
            node("ワ", acc=0, mora_size=1, chain_flag=1),
            node("アメ", acc=1, mora_size=2, chain_flag=-1),
            node("デスネ", acc=0, mora_size=3, chain_flag=1),
            node("。", acc=0, mora_size=0, string="。", pos="記号"),
        ]
        value = frontend_features_to_pronunciation(features)

        self.assertEqual(len(value.phrases), 2)
        self.assertEqual(value.phrases[0].morae, ("キョ", "ー", "ワ"))
        self.assertEqual(value.phrases[0].accent, 2)
        self.assertEqual(value.phrases[1].morae, ("ア", "メ", "デ", "ス", "ネ"))
        self.assertEqual(value.phrases[1].accent, 1)
        self.assertEqual(value.terminator, "。")

    def test_question_mark_is_normalized(self):
        features = [
            node("アメ", acc=0, mora_size=2),
            node("？", acc=0, mora_size=0, string="？", pos="記号"),
        ]
        self.assertEqual(
            text_to_pronunciation_string(
                "飴？", run_frontend=lambda _: features
            ),
            "アメ'？",
        )

    def test_sentence_terminators_are_normalized_independently(self):
        for symbol, expected in (
            ("。", "。"),
            (".", "。"),
            ("？", "？"),
            ("?", "？"),
            ("！", "！"),
            ("!", "！"),
        ):
            with self.subTest(symbol=symbol):
                features = [
                    node("アメ", acc=0, mora_size=2),
                    node(symbol, acc=0, mora_size=0, string=symbol, pos="記号"),
                ]
                value = frontend_features_to_pronunciation(features)
                self.assertEqual(value.terminator, expected)

        without_terminator = frontend_features_to_pronunciation(
            [node("アメ", acc=0, mora_size=2)]
        )
        self.assertIsNone(without_terminator.terminator)

    def test_digraph_counts_as_one_mora(self):
        features = [node("キャク", acc=1, mora_size=2)]
        self.assertEqual(
            text_to_pronunciation_string(
                "客", run_frontend=lambda _: features
            ),
            "キャ'ク",
        )

    def test_invalid_pronunciation_is_rejected(self):
        features = [node("*", acc=1, mora_size=1)]
        with self.assertRaises(OpenJTalkConversionError):
            frontend_features_to_pronunciation(features)

    def test_run_frontend_uses_shared_openjtalk_lock(self):
        def run_frontend(_):
            self.assertTrue(OPENJTALK_LOCK._is_owned())
            return [node("アメ", acc=1, mora_size=2)]

        value = text_to_pronunciation_string("雨", run_frontend=run_frontend)
        self.assertEqual(value, "ア'メ")


if __name__ == "__main__":
    unittest.main()
