import curses
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from voiceger_editor.caption_batch import CaptionBatchItem
from voiceger_editor.settings import Settings
from voiceger_editor.tui import TuiApp
from voiceger_editor.voicevox_api_models import AccentPhrase, AudioQuery, Mora, VoicegerSegment


def english_query(phonemes, text="example"):
    return AudioQuery(
        accent_phrases=[],
        voicegerSegments=[
            VoicegerSegment(language="en", text=text, phonemes=list(phonemes))
        ],
    )


def mixed_query(english_phonemes=("HH", "AH1")):
    return AudioQuery(
        accent_phrases=[
            AccentPhrase(
                moras=[Mora(text="ア", vowel="a", vowel_length=0.1, pitch=0.0)],
                accent=1,
            )
        ],
        voicegerSegments=[
            VoicegerSegment(
                language="ja",
                text="雨",
                accentPhraseStart=0,
                accentPhraseCount=1,
            ),
            VoicegerSegment(
                language="en",
                text="hello",
                phonemes=list(english_phonemes),
            ),
        ],
    )


def japanese_query(*phrase_specs, source_text="なのだ。", terminator="。"):
    phrases = [
        AccentPhrase(
            moras=[
                Mora(text=mora, vowel="a", vowel_length=0.1, pitch=0.0)
                for mora in moras
            ],
            accent=accent,
        )
        for moras, accent in phrase_specs
    ]
    phrases.append(
        AccentPhrase(
            moras=[
                Mora(text=mora, vowel="a", vowel_length=0.1, pitch=0.0)
                for mora in ("ア", "メ")
            ],
            accent=2,
        )
    )
    return AudioQuery(
        accent_phrases=phrases,
        voicegerSegments=[
            VoicegerSegment(
                language="ja",
                text=source_text,
                accentPhraseStart=0,
                accentPhraseCount=len(phrase_specs),
                pronunciationTerminator=terminator,
            ),
            VoicegerSegment(
                language="en", text="hello", phonemes=["HH", "AH1"]
            ),
            VoicegerSegment(
                language="ja",
                text="雨",
                accentPhraseStart=len(phrase_specs),
                accentPhraseCount=1,
                pronunciationTerminator="？",
            ),
        ],
    )


def candidate(number):
    return SimpleNamespace(
        number=number,
        wav_path=Path(f"/tmp/take-{number}.wav"),
        sampling_rate=32000,
        frame_count=320,
        source_text="candidate source",
        style_name="Neutral",
    )


class FakeSession:
    def __init__(self, query=None, candidates=()):
        self.query = query or english_query(["AA1", "IY0", "ER1"])
        self.is_prepared = True
        self.caption = "example"
        self.settings = Settings()
        self._pure_japanese_utterance_text = "example"
        self.candidates = tuple(candidates)
        self.replace_query_calls = []
        self.replace_settings_calls = []
        self.replace_caption_calls = []
        self.build_calls = 0
        self.utterance_manually_edited = False
        self.rebuild_error = None
        self.discard_calls = 0
        self.close_calls = 0
        self.accept_calls = []
        self.accept_error = None
        self.generate_error = None

    @property
    def has_active_batch(self):
        return bool(self.candidates)

    @property
    def active_candidate_count(self):
        return len(self.candidates)

    @property
    def pure_japanese_utterance_text(self):
        if self.query.voicegerSegments is not None:
            return None
        return self._pure_japanese_utterance_text

    def replace_query(self, query, *, pure_japanese_utterance_text=None):
        self.replace_query_calls.append(query)
        self.query = query
        if query.voicegerSegments is None and pure_japanese_utterance_text is not None:
            self._pure_japanese_utterance_text = pure_japanese_utterance_text
        elif query.voicegerSegments is not None:
            self._pure_japanese_utterance_text = None
        self.utterance_manually_edited = True
        self.candidates = ()

    def replace_caption(self, caption):
        self.replace_caption_calls.append(caption)
        self.caption = caption

    def prepare_from_caption(self):
        self.build_calls += 1
        if self.rebuild_error is not None:
            raise self.rebuild_error
        self.is_prepared = True
        self.utterance_manually_edited = False
        self.candidates = ()

    def build_pronunciation_from_caption(self):
        self.prepare_from_caption()

    def generate_takes(self):
        if self.generate_error is not None:
            raise self.generate_error
        return iter(())

    def replace_settings(self, settings):
        self.replace_settings_calls.append(settings)
        if any(
            getattr(settings, name) != getattr(self.settings, name)
            for name in ("style_id", "speed", "top_k", "top_p", "temperature")
        ):
            self.candidates = ()
        self.settings = settings

    def discard_takes(self):
        self.discard_calls += 1
        self.candidates = ()

    def accept_take(self, number):
        self.accept_calls.append(number)
        if self.accept_error is not None:
            raise self.accept_error
        return SimpleNamespace(
            wav_path=Path(f"/tmp/accepted-{number}.wav"),
            text_path=None,
        )

    def close(self):
        self.close_calls += 1


