"""Small fixtures shared by focused rendering-owner tests."""

from pathlib import Path

from voiceger_editor.settings import Settings
from voiceger_editor.tui_rendering import TuiRenderState
from voiceger_editor.tui_status import EMPTY_STATUS


def render_state(*, editor=None, focus_key=("settings", None), settings=None):
    return TuiRenderState(
        voiceger_root=Path("/nonexistent/voiceger"),
        settings=settings or Settings(),
        session=None,
        focus_key=focus_key,
        status=EMPTY_STATUS,
        segments=(),
        pronunciation_rows=(),
        busy=False,
        worker_operation=None,
        worker_target=None,
        operation_completed=0,
        operation_total=0,
        pressed_adjustment=None,
        editor=editor,
    )
