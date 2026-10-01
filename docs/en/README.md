# User Documentation

This is the English user documentation for Voiceger Editor v1.

Voiceger Editor adds pronunciation editing, Take generation, and a VOICEVOX-style API to a local Voiceger installation.

Voiceger itself is installed separately.

## Start here

If this is your first time using Voiceger Editor, read:

1. [Setup](setup.md)
2. [TUI](tui.md)
3. [Pronunciation](pronunciation.md)

The normal setup is:

```text
Install Voiceger
→ set VOICEGER_ROOT
→ install Voiceger Editor from PyPI
→ run --check
→ read and accept the Voiceger:Zundamon terms
→ start the TUI
```

Install the TUI with:

```bash
python -m pip install 'voiceger-editor[tui]'
```

Check the installation with:

```bash
voiceger-editor --version
voiceger-editor --check
```

## Documentation

- [Setup](setup.md) — install Voiceger Editor, configure Voiceger, run diagnostics, and complete first use.
- [TUI](tui.md) — keyboard navigation, editing, Take generation, playback, and saving.
- [Pronunciation](pronunciation.md) — Japanese reading and pitch accent, plus English ARPAbet pronunciation and stress.
- [User Dictionary](dictionary.md) — save, edit, and delete Japanese and English pronunciations.
- [Settings](settings.md) — styles, speed, Takes, output, TXT/LAB, and sampling controls.
- [LAB Output](lab-output.md) — optional phoneme-timing sidecars and their requirements.
- [HTTP API](api.md) — VOICEVOX-style API setup, endpoints, and request examples.
- [Compatibility](compatibility.md) — tested Voiceger revision, language scope, and compatibility limits.

## Supported v1 scope

The documented v1 speech scope is:

- Japanese;
- Japanese with English sections.

Japanese supports editable reading and pitch accent.

English sections support editable ARPAbet pronunciation and stress.

See [Compatibility](compatibility.md) for the exact boundary.

## Generated audio and licenses

Audio generated through Voiceger:Zundamon is **not covered by the MIT License of Voiceger Editor**.

You must follow the official Voiceger:Zundamon terms when using generated audio:

https://zunko.jp/con_ongen_kiyaku.html

The full terms and license boundary is kept directly in the root [README](../../README.md).
