"""Server-owned Web synthesis settings and item voice reconciliation.

The existing Settings and UtteranceSession owners define validation and Take
semantics. This module provides only the Web concurrency and persistence edge.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .settings import Settings, SettingsError, save_settings
from .styles import available_styles, get_style
from .voiceger_environment import resolve_voiceger_root


class WebSettingsValidation(ValueError):
    """Invalid or unavailable setting supplied by the Web client."""


class WebSettingsUnavailable(RuntimeError):
    """Settings could not be saved on the Mac."""


_SHARED_FIELDS = ("style_id", "speed", "top_k", "top_p", "temperature")


class WebSettingsMixin:
    """Use the shared Settings model under the Web service's RLock."""

    def _styles(self):
        adapter = self._batch_adapter
        root = (
            adapter.voiceger_root
            if adapter is not None and hasattr(adapter, "voiceger_root")
            else resolve_voiceger_root(None)[0]
        )
        return available_styles(root)

    def _settings_view(self, session) -> dict[str, Any]:
        current = self._recipe_settings()
        return {
            "revision": session.revision,
            "settings_revision": self._settings_revision,
            "values": {
                name: getattr(current, name) for name in _SHARED_FIELDS
            },
            "styles": [
                {"id": style.id, "name": style.name}
                for style in self._styles()
            ],
        }

    def get_web_settings(self, identifier: str) -> dict[str, Any]:
        with self._lock:
            session = self._session(identifier)
            return self._settings_view(session)

    @staticmethod
    def _changed_synthesis(before: Settings, after: Settings) -> bool:
        return any(
            getattr(before, field) != getattr(after, field)
            for field in _SHARED_FIELDS
        )

    def _require_available_style(self, style_id: int) -> None:
        if style_id not in {style.id for style in self._styles()}:
            raise WebSettingsValidation("Selected Style is not available on the Mac")

    def _settings_guard(self, identifier: str, revision: int):
        from .web_sessions import WebSessionConflict

        session = self._session(identifier)
        if session.revision != revision:
            raise WebSessionConflict(
                "Batch was changed in another tab", code="revision_conflict"
            )
        if self._active is not None:
            raise WebSessionConflict(
                "Wait for the running operation", code="worker_busy"
            )
        return session

    def set_item_voice(
        self, identifier: str, revision: int, item_id: str, *,
        style_id: int, speed: float,
    ) -> dict[str, Any]:
        from .web_sessions import WebSessionNotFound

        with self._lock:
            session = self._settings_guard(identifier, revision)
            try:
                item = session.batch.get_item(item_id)
            except KeyError:
                raise WebSessionNotFound("Batch item not found") from None
            try:
                new_settings = replace(
                    item.session.settings, style_id=style_id, speed=speed
                )
            except (SettingsError, TypeError, ValueError) as exc:
                raise WebSettingsValidation("Style or Speed is invalid") from exc
            if new_settings == item.session.settings:
                return self._batch_snapshot(session)
            self._require_available_style(style_id)
            try:
                # This intentionally reconfigures future regeneration without
                # removing existing candidates or their acceptance markers.
                item.session.replace_settings(new_settings, preserve_takes=True)
            except (ValueError, RuntimeError, OSError) as exc:
                raise WebSettingsValidation(
                    "Item Style/Speed could not be applied"
                ) from exc
            session.preview_audio = None
            session.revision += 1
            return self._batch_snapshot(session)

    def save_common_synthesis(
        self, identifier: str, revision: int, settings_revision: int, *,
        style_id: int, speed: float, top_k: int, top_p: float,
        temperature: float,
    ) -> dict[str, Any]:
        from .web_sessions import WebSessionConflict

        with self._lock:
            session = self._settings_guard(identifier, revision)
            if self._settings_revision != settings_revision:
                raise WebSessionConflict(
                    "Common settings were changed in another tab",
                    code="settings_revision_conflict",
                )
            previous = self._recipe_settings()
            try:
                updated = replace(
                    previous, style_id=style_id, speed=speed,
                    top_k=top_k, top_p=top_p, temperature=temperature,
                )
            except (SettingsError, TypeError, ValueError) as exc:
                raise WebSettingsValidation("Invalid synthesis settings") from exc

            changed_names = {
                name for name in _SHARED_FIELDS
                if getattr(previous, name) != getattr(updated, name)
            }
            if "style_id" in changed_names:
                self._require_available_style(style_id)

            # TUI full Apply reconciles shared sampling values even for
            # imported recipe items with older values. Item Style/Speed are
            # retained unless that particular global field was changed.
            targets = []
            for owned_session in self._sessions.values():
                for item in owned_session.batch.items:
                    original = item.session.settings
                    changes = {
                        name: getattr(updated, name)
                        for name in _SHARED_FIELDS
                        if name not in {"style_id", "speed"}
                        or name in changed_names
                    }
                    target = replace(original, **changes)
                    if target != original:
                        adapter = getattr(item.session, "_adapter", None)
                        if adapter is not None:
                            try:
                                get_style(adapter.voiceger_root, target.style_id)
                            except (ValueError, OSError, AttributeError) as exc:
                                raise WebSettingsValidation(
                                    "An item's Style is unavailable on the Mac"
                                ) from exc
                        targets.append((owned_session, item, target))

            if not changed_names and not targets:
                return self._settings_view(session)

            # Only an accepted save is applied in memory. No temporary Takes
            # are modified if filesystem persistence fails.
            if changed_names:
                try:
                    save_settings(updated)
                except (OSError, SettingsError) as exc:
                    raise WebSettingsUnavailable(
                        "Could not save settings on the Mac"
                    ) from exc

            affected_sessions: set[str] = set()
            for owned_session, item, target in targets:
                synthesis_changed = self._changed_synthesis(
                    item.session.settings, target
                )
                item.session.replace_settings(target)
                if synthesis_changed:
                    item.clear_acceptance()
                    item.clear_generation_outcome()
                owned_session.preview_audio = None
                affected_sessions.add(owned_session.identifier)

            self._batch_settings = updated
            self._settings_revision += 1
            for owned_session in self._sessions.values():
                if changed_names or owned_session.identifier in affected_sessions:
                    owned_session.revision += 1
            return self._settings_view(session)
