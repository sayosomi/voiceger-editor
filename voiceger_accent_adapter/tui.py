"""Keyboard-first terminal interface for local Voiceger synthesis."""

from __future__ import annotations

import argparse
import curses
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import unicodedata
from threading import Thread
from typing import Any, Sequence

from .english_stress import english_phonemes_to_editor_state
from .query_editing import (
    english_editor_state,
    japanese_pronunciation,
    move_english_primary_stress,
    replace_english_base_phonemes,
    replace_japanese_pronunciation,
)
from .session import UtteranceSession
from .settings import Settings, SettingsError, load_settings, save_settings
from .styles import available_styles
from .voiceger_adapter import VoicegerAdapter


_VOWELS = frozenset(
    {
        "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY",
        "IH", "IY", "OW", "OY", "UH", "UW",
    }
)
_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"
_HELP_ITEMS = (
    "Tab: next area",
    "Enter: edit / activate / accept according to focus",
    "Up/Down: pronunciation or take navigation according to focus",
    "Left/Right: English primary stress movement",
    "Shift+Tab: select another English primary-stress marker",
    "F5 / Ctrl+G: generate",
    "Space: replay take",
    "1-8: select take",
    "r: regenerate current take",
    "R (Shift+R): regenerate all takes",
    "t: edit text",
    "s: style",
    "v: speed",
    "n: take count",
    "o: output directory",
    "x: toggle text sidecar",
    "?: help",
    "q: quit",
)


def format_english_phonemes(
    phonemes: Sequence[str],
    *,
    selected_primary: int | None = None,
) -> str:
    """Render stress-free ARPAbet, marking primary-stress anchors visually."""

    state = english_phonemes_to_editor_state(phonemes)
    result: list[str] = []
    vowel_position = 0
    for token in state.base_phonemes:
        if token in _VOWELS:
            stress = state.vowel_stresses[vowel_position]
            selected = vowel_position == selected_primary
            if selected:
                rendered = f"▶[{token}]"
            elif stress == 1:
                rendered = f"[{token}]"
            else:
                rendered = token
            result.append(rendered)
            vowel_position += 1
        else:
            result.append(token)
    return " ".join(result)


def _take_key_action(
    key: Any,
    *,
    candidate_numbers: Sequence[int],
    current_number: int | None,
) -> tuple[str, int | None] | None:
    """Translate take-review keys without consuming text-editor key events."""

    numbers = tuple(sorted(candidate_numbers))
    if key == curses.KEY_UP:
        if not numbers:
            return None
        if current_number not in numbers:
            return "select", numbers[-1]
        index = numbers.index(current_number)
        return "select", numbers[max(0, index - 1)]
    if key == curses.KEY_DOWN:
        if not numbers:
            return None
        if current_number not in numbers:
            return "select", numbers[0]
        index = numbers.index(current_number)
        return "select", numbers[min(len(numbers) - 1, index + 1)]
    if key == " ":
        return ("replay", current_number) if current_number in numbers else None
    if key in _ENTER_KEYS:
        return ("accept", current_number) if current_number in numbers else None
    if isinstance(key, str) and len(key) == 1 and key in "12345678":
        number = int(key)
        return ("select", number) if number in numbers else ("missing", number)
    if key == "r":
        return "regenerate", current_number
    if key == "R":
        return "regenerate_all", None
    return None


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voiceger-accent-adapter",
        description="Keyboard-first local pronunciation editing and take review.",
    )
    parser.add_argument("text", nargs="?", help="one utterance to edit and synthesize")
    parser.add_argument("--voiceger-root", type=Path, help="Voiceger installation path")
    parser.add_argument("--config", type=Path, help="settings file path")
    parser.add_argument("--output-dir", type=Path, help="override output directory")
    parser.add_argument("--take-count", type=int, help="override take count (1–8)")
    parser.add_argument("--style", type=int, help="override reference style ID")
    parser.add_argument("--speed", type=float, help="override speech speed")
    save_group = parser.add_mutually_exclusive_group()
    save_group.add_argument(
        "--save-text", dest="save_text", action="store_true",
        help="save an exact source-text sidecar",
    )
    save_group.add_argument(
        "--no-save-text", dest="save_text", action="store_false",
        help="disable source-text sidecars",
    )
    parser.set_defaults(save_text=None)
    return parser


def settings_for_invocation(args: argparse.Namespace, base: Settings) -> Settings:
    """Apply command-line overrides without writing them to persisted settings."""

    overrides = {
        name: value
        for name, value in (
            ("output_dir", args.output_dir),
            ("take_count", args.take_count),
            ("style_id", args.style),
            ("speed", args.speed),
            ("save_text", args.save_text),
        )
        if value is not None
    }
    return replace(base, **overrides)


