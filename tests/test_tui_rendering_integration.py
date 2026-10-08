import curses
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from voiceger_editor.caption_batch import CaptionBatchItem
from voiceger_editor.openjtalk_dictionary import expand_word_type, normalize_surface
from voiceger_editor.pronunciation import parse_pronunciation
from voiceger_editor.settings import Settings
from voiceger_editor.terms_acceptance import (
    ACCEPTANCE_COMMAND,
    OFFICIAL_TERMS_URL,
    TermsAcceptanceStatus,
    VoicegerTermsAcceptanceError,
)
from voiceger_editor.tui_editors import (
    OpenDictionaryIntent,
    PreviewIntent,
    ReplaceQueryIntent,
)
from voiceger_editor.tui_input import PasteText
from voiceger_editor.tui_operations import (
    BatchCandidateReplacedEffect,
    CandidateReplacedEffect,
    DiscardInitialBatchEffect,
    PlayPreviewEffect,
)
from voiceger_editor.tui_status import EMPTY_STATUS, StatusKind, error_status, info_status, warning_status
from voiceger_editor.tui import TuiApp, main
from voiceger_editor.user_dictionary import JapaneseWordType
from voiceger_editor.voicevox_api_models import (
    AccentPhrase,
    AudioQuery,
    Mora,
    VoicegerSegment,
)


from tests.tui_app_test_support import (
    TuiAppTestCase,
    FakeScreen,
    candidate,
    editor_document,
    english_grouping,
    english_query,
    focus_candidate,
    japanese_query,
    mixed_query,
    navigation_document,
    navigation_items,
    set_navigation_focus,
)

class TuiRenderingIntegrationTests(TuiAppTestCase):
    def test_active_generation_renders_ctrl_c_cancel_hint(self):
        app = self.make_app(query=mixed_query())
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._active_operation_id = 1
        app._screen = FakeScreen(rows=24, columns=100)

        app._render()

        self.assertIn("[Ctrl+C] Cancel generation", self.rendered(app._screen))

    def test_batch_list_shows_active_item_generation_percentage(self):
        for completed, expected in ((0, "[0%]"), (2, "[50%]")):
            with self.subTest(completed=completed):
                app = self.make_app(query=mixed_query())
                item_id = app._batch.open_item_id
                app._operations.busy = True
                app._operations.worker_operation = "initial"
                app._operations._worker_item_id = item_id
                app._operations._active_operation_id = 1
                app._operations.operation_completed = completed
                app._operations.operation_total = 4

                app._handle_key("\x1b")
                app._screen = FakeScreen(rows=24, columns=100)
                app._render()

                self.assertIn(expected, self.rendered(app._screen))

    def test_background_generation_stays_visible_in_help_with_unrelated_status(self):
        app = self.make_app(query=mixed_query())
        item_id = app._batch.open_item_id
        app._operations.busy = True
        app._operations.worker_operation = "initial"
        app._operations._worker_item_id = item_id
        app._operations._active_operation_id = 7
        app._operations.operation_completed = 1
        app._operations.operation_total = 4
        app._operations._cancellation_event = Event()
        app._status = info_status("Caption 2 was added.")

        app._handle_key("?")
        app._screen = FakeScreen(rows=24, columns=100)
        app._render()
        rendered = self.rendered(app._screen)

        self.assertIn(
            "Generating · Caption 1 · Take 2/4 · [Ctrl+C] Cancel generation",
            rendered,
        )
        self.assertIn("Status: Caption 2 was added.", rendered)

    def test_help_scroll_clamp_accounts_for_status_footer_height(self):
        app = self.make_app(query=mixed_query())
        app._screen = FakeScreen(rows=8, columns=32)
        app._status = info_status(
            "This is a long shared Status message that occupies multiple footer rows."
        )
        app._open_help()
        height, width = app._screen.getmaxyx()
        max_scroll = app._renderer.help_max_scroll(
            height,
            width,
            app._status,
        )
        self.assertGreater(
            max_scroll,
            app._renderer.help_max_scroll(height, width),
        )

        app._help_scroll = 10_000
        app._handle_key(curses.KEY_DOWN)

        self.assertEqual(app._help_scroll, max_scroll)
