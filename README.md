# Voiceger Editor

Voiceger Editor is a pronunciation and synthesis editor for [Voiceger](https://github.com/zunzun999/voiceger_v2).

It adds:

- a keyboard-first TUI;
- Japanese pronunciation and pitch-accent editing;
- English ARPAbet pronunciation and stress editing;
- multiple generated Takes;
- Japanese and English user dictionaries;
- optional TXT and LAB output;
- a VOICEVOX-style HTTP API.

Voiceger itself is not included or modified.

> [!IMPORTANT]
> Audio generated with Voiceger:Zundamon is **not covered by the MIT License of Voiceger Editor**.
>
> Generated audio is subject to the official Voiceger:Zundamon terms:
>
> https://zunko.jp/con_ongen_kiyaku.html
>
> Credit is required when using generated audio.

## Quick Start

Install Voiceger separately and set its path.

On macOS or Linux:

```bash
export VOICEGER_ROOT="$HOME/voiceger_v2"
source "$VOICEGER_ROOT/.venv/bin/activate"
```

On Windows PowerShell:

```powershell
$env:VOICEGER_ROOT = "$HOME\voiceger_v2"
& "$env:VOICEGER_ROOT\.venv\Scripts\Activate.ps1"
```

Voiceger Editor 0.1 is tested with Voiceger revision:

```text
f77c1172baf1f490bb962f2d2acd01c852ef3464
```

Install Voiceger Editor from PyPI:

```text
python -m pip install "voiceger-editor[tui]"
```

On Windows, TUI playback requires `ffplay.exe` in `PATH`. Use an FFmpeg build that includes `ffplay.exe`.

Check the installation:

```bash
voiceger-editor --version
voiceger-editor --check
```

Start the TUI:

```bash
voiceger-editor
```

Or start with text:

```bash
voiceger-editor "このずんだ餅はvery sweetなのだ。"
```

On first use, read and explicitly accept the Voiceger:Zundamon terms before synthesis.

See [Setup](docs/en/setup.md) for the complete installation guide.

## Basic Workflow

```text
BATCH LIST
→ Enter a Caption
→ BATCH ITEM n/m
→ check or edit pronunciation
→ Generate
→ listen to Takes
→ accept one Take
```

The supported 0.1 speech scope is:

- Japanese;
- Japanese with English sections.

0.1.0 is the initial public release. Interfaces may still change before 1.0.

See [Compatibility](docs/en/compatibility.md) for details.

## HTTP API

Install API support:

```text
python -m pip install "voiceger-editor[api]"
```

Start it with:

```text
python -m uvicorn voiceger_editor.api:app --host 127.0.0.1 --port 8001
```

The API provides a VOICEVOX-style workflow:

```text
text
→ /audio_query
→ edit query
→ /synthesis
→ WAV
```

The corresponding Zundamon style IDs match VOICEVOX.

See [HTTP API](docs/en/api.md).

## Documentation

- [Setup](docs/en/setup.md)
- [TUI](docs/en/tui.md)
- [Pronunciation](docs/en/pronunciation.md)
- [User Dictionary](docs/en/dictionary.md)
- [Settings](docs/en/settings.md)
- [LAB Output](docs/en/lab-output.md)
- [HTTP API](docs/en/api.md)
- [Compatibility](docs/en/compatibility.md)

See [User Documentation](docs/en/README.md) for the full index.

## Development

All production code in this repository is written by AI coding agents.

The human role focuses on product decisions, supervision, and final UI/UX judgment.

## Generated Audio and License

Voiceger Editor is an unofficial project. It is not made, approved, or supported by the Voiceger project or the Tohoku Zunko / Zundamon Project.

Audio generated with Voiceger:Zundamon is subject to the official terms:

https://zunko.jp/con_ongen_kiyaku.html

The official terms require Voiceger credit. Examples:

```text
Voicegerずんだもん
Voiceger:Zundamon
```

The official terms are authoritative. The notice shown by Voiceger Editor does not replace them.

The code in this repository is licensed under the MIT License.

The MIT License applies **only to this repository's code**. It does not grant rights to Voiceger, GPT-SoVITS, Voiceger models, reference audio, generated audio, the Zundamon character, name, voice, trademarks, or other third-party materials.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for dependency and runtime notices.
