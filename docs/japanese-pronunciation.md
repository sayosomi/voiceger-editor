# Japanese pronunciation and accent control

Status: draft

## 1. Purpose

Voiceger currently accepts target text and performs Japanese text normalization, G2P, and prosody analysis internally. Its Japanese frontend uses OpenJTalk/pyopenjtalk and GPT-SoVITS consumes the resulting phoneme/prosody sequence.

This project adds an editable pronunciation layer in front of that pipeline without copying Voiceger into this repository.

The main use case is:

1. Write normal Japanese text.
2. Automatically obtain an editable pronunciation.
3. Correct readings, accent positions, or accent-phrase boundaries only where needed.
4. Synthesize using the corrected pronunciation.
5. Preserve the corrected pronunciation as reproducible source data.

## 2. Public data model

### 2.1 Display text

`text` is the original/display form.

Example:

```json
{
  "text": "明日の天気は晴れ。"
}
```

It should remain suitable for scripts, subtitles, logs, and UI display.

### 2.2 Pronunciation

`pronunciation` is an optional spoken-form override.

The initial notation follows the core accent-position rules used by VOICEVOX's AquesTalk-style kana notation, with one convenience difference: this project accepts both hiragana and katakana.

Initial rules:

- `'` — accent position; it follows the selected mora.
- Every accent phrase must contain exactly one `'`.
- `/` — accent-phrase boundary without an explicit pause.
- Kana — spoken reading.
- An optional final `。` or `？` is preserved in the initial subset.
- `、` pause delimiters and `_` devoicing are not part of the first parser subset yet.

Examples:

```text
あ'め   -> accent = 1
あめ'   -> accent = 2

ア'メ   -> accent = 1
アメ'   -> accent = 2
```

The internal `accent` value is 1-based and matches the mora immediately before `'`.

This notation is intentionally described as VOICEVOX-style / AquesTalk-style rather than full AquesTalk compatibility.

## 3. Resolution rules

For Japanese input:

1. If `pronunciation` is absent, derive it automatically from `text`.
2. If `pronunciation` is present, treat it as authoritative for reading/prosody.
3. Convert either path into one shared internal prosody representation.
4. Convert that representation into the phoneme/prosody sequence expected by the installed Voiceger/GPT-SoVITS version.
5. Return the resolved pronunciation used for synthesis.

The automatic and manual paths must converge before Voiceger-specific conversion. There should not be two independent synthesis implementations.

## 4. Automatic pronunciation generation

OpenJTalk/pyopenjtalk is the initial source of:

- kana reading
- accent phrase segmentation
- accent information
- mora-related information needed to reconstruct editable notation

The converter should produce a deterministic editable pronunciation for a given frontend/version where practical.

Unknown words and proper nouns should remain correctable by either:

- OpenJTalk user dictionaries, or
- a per-utterance `pronunciation` override.

## 5. Internal architecture

Target layering:

```text
text
  ↓
OpenJTalk analyzer
  ↓
InternalProsody
  ↓
pronunciation formatter
  ↕
pronunciation parser
  ↓
InternalProsody
  ↓
VoicegerAdapter
  ↓
Voiceger / GPT-SoVITS
```

Suggested modules:

```text
voiceger_accent_adapter/
  prosody.py
  openjtalk_converter.py
  pronunciation.py
  voiceger_adapter.py
  api.py
```

### InternalProsody

The first core representation uses a VOICEVOX-like accent-phrase model:

```text
AccentPhrase
  morae: ordered mora sequence
  accent: 1-based mora index, required
```

The model must remain Voiceger-independent.

Future extensions may add pause/devoicing/interrogative metadata without changing the meaning of `accent`.

## 6. Voiceger integration

Current upstream Voiceger ultimately calls GPT-SoVITS `get_tts_wav(...)`, which obtains Japanese phones through its internal `get_phones_and_bert()` → `clean_text()` → Japanese `g2p()` path.

The current public-style TTS entry point does not expose a parameter for precomputed Japanese phones/prosody.

A local runtime spike has validated that the installed Voiceger can be imported without modifying its files and its Japanese G2P output can be replaced for one synthesis call.

Validated minimal pair:

```text
雨 -> ['a', ']', 'm', 'e']
飴 -> ['a', '[', 'm', 'e']
```

Using the same visible sentence `今日は雨ですね。`, changing only the injected `]` / `[` marker produced two natural WAV files with an audible accent difference.

