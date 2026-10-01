# Compatibility

This page describes the supported Voiceger Editor v1 compatibility scope.

Something outside this scope may still work, but it is not guaranteed.

## Voiceger

Voiceger Editor v1 is tested with:

```text
f77c1172baf1f490bb962f2d2acd01c852ef3464
```

Other Voiceger revisions may work.

Run:

```bash
voiceger-editor --check
```

to compare the local installation with the tested revision.

A different revision normally produces a warning rather than an automatic failure.

## Python

Voiceger Editor v1 supports Python 3.9.

It is intended to run inside Voiceger's Python environment.

## Supported speech scope

The documented v1 scope is:

- Japanese;
- Japanese with English sections.

Japanese supports text-to-pronunciation conversion, editable readings, editable pitch accent, the Japanese user dictionary, previews and Takes, the VOICEVOX-style AudioQuery workflow, and optional LAB output.

English sections support Voiceger English G2P, ARPAbet-style phonemes, stress editing, the English user dictionary, previews, mixed synthesis, and optional alignment support.

Other Voiceger language modes are not part of the Voiceger Editor v1 compatibility guarantee.

## Styles

The corresponding VOICEVOX Zundamon style IDs are:

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

Neutral (`3`) is the default.

The same IDs are used by the TUI, saved settings, `--style`, `/speakers`, and API `speaker=` parameters.

Only styles whose reference WAVs exist locally are available.

Matching a style ID does not mean that the generated audio is VOICEVOX audio. Voiceger remains the synthesis engine.

## VOICEVOX-style API

Voiceger Editor implements a useful subset of the VOICEVOX Engine API.

Main supported endpoints include:

```text
GET  /version
GET  /speakers
POST /audio_query
POST /accent_phrases
POST /synthesis
```

Japanese dictionary endpoints are also available.

See [HTTP API](api.md).

## AudioQuery fields

Supported controls include:

| Field | Support |
| --- | --- |
| `accent_phrases` | Supported |
| `speedScale` | Supported |
| `outputSamplingRate` | Supported |
| `outputStereo` | Supported |

These known VOICEVOX controls are accepted but do not currently have direct Voiceger equivalents:

```text
pitchScale
intonationScale
volumeScale
prePhonemeLength
postPhonemeLength
pauseLength
pauseLengthScale
```

Changed values are ignored with a warning.

## Voiceger Editor AudioQuery extensions

Voiceger Editor may add:

```text
voicegerSegments
pronunciationPunctuation
```

Applications should keep these fields when passing a query from `/audio_query` to `/synthesis`.

## Japanese dictionary compatibility

The Japanese dictionary API uses a VOICEVOX-compatible UUID-keyed `UserDictWord` representation.

A compatible dictionary can be imported through `POST /import_user_dict`.

The English pronunciation dictionary is a Voiceger Editor feature and is separate from the VOICEVOX dictionary API.

## LAB output

Optional LAB output supports the Voiceger Editor Japanese, English, and Japanese-English alignment workflows.

Japanese alignment uses Julius.

English alignment uses PocketSphinx 5.1.1.

LAB sidecars are part of the accepted-Take workflow. They are not returned by the HTTP `/synthesis` endpoint.

See [LAB Output](lab-output.md).

## Output files

Accepted TUI Takes use:

```text
YYYYMMDDHHMM_テキスト.wav
```

If the basename already exists, Voiceger Editor adds `-2`, `-3`, and so on.

Optional `.txt` and `.lab` files use the same basename.

The source text is not silently shortened if the filename is too long.

The HTTP `/synthesis` endpoint returns WAV data directly and does not use this naming system.

## Application identity

The v1 public names are:

```text
Product:        Voiceger Editor
Repository:     sayosomi/voiceger-editor
PyPI:           voiceger-editor
CLI:            voiceger-editor
Python package: voiceger_editor
```

Pre-release names are not compatibility aliases.

## What compatibility does not mean

Voiceger Editor does not use VOICEVOX for synthesis.

It does not guarantee every VOICEVOX endpoint, every VOICEVOX synthesis control, identical generated speech, identical metadata, or support for every Voiceger language mode.

Voiceger remains a separate upstream runtime and is not modified by Voiceger Editor.
