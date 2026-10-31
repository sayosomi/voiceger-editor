"""Run isolated Issue #325 dictionary import mobile Web E2E against a fresh safe checkout.

Usage (from ~/Code/voiceger-editor):
    ~/voiceger_v2/.venv/bin/python scripts/run_web_e2e_325.py

The script does not modify Voiceger, real user settings, or accepted audio.
Accepts clean main or a clean topic branch, fast-forwards only; never resets/stashes.
"""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys


REPOSITORY = Path(__file__).resolve().parents[1]
BRANCH = "sayosomi/issue-325-web-dictionary-import"
ORIGINS = frozenset({
    "https://github.com/sayosomi/voiceger-editor",
    "https://github.com/sayosomi/voiceger-editor.git",
    "git@github.com:sayosomi/voiceger-editor.git",
})
SCRATCH = REPOSITORY / "scratch" / "issue325-e2e"
PORT = 8002


class LaunchBlocked(RuntimeError):
    """A local safety precondition was not met."""


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPOSITORY), *args],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise LaunchBlocked(
            "git " + " ".join(args) + " failed: " +
            (result.stderr.strip() or result.stdout.strip() or "unknown error")
        )
    return result.stdout.strip()


def _verify_and_refresh() -> str:
    if _git("rev-parse", "--show-toplevel") != str(REPOSITORY):
        raise LaunchBlocked("Repository identity mismatch")
    origin = _git("remote", "get-url", "origin")
    if origin not in ORIGINS:
        raise LaunchBlocked("Unexpected origin: " + origin)
    current = _git("branch", "--show-current")
    if current not in {"main", BRANCH}:
        raise LaunchBlocked("Expected main or " + BRANCH + "; current: " + current)
    if _git("status", "--porcelain"):
        raise LaunchBlocked("Uncommitted or untracked changes exist; nothing was overwritten")
    _git("fetch", "origin", "--prune")
    remote = _git("rev-parse", "--verify", "refs/remotes/origin/" + BRANCH)
    if current == "main":
        base = _git("rev-parse", "--verify", "refs/remotes/origin/main")
        local_main = _git("rev-parse", "--verify", "HEAD")
        if local_main != base:
            ancestor = subprocess.run(
                ["git", "-C", str(REPOSITORY), "merge-base", "--is-ancestor",
                 local_main, base], capture_output=True,
            )
            if ancestor.returncode != 0:
                raise LaunchBlocked("Local main diverged; no reset or merge")
            _git("merge", "--ff-only", "refs/remotes/origin/main")
        exists = subprocess.run(
            ["git", "-C", str(REPOSITORY), "show-ref", "--verify", "--quiet",
             "refs/heads/" + BRANCH], check=False,
        ).returncode == 0
        if exists:
            _git("switch", BRANCH)
        else:
            _git("switch", "--track", "-c", BRANCH,
                 "refs/remotes/origin/" + BRANCH)
    local = _git("rev-parse", "--verify", "HEAD")
    if local != remote:
        ancestor = subprocess.run(
            ["git", "-C", str(REPOSITORY), "merge-base", "--is-ancestor", local, remote],
            check=False, capture_output=True, text=True,
        )
        if ancestor.returncode != 0:
            raise LaunchBlocked("Local branch diverged from origin; no reset or merge")
        _git("merge", "--ff-only", "refs/remotes/origin/" + BRANCH)
    updated = _git("rev-parse", "--verify", "HEAD")
    if updated != remote or _git("status", "--porcelain"):
        raise LaunchBlocked("Could not verify clean exact remote HEAD after fast-forward")
    return updated


def _prepare_scratch() -> Path:
    parent = SCRATCH.parent
    if parent.is_symlink() or SCRATCH.is_symlink():
        raise LaunchBlocked("Scratch path is a symbolic link; refusing cleanup")
    if SCRATCH.exists() and not SCRATCH.is_dir():
        raise LaunchBlocked("Scratch path is not a directory; refusing cleanup")
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)  # Only this exact disposable issue folder.
    output = SCRATCH / "output"
    output.mkdir(parents=True)
    return output


def _check_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", PORT))
        except OSError as exc:
            raise LaunchBlocked("Port 8002 is already in use; stop the old E2E server") from exc


