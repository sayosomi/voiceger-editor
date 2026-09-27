# voiceger-accent-adapter

An experimental adapter that exposes Voiceger / GPT-SoVITS through a VOICEVOX-style Japanese TTS API with editable accent phrases and selectable reference-audio styles.

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

## API

```http
GET  /version
GET  /speakers
POST /audio_query
POST /accent_phrases
POST /synthesis
```

The older experimental `/pronunciation` and `/tts` endpoints are not kept.

v1 supports one Japanese utterance per request; embedded newlines are rejected.

## Start the API

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

## Styles / speaker IDs

The numbered WAV files under Voiceger's local `reference/` directory are exposed as VOICEVOX talk styles.

| speaker | style | reference WAV |
| ---: | --- | --- |
| 1 | Neutral | `01_ref_emoNormal026.wav` |
| 2 | Sweet | `02_ref_emoAma026.wav` |
| 3 | Snippy | `03_ref_emoTsun026.wav` |
| 4 | Sexy | `04_ref_emoSexy026.wav` |
| 5 | Whispering | `05_ref_emoSasa026.wav` |
| 6 | Murmuring | `06_ref_emoMurmur026.wav` |
| 7 | Exhausted | `07_ref_emoHero026.wav` |
| 8 | Sobbing | `08_ref_emoSobbing026.wav` |

Only styles whose reference WAV exists locally are returned by `GET /speakers`.

The preset reference WAVs use the common prompt text:

```text
私はいつもミネラルウォーターを持ち歩いています。
```

Check available styles:

```bash
curl -sS http://127.0.0.1:8001/speakers | jq
```

## Create an AudioQuery

Choose the desired reference-audio style with `speaker`:

```bash
curl -sS -X POST -G \
  'http://127.0.0.1:8001/audio_query' \
  --data-urlencode 'text=今日は雨ですね。' \
  --data-urlencode 'speaker=1' \
  > query.json
```

The returned `AudioQuery` follows the VOICEVOX shape and does not contain adapter-only display-text fields.

The readable `kana` field is included, but synthesis is driven by `accent_phrases`.

## Edit an accent

For example, move the second accent phrase to accent position 5:

```bash
jq '.accent_phrases[1].accent = 5' query.json > manual.json
```

Editable kana can also be converted directly to structured accent phrases:

```bash
curl -sS -X POST -G \
  'http://127.0.0.1:8001/accent_phrases' \
  --data-urlencode "text=キョ'ーワ/アメデスネ'。" \
  --data-urlencode 'speaker=1' \
  --data-urlencode 'is_kana=true'
```

## Synthesize

Use the same or another available style ID when synthesizing:

```bash
curl -sS -X POST \
  'http://127.0.0.1:8001/synthesis?speaker=1' \
  -H 'Content-Type: application/json' \
  --data-binary @manual.json \
  --output result.wav
```

`/synthesis` returns `audio/wav`, like VOICEVOX ENGINE.

The engine API does **not** permanently save the WAV. It creates a temporary WAV for the response and deletes it after transmission. The caller (for example nuiReel or a CLI) chooses the final output filename and destination.

This also means the `AudioQuery` returned by `/audio_query` can be sent directly to `/synthesis`, matching the VOICEVOX workflow.

## Mixed-language text

Pure Japanese requests keep the normal VOICEVOX-shaped `AudioQuery` with no adapter-only extension.

When other languages are detected, `/audio_query` adds an optional `voicegerSegments` field. Japanese segments reference slices of the normal `accent_phrases` array; non-Japanese segments keep their original text and language.

Example concept:

```json
{
  "accent_phrases": [
    "... Japanese accent phrases ..."
  ],
  "kana": null,
  "voicegerSegments": [
    {
      "language": "ja",
      "text": "今日は",
      "accentPhraseStart": 0,
      "accentPhraseCount": 1
    },
    {
      "language": "en",
      "text": "OpenAI"
    },
    {
      "language": "ja",
      "text": "を使うよ。",
      "accentPhraseStart": 1,
      "accentPhraseCount": 2
    }
  ]
}
```

During synthesis:

- Japanese segments use the edited `accent_phrases` and the adapter's Voiceger G2P hook.
- English segments are handled by Voiceger's native `Japanese-English Mixed` path.
- Other detected languages fall back to Voiceger's `Multilingual Mixed` path.
- The original segment order is preserved.

Current automatic segmentation uses Voiceger's bundled LangSegment. Japanese/English is the primary validated design target. Han-only Chinese vs Japanese can be inherently ambiguous and should not be treated as guaranteed automatic classification yet.

Inspect local segmentation with:

```bash
~/voiceger_v2/.venv/bin/python scripts/probe_mixed_language.py
```

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

## Current AudioQuery support

Currently applied:

- `accent_phrases`
- `speedScale`

The following familiar VOICEVOX fields are present but not implemented yet. Changing them returns an explicit error instead of being silently ignored:

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

The complete pronunciation path has been validated locally without modifying Voiceger source files:

```text
text
  -> OpenJTalk
  -> editable pronunciation
  -> AccentPhrase data
  -> Voiceger-compatible G2P tokens
  -> runtime hook
  -> natural audio
```

For representative Japanese phrases, adapter-generated G2P tokens matched Voiceger's built-in G2P tokens exactly, including accent-phrase boundaries.

## Upstream dependency

Voiceger is developed separately at:

https://github.com/zunzun999/voiceger_v2

This repository is not a fork and does not contain Voiceger source, model weights, or reference audio. Runtime integration uses the user's local Voiceger installation.

## Status

Early implementation. The pronunciation path, runtime hook, VOICEVOX-style AudioQuery flow, local reference-audio style discovery, and mixed-language query extension are implemented and ready for local integration testing.

## License

Not selected yet. Before public release, only code authored in this repository should be licensed here; Voiceger and its dependencies/assets remain subject to their own terms.
