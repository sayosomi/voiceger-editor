"""CLI argument and invocation-setting helpers for the terminal interface."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from .settings import Settings


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voiceger-accent-adapter",
        description="Keyboard-first local pronunciation editing and take review.",
    )
    parser.add_argument("text", nargs="?", help="one utterance to edit and synthesize")
    parser.add_argument("--voiceger-root", type=Path, help="Voiceger installation path")
    parser.add_argument("--config", type=Path, help="settings file path")
    parser.add_argument("--output-dir", type=Path, help="override output directory")
    parser.add_argument("--take-count", type=int, help="override take count (1–100)")
    parser.add_argument("--style", type=int, help="override reference style ID")
    parser.add_argument("--speed", type=float, help="override speech speed")
    save_group = parser.add_mutually_exclusive_group()
    save_group.add_argument(
        "--save-text",
        dest="save_text",
        action="store_true",
        help="save an exact source-text sidecar",
    )
    save_group.add_argument(
        "--no-save-text",
        dest="save_text",
        action="store_false",
        help="disable source-text sidecars",
    )
    lab_group = parser.add_mutually_exclusive_group()
    lab_group.add_argument(
        "--save-lab",
        dest="save_lab",
        action="store_true",
        help="generate a LAB phoneme-timing sidecar for accepted pure-language takes",
    )
    lab_group.add_argument(
        "--no-save-lab",
        dest="save_lab",
        action="store_false",
        help="disable LAB sidecars",
    )
    parser.set_defaults(save_text=None, save_lab=None)
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
            ("save_lab", getattr(args, "save_lab", None)),
        )
        if value is not None
    }
    return replace(base, **overrides)
