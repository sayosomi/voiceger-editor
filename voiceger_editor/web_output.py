"""Mac-owned Output settings for the authenticated Web frontend."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from .filename import (
    FilenameTemplateError, render_output_basename, validate_filename_template,
)
from .output import (
    FLAC_ENCODINGS, MP3_BITRATES, WAV_ENCODINGS,
    available_output_formats, output_extension,
)
from .settings import SettingsError
from .web_settings import WebSettingsUnavailable, save_settings


OUTPUT_FIELDS = (
    "output_dir", "filename_template", "output_format", "wav_encoding",
    "flac_encoding", "mp3_bitrate", "save_text", "save_lab",
)


class WebOutputValidation(ValueError):
    """Safe allowlisted errors; never expose a Mac filesystem path."""

    CODES = frozenset({
        "invalid_output_dir", "invalid_filename_template",
        "invalid_output_format", "invalid_output_encoding",
    })

    def __init__(self, code: str) -> None:
        if code not in self.CODES:
            raise ValueError("Unknown Output error code")
        super().__init__(code)
        self.code = code


class WebOutputMixin:
    """Apply one atomic Mac configuration update before changing live state."""

    def _output_settings_view(self, session) -> dict[str, Any]:
        current = self._recipe_settings()
        return {
            "revision": session.revision,
            "settings_revision": self._settings_revision,
            "values": {
                key: str(getattr(current, key)) if key == "output_dir"
                else getattr(current, key)
                for key in OUTPUT_FIELDS
            },
            "formats": list(available_output_formats()),
            "encodings": {
                "wav": list(WAV_ENCODINGS),
                "flac": list(FLAC_ENCODINGS),
                "mp3": list(MP3_BITRATES),
            },
        }

    def get_web_output_settings(self, identifier: str) -> dict[str, Any]:
        with self._lock:
            return self._output_settings_view(self._session(identifier))

    def preview_web_filename(
        self, identifier: str, template: str, output_format: str,
    ) -> dict[str, str]:
        """Read-only preview; no writes, candidate creation or browser naming rules."""
        with self._lock:
            self._session(identifier)
            if output_format not in available_output_formats():
                raise WebOutputValidation("invalid_output_format")
            try:
                current = self._recipe_settings()
                style = next(
                    (entry.name for entry in self._styles()
                     if entry.id == current.style_id),
                    "Neutral",
                )
                basename = render_output_basename(
                    template=template, text="サンプル", style=style,
                )
            except (FilenameTemplateError, ValueError, TypeError):
                raise WebOutputValidation("invalid_filename_template") from None
            return {"filename": basename + output_extension(output_format)}

    def save_web_output_settings(
        self, identifier: str, revision: int, settings_revision: int,
        **changes: Any,
    ) -> dict[str, Any]:
        from .web_sessions import WebSessionConflict

        with self._lock:
            session = self._settings_guard(identifier, revision)
            if self._settings_revision != settings_revision:
                raise WebSessionConflict(
                    "Output settings changed in another tab",
                    code="settings_revision_conflict",
                )
            if set(changes) != set(OUTPUT_FIELDS):
                raise WebOutputValidation("invalid_output_format")
            if changes["output_format"] not in available_output_formats():
                raise WebOutputValidation("invalid_output_format")
            try:
                updated = replace(self._recipe_settings(), **changes)
            except (SettingsError, ValueError, TypeError):
                raise WebOutputValidation("invalid_filename_template") from None
            destination: Path = updated.output_dir
            if not destination.is_absolute():
                raise WebOutputValidation("invalid_output_dir")
            try:
                if destination.is_symlink() or (
                    destination.exists() and not destination.is_dir()
                ):
                    raise WebOutputValidation("invalid_output_dir")
            except OSError as exc:
                raise WebSettingsUnavailable("Output directory could not be checked") from exc

            previous = self._recipe_settings()
            if updated == previous:
                return self._output_settings_view(session)

            targets = []
            for owned in self._sessions.values():
                for item in owned.batch.items:
                    scoped = replace(
                        item.session.settings,
                        **{key: getattr(updated, key) for key in OUTPUT_FIELDS},
                    )
                    if scoped != item.session.settings:
                        targets.append((item.session, scoped))

            # Persistence failure does not change any in-memory state, review
            # token, Take candidate or accepted file.
            try:
                save_settings(updated)
            except (OSError, SettingsError) as exc:
                raise WebSettingsUnavailable("Output configuration could not be saved") from exc

            for item_session, scoped in targets:
                item_session.replace_settings(scoped, preserve_takes=True)
            self._batch_settings = updated
            self._settings_revision += 1

            if updated.output_dir != previous.output_dir:
                # The recipe and dictionary file handlers cache a verified
                # Output root. Never allow a pre-change review to commit against
                # the newly selected directory.
                self._web_recipe_root = None
                for owned in self._sessions.values():
                    self._discard_review(owned)
                    owned.pending_dictionary_export = None
                    owned.pending_dictionary_import = None

            for owned in self._sessions.values():
                owned.preview_audio = None
                owned.revision += 1
            return self._output_settings_view(session)
