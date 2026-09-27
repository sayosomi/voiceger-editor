# voiceger-accent-adapter

An experimental adapter that exposes Voiceger / GPT-SoVITS through a VOICEVOX-style TTS API with editable Japanese accent phrases, editable English stress, and selectable reference-audio styles.

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

## v1 scope

The supported language scope for v1 is:

- Japanese
- Japanese + English mixed text

Japanese-English mixed synthesis has been validated locally. Japanese sections remain accent-editable through `accent_phrases`. English sections expose Voiceger's native stress-bearing ARPAbet tokens through `voicegerSegments[].phonemes`, so lexical stress can be edited before synthesis.

Other multilingual combinations are not part of the v1 compatibility guarantee, even if the underlying Voiceger/GPT-SoVITS runtime may support them.

## API

```http
GET  /version
GET  /speakers
POST /audio_query
POST /accent_phrases
POST /synthesis
```

The older experimental `/pronunciation` and `/tts` endpoints are not kept.

v1 supports one utterance per request; embedded newlines are rejected.

## Start the API

Set `VOICEGER_ROOT` to your local Voiceger installation, then run the adapter from this repository:

```bash
cd /path/to/voiceger-accent-adapter
export VOICEGER_ROOT=/path/to/voiceger_v2

"$VOICEGER_ROOT/.venv/bin/python" -m pip install -e '.[api]'

"$VOICEGER_ROOT/.venv/bin/python" -m uvicorn \
  voiceger_accent_adapter.api:app \
  --host 127.0.0.1 \
  --port 8001
```

## Keyboard-first terminal interface

Install the terminal interface in Voiceger's Python environment, then start it
with an utterance or enter the text after launch:

```bash
"$VOICEGER_ROOT/.venv/bin/python" -m pip install -e '.[tui]'
voiceger-accent-adapter "今日はhelloと言うよ。"
```

The TUI uses one continuous, non-wrapping vertical action list. Use `↑` / `↓`
to move through Text, pronunciation segments in source order, Generate or
Regenerate all, available candidates, Regenerate selected, Settings, Help, and
Quit. `Enter` opens or performs the focused action; `Space` replays a focused
candidate. `Tab` is an optional accelerator. Pronunciation segments are compact
selectable `LANG | source | pronunciation` rows, with long content wrapped as
needed. Normal Navigation has no persistent control footer. Help remains a
visible Navigation action, and `?` is an optional shortcut. Candidate review
keeps the candidate in the same list; `Esc` returns to the last selected
pronunciation segment.

Text and Japanese pronunciation each open as a single-field modal: Enter applies
the input and Esc discards it directly back to Navigation. Text apply rebuilds
pronunciation. If applying either field fails, the modal stays open with the
input ready for correction. The Japanese editor shows the literal
AquesTalk-style pronunciation; type `'` and `/` directly, with ordinary cursor
movement and editing. Settings remain a multi-field draft: Enter finishes the
active field, Apply commits the settings, and Esc discards the whole settings
draft. English segments show selectable lexical word/token rows. Select a word
to edit its stress-free phoneme tokens and each existing primary-stress marker
in a dedicated word editor. Enter commits phonemes into the word draft while
leaving stress editable; Done returns the word draft to its segment, and Esc
cancels the current English editor layer. Stress digits are hidden; primary
stress is shown with brackets. Voiceger's whole-segment English G2P supplies
the transient word boundaries, and the editor fails closed if those groups do
not reproduce Voiceger's canonical flat phoneme sequence. Settings are also
reachable in the action list.

`F5` / `Ctrl+G`, number keys `1`–`8`, `r`, `R`, `t`, `s`, `v`, `n`, `o`, `x`,
and `?` remain accelerators to the corresponding visible actions. These
settings persist in the platform user config; command-line options override
them for one invocation. Candidate WAVs remain temporary until accepted.

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
  --data-urlencode 'text=今日は雨なのだ。' \
  --data-urlencode 'speaker=1' \
  > query.json
