# HTTP API

Voiceger Editor provides a VOICEVOX-style HTTP API.

The basic workflow is:

~~~text
text
→ AudioQuery
→ edit the query if needed
→ synthesis
→ WAV
~~~

It implements a useful subset of the VOICEVOX Engine API. It is not a complete replacement for VOICEVOX Engine.

## Install and start

Install API support from PyPI:

~~~bash
python -m pip install 'voiceger-editor[api]'
~~~

Voiceger must already be installed and the Voiceger:Zundamon terms must already be accepted.

Start the API:

~~~bash
python -m uvicorn   voiceger_editor.api:app   --host 127.0.0.1   --port 8001
~~~

FastAPI documentation is available at http://127.0.0.1:8001/docs.

## Endpoints

Main endpoints:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | / | Engine information |
| GET | /version | Voiceger Editor version |
| GET | /speakers | Available Voiceger styles |
| POST | /audio_query | Create an AudioQuery from text |
| POST | /accent_phrases | Create accent phrases |
| POST | /synthesis | Generate WAV audio |

Japanese dictionary endpoints:

~~~text
GET    /user_dict
POST   /user_dict_word
PUT    /user_dict_word/{word_uuid}
DELETE /user_dict_word/{word_uuid}
POST   /import_user_dict
~~~

## Speakers and styles

/speakers exposes local Voiceger reference WAVs as VOICEVOX-style talk styles.

The corresponding Zundamon style IDs match VOICEVOX:

| Style | ID |
| --- | ---: |
| Sweet | 1 |
| Neutral | 3 |
| Sexy | 5 |
| Snippy | 7 |
| Whispering | 22 |
| Murmuring | 38 |
| Exhausted | 75 |
| Sobbing | 76 |

The Voiceger Editor speaker UUID is:

~~~text
voiceger-editor-zundamon
~~~

Only locally available reference styles are returned.

## Create an AudioQuery

~~~bash
curl -s -G -X POST   'http://127.0.0.1:8001/audio_query'   --data-urlencode 'text=今日は雨なのだ。'   --data-urlencode 'speaker=3'   > query.json
~~~

Japanese-English mixed text can be passed in the same way.

## Synthesize

~~~bash
curl -s -X POST   'http://127.0.0.1:8001/synthesis?speaker=3'   -H 'Content-Type: application/json'   --data-binary @query.json   --output output.wav
~~~

The response is WAV data. The API does not save the WAV into the normal Voiceger Editor output directory and does not create TXT or LAB sidecars.

## Edit pronunciation

The JSON returned by /audio_query can be edited before /synthesis.

For Japanese, accent_phrases contains morae and the 1-based accent position. Changing an accent value changes the Japanese accent used for synthesis.

The /accent_phrases endpoint can also accept editable kana notation with is_kana=true. API kana notation uses / between accent phrases.

See [Pronunciation](pronunciation.md).

## AudioQuery controls

Applied controls include:

| Field | Behavior |
| --- | --- |
| accent_phrases | Japanese pronunciation and accent |
| speedScale | Voiceger speech speed |
| outputSamplingRate | Output sample rate |
| outputStereo | Mono or duplicated stereo |

These known VOICEVOX fields are accepted, but Voiceger currently has no matching control:

~~~text
pitchScale
intonationScale
volumeScale
prePhonemeLength
postPhonemeLength
pauseLength
pauseLengthScale
~~~

Non-default values are ignored with a warning instead of causing the whole request to fail.

## Voiceger Editor extensions

An AudioQuery may contain:

~~~text
voicegerSegments
pronunciationPunctuation
~~~

voicegerSegments preserves mixed-language sections and English phonemes.

pronunciationPunctuation preserves Japanese punctuation information.

Keep these fields when passing a query from /audio_query to /synthesis.

## Sampling

The HTTP API currently uses the Voiceger defaults:

~~~text
Top K:       20
Top P:       1.00
Temperature: 1.00
~~~

These are not currently AudioQuery fields.

## Japanese dictionary

The API and TUI share the same Japanese dictionary. /import_user_dict accepts the UUID-keyed expanded VOICEVOX UserDictWord form.

The separate English pronunciation dictionary is currently managed through the TUI.

See [User Dictionary](dictionary.md).

## Errors

Common status codes:

| Status | Meaning |
| --- | --- |
| 400 | Invalid pronunciation or query |
| 403 | Terms acceptance is required |
| 422 | Invalid style or request value |
| 500 | Synthesis or dictionary operation failed |
| 503 | Voiceger environment is not ready |

See [Compatibility](compatibility.md) for the supported boundary.
