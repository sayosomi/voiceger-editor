# voiceger-accent-adapter

An experimental adapter for controllable Japanese pronunciation and accent/prosody with [Voiceger](https://github.com/zunzun999/voiceger_v2).

## Goal

Provide a stable layer between user-editable Japanese pronunciation notation and Voiceger / GPT-SoVITS without vendoring or redistributing Voiceger itself.

The intended workflow is:

```text
Japanese text
    ↓
OpenJTalk-based automatic pronunciation/prosody
    ↓
editable pronunciation notation
    ↓
voiceger-accent-adapter
    ↓
Voiceger / GPT-SoVITS
    ↓
audio
```

## Core ideas

- Keep display text and spoken pronunciation separate.
- Generate a usable pronunciation automatically from Japanese text.
- Allow manual correction using a VOICEVOX-style / AquesTalk-style notation.
- Every accent phrase has exactly one `'`; `あ'め` means accent position 1 and `あめ'` means accent position 2.
- Use `/` for a no-pause accent-phrase boundary.
- Accept both hiragana and katakana in the editable notation.
- Prefer an explicitly supplied pronunciation over automatic analysis.
- Return the resolved pronunciation actually used for synthesis.
- Isolate Voiceger-specific integration behind an adapter so the pronunciation/prosody core can be tested independently.
- Do not copy or redistribute Voiceger source code, models, reference audio, or other Voiceger assets in this repository.

## Validated path

Local spikes have validated the complete path without modifying Voiceger files:

```text
text
  -> OpenJTalk
  -> editable pronunciation
  -> parser
  -> Voiceger-compatible G2P tokens
  -> runtime hook
  -> natural audio
```

For example:

```text
雨 -> ア'メ -> a ] m e
飴 -> アメ' -> a [ m e
```

At the Japanese G2P hook point, `/` is converted to OpenJTalk's `#` boundary token. Voiceger v2's existing `clean_text()` then converts `#` to `UNK`, reproducing the normal Voiceger frontend path. Dropping the boundary token entirely was tested and can destabilize synthesis.

## API

The current development API provides:

```http
POST /pronunciation
POST /tts
```

v1 currently supports one Japanese utterance per request (no embedded newlines).

### Run with the existing Voiceger environment

Assuming Voiceger is installed at `~/voiceger_v2`, first install this adapter and its API-only dependencies into Voiceger's existing virtualenv:

```bash
cd ~/Code/voiceger-accent-adapter
~/voiceger_v2/.venv/bin/python -m pip install -e '.[api]'
```

Then start the API:

```bash
cd ~/Code/voiceger-accent-adapter

~/voiceger_v2/.venv/bin/python -m uvicorn \
  voiceger_accent_adapter.api:app \
  --host 127.0.0.1 \
  --port 8001
```

Override the Voiceger location when needed:

```bash
VOICEGER_ROOT=/path/to/voiceger_v2 \
  /path/to/voiceger/.venv/bin/python -m uvicorn \
  voiceger_accent_adapter.api:app \
  --host 127.0.0.1 \
  --port 8001
```

### Automatic pronunciation

```bash
curl -s http://127.0.0.1:8001/pronunciation \
  -H 'Content-Type: application/json' \
  -d '{"text":"今日は雨ですね。"}'
```

Expected shape:

```json
{
  "text": "今日は雨ですね。",
  "pronunciation": "キョ'ーワ/ア'メデスネ。",
  "source": "openjtalk"
}
```

### Synthesis with automatic pronunciation

```bash
curl -s http://127.0.0.1:8001/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"今日は雨ですね。"}'
```

### Synthesis with a manual override

```bash
curl -s http://127.0.0.1:8001/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"今日は雨ですね。","pronunciation":"キョ'\''ーワ/アメデスネ'\''。"}'
```

Output WAV filenames follow VOICEVOX's default naming shape:

```text
001_ずんだもん（style_1）_今日は雨ですね。.wav
002_ずんだもん（style_1）_明日の天気は晴….wav
```

The default character/style labels are `ずんだもん` and `style_1`. Override them with `VOICEGER_CHARACTER_NAME` and `VOICEGER_STYLE_NAME` when needed. The text fragment is sanitized and shortened with the same 10-character rule used by VOICEVOX.

The response includes the canonical pronunciation actually used and the generated filename:

```json
{
  "message": "success",
  "resolved_pronunciation": "...",
  "file_name": "001_ずんだもん（style_1）_今日は雨ですね。.wav",
  "file_path": "...",
  "sampling_rate": 32000
}
```

Generated WAV files use a readable local timestamp + source-text filename:

```text
20260927142800_今日は雨ですね。.wav
20260927142800_今日は雨ですね。_2.wav
```

Characters that are unsafe in common filesystems are replaced with `_`, and very long source text is truncated in the filename only.

See [docs/japanese-pronunciation.md](docs/japanese-pronunciation.md) for the current design.

## Upstream dependency

Voiceger is developed separately at:

https://github.com/zunzun999/voiceger_v2

This repository is not a fork and does not contain Voiceger itself. Runtime integration imports the locally installed Voiceger / GPT-SoVITS modules and temporarily hooks the Japanese G2P path during synthesis.

## Status

Early implementation. The pronunciation and runtime-injection path is validated locally; the HTTP API is now ready for local integration testing.

## License

Not selected yet. Before public release, only code authored in this repository should be licensed here; Voiceger and its dependencies remain subject to their own terms.
