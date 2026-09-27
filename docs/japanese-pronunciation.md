# Japanese pronunciation and accent control

Status: draft

## 1. Purpose

This project adds editable Japanese pronunciation and pitch-accent control in front of a locally installed Voiceger / GPT-SoVITS runtime without copying or modifying Voiceger source files.

The public API intentionally follows the VOICEVOX workflow:

1. Send ordinary Japanese text to `POST /audio_query`.
2. Receive an `AudioQuery` containing `accent_phrases` and readable `kana`.
3. Edit `accent_phrases` when pronunciation or accent needs correction.
4. Send the edited query to `POST /synthesis`.
5. Receive `audio/wav`.

The older experimental `/pronunciation` and `/tts` APIs are not retained.

## 2. Pronunciation notation

The editable kana notation follows the core VOICEVOX / AquesTalk-style accent rules, with one convenience difference: this adapter accepts both hiragana and katakana.

Rules in the initial subset:

- `'` follows the mora selected as the accent position.
- Every accent phrase contains exactly one `'`.
- `/` separates accent phrases without an explicit pause.
- An optional final `。` or `？` is preserved.
- `、` pause delimiters and `_` devoicing are not implemented yet.

Examples:

```text
あ'め   -> accent = 1
あめ'   -> accent = 2

ア'メ   -> accent = 1
アメ'   -> accent = 2
```

The internal `accent` value is 1-based and matches the mora immediately before `'`.

## 3. Public API model

### POST /audio_query

VOICEVOX-style query creation:

```http
POST /audio_query?text=今日は雨ですね。&speaker=1
```

The response contains:

- `accent_phrases`
- `speedScale`
- `pitchScale`
- `intonationScale`
- `volumeScale`
- `prePhonemeLength`
- `postPhonemeLength`
- `pauseLength`
- `pauseLengthScale`
- `outputSamplingRate`
- `outputStereo`
- `kana`

The adapter also includes `text` as an extension so the original display text remains available for readable output filenames.

`kana` is a readable representation. Synthesis is driven by `accent_phrases`, matching the VOICEVOX model.

### POST /accent_phrases

Ordinary text:

```http
POST /accent_phrases?text=今日は雨ですね。&speaker=1
```

Editable kana:

```http
POST /accent_phrases?text=キョ'ーワ/アメデスネ'。&speaker=1&is_kana=true
```

This provides the VOICEVOX-style path for converting AquesTalk-style notation back into structured accent phrases.

### POST /synthesis

```http
POST /synthesis?speaker=1
Content-Type: application/json

<AudioQuery JSON>
```

The response is `audio/wav`, not JSON.

The generated WAV is also stored locally with a VOICEVOX-style filename such as:

```text
001_ずんだもん（style_1）_今日は雨ですね。.wav
```

## 4. Automatic pronunciation generation

OpenJTalk / pyopenjtalk provides:

- kana reading;
- accent phrase segmentation;
- accent information;
- mora-related information.

The converter reads `pyopenjtalk.run_frontend()` output and produces the core `Pronunciation` model and VOICEVOX-like `AccentPhrase` data.

Validated examples:

```text
雨                 -> ア'メ
飴                 -> アメ'
今日は雨ですね。   -> キョ'ーワ/ア'メデスネ。
明日の天気は晴れ。 -> アシタ'ノ/テ'ンキワ/ハレ'。
私は思う。         -> ワタシワ'/オモ'ウ。
```

## 5. Internal architecture

```text
text
  ↓
OpenJTalk analyzer
  ↓
Pronunciation
  ↓
VOICEVOX-like AccentPhrase / AudioQuery
  ↓
editable accent values
  ↓
Pronunciation
  ↓
Voiceger frontend tokens
  ↓
runtime G2P hook
  ↓
Voiceger / GPT-SoVITS
```

Core modules:

```text
voiceger_accent_adapter/
  pronunciation.py
  openjtalk_converter.py
  voicevox_api_models.py
  voicevox_query.py
  voiceger_tokens.py
  voiceger_adapter.py
  api.py
```

## 6. Voiceger integration

Voiceger ultimately calls GPT-SoVITS `get_tts_wav(...)`, which obtains Japanese phones through its internal `get_phones_and_bert()` → `clean_text()` → Japanese `g2p()` path.

The adapter imports the installed Voiceger runtime and temporarily replaces the Japanese `g2p()` function only during synthesis. The original function is restored afterward.

Validated minimal pair:

```text
雨 -> ['a', ']', 'm', 'e']
飴 -> ['a', '[', 'm', 'e']
```

For representative real text, adapter-generated G2P tokens matched Voiceger's built-in G2P tokens exactly.

### Phrase-boundary handling

OpenJTalk emits `#` for an accent-phrase boundary. Voiceger v2's existing `clean_text()` converts `#` to `UNK`.

Because the adapter hooks before `clean_text()`, public `/` maps to `#` at the hook point. This reproduces Voiceger's normal frontend path.

Dropping the boundary token entirely was tested and caused unstable synthesis.

## 7. AudioQuery support

Currently applied:

- `accent_phrases`
- `speedScale`

Present for VOICEVOX-style API shape but not yet implemented:

- `pitchScale`
- `intonationScale`
- `volumeScale`
- `prePhonemeLength`
- `postPhonemeLength`
- `pauseLength`
- `pauseLengthScale`
- arbitrary `outputSamplingRate`
- stereo output

Changing an unsupported field returns an error rather than silently ignoring it.

## 8. Compatibility scope

Initial scope:

- Japanese talk synthesis only.
- One utterance per request; embedded newlines are rejected.
- `speaker` is accepted in the VOICEVOX-style query position; the current adapter has one configured Voiceger voice.
- Editable kana accepts hiragana and katakana.
- Adapter integration should be tested against known Voiceger revisions because it relies on upstream runtime internals.

This project aims for a VOICEVOX-like API workflow, not full drop-in VOICEVOX ENGINE compatibility.

## 9. Non-goals for the first version

- Full reproduction of all AquesTalk symbols.
- Full VOICEVOX ENGINE endpoint coverage.
- Bundling Voiceger.
- Bundling Voiceger/GPT-SoVITS models or reference audio.
- Reimplementing GPT-SoVITS inference.
- A graphical accent editor.

## 10. Acceptance criteria

- Plain Japanese text produces a usable `AudioQuery`.
- Every generated accent phrase has a valid 1-based `accent`.
- `あ'め` parses as `accent=1`.
- `あめ'` parses as `accent=2`.
- Editing `accent_phrases[n].accent` changes synthesized accent.
- `/accent_phrases?is_kana=true` converts editable kana into structured accent phrases.
- `/synthesis` returns a valid WAV.
- Generated filenames use the VOICEVOX-style readable format.
- Core parser/converter tests can run independently of Voiceger where practical.
- Voiceger-dependent tests remain isolated.
- No upstream Voiceger source or bundled assets are committed to this repository.

## 11. Open questions

- Add VOICEVOX-style `、` pause delimiters and `_` devoicing.
- Improve interrogative handling.
- Decide whether automatic `kana` output should always canonicalize to katakana.
- Mixed Japanese/English handling.
- Support more AudioQuery acoustic controls.
- Add speaker/style metadata endpoints if needed.
- Version compatibility strategy for future Voiceger/GPT-SoVITS changes.