```

The returned `AudioQuery` follows the VOICEVOX shape for pure Japanese and does not contain adapter-only display-text fields.

The readable `kana` field is included for pure Japanese, but synthesis is driven by `accent_phrases`.

## Edit an accent

For example, move the second accent phrase to accent position 5:

```bash
jq '.accent_phrases[1].accent = 5' query.json > manual.json
```

Editable kana can also be converted directly to structured accent phrases:

```bash
curl -sS -X POST -G \
  'http://127.0.0.1:8001/accent_phrases' \
  --data-urlencode "text=キョ'ーワ/ア'メ/ナ'ノダ。" \
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

The engine API does **not** permanently save the WAV. It creates a temporary WAV for the response and deletes it after transmission. The caller chooses the final output filename and destination.

This also means the `AudioQuery` returned by `/audio_query` can be sent directly to `/synthesis`, matching the VOICEVOX workflow.

## Japanese-English mixed text

Japanese-English mixed text is supported in v1.

Example:

```text
今日はhelloと言うのだ。
```

For mixed text, `/audio_query` adds an optional `voicegerSegments` extension. Japanese segments reference slices of the normal `accent_phrases` array, while English segments preserve their original text.

Example shape:

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
      "text": "hello",
      "phonemes": ["HH", "AH0", "L", "OW1"]
    },
    {
      "language": "ja",
      "text": "と言うのだ。",
      "accentPhraseStart": 1,
      "accentPhraseCount": 2
    }
  ]
}
```

During synthesis:

- Japanese segments use the edited `accent_phrases` and the adapter's Voiceger G2P hook.
- English segments use the editable `phonemes` list when present. Older queries without `phonemes` still fall back to Voiceger's native English G2P.
- Original segment order is preserved.
- Automatic segmentation uses Voiceger's bundled LangSegment.

This Japanese-English path has been validated locally end to end.

### Edit English stress

English phonemes use the same ARPAbet stress markers as Voiceger/GPT-SoVITS:

- `0`: unstressed
- `1`: primary stress
- `2`: secondary stress

For example:

```json
{
  "language": "en",
  "text": "record",
  "phonemes": ["R", "IH0", "K", "AO1", "R", "D"]
}
```

Changing the stress digit on a vowel changes the stress information sent to Voiceger. Only valid Voiceger ARPAbet tokens are accepted; invalid values such as `AH3` return an error instead of silently becoming `UNK`.

Other language combinations are currently out of scope for the documented v1 behavior.

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

Validated paths include:

- pure Japanese automatic pronunciation;
- manual Japanese accent edits;
- selectable reference-audio styles;
- Japanese-English mixed text;
- editable English ARPAbet stress overrides.

For representative Japanese phrases, adapter-generated G2P tokens matched Voiceger's built-in G2P tokens exactly, including accent-phrase boundaries.

## Integration test

The recorded Voiceger compatibility target for v1 is:

```text
f77c1172baf1f490bb962f2d2acd01c852ef3464
```

Real Voiceger synthesis tests are opt-in so the normal unit-test suite does not load the models.

Run them with:

```bash
cd /path/to/voiceger-accent-adapter
export VOICEGER_ROOT=/path/to/voiceger_v2

VOICEGER_RUN_INTEGRATION=1 \
"$VOICEGER_ROOT/.venv/bin/python" -m unittest discover \
  -s tests/integration \
  -p 'test_*.py' \
  -v
```

The integration suite checks:

- the local Voiceger checkout revision;
- Japanese manual-accent synthesis;
- Japanese-English mixed synthesis;
- basic duration bounds to catch semantic-token runaway regressions.

## Upstream dependency

Voiceger is developed separately at:

https://github.com/zunzun999/voiceger_v2

This repository is not a fork and does not contain Voiceger source, model weights, or reference audio. Runtime integration uses the user's local Voiceger installation.

## Status

Early implementation. The core Japanese pronunciation path, VOICEVOX-style AudioQuery flow, reference-audio style selection, and Japanese-English mixed synthesis are validated locally.

## Generated audio and Voiceger terms

Audio generated through this adapter using the Voiceger Zundamon voice is subject to the official Voiceger Zundamon audio usage terms.

Please check the latest terms before using, publishing, or distributing generated audio:

https://zunko.jp/con_ongen_kiyaku.html

## License

Not selected yet. Before public release, only code authored in this repository should be licensed here; Voiceger and its dependencies/assets remain subject to their own terms.
