"""Isolated Android/Tailscale Web E2E for Issue #327.

Runs the tested source checkout, not a previously installed package.
Only scratch/issue327-e2e contains temporary settings, dictionaries and audio.
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
BRANCH = "sayosomi/issue-327-web-slice-10a"
ORIGINS = frozenset({
    "https://github.com/sayosomi/voiceger-editor",
    "https://github.com/sayosomi/voiceger-editor.git",
    "git@github.com:sayosomi/voiceger-editor.git",
})
SCRATCH = REPOSITORY / "scratch" / "issue327-e2e"
PORT = 8002


class LaunchBlocked(RuntimeError):
    pass


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
        raise LaunchBlocked("Repository path is not the expected checkout")
    if _git("remote", "get-url", "origin") not in ORIGINS:
        raise LaunchBlocked("Unexpected Git origin; no files were modified")
    current = _git("branch", "--show-current")
    if current not in {"main", BRANCH}:
        raise LaunchBlocked("Expected clean main or " + BRANCH + "; found " + current)
    if _git("status", "--porcelain"):
        raise LaunchBlocked("Uncommitted/untracked files exist; no checkout changes were made")

    _git("fetch", "origin", "--prune")
    remote = _git("rev-parse", "--verify", "refs/remotes/origin/" + BRANCH)
    if current == "main":
        main = _git("rev-parse", "--verify", "refs/remotes/origin/main")
        local = _git("rev-parse", "HEAD")
        if local != main:
            if subprocess.run(
                ["git", "-C", str(REPOSITORY), "merge-base", "--is-ancestor",
                 local, main], check=False,
            ).returncode:
                raise LaunchBlocked("Local main diverged; no switch/merge performed")
            _git("merge", "--ff-only", "refs/remotes/origin/main")
        exists = subprocess.run(
            ["git", "-C", str(REPOSITORY), "show-ref", "--quiet", "--verify",
             "refs/heads/" + BRANCH], check=False,
        ).returncode == 0
        if exists:
            _git("switch", BRANCH)
        else:
            _git("switch", "--track", "-c", BRANCH, "refs/remotes/origin/" + BRANCH)

    local = _git("rev-parse", "HEAD")
    if local != remote:
        if subprocess.run(
            ["git", "-C", str(REPOSITORY), "merge-base", "--is-ancestor",
             local, remote], check=False,
        ).returncode:
            raise LaunchBlocked("Topic branch diverged; no reset or force switch")
        _git("merge", "--ff-only", "refs/remotes/origin/" + BRANCH)

    actual = _git("rev-parse", "HEAD")
    if actual != remote or _git("status", "--porcelain"):
        raise LaunchBlocked("Exact remote HEAD or clean checkout could not be verified")
    return actual


def _prepare_scratch() -> None:
    if SCRATCH.parent.is_symlink() or SCRATCH.is_symlink():
        raise LaunchBlocked("Disposable scratch path is a symlink")
    if SCRATCH.exists() and not SCRATCH.is_dir():
        raise LaunchBlocked("Disposable scratch path is not a directory")
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    (SCRATCH / "output").mkdir(parents=True)
    (SCRATCH / "home").mkdir()


def _check_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        try:
            server.bind(("127.0.0.1", PORT))
        except OSError as exc:
            raise LaunchBlocked("Port 8002 is occupied; stop the prior E2E server") from exc


def _copy_current_terms_acceptance(source: Path, destination: Path) -> None:
    """Reuse only the Mac user's validated current consent in disposable HOME."""
    from voiceger_editor.terms_acceptance import current_acceptance_status

    if not current_acceptance_status(source).accepted:
        raise LaunchBlocked(
            "Current Voiceger terms are not accepted on the Mac. "
            "Review the official terms and run "
            "'voiceger-editor --accept-voiceger-terms' locally."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if not current_acceptance_status(destination).accepted:
        raise LaunchBlocked("The isolated terms acceptance copy failed validation")


def main() -> int:
    try:
        head = _verify_and_refresh()
        sys.path.insert(0, str(REPOSITORY))
        from voiceger_editor.terms_acceptance import current_acceptance_status

        real_terms = current_acceptance_status()
        if not real_terms.accepted:
            raise LaunchBlocked(
                "The Mac has no current Voiceger terms acceptance. "
                "Review the official terms and run "
                "'voiceger-editor --accept-voiceger-terms' locally."
            )
        _check_port()
        _prepare_scratch()
    except (LaunchBlocked, OSError) as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 1

    real_home = Path.home()
    token = secrets.token_urlsafe(32)
    os.environ["VOICEGER_ROOT"] = str(real_home / "voiceger_v2")
    os.environ["VOICEGER_WEB_TOKEN"] = token
    # Isolate default_config_path(), so common settings save cannot modify
    # the Human's normal macOS Application Support config.json.
    os.environ["HOME"] = str(SCRATCH / "home")

    try:
        from voiceger_editor.terms_acceptance import default_acceptance_path
        _copy_current_terms_acceptance(real_terms.path, default_acceptance_path())
        from voiceger_editor.settings import Settings
        from voiceger_editor.user_dictionary import UserDictionaryCore
        from voiceger_editor.voiceger_adapter import VoicegerAdapter
        from voiceger_editor.web import create_web_app
        from voiceger_editor.web_sessions import WebSessionOperations
        import uvicorn

        output = SCRATCH / "output"
        adapter = VoicegerAdapter(
            voiceger_root=Path(os.environ["VOICEGER_ROOT"]), output_dir=output,
        )
        adapter.user_dictionary = UserDictionaryCore(
            adapter.voiceger_root, data_directory=SCRATCH / "dictionary",
        )
        service = WebSessionOperations(
            dictionary_adapter=adapter, dictionary_core=adapter.user_dictionary,
        )
        service._batch_settings = Settings(output_dir=output)
        print("E2E HEAD: " + head, flush=True)
        print("ISOLATED SETTINGS: " + str(SCRATCH / "home"), flush=True)
        print("VOICEGER TERMS: validated Mac consent copied to test HOME", flush=True)
        print("ISOLATED OUTPUT: " + str(output), flush=True)
        print("LOCAL URL: http://127.0.0.1:8002", flush=True)
        print("ACCESS TOKEN: " + token, flush=True)
        print("Tailscale Serve: use the existing HTTPS URL to 127.0.0.1:8002", flush=True)
        print("To stop and clean this run: Ctrl+C", flush=True)
        uvicorn.run(create_web_app(service=service), host="127.0.0.1", port=PORT)
        return 0
    except KeyboardInterrupt:
        return 0
    except (LaunchBlocked, OSError) as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 1
    finally:
        if SCRATCH.exists() and not SCRATCH.is_symlink():
            shutil.rmtree(SCRATCH)


if __name__ == "__main__":
    raise SystemExit(main())