class TuiApp:
    """Own the curses view and route edits through the reusable session core."""

    def __init__(
        self,
        *,
        adapter: VoicegerAdapter,
        settings: Settings,
        persisted_settings: Settings | None = None,
        config_path: str | os.PathLike[str] | None = None,
        source_text: str | None = None,
    ) -> None:
        self.adapter = adapter
        self.settings = settings
        self._persisted_settings = persisted_settings or settings
        self.config_path = config_path
        self.session: UtteranceSession | None = None
        self._initial_text = source_text
        self._screen: Any = None
        self._events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._worker: Thread | None = None
        self._worker_operation: str | None = None
        self._worker_target: int | None = None
        self._worker_error: BaseException | None = None
        self._busy = False
        self._exit_requested = False
        self._focus = "pronunciation"
        self._segment_index = 0
        self._current_take: int | None = None
        self._selected_primary: dict[int, int] = {}
        self._status = "Enter text, edit pronunciation, then press F5 to generate."
        self._player: subprocess.Popen[Any] | None = None
        self._help_open = False
        self._editor_prompt: str | None = None
        self._editor_type: str | None = None
        self._editor_value = ""
        self._editor_cursor = 0
        self._color_attr = 0

    def run(self, screen: Any) -> None:
        self._screen = screen
        try:
            screen.keypad(True)
            screen.timeout(100)
            self._initialize_colors()
            try:
                curses.curs_set(0)
            except curses.error:
                pass

            source_text = self._initial_text
            if source_text is None:
                source_text = self._read_line("Source text", "")
                if source_text is None:
                    return
            while self.session is None:
                if not source_text.strip():
                    source_text = self._read_line("Source text (one utterance)", source_text)
                    if source_text is None:
                        return
                    continue
                try:
                    self.session = UtteranceSession.from_text(
                        adapter=self.adapter,
                        source_text=source_text,
                        settings=self.settings,
                    )
                    self._status = "Query ready. Edit pronunciation, then press F5 to generate."
                except Exception as exc:
                    self._status = f"Error: Unable to prepare utterance: {exc}"
                    self._render()
                    source_text = self._read_line("Source text", source_text)
                    if source_text is None:
                        return

            while not self._exit_requested:
                self._consume_events()
                self._render()
                key = self._read_key()
                if key is not None:
                    self._handle_key(key)

            while self._busy:
                self._consume_events()
                if not self._busy:
                    break
                self._render()
                self._read_key()
        finally:
            worker = self._worker
            try:
                if worker is not None and worker.ident is not None:
                    worker.join()
            finally:
                try:
                    self._stop_playback()
                finally:
                    if self.session is not None and (
                        worker is None or not worker.is_alive()
                    ):
                        self.session.close()

    def _read_key(self) -> Any:
        try:
            key = self._screen.get_wch()
        except curses.error:
            return None
        if key == -1:
            return None
        if key == _ESCAPE:
            return _ESCAPE
        return key

    def _initialize_colors(self) -> None:
        """Set up optional theme-default colors; attributes remain the main cue."""

        self._color_attr = 0
        try:
            if not curses.has_colors():
                return
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            self._color_attr = curses.color_pair(1)
        except (AttributeError, curses.error):
            self._color_attr = 0

    @staticmethod
    def _attribute(name: str) -> int:
        return int(getattr(curses, name, 0))

    def _focus_attribute(self) -> int:
        return (
            self._attribute("A_REVERSE")
            | self._attribute("A_BOLD")
            | self._color_attr
        )

    def _handle_key(self, key: Any) -> None:
        if key in ("q", "Q", "\x03"):
            self._exit_requested = True
            if self._busy:
                self._status = "Finishing the current sequential synthesis before cleanup…"
            return

        if self._help_open:
            if key == "?" or key == _ESCAPE or key in _ENTER_KEYS:
                self._help_open = False
            return

        if key == "?":
            self._help_open = True
            return

        if key == _ESCAPE:
            self._focus = "pronunciation"
            self._status = "Pronunciation editing focused."
            return
        if key == curses.KEY_F5 or key == "\x07":
            self._start_generation()
            return
        if key == curses.KEY_BTAB:
            if self._focus == "pronunciation":
                self._cycle_selected_primary()
            return
        if key == "\t":
            self._cycle_focus()
            return

        if self._busy and key in {"t", "s", "v", "n", "o", "x"}:
            self._status = "Wait for the current synthesis operation to finish before editing."
            return

        if key == "t":
            self._edit_source_text()
            return
        if key == "s":
            self._edit_setting("style")
            return
        if key == "v":
            self._edit_setting("speed")
            return
        if key == "n":
            self._edit_setting("take_count")
            return
        if key == "o":
            self._edit_setting("output_dir")
            return
        if key == "x":
            self._change_settings(save_text=not self.settings.save_text)
            return

        if self._focus == "takes":
            self._handle_take_key(key)
        elif self._focus == "pronunciation":
            self._handle_pronunciation_key(key)
        elif self._focus == "source" and key in _ENTER_KEYS:
            if self._busy:
                self._status = "Wait for synthesis to finish before editing source text."
            else:
                self._edit_source_text()
        elif self._focus == "generate" and key in _ENTER_KEYS:
            if self._busy:
                self._status = "A sequential take operation is already running."
            elif self.session is not None and self.session.has_active_batch:
                self._start_regenerate_all()
            else:
                self._start_generation()

    def _cycle_focus(self) -> None:
        candidates = self.session.candidates if self.session is not None else ()
        order = ["source", "pronunciation", "generate"]
        if candidates:
            order.append("takes")
        try:
            index = order.index(self._focus)
        except ValueError:
            index = -1
        self._focus = order[(index + 1) % len(order)]
        self._status = f"{self._focus.capitalize()} area focused."

    def _handle_pronunciation_key(self, key: Any) -> None:
        if key == curses.KEY_UP:
            self._move_segment(-1)
        elif key == curses.KEY_DOWN:
            self._move_segment(1)
        elif key in _ENTER_KEYS:
            if self._busy:
                self._status = "Wait for synthesis to finish before editing pronunciation."
            else:
                self._edit_selected_segment()
        elif key == curses.KEY_LEFT:
            if not self._busy:
                self._move_selected_stress(-1)
        elif key == curses.KEY_RIGHT:
            if not self._busy:
                self._move_selected_stress(1)

    def _handle_take_key(self, key: Any) -> None:
        if self.session is None:
            return
        numbers = [candidate.number for candidate in self.session.candidates]
        action = _take_key_action(
            key,
            candidate_numbers=numbers,
            current_number=self._current_take,
        )
        if action is None:
            return
        name, number = action
        if name == "missing":
            self._status = f"Take {number} has not been generated yet."
        elif name == "select" and number is not None:
            self._current_take = number
            self._play_take(number)
        elif name == "replay" and number is not None:
            self._play_take(number)
        elif name == "accept" and number is not None:
            if self._busy:
                self._status = "Wait for the current generation to finish before accepting."
            else:
                self._accept_take(number)
        elif name == "regenerate" and number is not None:
            if self._busy:
                self._status = "Wait for the current generation to finish."
            else:
                self._start_regeneration(number)
        elif name == "regenerate_all":
            if self._busy:
                self._status = "Wait for the current generation to finish."
            elif numbers:
                self._start_regenerate_all()

    def _segments(self) -> list[tuple[str, str, int | None]]:
        if self.session is None:
            return []
        query = self.session.query
        if query.voicegerSegments is None:
            return [("ja", self.session.source_text, None)]
        return [
            (segment.language, segment.text, index)
            for index, segment in enumerate(query.voicegerSegments)
        ]

    def _move_segment(self, delta: int) -> None:
        segments = self._segments()
        if not segments:
            return
        self._segment_index = min(
            max(0, self._segment_index + delta), len(segments) - 1
        )
        self._status = f"Pronunciation segment {self._segment_index + 1}/{len(segments)}."

    def _edit_selected_segment(self) -> None:
        if self.session is None:
            return
        segments = self._segments()
        if not segments:
            return
        self._segment_index = min(self._segment_index, len(segments) - 1)
        language, segment_text, model_index = segments[self._segment_index]
        query = self.session.query
        if language == "ja":
            segment_index = model_index if query.voicegerSegments is not None else None
            try:
                current = japanese_pronunciation(query, segment_index=segment_index)
            except Exception as exc:
                self._status = f"Error: Cannot render Japanese pronunciation: {exc}"
                return
            replacement = self._read_line(
                f"JA {segment_text} pronunciation", current, editor_type="japanese"
            )
            if replacement is None:
                self._status = "Pronunciation edit canceled."
                return
            try:
                updated = replace_japanese_pronunciation(
                    query,
                    replacement,
                    segment_index=segment_index,
                )
                self._stop_playback()
                self.session.replace_query(updated)
                self._status = "Japanese pronunciation updated; old takes cleared."
            except Exception as exc:
                self._status = f"Error: Pronunciation was not changed: {exc}"
            return

        if language == "en" and model_index is not None:
            try:
                state = english_editor_state(query, segment_index=model_index)
            except Exception as exc:
                self._status = f"Error: Cannot edit English phonemes: {exc}"
                return
            replacement = self._read_line(
                f"EN {segment_text} phonemes (stress digits hidden)",
                " ".join(state.base_phonemes),
                editor_type="english",
            )
            if replacement is None:
                self._status = "English phoneme edit canceled."
                return
            try:
                updated = replace_english_base_phonemes(
                    query,
                    segment_index=model_index,
                    base_phonemes=replacement.split(),
                )
                self._stop_playback()
                self.session.replace_query(updated)
                new_state = english_editor_state(updated, segment_index=model_index)
                self._refresh_selected_primary(model_index, new_state)
                self._status = "English phonemes updated; stress was retained by vowel position."
            except Exception as exc:
                self._status = f"Error: English phonemes were not changed: {exc}"
            return

        self._status = f"Error: Pronunciation editing is not available for {language!r} segments."

    def _move_selected_stress(self, delta: int) -> None:
        if self.session is None:
            return
        segments = self._segments()
        if not segments or self._segment_index >= len(segments):
            return
        language, _, model_index = segments[self._segment_index]
        if language != "en" or model_index is None:
            return
        query = self.session.query
        try:
            state = english_editor_state(query, segment_index=model_index)
        except Exception as exc:
            self._status = f"Error: Cannot move English stress: {exc}"
            return
        primary = state.primary_stress_vowel_positions
        if not primary:
            self._status = "This English segment has no primary-stress anchor to move."
            return
        source = self._selected_primary.get(model_index, primary[0])
        if source not in primary:
            source = primary[0]
        target = source + delta
        if not 0 <= target < len(state.vowel_stresses):
            self._status = "Primary stress is already at the edge of this segment."
            return
        if target in primary:
            self._status = "Target vowel already has primary stress."
            return
        try:
            updated = move_english_primary_stress(
                query,
                segment_index=model_index,
                source_vowel_position=source,
                target_vowel_position=target,
            )
            self._stop_playback()
            self.session.replace_query(updated)
            self._selected_primary[model_index] = target
            self._status = "Primary stress moved; other stress markers were preserved."
        except Exception as exc:
            self._status = f"Error: Primary stress was not changed: {exc}"

    def _cycle_selected_primary(self) -> None:
        if self.session is None:
            return
        segments = self._segments()
        if self._segment_index >= len(segments):
            return
        language, _, model_index = segments[self._segment_index]
        if language != "en" or model_index is None:
            return
        try:
            state = english_editor_state(
                self.session.query,
                segment_index=model_index,
            )
        except Exception as exc:
            self._status = f"Error: Cannot select English stress marker: {exc}"
            return
        positions = state.primary_stress_vowel_positions
        if not positions:
            self._status = "This English segment has no primary-stress marker."
            return
        selected = self._selected_primary.get(model_index, positions[0])
        if selected not in positions:
            selected = positions[0]
        selected_index = positions.index(selected)
        self._selected_primary[model_index] = positions[
            (selected_index + 1) % len(positions)
        ]
        self._status = (
            f"Selected primary-stress marker "
            f"{self._selected_primary[model_index] + 1}/{len(positions)}."
        )

    def _refresh_selected_primary(self, segment_index: int, state: Any) -> None:
        positions = state.primary_stress_vowel_positions
        if positions:
            self._selected_primary[segment_index] = positions[0]
        else:
            self._selected_primary.pop(segment_index, None)

    def _edit_source_text(self) -> None:
        if self.session is None:
            return
        replacement = self._read_line("Source text", self.session.source_text)
        if replacement is None or replacement == self.session.source_text:
            self._status = "Source text unchanged."
            return
        try:
            replacement_session = UtteranceSession.from_text(
                adapter=self.adapter,
                source_text=replacement,
                settings=self.settings,
            )
        except Exception as exc:
            self._status = f"Error: Source text was not changed: {exc}"
            return
        self._stop_playback()
        self.session.close()
        self.session = replacement_session
        self._segment_index = 0
        self._current_take = None
        self._selected_primary.clear()
        self._focus = "pronunciation"
        self._status = "Source text updated and pronunciation rebuilt."

    def _edit_setting(self, name: str) -> None:
        if name == "style":
            styles = available_styles(self.adapter.voiceger_root)
            choices = ", ".join(f"{item.id}={item.name}" for item in styles)
            raw = self._read_line(f"Style ID ({choices})", str(self.settings.style_id))
            if raw is None:
                return
            try:
                self._change_settings(style_id=int(raw))
            except ValueError as exc:
                self._status = f"Error: Style was not changed: {exc}"
            return
        if name == "speed":
            raw = self._read_line("Speed (positive number)", str(self.settings.speed))
            if raw is None:
                return
            try:
                self._change_settings(speed=float(raw))
            except (ValueError, SettingsError) as exc:
                self._status = f"Error: Speed was not changed: {exc}"
            return
        if name == "take_count":
            raw = self._read_line("Take count (1–8)", str(self.settings.take_count))
            if raw is None:
                return
            try:
                self._change_settings(take_count=int(raw))
            except (ValueError, SettingsError) as exc:
                self._status = f"Error: Take count was not changed: {exc}"
            return
        if name == "output_dir":
            raw = self._read_line("Output directory", str(self.settings.output_dir))
            if raw is None:
                return
            try:
                self._change_settings(output_dir=Path(raw).expanduser())
            except (ValueError, SettingsError) as exc:
                self._status = f"Error: Output directory was not changed: {exc}"

    def _change_settings(self, **changes: Any) -> None:
        try:
            updated = replace(self.settings, **changes)
            if self.session is not None:
                self._stop_playback()
                self.session.replace_settings(updated)
        except (SettingsError, ValueError) as exc:
            self._status = f"Error: Settings were not changed: {exc}"
            return
        self.settings = updated
        try:
            persisted = replace(self._persisted_settings, **changes)
        except SettingsError as exc:
            self._status = f"Error: Settings changed for this run but were not saved: {exc}"
            return
        self._persisted_settings = persisted
        self._current_take = None
        self._selected_primary.clear()
        try:
            save_settings(persisted, self.config_path)
        except OSError as exc:
            self._status = f"Error: Settings changed for this run but could not be saved: {exc}"
        else:
            self._status = "Settings saved. Existing temporary takes were cleared."

    def _start_generation(self) -> None:
        if self._busy:
            self._status = "A sequential take operation is already running."
            return
        if self.session is None:
            return
        if self.session.has_active_batch:
            self._status = "A take batch already exists; use R to regenerate all takes."
            return
        try:
            iterator = self.session.generate_takes()
        except Exception as exc:
            self._status = f"Error: Could not start take generation: {exc}"
            return
        self._focus = "takes"
        self._current_take = None
        self._run_in_worker(
            lambda: iterator,
            "Generating takes sequentially…",
            operation="initial",
        )

    def _start_regeneration(self, number: int) -> None:
        if self.session is None:
            return
        self._stop_playback()
        self._current_take = number
        self._run_in_worker(
            lambda: (self.session.regenerate_take(number),),
            f"Regenerating take {number}…",
            operation="regenerate_one",
            target=number,
        )

    def _start_regenerate_all(self) -> None:
        if self.session is None:
            return
        try:
            iterator = self.session.regenerate_all_takes()
        except Exception as exc:
            self._status = f"Error: Could not regenerate all takes: {exc}"
            return
        self._run_in_worker(
            lambda: iterator,
            "Regenerating takes sequentially…",
            operation="regenerate_all",
        )

    def _run_in_worker(
        self,
        make_values: Any,
        status: str,
        *,
        operation: str,
        target: int | None = None,
    ) -> None:
        self._busy = True
        self._worker_operation = operation
        self._worker_target = target
        self._worker_error = None
        self._status = status

        def work() -> None:
            try:
                with open(os.devnull, "w", encoding="utf-8") as sink:
                    with redirect_stdout(sink), redirect_stderr(sink):
                        for candidate in make_values():
                            self._events.put(("candidate", candidate))
            except BaseException as exc:
                self._events.put(("error", exc))
            finally:
                self._events.put(("done", None))

        self._worker = Thread(target=work, name="voiceger-tui-synthesis", daemon=True)
        self._worker.start()

    def _consume_events(self) -> None:
        while True:
            try:
                kind, value = self._events.get_nowait()
            except queue.Empty:
                return
            if kind == "candidate":
                operation = self._worker_operation
                self._status = f"Take {value.number} ready. Use arrows or 1–8 to audition."
                if operation == "initial":
                    if self._current_take is None:
                        self._current_take = value.number
                        self._play_take(value.number)
                elif operation == "regenerate_one":
                    if value.number == self._worker_target:
                        self._current_take = value.number
                        self._play_take(value.number)
                elif operation == "regenerate_all":
                    if value.number == self._current_take:
                        self._play_take(value.number)
            elif kind == "error":
                self._worker_error = value
                self._status = f"Error: Generation failed: {value}"
                if self._worker_operation == "initial":
                    self._stop_playback()
                    if self.session is not None:
                        self.session.discard_takes()
                    self._current_take = None
                    self._focus = "pronunciation"
            elif kind == "done":
                operation = self._worker_operation
                self._busy = False
                if self._worker_error is not None:
                    self._status = f"Error: Generation failed: {self._worker_error}"
                elif operation == "initial" and self.session is not None and self.session.candidates:
                    if self._current_take is None:
                        self._current_take = self.session.candidates[0].number
                    self._status = (
                        f"{len(self.session.candidates)} take(s) available. "
                        "Use arrows or 1–8 to audition."
                    )
                elif operation in {"regenerate_one", "regenerate_all"}:
                    self._status = "Take regeneration finished."
                elif not self._exit_requested:
                    self._status = "No takes were generated. Press F5 to try again."
                self._worker_operation = None
                self._worker_target = None

    def _play_take(self, number: int) -> None:
        if self.session is None:
            return
        candidate = next(
            (item for item in self.session.candidates if item.number == number),
            None,
        )
        if candidate is None:
            self._status = f"Take {number} is not available yet."
            return
        self._stop_playback()
        try:
            if sys.platform == "darwin":
                player = shutil.which("afplay")
                if player:
                    command = [player, str(candidate.wav_path)]
                else:
                    player = shutil.which("ffplay")
                    command = (
                        [player, "-nodisp", "-autoexit", "-loglevel", "error", str(candidate.wav_path)]
                        if player
                        else None
                    )
            else:
                player = shutil.which("ffplay")
                command = (
                    [player, "-nodisp", "-autoexit", "-loglevel", "error", str(candidate.wav_path)]
                    if player
                    else None
                )
            if command is None:
                self._status = "Error: Playback needs afplay (macOS) or ffplay (other systems)."
                return
            self._player = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._current_take = number
            self._status = f"Playing take {number}."
        except OSError as exc:
            self._status = f"Error: Could not play take {number}: {exc}"

    def _stop_playback(self) -> None:
        process = self._player
        self._player = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _accept_take(self, number: int) -> None:
        if self.session is None or self._busy:
            return
        self._stop_playback()
        try:
            saved = self.session.accept_take(number)
        except Exception as exc:
            self._status = f"Error: Could not save take {number}: {exc}"
            return
        self._current_take = None
        self._focus = "pronunciation"
        sidecar = f" and {saved.text_path.name}" if saved.text_path else ""
        self._status = f"Saved {saved.wav_path.name}{sidecar}."

    def _read_line(
        self,
        prompt: str,
        initial: str = "",
        *,
        editor_type: str = "text",
    ) -> str | None:
        if self._screen is None:
            return None
        buffer = list(initial)
        cursor = len(buffer)
        self._editor_prompt = prompt
        self._editor_type = editor_type
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        try:
            while True:
                self._editor_value = "".join(buffer)
                self._editor_cursor = cursor
                self._render()
                try:
                    key = self._screen.get_wch()
                except curses.error:
                    continue
                if key in _ENTER_KEYS:
                    self._status = ""
                    return "".join(buffer)
                if key == _ESCAPE or key == "\x03":
                    return None
                if editor_type == "japanese" and key in {"a", "p"}:
                    marker = "'" if key == "a" else "/"
                    if cursor > 0 and buffer[cursor - 1] == marker:
                        del buffer[cursor - 1]
                        cursor -= 1
                    else:
                        buffer.insert(cursor, marker)
                        cursor += 1
                elif key == curses.KEY_LEFT:
                    cursor = max(0, cursor - 1)
                elif key == curses.KEY_RIGHT:
                    cursor = min(len(buffer), cursor + 1)
                elif key == curses.KEY_HOME or key == "\x01":
                    cursor = 0
                elif key == curses.KEY_END or key == "\x05":
                    cursor = len(buffer)
                elif key in (curses.KEY_BACKSPACE, "\x7f", "\x08"):
                    if cursor:
                        cursor -= 1
                        del buffer[cursor]
                elif key == curses.KEY_DC:
                    if cursor < len(buffer):
                        del buffer[cursor]
                elif isinstance(key, str) and len(key) == 1 and key.isprintable():
                    buffer.insert(cursor, key)
                    cursor += 1
        finally:
            self._editor_prompt = None
            self._editor_type = None
            self._editor_value = ""
            self._editor_cursor = 0
            try:
                curses.curs_set(0)
            except curses.error:
                pass

    def _render_help(self, width: int) -> None:
        self._safe_add(
            0,
            0,
            "Voiceger Accent Adapter — Help",
            width,
            self._attribute("A_BOLD"),
        )
        self._safe_add(1, 0, "Keyboard shortcuts", width, self._attribute("A_UNDERLINE"))
        if width >= 118:
            half = width // 2
            for index, item in enumerate(_HELP_ITEMS):
                row = 2 + index // 2
                column = 1 if index % 2 == 0 else half
                self._safe_add(row, column, item, half if index % 2 == 0 else width)
        else:
            for index, item in enumerate(_HELP_ITEMS):
                self._safe_add(2 + index, 1, item, width)

    def _context_hints(self) -> str:
        if self._editor_prompt is not None:
            if self._editor_type == "japanese":
                return "←/→ cursor | Home/End | Backspace/Delete"
            return "←/→ cursor | Home/End | Backspace/Delete | Enter Save | Esc Cancel"
        if self._help_open:
            return "? / Esc / Enter close help"
        if self._focus == "source":
            return "Text: Enter edit | t shortcut | Tab next area"
        if self._focus == "pronunciation":
            return "Pronunciation: Enter edit | ↑/↓ segment | Shift+Tab EN marker | ←/→ EN stress"
        if self._focus == "generate":
            return "Generate: Enter action | F5/Ctrl+G | Tab next area"
        return "Takes: ↑/↓ select/play | Space replay | Enter accept | 1–8 | r/R regenerate"

    def _render(self) -> None:
        if self._screen is None:
            return
        screen = self._screen
        height, width = screen.getmaxyx()
        screen.erase()

        if self._help_open:
            self._render_help(width)
        else:
            self._safe_add(0, 0, "Voiceger Accent Adapter", width, self._attribute("A_BOLD"))
            settings = self.settings
            style_name = next(
                (
                    style.name
                    for style in available_styles(self.adapter.voiceger_root)
                    if style.id == settings.style_id
                ),
                "unavailable",
            )
            settings_prefix = (
                f"Style {settings.style_id} {style_name} | Speed {settings.speed:.2f} | "
                f"Takes {settings.take_count}"
            )
            text_state = "TXT ON" if settings.save_text else "TXT OFF"
            prefix_limit = max(0, width - len(text_state) - 4)
            settings_line = (
                f"{settings_prefix[:prefix_limit]} | {text_state}"
                if prefix_limit
                else text_state
            )
            self._safe_add(1, 0, settings_line, width)
            self._safe_add(2, 0, f"Output: {settings.output_dir}", width)

            editor_active = self._editor_prompt is not None
            content_bottom = height - (9 if editor_active else 4)
            if self.session is not None:
                source_focused = self._focus == "source"
                source_attr = self._focus_attribute() if source_focused else 0
                self._safe_add(
                    4,
                    0,
                    f"{'▶' if source_focused else ' '} Text",
                    width,
                    source_attr,
                )
                edit_hint = "[Enter: Edit]"
                edit_column = max(2, width - len(edit_hint) - 2)
                self._safe_add(5, 2, self.session.source_text, edit_column)
                self._safe_add(5, edit_column, edit_hint, width, source_attr)

                pronunciation_focused = self._focus == "pronunciation"
                self._safe_add(
                    7,
                    0,
                    f"{'▶' if pronunciation_focused else ' '} Pronunciation",
                    width,
                    self._focus_attribute() if pronunciation_focused else 0,
                )
                segments = self._segments()
                for index, (language, text, model_index) in enumerate(segments):
                    row = 8 + index
                    selected_segment = index == self._segment_index
                    marker = "▶" if selected_segment else " "
                    if language == "ja":
                        try:
                            query = self.session.query
                            pronunciation = japanese_pronunciation(
                                query,
                                segment_index=(
                                    model_index if query.voicegerSegments is not None else None
                                ),
                            )
                            description = f"{marker} JA {text}: {pronunciation}"
                        except Exception as exc:
                            description = f"{marker} JA {text}: <{exc}>"
                    elif language == "en" and model_index is not None:
                        try:
                            query = self.session.query
                            segment = query.voicegerSegments[model_index]
                            state = english_editor_state(query, segment_index=model_index)
                            primary = state.primary_stress_vowel_positions
                            selected_primary = self._selected_primary.get(
                                model_index,
                                primary[0] if primary else None,
                            )
                            if selected_primary is not None and selected_primary not in primary:
                                selected_primary = primary[0] if primary else None
                            description = (
                                f"{marker} EN {text}: "
                                f"{format_english_phonemes(segment.phonemes or (), selected_primary=selected_primary)}"
                            )
                        except Exception as exc:
                            description = f"{marker} EN {text}: <{exc}>"
                    else:
                        description = f"{marker} {language.upper()} {text}"
                    selected_attr = (
                        self._attribute("A_REVERSE") | self._attribute("A_BOLD")
                        if selected_segment and pronunciation_focused
                        else self._attribute("A_UNDERLINE") if selected_segment else 0
                    )
                    self._safe_add(row, 2, description, width, selected_attr)

                generate_row = 8 + len(segments)
                has_batch = self.session.has_active_batch
                action = (
                    f"[ Regenerate all {settings.take_count} takes ]"
                    if has_batch
                    else f"[ Generate {settings.take_count} takes ]"
                )
                generate_focused = self._focus == "generate"
                self._safe_add(
                    generate_row,
                    0,
                    f"{'▶ ' if generate_focused else '  '}{action}",
                    width,
                    self._focus_attribute() if generate_focused else 0,
                )

                candidate_row = generate_row + 2
                takes_focused = self._focus == "takes"
                self._safe_add(
                    candidate_row,
                    0,
                    f"{'▶' if takes_focused else ' '} Candidates",
                    width,
                    self._focus_attribute() if takes_focused else 0,
                )
                for offset, candidate in enumerate(self.session.candidates):
                    row = candidate_row + 1 + offset
                    duration = _duration_seconds(candidate.audio, candidate.sampling_rate)
                    selected_take = candidate.number == self._current_take
                    description = (
                        f"{'▶' if selected_take else ' '} {candidate.number}  {duration:.2f}s"
                    )
                    selected_attr = (
                        self._focus_attribute()
                        if selected_take and takes_focused
                        else self._attribute("A_BOLD") if selected_take else 0
                    )
                    self._safe_add(row, 2, description, width, selected_attr)
                    if row >= content_bottom:
                        break

        status_row = height - 3
        status = self._status
        if self._busy and not self._help_open:
            status = "Synthesis is sequential; completed takes are available above."
        if status and not status.startswith(("Status:", "Error:")):
            status = f"Status: {status}"
        status_attr = self._attribute("A_BOLD")
        if status.startswith("Error:"):
            status_attr |= self._attribute("A_REVERSE")
        self._safe_add(status_row, 0, status, width, status_attr)
        self._safe_add(status_row + 1, 0, self._context_hints(), width)
        self._safe_add(
            status_row + 2,
            0,
            "? Help   q Quit",
            width,
            self._attribute("A_BOLD"),
        )

        if self._editor_prompt is not None:
            label_row = height - 7
            input_row = height - 4
            self._safe_add(
                label_row,
                0,
                f"Editor: {self._editor_prompt}",
                width,
                self._attribute("A_BOLD"),
            )
            if self._editor_type == "japanese":
                self._safe_add(label_row + 1, 0, "a Accent (') | p Phrase (/)", width)
                self._safe_add(
                    label_row + 2,
                    0,
                    "' / direct input | Enter Save | Esc Cancel",
                    width,
                )
            else:
                self._safe_add(
                    label_row + 1,
                    0,
                    "←/→ Move | Home/End | Backspace/Delete",
                    width,
                )
                self._safe_add(label_row + 2, 0, "Enter Save | Esc Cancel", width)
            visible, cursor_cells = _visible_input(
                self._editor_value,
                self._editor_cursor,
                max(1, width - 4),
            )
            self._safe_add(input_row, 0, f"> {visible}", width, self._focus_attribute())
            try:
                screen.move(input_row, min(width - 1, 2 + cursor_cells))
            except curses.error:
                pass
        screen.refresh()

    def _safe_add(
        self,
        row: int,
        column: int,
        value: str,
        width: int,
        attr: int = 0,
    ) -> None:
        if self._screen is None or row < 0 or column < 0 or width <= column:
            return
        try:
            arguments = (row, column, value, max(0, width - column - 1))
            if attr:
                self._screen.addnstr(*arguments, attr)
            else:
                self._screen.addnstr(*arguments)
        except curses.error:
            pass

