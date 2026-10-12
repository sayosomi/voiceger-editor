# Japanese pronunciation and accent control

Status: draft

## 1. Purpose

This project adds editable Japanese pronunciation and pitch-accent control in front of a locally installed Voiceger / GPT-SoVITS runtime without copying or modifying Voiceger source files.

The public API intentionally follows the VOICEVOX workflow:

1. Send ordinary Japanese or Japanese-English mixed text to `POST /audio_query`.
2. Receive an `AudioQuery` containing editable Japanese `accent_phrases`.
3. Edit `accent_phrases` when Japanese pronunciation or accent needs correction.
4. Send the edited query to `POST /synthesis`.
5. Receive `audio/wav`.

The older experimental `/pronunciation` and `/tts` APIs are not retained.

### 0.1 language scope

The documented and validated 0.1 language scope is:

- Japanese
- Japanese + English mixed text

Other multilingual combinations are not part of the 0.1 compatibility guarantee.

## 2. Pronunciation notation

The editable kana notation follows the core VOICEVOX / AquesTalk-style accent rules, with one convenience difference: this adapter accepts both hiragana and katakana.

Rules in the supported subset:

- `'` follows the mora selected as the accent position.
- Legacy single-peak phrases contain exactly one `'`.
- Adapter-only multi-peak phrases use explicit `[` (rise) and `]` (fall) markers **after complete morae**, with no `'` inside that phrase. Their events must alternate, begin after mora 1, occur at distinct non-final mora boundaries, and agree with the first standard fall/accent.
- Markers inside a small-kana digraph, mixed `'` / `[` / `]` syntax, or malformed sequences are rejected.
- `/` separates adjacent accent phrases when no punctuation appears between them.
- `。`, `、`, `？`, `！`, and `…` are ordered pronunciation items and may appear between phrases or at the end.
- ASCII `.`, `,`, `?`, and `!` are accepted while editing and canonicalized to `。`, `、`, `？`, and `！`.
- OpenJTalk comma-like symbols `：`, `；`, `，`, and `·` are canonicalized to `、`.
- `_` devoicing is not implemented.

Examples:

```text
あ'め                 -> accent = 1
あめ'                 -> accent = 2
ア'メ                 -> accent = 1
アメ'                 -> accent = 2
ソ'ウ？ソ'ウナノダ！ -> punctuation remains in sequence
デ'モ、ホント'ウ…    -> comma and ellipsis remain in sequence
```

The internal `accent` value is 1-based and matches the mora immediately before `'` for legacy input. For multi-peak phrases, it is the index of the **first fall** (the VOICEVOX-compatible projection). Internally, `Pronunciation` stores an ordered sequence of `AccentPhrase` and `PronunciationPunctuation` items. An `AccentPhrase` optionally carries an immutable ordered tuple of `PitchEvent(after_mora, symbol)` values; these are not phrase separators or punctuation.

For example, `ス[タ]ック[チャ]ンヲ/ツク'ッタ/ノダ'！` produces `s u [ t a ] cl k u [ ch a ] N o # ts u [ k u ] cl t a # n o [ d a !` at the Japanese G2P hook. The second rise/fall does **not** introduce `#`; the two existing `/` boundaries still do. Legacy `スタ'ックチャンヲ/ツク'ッタ/ノダ'！` retains its previous token stream. `ー` repeats the previous vowel, `ッ` maps to its own mora, and small kana stays attached to the preceding base kana.

