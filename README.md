# voiceger-accent-adapter

An experimental adapter that exposes Voiceger / GPT-SoVITS through a VOICEVOX-style Japanese TTS API with editable accent phrases.

## Goal

Keep Voiceger itself unmodified while providing a workflow close to VOICEVOX ENGINE:

```text
text
  ↓
POST /audio_query?text=...&speaker=...
  ↓
AudioQuery
  ↓
edit accent_phrases if needed
  ↓
POST /synthesis?speaker=...
  ↓
audio/wav
```

The adapter uses OpenJTalk for automatic Japanese pronunciation and injects the resolved prosody into the locally installed Voiceger runtime.

## Pronunciation notation

The editable kana notation follows the core VOICEVOX / AquesTalk-style rules:

- every accent phrase contains exactly one `'`;
- `'` follows the selected mora;
- `/` separates accent phrases without a pause;
- both hiragana and katakana are accepted by this adapter.

Examples:

```text
雨 -> ア'メ
飴 -> アメ'
```

Internally these map to the Voiceger/OpenJTalk prosody tokens already validated against the local Voiceger runtime.

## API

The primary API is intentionally VOICEVOX-style.

```http
POST /audio_query
POST /accent_phrases
POST /synthesis
```

The older experimental `/pronunciation` and `/tts` endpoints are not kept.

v1 supports one Japanese utterance per request; embedded newlines are rejected.

### Start the API

Assuming Voiceger is installed at `~/voiceger_v2`:

```bash
cd ~/Code/voiceger-accent-adapter
~/voiceger_v2/.venv/bin/python -m pip install -e '.[api]'

~/voiceger_v2/.venv/bin/python -m uvicorn \
  voiceger_accent_adapter.api:app \
  --host 127.0.0.1 \
  --port 8001
```

Override the Voiceger location with `VOICEGER_ROOT` when needed.

## Create an AudioQuery

```bash
curl -s -X POST \
  'http://127.0.0.1:8001/audio_query?text=今日は雨ですね。&speaker=1' \
  > query.json
```

The response follows the VOICEVOX-style AudioQuery shape:

```json
{
  "accent_phrases": [
    {
      "moras": [
        {
          "text": "キョ",
          "consonant": "ky",
          "consonant_length": 0,
          "vowel": "o",
          "vowel_length": 0,
          "pitch": 0
        }
      ],
      "accent": 1,
      "pause_mora": null,
      "is_interrogative": false
    }
  ],
  "speedScale": 1,
  "pitchScale": 0,
  "intonationScale": 1,
  "volumeScale": 1,
  "prePhonemeLength": 0.1,
  "postPhonemeLength": 0.1,
  "pauseLength": null,
  "pauseLengthScale": 1,
  "outputSamplingRate": 32000,
  "outputStereo": false,
  "kana": "キョ'ーワ/ア'メデスネ。",
  "text": "今日は雨ですね。"
}
```

`kana` is a readable representation. As with VOICEVOX, synthesis is driven by `accent_phrases`, not by editing `kana` directly.

## Edit an accent

For example, change the second accent phrase to accent position 5:

```bash
jq '.accent_phrases[1].accent = 5' query.json > manual.json
```

You can also create accent phrases directly from editable kana:

```bash
curl -s -X POST \
  'http://127.0.0.1:8001/accent_phrases?text=キョ%27ーワ%2Fアメデスネ%27。&speaker=1&is_kana=true'
```

## Synthesize

```bash
curl -OJ -X POST \
  'http://127.0.0.1:8001/synthesis?speaker=1' \
  -H 'Content-Type: application/json' \
  --data-binary @manual.json
```

`/synthesis` returns `audio/wav`, like VOICEVOX ENGINE. The response also sets a readable `Content-Disposition` filename, so `curl -OJ` keeps the VOICEVOX-style filename automatically.

The adapter also stores the generated WAV under:

```text
~/.voiceger-accent-adapter/output/
```

with a VOICEVOX-style filename:

```text
001_ずんだもん（style_1）_今日は雨ですね。.wav
002_ずんだもん（style_1）_明日の天気は晴れでしょうか….wav
```

The default labels are `ずんだもん` and `style_1`. Override them with:

```bash
VOICEGER_CHARACTER_NAME="ずんだもん"
VOICEGER_STYLE_NAME="style_1"
```

## Current AudioQuery support

The current adapter applies:

- `accent_phrases`
- `speedScale`

The following VOICEVOX-style fields are present in the query for API familiarity but are not implemented yet; changing them currently returns an error rather than silently ignoring them:

- `pitchScale`
- `intonationScale`
- `volumeScale`
- `prePhonemeLength`
- `postPhonemeLength`
- `pauseLength`
- `pauseLengthScale`
- non-32000 `outputSamplingRate`
- `outputStereo=true`

## Validated Voiceger integration

The complete path has been validated locally without modifying Voiceger source files:

```text
text
  -> OpenJTalk
  -> editable pronunciation
  -> AccentPhrase data
  -> Voiceger-compatible G2P tokens
  -> runtime hook
  -> natural audio
```

For the tested local Voiceger version, adapter-generated G2P tokens exactly matched Voiceger's built-in G2P tokens for representative Japanese phrases, including accent-phrase boundaries.

## Upstream dependency

Voiceger is developed separately at:

https://github.com/zunzun999/voiceger_v2

This repository is not a fork and does not contain Voiceger itself. Runtime integration imports the locally installed Voiceger / GPT-SoVITS modules and temporarily hooks the Japanese G2P path during synthesis.

## Status

Early implementation. The pronunciation path, runtime hook, and initial VOICEVOX-style API are validated or ready for local integration testing.

## License

Not selected yet. Before public release, only code authored in this repository should be licensed here; Voiceger and its dependencies remain subject to their own terms.