class FakeScreen:
    def __init__(self, keys=(), rows=24, columns=80):
        self.keys = list(keys)
        self.rows = rows
        self.columns = columns
        self.drawn = []
        self.refresh_count = 0
        self.cursor = None
        self.timeouts = []

    def getmaxyx(self):
        return self.rows, self.columns

    def keypad(self, enabled):
        return None

    def timeout(self, milliseconds):
        self.timeouts.append(milliseconds)

    def addnstr(self, row, column, value, count, attr=0):
        self.drawn.append((row, column, value[:count], attr))

    def move(self, row, column):
        self.cursor = (row, column)

    def refresh(self):
        self.refresh_count += 1
        return None

    def erase(self):
        self.drawn.clear()
        self.cursor = None
        return None

    def get_wch(self):
        if not self.keys:
            raise curses.error("no more fake keys")
        return self.keys.pop(0)


def navigation_document(app, width):
    return [
        (line.text, line.key)
        for line in app._renderer.navigation_document(app._render_state(), width)
    ]


def set_navigation_focus(app, key, *, moved=False):
    app._dispatch_navigation_actions(
        app._navigation.set_focus_key(
            app._navigation_context(), key, moved=moved
        )
    )


def navigation_items(app):
    return list(app._navigation.navigation_items(app._navigation_context()))


def focus_candidate(app, number):
    app._dispatch_navigation_actions(
        app._navigation.focus_candidate(app._navigation_context(), number)
    )


def english_grouping(app, segment_index):
    return app._editor_controller.english_grouping(
        app.session.query,
        segment_index,
    )


def editor_document(app, width):
    return app._renderer.editor_document(app._render_state(), width)


class TuiAppTestCase(unittest.TestCase):
    @staticmethod
    def make_app(*, query=None, candidates=(), groups=None, batch_item=True):
        adapter = Mock()
        adapter.voiceger_root = Path("/nonexistent/voiceger")
        adapter.user_dictionary.list_japanese_entries.return_value = {}
        adapter.user_dictionary.list_english_entries.return_value = {}
        query = query or english_query(["AA1", "IY0", "ER1"])
        if groups is None:
            segment = next(
                item for item in (query.voicegerSegments or []) if item.language == "en"
            )
            groups = ((segment.text, tuple(segment.phonemes or ())),)
        adapter.english_word_phoneme_groups.return_value = groups
        app = TuiApp(adapter=adapter, settings=Settings())
        app.session = FakeSession(query=query, candidates=candidates)
        app.session.caption = "今日は" + next(
            (segment.text for segment in (query.voicegerSegments or []) if segment.language == "en"),
            "example",
        )
        if query.voicegerSegments is None:
            app.session._pure_japanese_utterance_text = app.session.caption
        if batch_item:
            app._batch.batch.add_item(CaptionBatchItem(app.session))
            app._batch.focus_key = ("caption", 0)
            app._batch.open_item(0)
        return app

    @staticmethod
    def rendered(screen):
        return "\n".join(text for _row, _column, text, _attr in screen.drawn)

    @staticmethod
    def finish_and_apply_pronunciation(app):
        editor = app._editor_controller.editor
        if editor is not None and editor.active_field is not None:
            app._handle_key("\n")
        app._handle_key(curses.KEY_DOWN)
        app._handle_key(curses.KEY_DOWN)
        app._handle_key("\n")

    @staticmethod
    def complete_dictionary_operation(app):
        app._operations.start_pending_worker()
        app._operations.join_worker()
        app._consume_events()
