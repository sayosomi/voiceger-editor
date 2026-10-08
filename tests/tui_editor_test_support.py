"""Shared data and controller harness for focused TUI editor regression suites."""

from pathlib import Path
import unittest

from voiceger_editor.settings import Settings
from voiceger_editor.tui_editors import TuiEditorController
from voiceger_editor.tui_rendering import _active_input_prefix
from voiceger_editor.voicevox_api_models import AccentPhrase, AudioQuery, Mora, VoicegerSegment


def _phrase(morae, accent):
    return AccentPhrase(
        moras=[
            Mora(text=mora, vowel="a", vowel_length=0.1, pitch=0.0)
            for mora in morae
        ],
        accent=accent,
    )


def mixed_query():
    return AudioQuery(
        accent_phrases=[
            _phrase(("ア", "シ", "タ", "ワ"), 4),
            _phrase(("キョ", "ウ"), 1),
        ],
        voicegerSegments=[
            VoicegerSegment(
                language="ja",
                text="明日は今日",
                accentPhraseStart=0,
                accentPhraseCount=2,
                pronunciationTerminator="？",
            ),
            VoicegerSegment(
                language="en",
                text="hello everyone",
                phonemes=["HH", "AH1", "L", "OW2", "EH1", "V", "R", "IY0"],
            ),
        ],
    )


def direct_japanese_query():
    return AudioQuery(
        accent_phrases=[_phrase(("ナ",), 1), _phrase(("ノ", "ダ"), 2)],
        voicegerSegments=[
            VoicegerSegment(
                language="ja",
                text="なのだ。",
                accentPhraseStart=0,
                accentPhraseCount=2,
                pronunciationTerminator="。",
            ),
            VoicegerSegment(
                language="en",
                text="hello",
                phonemes=["HH", "AH1"],
            ),
        ],
    )


def segments(query):
    return [
        (item.language, item.text, index)
        for index, item in enumerate(query.voicegerSegments or [])
    ]


class GroupProvider:
    def __init__(self, groups):
        self.groups = groups
        self.calls = []

    def __call__(self, source):
        self.calls.append(source)
        return self.groups[source]


class EditorControllerTestCase(unittest.TestCase):
    def make_controller(self, groups=None, styles=()):
        provider = GroupProvider(groups or {})
        controller = TuiEditorController(
            english_word_groups=provider,
            available_styles=lambda: styles,
            input_prefix=_active_input_prefix,
        )
        return controller, provider

    @staticmethod
    def settings():
        return Settings(output_dir=Path("/tmp/voiceger-editor-tests"))