This explicit notation is a shared-core representation; editor/Dictionary UI adoption and word matching belong to later Issues (#274–#276). Spaces and `/` retain their existing real-boundary semantics.

## 3. Public API model

### POST /audio_query

VOICEVOX-style query creation:

```http
POST /audio_query?text=今日は雨ですね。&speaker=3
```

For pure Japanese, the response contains the normal VOICEVOX-like fields:

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

The adapter also emits optional `pronunciationPunctuation` metadata. Each entry stores a canonical punctuation mark and the zero-based accent-phrase index it follows. This keeps punctuation order independent from editable accent values:

```json
{
  "afterAccentPhrase": 0,
  "mark": "、"
}
```

`kana` remains the **VOICEVOX-compatible legacy projection** (one `'` per real accent phrase), even when extra peaks exist. Synthesis reconstructs pronunciation from `accent_phrases`, optional `pronunciationPitchEvents`, and punctuation metadata. The adapter-specific `pronunciationPitchEvents` array is omitted for legacy queries; when present it carries the **complete, ordered event sequence** for affected phrases only, not an alteration of the standard `accent` field:

```json
{
  "accentPhraseIndex": 0,
  "events": [
    {"afterMora": 1, "symbol": "["},
    {"afterMora": 2, "symbol": "]"},
    {"afterMora": 4, "symbol": "["},
    {"afterMora": 5, "symbol": "]"}
  ]
}
```

Indexes in `pronunciationPitchEvents` are **global** across `accent_phrases`, including mixed Japanese-English queries. They are converted to local segment indexes only when constructing per-segment pronunciation; persisted JSON/session snapshots retain global indexes. Malformed, duplicated, out-of-range, unordered, or accent-inconsistent events are rejected instead of being ignored. Editing/removing Japanese phrases shifts or clears only the affected event records. Legacy accent-move operations reject an affected multi-peak phrase instead of silently collapsing its events.

Queries created before the punctuation metadata existed still use the legacy final-terminator fallback. Adapter-unaware VOICEVOX consumers may ignore the extension and continue using single-accent `accent_phrases` and `kana` (without the extra events). This is a deliberate, lossy compatibility projection; native adapter query/session JSON preserves the extension losslessly.

For Japanese-English mixed input, `voicegerSegments` is additionally present to preserve the English text and map Japanese sections to the corresponding `accent_phrases`. Japanese segments carry their own `pronunciationPunctuation` metadata so punctuation stays attached to the Japanese sequence.

### POST /accent_phrases

Ordinary Japanese text:

```http
POST /accent_phrases?text=今日は雨ですね。&speaker=3
```

Editable kana:

```http
POST /accent_phrases?text=キョ'ーワ/アメデスネ'。&speaker=3&is_kana=true
```

This provides the VOICEVOX-style path for converting AquesTalk-style notation back into structured accent phrases.

### POST /synthesis

```http
POST /synthesis?speaker=3
Content-Type: application/json

<AudioQuery JSON>
```

The response is `audio/wav`, not JSON. As with VOICEVOX ENGINE, the API uses a temporary WAV for the HTTP response and does not permanently save it. The caller chooses the final filename and destination.

## 4. Reference-audio styles

The adapter exposes Voiceger's numbered WAV files under the local `reference/` directory as VOICEVOX talk styles:

| speaker | style | reference WAV |
| ---: | --- | --- |
| 3 | Neutral | `01_ref_emoNormal026.wav` |
| 1 | Sweet | `02_ref_emoAma026.wav` |
| 7 | Snippy | `03_ref_emoTsun026.wav` |
| 5 | Sexy | `04_ref_emoSexy026.wav` |
| 22 | Whispering | `05_ref_emoSasa026.wav` |
| 38 | Murmuring | `06_ref_emoMurmur026.wav` |
| 75 | Exhausted | `07_ref_emoHero026.wav` |
| 76 | Sobbing | `08_ref_emoSobbing026.wav` |

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

Pure Japanese:

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

Japanese-English mixed:

```text
text
  ↓
LangSegment
  ↓
ja / en segments
  ↓
ja: OpenJTalk -> editable AccentPhrase data
en: original English text retained
  ↓
AudioQuery + voicegerSegments
  ↓
ja: edited G2P override
en: Voiceger native Japanese-English Mixed path
  ↓
Voiceger / GPT-SoVITS
```

Core modules include:

```text
voiceger_editor/
  pronunciation.py
  openjtalk_converter.py
  mixed_language.py
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

### Phrase-boundary and punctuation handling

OpenJTalk emits `#` for an accent-phrase boundary. Voiceger v2's existing `clean_text()` converts `#` to `UNK`.

Because the adapter hooks before `clean_text()`, public `/` maps to `#` at the hook point. This reproduces Voiceger's normal frontend path. When an ordered punctuation item appears between phrases, the adapter emits the Voiceger punctuation token in that position instead of inserting `#`.

Canonical token mapping is:

| Editable punctuation | Voiceger token |
| --- | --- |
| `。` | `.` |
| `、` | `,` |
| `？` | `?` |
| `！` | `!` |
| `…` | `…` |

Dropping the boundary token entirely for adjacent unpunctuated phrases was tested and caused unstable synthesis.

## 8. Japanese-English mixed extension

Pure Japanese remains a normal VOICEVOX-shaped `AudioQuery`.

For Japanese-English mixed input, the adapter adds optional `voicegerSegments` metadata. Each segment preserves its language and original text. Japanese segments additionally point to a contiguous range in the shared `accent_phrases` array:

```json
{
  "language": "ja",
  "text": "今日は",
  "accentPhraseStart": 0,
  "accentPhraseCount": 1
}
```

English segments omit the accent phrase range:

```json
{
  "language": "en",
  "text": "OpenAI"
}
```

At synthesis time:

1. Reconstruct the original Japanese/English segment order.
2. Convert referenced Japanese accent phrases back to Voiceger/OpenJTalk prosody tokens.
3. Hook only those Japanese G2P calls.
4. Let Voiceger process English through its native `Japanese-English Mixed` frontend.

Automatic segmentation uses Voiceger's bundled LangSegment.

The Japanese-English mixed path has been validated locally end to end.

Other language combinations are intentionally outside the documented 0.1 scope. The implementation may expose underlying Voiceger multilingual behavior, but it is not currently guaranteed or treated as a compatibility target.

## 9. AudioQuery support

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

## 10. Compatibility scope

Initial 0.1 scope:

- Japanese talk synthesis.
- Japanese-English mixed talk synthesis.
- One utterance per request; embedded newlines are rejected.
- `speaker` is a VOICEVOX-style style ID selecting a local Voiceger reference WAV.
- Known preset styles use the VOICEVOX Zundamon IDs: Neutral 3, Sweet 1, Snippy 7, Sexy 5, Whispering 22, Murmuring 38, Exhausted 75, and Sobbing 76 when the corresponding WAV files exist.
- Editable Japanese kana accepts hiragana and katakana.
- Adapter integration should be tested against known Voiceger revisions because it relies on upstream runtime internals.

Not guaranteed in 0.1:

- Chinese/Japanese mixed automatic classification.
- Korean or other multilingual combinations.
- Full drop-in VOICEVOX ENGINE compatibility.

## 11. Non-goals for the first version

- Full reproduction of all AquesTalk symbols.
- Full VOICEVOX ENGINE endpoint coverage.
- General-purpose multilingual accent editing.
- Bundling Voiceger.
- Bundling Voiceger/GPT-SoVITS models or reference audio.
- Reimplementing GPT-SoVITS inference.
- A graphical accent editor.

## 12. Acceptance criteria

- Plain Japanese text produces a usable `AudioQuery`.
- Every generated Japanese accent phrase has a valid 1-based `accent`.
- `あ'め` parses as `accent=1`.
- `あめ'` parses as `accent=2`.
- Editing `accent_phrases[n].accent` changes synthesized Japanese accent.
- `/accent_phrases?is_kana=true` converts editable kana into structured accent phrases.
- `/synthesis` returns a valid WAV.
- Japanese-English mixed input preserves English text and keeps Japanese sections accent-editable.
- Japanese-English mixed synthesis completes successfully through Voiceger's native mixed frontend.
- The engine API does not persist synthesis output; callers choose filenames appropriate to their workflow.
- Selecting different supported `speaker` IDs uses the corresponding reference WAV.
- Core parser/converter tests can run independently of Voiceger where practical.
- Voiceger-dependent tests remain isolated.
- No upstream Voiceger source or bundled assets are committed to this repository.

## 13. Open questions

- Add `_` devoicing.
- Improve interrogative handling.
- Decide whether automatic `kana` output should always canonicalize to katakana.
- Support more AudioQuery acoustic controls.
- Consider additional VOICEVOX metadata endpoints beyond `/version` and `/speakers`.
- Version compatibility strategy for future Voiceger/GPT-SoVITS changes.