def _duration_seconds(audio: Any, sampling_rate: int) -> float:
    try:
        return len(audio) / float(sampling_rate)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _display_width(value: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1
        for character in value
    )


def _visible_input(value: str, cursor: int, width: int) -> tuple[str, int]:
    """Keep the editor cursor visible while entering long or wide text."""

    start = 0
    while start < cursor and _display_width(value[start:cursor]) >= width:
        start += 1

    visible: list[str] = []
    used = 0
    for character in value[start:]:
        cell_width = 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1
        if used + cell_width > width:
            break
        visible.append(character)
        used += cell_width
    return "".join(visible), _display_width(value[start:cursor])


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        persisted_settings = load_settings(args.config)
        settings = settings_for_invocation(args, persisted_settings)
    except (SettingsError, ValueError) as exc:
        print(f"Cannot load settings: {exc}", file=sys.stderr)
        return 2
    adapter = VoicegerAdapter(
        voiceger_root=args.voiceger_root,
        output_dir=settings.output_dir,
    )
    app = TuiApp(
        adapter=adapter,
        settings=settings,
        persisted_settings=persisted_settings,
        config_path=args.config,
        source_text=args.text,
    )
    try:
        curses.wrapper(app.run)
    except curses.error as exc:
        print(
            f"The terminal UI could not start: {exc}. Run this command in a real terminal.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
