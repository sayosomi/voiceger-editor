# User Documentation

This is the English user documentation for Voiceger Editor 0.1.

Voiceger Editor adds pronunciation editing, Take generation, and a VOICEVOX-style API to a local Voiceger installation.

Voiceger itself is installed separately.

## Start here

For first-time setup, read:

1. [Setup](setup.md)
2. [TUI](tui.md)
3. [Pronunciation](pronunciation.md)

The normal setup is:

```text
Install Voiceger
→ set VOICEGER_ROOT
→ install Voiceger Editor from PyPI
→ run --check
→ accept the Voiceger:Zundamon terms
→ start the TUI
```

## Guides

- [Setup](setup.md) — install from PyPI, configure Voiceger, run diagnostics, and complete first use.
- [TUI](tui.md) — keyboard navigation, editing, Take generation, playback, and saving.
- [Pronunciation](pronunciation.md) — Japanese pronunciation and pitch accent, plus English ARPAbet and stress.
- [User Dictionary](dictionary.md) — Japanese and English reusable pronunciation entries.
- [Settings](settings.md) — styles, speed, Takes, output, TXT/LAB, and sampling controls.
- [LAB Output](lab-output.md) — optional phoneme-timing sidecars and their extra requirements.
- [HTTP API](api.md) — VOICEVOX-style API installation, endpoints, and examples.
- [Compatibility](compatibility.md) — tested Voiceger revision, language scope, and compatibility limits.

## Supported 0.1 scope

The documented 0.1 speech scope is:

- Japanese;
- Japanese with English sections.

Japanese pronunciation and pitch accent can be edited.

English sections can use editable ARPAbet pronunciation and stress.

## Project names

The public 0.1 names are:

```text
Product:        Voiceger Editor
Repository:     sayosomi/voiceger-editor
PyPI:           voiceger-editor
CLI:            voiceger-editor
Python package: voiceger_editor
```

## Terms and license

Generated Voiceger:Zundamon audio is not covered by the MIT License of Voiceger Editor.

The important generated-audio terms and license boundary are kept directly in the root [README](../../README.md).
