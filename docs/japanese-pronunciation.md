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

`kana` is a readable representation. Synthesis is driven by `accent_phrases`, matching the VOICEVOX model. The adapter does not add a private `text` field to `AudioQuery`; the query returned by `/audio_query` is sufficient input for `/synthesis`.

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

The response is `audio/wav`, not JSON. As with VOICEVOX ENGINE, the API uses a temporary WAV for the HTTP response and does not permanently save it. The caller chooses the final filename and destination.

## 4. Reference-audio styles

The adapter exposes Voiceger's numbered WAV files under the local `reference/` directory as VOICEVOX talk styles:

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

Only locally existing WAVs are advertised by `GET /speakers`.

These preset references share the upstream prompt text:

```text
私はいつもミネラルウォーターを持ち歩いています。
```

The selected `speaker` determines the reference WAV used by GPT-SoVITS synthesis.

## 5. Automatic pronunciation generation

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

## 6. Internal architecture

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

## 7. Voiceger integration

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

## 8. AudioQuery support

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

## 9. Compatibility scope

Initial scope:

- Japanese talk synthesis only.
- One utterance per request; embedded newlines are rejected.
- `speaker` is a VOICEVOX-style style ID selecting a local Voiceger reference WAV.
- The known preset styles are Neutral, Sweet, Snippy, Sexy, Whispering, Murmuring, Exhausted, and Sobbing (IDs 1–8 when the corresponding WAV files exist).
- Editable kana accepts hiragana and katakana.
- Adapter integration should be tested against known Voiceger revisions because it relies on upstream runtime internals.

This project aims for a VOICEVOX-like API workflow, not full drop-in VOICEVOX ENGINE compatibility.

## 10. Non-goals for the first version

- Full reproduction of all AquesTalk symbols.
- Full VOICEVOX ENGINE endpoint coverage.
- Bundling Voiceger.
- Bundling Voiceger/GPT-SoVITS models or reference audio.
- Reimplementing GPT-SoVITS inference.
- A graphical accent editor.

## 11. Acceptance criteria

- Plain Japanese text produces a usable `AudioQuery`.
- Every generated accent phrase has a valid 1-based `accent`.
- `あ'め` parses as `accent=1`.
- `あめ'` parses as `accent=2`.
- Editing `accent_phrases[n].accent` changes synthesized accent.
- `/accent_phrases?is_kana=true` converts editable kana into structured accent phrases.
- `/synthesis` returns a valid WAV.
- The engine API does not persist synthesis output; callers can choose filenames appropriate to their workflow.
- Selecting different supported `speaker` IDs uses the corresponding reference WAV.
- Core parser/converter tests can run independently of Voiceger where practical.
- Voiceger-dependent tests remain isolated.
- No upstream Voiceger source or bundled assets are committed to this repository.

## 12. Open questions

- Add VOICEVOX-style `、` pause delimiters and `_` devoicing.
- Improve interrogative handling.
- Decide whether automatic `kana` output should always canonicalize to katakana.
- Mixed Japanese/English handling.
- Support more AudioQuery acoustic controls.
- Consider additional VOICEVOX metadata endpoints beyond `/version` and `/speakers`.
- Version compatibility strategy for future Voiceger/GPT-SoVITS changes.