Therefore the first adapter may:

1. import the installed Voiceger/GPT-SoVITS modules at runtime;
2. intercept or wrap the Japanese text-cleaning/G2P stage;
3. provide the phoneme/prosody sequence generated from `InternalProsody`;
4. call the existing Voiceger/GPT-SoVITS inference path.

Voiceger-specific hooks must remain contained in `voiceger_adapter.py` (or equivalent) so upstream changes do not leak into the core notation/parser.

No Voiceger source files should need to be permanently modified for the preferred integration mode.

### Phrase-boundary handling

OpenJTalk emits `#` for an accent-phrase boundary. Voiceger v2 preserves `[` and `]`, while its existing `clean_text()` converts `#` to `UNK`.

The adapter hooks at the Japanese `g2p()` stage, before `clean_text()`. Therefore public `/` notation maps to a literal `#` token at that hook point, and Voiceger's existing cleaner is allowed to perform the same `# -> UNK` conversion as the normal built-in path.

A spike that removed the boundary token entirely produced unstable synthesis for the automatically generated pronunciation, while the earlier spike that preserved `#` produced natural audio. The adapter should therefore match the built-in G2P stream exactly rather than comparing against a `#`-stripped stream.

## 7. API sketch

### POST /pronunciation

Request:

```json
{
  "text": "明日の天気は晴れ。",
  "text_language": "Japanese"
}
```

Response:

```json
{
  "text": "明日の天気は晴れ。",
  "pronunciation": "<generated editable pronunciation>",
  "source": "openjtalk"
}
```

### POST /tts

Automatic pronunciation:

```json
{
  "text": "明日の天気は晴れ。",
  "text_language": "Japanese"
}
```

Manual pronunciation:

```json
{
  "text": "明日の天気は晴れ。",
  "pronunciation": "<manually edited pronunciation>",
  "text_language": "Japanese"
}
```

Response should include at least:

```json
{
  "message": "success",
  "resolved_pronunciation": "<pronunciation actually used>",
  "file_path": "...",
  "sampling_rate": 32000
}
```

Exact output transport (path vs streamed audio) is not yet fixed.

## 8. Compatibility

Initial scope:

- Japanese only for pronunciation editing.
- Existing Voiceger behavior remains the fallback for unsupported languages.
- `pronunciation` is optional and therefore does not replace ordinary `text` input.
- Adapter compatibility should be versioned/tested against known Voiceger revisions because the integration relies on upstream internals.
- Editable pronunciation accepts hiragana and katakana even though VOICEVOX's kana parser itself requires katakana.

## 9. Non-goals for the first version

- Full reproduction of every AquesTalk voice-symbol feature.
- Full VOICEVOX kana-parser compatibility.
- Bundling Voiceger.
- Bundling Voiceger/GPT-SoVITS model weights or reference audio.
- Reimplementing GPT-SoVITS inference.
- Building a graphical accent editor before the notation/API is stable.

## 10. Initial acceptance criteria

- Plain Japanese text can be converted to an editable pronunciation.
- Every generated accent phrase contains exactly one `'`.
- `あ'め` parses as `accent=1`.
- `あめ'` parses as `accent=2`.
- Generated pronunciation can be parsed back into the same internal prosody semantics for supported cases.
- A user can change the accent position and hear a corresponding synthesis difference.
- A user can change an accent-phrase boundary and have that change reach synthesis.
- `/tts` works with and without an explicit `pronunciation`.
- `/tts` reports `resolved_pronunciation`.
- Core parser/converter tests can run without Voiceger installed.
- Voiceger-dependent tests are isolated as integration tests.
- No upstream Voiceger source or bundled assets are committed to this repository.

## 11. Open questions

- Exact mapping from VOICEVOX-style `accent` values to Voiceger `[` / `]` tokens for all accent types.
- Verify phrase-boundary behavior across more Voiceger/GPT-SoVITS revisions; the current adapter emits `#` at the G2P hook and relies on Voiceger v2 `clean_text()` to convert it to `UNK`.
- When to add VOICEVOX-style `、` pause delimiters and `_` devoicing.
- How punctuation and interrogative endings should be serialized beyond the initial subset.
- Whether automatic output should canonicalize to hiragana or katakana.
- How to represent mixed Japanese/English input.
- The most stable hook point for the current Voiceger revision.
- Whether audio should be returned as a file path, bytes/stream, or both.