def main() -> int:
    try:
        head = _verify_and_refresh()
        _check_port()
        output = _prepare_scratch()
    except (LaunchBlocked, OSError) as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 1

    token = secrets.token_urlsafe(32)
    os.environ["VOICEGER_ROOT"] = str(Path.home() / "voiceger_v2")
    os.environ["VOICEGER_WEB_TOKEN"] = token

    # Executing scripts/*.py must load this exact checkout, never an older
    # installed package or a previously imported product module.
    sys.path.insert(0, str(REPOSITORY))

    try:
        from voiceger_editor.voiceger_adapter import VoicegerAdapter
        from voiceger_editor.user_dictionary import UserDictionaryCore
        from voiceger_editor.session import UtteranceSession
        from voiceger_editor.settings import Settings
        from voiceger_editor.web import create_web_app
        from voiceger_editor.web_sessions import WebSessionOperations
        import uvicorn

        adapter = VoicegerAdapter(
            voiceger_root=Path(os.environ["VOICEGER_ROOT"]),
            output_dir=output,
        )
        # All dictionary edits stay inside this disposable E2E directory.
        # Never modify normal user dictionary files.
        adapter.user_dictionary = UserDictionaryCore(
            adapter.voiceger_root, data_directory=SCRATCH / "dictionary"
        )
        # Seed only the disposable user dictionary so both output formats and
        # the VOICEVOX pitch-loss warning can be tested without touching real words.
        from voiceger_editor.pronunciation import PitchEvent
        adapter.user_dictionary.add_japanese_word(
            surface="雨", pronunciation="アメ", accent_type=1,
        )
        adapter.user_dictionary.add_japanese_word(
            surface="スタックチャン", pronunciation="スタックチャン",
            accent_type=2, pitch_events=(
                PitchEvent(1, "["), PitchEvent(2, "]"),
                PitchEvent(4, "["), PitchEvent(5, "]"),
            ),
        )
        adapter.user_dictionary.add_english_entry(
            "sweet", ["S", "W", "IY1", "T"],
        )
        # A separate disposable dictionary supplies NEW and CONFLICT entries.
        from voiceger_editor.dictionary_export import (
            export_voiceger_editor_dictionaries, export_voicevox_dictionary,
        )
        incoming = UserDictionaryCore(
            adapter.voiceger_root, data_directory=SCRATCH / "incoming"
        )
        incoming.add_japanese_word(
            surface="雨", pronunciation="アメ", accent_type=0,
        )
        incoming.add_japanese_word(
            surface="太陽", pronunciation="タイヨー", accent_type=1,
        )
        incoming.add_english_entry("sweet", ["S", "W", "EH1", "T"])
        incoming.add_english_entry("zunda", ["Z", "UW1", "N", "D", "AH0"])
        zip_file = export_voiceger_editor_dictionaries(incoming, output).paths[0]
        json_file = export_voicevox_dictionary(incoming, output).paths[0]
        print("IMPORT ZIP: " + zip_file.name, flush=True)
        print("IMPORT JSON: " + json_file.name, flush=True)
        settings = Settings(output_dir=output, save_text=True)

        def factory(caption: str) -> UtteranceSession:
            return UtteranceSession.from_caption(
                adapter=adapter, caption=caption, settings=settings,
            )

        service = WebSessionOperations(
            caption_factory=factory,
            dictionary_core=adapter.user_dictionary,
            dictionary_adapter=adapter,
        )
        # The Web export writer reads the shared Settings owner, not the
        # caption factory. Keep ALL export bytes in this disposable folder.
        service._batch_settings = settings
        web_app = create_web_app(service=service)
        print("E2E HEAD: " + head, flush=True)
        print("ISOLATED DICTIONARY: " + str(SCRATCH / "dictionary"), flush=True)
        print("LOCAL URL: http://127.0.0.1:8002", flush=True)
        print("ACCESS TOKEN: " + token, flush=True)
        print("Tailscale Serve: use your existing HTTPS URL targeting 127.0.0.1:8002", flush=True)
        print("To stop and clean this test's temporary files: Ctrl+C", flush=True)
        uvicorn.run(web_app, host="127.0.0.1", port=PORT)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        # Keep normal settings and audio untouched. An interrupted process is
        # cleaned at the next start using the same one canonical scratch path.
        if SCRATCH.exists() and not SCRATCH.is_symlink():
            shutil.rmtree(SCRATCH)


if __name__ == "__main__":
    raise SystemExit(main())
