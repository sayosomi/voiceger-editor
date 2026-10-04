"""Runtime and persistence policy for TUI settings application."""

from __future__ import annotations

from dataclasses import replace
import os
from typing import Any, Callable, Sequence

from .settings import Settings, SettingsError
from .tui_editors import SettingsApplicationResult
from .tui_status import Status, error_status, info_status


_SYNTHESIS_SETTING_NAMES = (
    "style_id",
    "speed",
    "top_k",
    "top_p",
    "temperature",
)


class TuiSettingsController:
    """Own runtime settings reconciliation and persistence semantics."""

    def __init__(
        self,
        *,
        settings: Settings,
        persisted_settings: Settings | None,
        config_path: str | os.PathLike[str] | None,
        operations: Any,
        sessions: Callable[[], Sequence[Any]],
        active_session: Callable[[], Any | None],
        set_batch_take_count: Callable[[int], None],
        set_status: Callable[[Status], None],
        save: Callable[[Settings, str | os.PathLike[str] | None], Any],
    ) -> None:
        self.settings = settings
        self.persisted_settings = persisted_settings or settings
        self.config_path = config_path
        self._operations = operations
        self._sessions = sessions
        self._active_session = active_session
        self._set_batch_take_count = set_batch_take_count
        self._set_status = set_status
        self._save = save

    def change(
        self,
        *,
        report_success: bool = True,
        **changes: Any,
    ) -> None:
        """Apply a partial interactive change and persist only those fields."""

        try:
            updated = replace(self.settings, **changes)
            synthesis_changed = self._synthesis_changed(
                updated,
                self.settings,
            )
            if synthesis_changed:
                self._operations.stop_playback()
            for session in self._sessions():
                session.replace_settings(updated)
        except (SettingsError, ValueError) as exc:
            self._set_status(error_status(f"Settings were not changed: {exc}"))
            return

        self.settings = updated
        self._set_batch_take_count(updated.take_count)

        try:
            persisted = replace(self.persisted_settings, **changes)
        except SettingsError as exc:
            self._set_status(
                error_status(
                    "Settings changed for this run but were not saved: "
                    f"{exc}"
                )
            )
            return

        self.persisted_settings = persisted
        if synthesis_changed:
            self._operations.clear_current_take()

        try:
            self._save(persisted, self.config_path)
        except OSError as exc:
            self._set_status(
                error_status(
                    "Settings changed for this run but could not be saved: "
                    f"{exc}"
                )
            )
        else:
            if report_success:
                self._set_status(
                    info_status(
                        "Settings saved. Existing temporary takes were cleared."
                        if synthesis_changed
                        else "Settings saved. Existing temporary takes were preserved."
                    )
                )

    def apply_target(self, target: Settings) -> SettingsApplicationResult:
        """Apply and persist the complete Settings target from the editor."""

        session = self._active_session()
        baseline = session.settings if session is not None else self.settings
        runtime_changed = target != self.settings or target != baseline
        synthesis_changed = self._synthesis_changed(target, baseline)

        if runtime_changed:
            try:
                if synthesis_changed:
                    self._operations.stop_playback()
                for owned_session in self._sessions():
                    owned_session.replace_settings(target)
            except (SettingsError, ValueError) as exc:
                status = error_status(f"Settings were not changed: {exc}")
                self._set_status(status)
                return SettingsApplicationResult(error_status=status)

            self.settings = target
            self._set_batch_take_count(target.take_count)
            if synthesis_changed:
                self._operations.clear_current_take()

        try:
            self._save(target, self.config_path)
        except (OSError, SettingsError) as exc:
            failure = (
                "Settings changed for this run but could not be saved"
                if runtime_changed
                else "Settings could not be saved"
            )
            status = error_status(f"{failure}: {exc}")
            self._set_status(status)
            return SettingsApplicationResult(error_status=status)

        self.persisted_settings = target
        self._set_status(info_status("Settings saved."))
        return SettingsApplicationResult()

    @staticmethod
    def _synthesis_changed(target: Settings, baseline: Settings) -> bool:
        return any(
            getattr(target, name) != getattr(baseline, name)
            for name in _SYNTHESIS_SETTING_NAMES
        )
