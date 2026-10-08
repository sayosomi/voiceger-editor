# HTTP API

Voiceger Editor provides a VOICEVOX-style HTTP API.

The basic workflow is:

```text
text
→ AudioQuery
→ edit the query if needed
→ synthesis
→ WAV
```

It implements a useful subset of the VOICEVOX Engine API.

It is not a complete replacement for VOICEVOX Engine.

## Install

Install API support from PyPI:

```text
python -m pip install "voiceger-editor[api]"
```

Voiceger must already be installed and `VOICEGER_ROOT` must point to it.

API use also requires prior Voiceger:Zundamon terms acceptance:

```bash
voiceger-editor --accept-voiceger-terms
```

## Start

This command works in both POSIX shells and Windows PowerShell:

```text
python -m uvicorn voiceger_editor.api:app --host 127.0.0.1 --port 8001
```

The examples below use:

```text
http://127.0.0.1:8001
```

FastAPI documentation is available at:

```text
http://127.0.0.1:8001/docs
```

The multiline `curl` examples below use a POSIX shell. In Windows PowerShell, use `curl.exe` to call the curl executable directly. Key PowerShell equivalents are shown below.

## Endpoints

Main endpoints:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/` | Engine information |
| GET | `/version` | Voiceger Editor version |
| GET | `/speakers` | Available Voiceger styles |
| POST | `/audio_query` | Create an AudioQuery from text |
| POST | `/accent_phrases` | Create accent phrases |
| POST | `/synthesis` | Generate WAV audio |

Japanese dictionary endpoints:

| Method | Endpoint |
| --- | --- |
| GET | `/user_dict` |
| POST | `/user_dict_word` |
| PUT | `/user_dict_word/{word_uuid}` |
| DELETE | `/user_dict_word/{word_uuid}` |
| POST | `/import_user_dict` |

English dictionary endpoints (Voiceger Editor extensions, not VOICEVOX endpoints):

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/english_user_dict` | List English pronunciations |
| POST | `/english_user_dict_word` | Add or replace an entry |
| PUT | `/english_user_dict_word/{surface}` | Update or rename an entry |
| DELETE | `/english_user_dict_word/{surface}` | Delete an entry |
| POST | `/import_english_user_dict` | Import native English dictionary JSON |

## Speakers and styles

```bash
curl http://127.0.0.1:8001/speakers
```

Voiceger reference WAVs are exposed as VOICEVOX-style talk styles.

The corresponding Zundamon style IDs match VOICEVOX:

| Style | ID |
| --- | ---: |
| Sweet | `1` |
| Neutral | `3` |
| Sexy | `5` |
| Snippy | `7` |
| Whispering | `22` |
| Murmuring | `38` |
| Exhausted | `75` |
| Sobbing | `76` |

Only styles available in the local Voiceger installation are returned.

The speaker UUID is specific to Voiceger Editor:

```text
voiceger-editor-zundamon
```

## Create an AudioQuery

Example:

```bash
curl -s -G -X POST \
  'http://127.0.0.1:8001/audio_query' \
  --data-urlencode 'text=今日は雨なのだ。' \
  --data-urlencode 'speaker=3' \
  > query.json
```

`speaker=3` selects Neutral.

Windows PowerShell:

```powershell
curl.exe -s -G -X POST "http://127.0.0.1:8001/audio_query" --data-urlencode "text=今日は雨なのだ。" --data-urlencode "speaker=3" --output query.json
```

English-only text can be used directly:

```text
Caption 01
```

For an all-English query, Voiceger Editor keeps all language segments as English
and synthesis uses Voiceger's native English mode.

Japanese-English mixed text can be used in the same request:

```text
このずんだ餅はvery sweetなのだ。
```

## Synthesize

Send the AudioQuery to `/synthesis`:

```bash
curl -s -X POST \
  'http://127.0.0.1:8001/synthesis?speaker=3' \
  -H 'Content-Type: application/json' \
  --data-binary @query.json \
  --output output.wav
```

Windows PowerShell:

```powershell
curl.exe -s -X POST "http://127.0.0.1:8001/synthesis?speaker=3" -H "Content-Type: application/json" --data-binary "@query.json" --output output.wav
```

The response is WAV data.

The API does not save the WAV in the normal Voiceger Editor output directory.

TXT and LAB sidecars are not created by `/synthesis`.

## Edit the AudioQuery

You can edit the JSON returned by `/audio_query` before synthesis.

For Japanese pronunciation, `accent_phrases` contains morae and accent positions.

Changing an accent value changes the selected accent position.

For English-only and mixed queries, keep the `voicegerSegments` extension when
sending the query to `/synthesis`; it preserves the English sections and their
explicit ARPAbet pronunciation.

## `/accent_phrases`

Normal text:

```bash
curl -s -G -X POST \
  'http://127.0.0.1:8001/accent_phrases' \
  --data-urlencode 'text=今日は雨なのだ。' \
  --data-urlencode 'speaker=3'
```

