"""Shared read-only TUI rendering fixtures and renderer test assertions."""

import unittest
from pathlib import Path
from types import SimpleNamespace

from voiceger_editor.settings import Settings
from voiceger_editor.tui_display import _display_width
from voiceger_editor.tui_editors import EnglishGroupingCache, EnglishWordGroup, PronunciationRow
from voiceger_editor.tui_rendering import TuiRenderer, TuiRenderState
from voiceger_editor.tui_status import EMPTY_STATUS
from voiceger_editor.voicevox_api_models import AccentPhrase, AudioQuery, Mora, VoicegerSegment


class FakeScreen:
    def __init__(self, rows=24, columns=80):
        self.rows = rows
        self.columns = columns
        self.drawn = []
        self.cursor = None

    def getmaxyx(self):
        return self.rows, self.columns

    def addnstr(self, row, column, value, count, attr=0):
        self.drawn.append((row, column, value[:count], attr))

    def move(self, row, column):
        self.cursor = (row, column)


class FakeSession:
    def __init__(self, candidates=()):
        self.caption = "明日はhello everyoneまた明日"
        self.query = AudioQuery(
            accent_phrases=[
                AccentPhrase(
                    moras=[
                        Mora(text=mora, vowel="a", vowel_length=0.1, pitch=0.0)
                        for mora in ("ア", "シ", "タ", "ワ")
                    ],
                    accent=4,
                ),
                AccentPhrase(
                    moras=[
                        Mora(text=mora, vowel="i", vowel_length=0.1, pitch=0.0)
                        for mora in ("イ", "イ", "テ", "ン", "キ")
                    ],
                    accent=3,
                ),
                AccentPhrase(
                    moras=[
                        Mora(text=mora, vowel="a", vowel_length=0.1, pitch=0.0)
                        for mora in ("マ", "タ", "ア", "シ", "タ")
                    ],
                    accent=3,
                ),
            ],
            voicegerSegments=[
                VoicegerSegment(
                    language="ja",
                    text="明日は",
                    accentPhraseStart=0,
                    accentPhraseCount=2,
                ),
                VoicegerSegment(
                    language="en",
                    text="hello everyone",
                    phonemes=[
                        "HH", "AH1", "L", "OW0", "EH1", "V", "R", "IY0",
                        "W", "AH0", "N",
                    ],
                ),
                VoicegerSegment(
                    language="ja",
                    text="また明日",
                    accentPhraseStart=2,
                    accentPhraseCount=1,
                ),
            ],
        )
        self.candidates = tuple(candidates)
        self.has_active_batch = bool(candidates)


def candidate(number):
    return SimpleNamespace(number=number, frame_count=320, sampling_rate=32000)


def rows_for(session=None):
    grouping = EnglishGroupingCache(
        "hello everyone",
        (
            EnglishWordGroup("hello", ("HH", "AH1", "L", "OW0"), True),
            EnglishWordGroup("everyone", ("EH1", "V", "R", "IY0", "W", "AH0", "N"), True),
        ),
    )
    return (
        PronunciationRow(
            "ja", "明日は", 0, 0, True, phrase_index=0,
            phrase_index_in_segment=0, moras=("ア", "シ", "タ", "ワ"), accent=4,
        ),
        PronunciationRow(
            "ja", "明日は", 0, 0, False, phrase_index=1,
            phrase_index_in_segment=1, moras=("イ", "イ", "テ", "ン", "キ"), accent=3,
        ),
        PronunciationRow(
            "en", "hello everyone", 1, 1, True, group_index=0,
            word="hello", phonemes=grouping.groups[0].phonemes,
            word_column_width=8, grouping=grouping,
        ),
        PronunciationRow(
            "en", "hello everyone", 1, 1, False, group_index=1,
            word="everyone", phonemes=grouping.groups[1].phonemes,
            vowel_offset=2, word_column_width=8, grouping=grouping,
        ),
        PronunciationRow(
            "ja", "また明日", 2, 2, True, phrase_index=2,
            phrase_index_in_segment=0, moras=("マ", "タ", "ア", "シ", "タ"), accent=3,
        ),
    )


def render_state(
    *,
    session=None,
    settings=None,
    focus_key=("settings_summary", None),
    status=EMPTY_STATUS,
    segments=(
        ("ja", "明日は", 0),
        ("en", "hello everyone", 1),
        ("ja", "また明日", 2),
    ),
    pronunciation_rows=None,
    busy=False,
    worker_operation=None,
    worker_target=None,
    operation_completed=0,
    operation_total=0,
    pressed_adjustment=None,
    editor=None,
    accepted_take_number=None,
    batch_item_position=None,
    output_path_edit=None,
    batch_item_number_jump_active=False,
    batch_item_number_jump_value="",
):
    return TuiRenderState(
        voiceger_root=Path("/nonexistent/voiceger"),
        settings=settings or Settings(),
        session=session,
        focus_key=focus_key,
        status=status,
        segments=segments if session is not None else (),
        pronunciation_rows=(
            pronunciation_rows if pronunciation_rows is not None
            else rows_for(session) if session is not None else ()
        ),
        busy=busy,
        worker_operation=worker_operation,
        worker_target=worker_target,
        operation_completed=operation_completed,
        operation_total=operation_total,
        pressed_adjustment=pressed_adjustment,
        editor=editor,
        accepted_take_number=accepted_take_number,
        batch_item_position=batch_item_position,
        output_path_edit=output_path_edit,
        batch_item_number_jump_active=batch_item_number_jump_active,
        batch_item_number_jump_value=batch_item_number_jump_value,
    )


class RenderingTestCase(unittest.TestCase):
    def setUp(self):
        self.renderer = TuiRenderer()

    @staticmethod
    def rendered(screen):
        return "\n".join(text for _row, _column, text, _attr in screen.drawn)

    @staticmethod
    def labels(rows):
        return [line.text for line in rows]

    def assert_inactive_draft_wrapping(self, editor, draft, width, marker):
        document, _cursor_line, _cursor_column = self.renderer.editor_document(
            render_state(editor=editor), width
        )
        draft_lines = [(line, key) for line, key in document if key == "draft"]

        self.assertGreater(len(draft_lines), 1)
        self.assertTrue(draft_lines[0][0].startswith(marker))
        self.assertEqual(
            "".join(line[len(marker):] for line, _key in draft_lines),
            draft,
        )
        self.assertTrue(all(key == "draft" for _line, key in draft_lines))
        self.assertTrue(
            all(
                line.startswith(" " * _display_width(marker))
                for line, _key in draft_lines[1:]
            )
        )
        self.assertTrue(
            all(_display_width(line) <= width - 1 for line, _key in draft_lines)
        )
        self.assertEqual(editor.payload["draft"], draft)
        return [line for line, _key in draft_lines]
