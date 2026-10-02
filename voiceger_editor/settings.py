"""Load and save the adapter's reusable user settings."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import sys
from typing import Any


_APP_DIRECTORY = "voiceger-editor"
_CONFIG_FILENAME = "config.json"
VOICEGER_DEFAULT_TOP_K = 20
VOICEGER_DEFAULT_TOP_P = 1.0
VOICEGER_DEFAULT_TEMPERATURE = 1.0
_SETTING_NAMES = {
    "output_dir",
    "take_count",
    "style_id",
    "speed",
    "top_k",
    "top_p",
    "temperature",
    "save_text",
    "save_lab",
}


class SettingsError(ValueError):
    """Raised when a settings file or settings value is invalid."""


def _default_output_dir() -> Path:
    # Keep the existing adapter output location as the reusable default.
    return Path.home() / ".voiceger-editor" / "output"


@dataclass(frozen=True)
class Settings:
    """UI-neutral settings shared by future command-line and TUI entry points."""

    output_dir: Path = field(default_factory=_default_output_dir)
    take_count: int = 4
    style_id: int = 3
    speed: float = 1.0
    top_k: int = VOICEGER_DEFAULT_TOP_K
    top_p: float = VOICEGER_DEFAULT_TOP_P
    temperature: float = VOICEGER_DEFAULT_TEMPERATURE
    save_text: bool = False
    save_lab: bool = False

    def __post_init__(self) -> None:
        try:
            raw_output_dir = os.fspath(self.output_dir)
        except TypeError as exc:
            raise SettingsError("output_dir must be a filesystem path") from exc
        if (
            not isinstance(raw_output_dir, str)
            or not raw_output_dir
            or "\x00" in raw_output_dir
        ):
            raise SettingsError("output_dir must be a non-empty filesystem path")
        try:
            output_dir = Path(raw_output_dir).expanduser()
        except (RuntimeError, ValueError) as exc:
            raise SettingsError(f"invalid output_dir: {exc}") from exc
        object.__setattr__(self, "output_dir", output_dir)

        if (
            isinstance(self.take_count, bool)
            or not isinstance(self.take_count, int)
            or not 1 <= self.take_count <= 100
        ):
            raise SettingsError("take_count must be an integer from 1 through 100")

        if (
            isinstance(self.style_id, bool)
            or not isinstance(self.style_id, int)
            or self.style_id <= 0
        ):
            raise SettingsError("style_id must be a positive integer")

        if isinstance(self.speed, bool) or not isinstance(self.speed, (int, float)):
            raise SettingsError("speed must be a positive finite number")
        try:
            speed = float(self.speed)
        except OverflowError as exc:
            raise SettingsError("speed must be a positive finite number") from exc
        if not math.isfinite(speed) or speed <= 0:
            raise SettingsError("speed must be a positive finite number")
        object.__setattr__(self, "speed", speed)

        if (
            isinstance(self.top_k, bool)
            or not isinstance(self.top_k, int)
            or not 1 <= self.top_k <= 100
        ):
            raise SettingsError("top_k must be an integer from 1 through 100")

        for name in ("top_p", "temperature"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SettingsError(
                    f"{name} must be a finite number from 0.00 through 1.00"
                )
            try:
                value = float(value)
            except OverflowError as exc:
                raise SettingsError(
                    f"{name} must be a finite number from 0.00 through 1.00"
                ) from exc
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise SettingsError(
                    f"{name} must be a finite number from 0.00 through 1.00"
                )
            object.__setattr__(self, name, value)

        if not isinstance(self.save_text, bool):
            raise SettingsError("save_text must be a boolean")
        if not isinstance(self.save_lab, bool):
            raise SettingsError("save_lab must be a boolean")


def _windows_config_home() -> Path:
    configured = os.environ.get("APPDATA")
    if configured:
        return Path(configured).expanduser()
    user_profile = os.environ.get("USERPROFILE")
    home = Path(user_profile).expanduser() if user_profile else Path.home()
    return home / "AppData" / "Roaming"


def default_config_path() -> Path:
    """Return the platform-appropriate path for the user settings file."""

    if sys.platform == "win32":
        config_home = _windows_config_home()
    elif sys.platform == "darwin":
        config_home = Path.home() / "Library" / "Application Support"
    else:
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
        config_home = (
            Path(xdg_config_home).expanduser()
            if xdg_config_home
            else Path.home() / ".config"
        )
    return config_home / _APP_DIRECTORY / _CONFIG_FILENAME


def _resolve_config_path(config_path: str | os.PathLike[str] | None) -> Path:
    if config_path is None:
        return default_config_path()
    try:
        return Path(config_path).expanduser()
    except (TypeError, RuntimeError, ValueError) as exc:
        raise SettingsError(f"invalid config path: {exc}") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in pairs:
        if key in values:
            raise SettingsError(f"duplicate setting {key!r}")
        values[key] = value
    return values


def load_settings(
    config_path: str | os.PathLike[str] | None = None,
) -> Settings:
    """Load settings from ``config_path`` or the user's default config file.

    An absent file returns defaults. Present files must contain a JSON object;
    omitted known settings use their defaults, while unknown or invalid values
    raise :class:`SettingsError` instead of being discarded.
    """

    path = _resolve_config_path(config_path)
    try:
        contents = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Settings()
    except UnicodeDecodeError as exc:
        raise SettingsError(f"{path}: config is not valid UTF-8") from exc

    try:
        values = json.loads(contents, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise SettingsError(
            f"{path}: malformed JSON at line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}"
        ) from exc
    except SettingsError as exc:
        raise SettingsError(f"{path}: {exc}") from exc

    if not isinstance(values, dict):
        raise SettingsError(f"{path}: config must be a JSON object")

    unknown = sorted(set(values) - _SETTING_NAMES)
    if unknown:
        names = ", ".join(repr(name) for name in unknown)
        raise SettingsError(f"{path}: unknown setting(s): {names}")

    try:
        return Settings(**values)
    except SettingsError as exc:
        raise SettingsError(f"{path}: {exc}") from exc


def save_settings(
    settings: Settings,
    config_path: str | os.PathLike[str] | None = None,
) -> Path:
    """Write validated settings as stable, UTF-8 JSON and return the file path."""

    if not isinstance(settings, Settings):
        raise TypeError("settings must be a Settings instance")

    path = _resolve_config_path(config_path)
    payload = {
        "output_dir": str(settings.output_dir),
        "take_count": settings.take_count,
        "style_id": settings.style_id,
        "speed": settings.speed,
        "top_k": settings.top_k,
        "top_p": settings.top_p,
        "temperature": settings.temperature,
        "save_text": settings.save_text,
        "save_lab": settings.save_lab,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((serialized + "\n").encode("utf-8"))
    return path