Editable kana notation can be used with `is_kana=true`:

```bash
curl -s -G -X POST \
  'http://127.0.0.1:8001/accent_phrases' \
  --data-urlencode "text=キョ'ーワ/ア'メナノダ。" \
  --data-urlencode 'speaker=3' \
  --data-urlencode 'is_kana=true'
```

API kana notation uses `/` between accent phrases.

See [Pronunciation](pronunciation.md).

## AudioQuery controls

These fields are applied:

| Field | Behavior |
| --- | --- |
| `accent_phrases` | Japanese pronunciation and accent |
| `speedScale` | Voiceger speech speed |
| `outputSamplingRate` | Output sample rate |
| `outputStereo` | Mono or duplicated stereo |

These VOICEVOX fields are accepted, but Voiceger does not currently provide equivalent controls:

```text
pitchScale
intonationScale
volumeScale
prePhonemeLength
postPhonemeLength
pauseLength
pauseLengthScale
```

Non-default values are ignored with a warning instead of causing the complete request to fail.

## Voiceger Editor extensions

An AudioQuery may contain:

```text
voicegerSegments
pronunciationPunctuation
```

`voicegerSegments` preserves language sections and English phonemes for mixed Japanese-English speech.

`pronunciationPunctuation` preserves Japanese punctuation information.

If `/audio_query` returns these fields, keep them when sending the query to `/synthesis`.

## Sampling settings

The HTTP API currently uses the Voiceger sampling defaults:

```text
Top K:       20
Top P:       1.00
Temperature: 1.00
```

Top K, Top P, and Temperature are not currently AudioQuery fields.

See [Settings](settings.md).

## Japanese user dictionary

The HTTP API and TUI use the same persistent Japanese dictionary.

List entries:

```bash
curl http://127.0.0.1:8001/user_dict
```

Add an entry:

```bash
curl -s -X POST \
  'http://127.0.0.1:8001/user_dict_word' \
  --data-urlencode 'surface=ずんだもん' \
  --data-urlencode 'pronunciation=ズンダモン' \
  --data-urlencode 'accent_type=3'
```

The default priority is `5`, with a supported range of `0–10`.

The API also supports update, delete, and import operations.

`/import_user_dict` accepts the UUID-keyed expanded VOICEVOX `UserDictWord` format.

The endpoints above cover the Japanese dictionary and remain VOICEVOX-compatible.

## English user dictionary

The HTTP API and TUI share the same persistent English dictionary. English routes are Voiceger Editor extensions, not VOICEVOX-compatible routes.

List the English dictionary:

```bash
curl http://127.0.0.1:8001/english_user_dict
```

The response is a JSON object whose keys are surface spellings and whose values are ARPAbet token arrays:

```json
{
  "sweet": ["S", "W", "IY1", "T"]
}
```

Add or replace an entry (existing spellings match without regard to letter case):

```bash
curl -s -X POST 'http://127.0.0.1:8001/english_user_dict_word' \
  -H 'Content-Type: application/json' \
  -d '{"surface":"sweet","phonemes":["S","W","IY1","T"]}'
```

This returns the validated `{"surface": ..., "phonemes": [...]}` object. To update or rename an existing word, use `PUT /english_user_dict_word/{surface}` with the same JSON request body. To remove a word, use `DELETE /english_user_dict_word/{surface}`. PUT and DELETE return `204 No Content`. If the original word is missing, update and delete return `422`; renaming to an existing surface also returns `422`.

Import a native English dictionary (same JSON shape as GET and TUI English export):

```bash
curl -s -X POST 'http://127.0.0.1:8001/import_english_user_dict?override=true' \
  -H 'Content-Type: application/json' \
  -d '{"sweet":["S","W","IY1","T"]}'
```

Import returns `204 No Content`. `override=false` is the default and retains existing entries with matching spellings; `override=true` replaces matching entries. Import is atomic: invalid data is rejected before the shared dictionary is modified.

Only valid Voiceger ARPAbet tokens are accepted. Invalid input returns `422`. The API writes the same `english_user_dict.json` file as the TUI. Changes made through these endpoints affect subsequent `/audio_query` calls without restarting the API process; previously returned AudioQuery values are unchanged. Edits by a different running process are not automatically reloaded into an already-running API process.

See [User Dictionary](dictionary.md).

## Errors

Common responses:

| Status | Meaning |
| --- | --- |
| `400` | Invalid pronunciation or query |
| `403` | Terms acceptance is required |
| `422` | Invalid style or request value |
| `500` | Synthesis or dictionary operation failed |
| `503` | Voiceger environment is not ready |

Errors contain a `detail` field.

## Compatibility

VOICEVOX-style compatibility does not mean that synthesis is performed by VOICEVOX.

The synthesis engine remains Voiceger.

Programs that depend on unsupported VOICEVOX endpoints or exact VOICEVOX Engine behavior may require changes.

See [Compatibility](compatibility.md).
