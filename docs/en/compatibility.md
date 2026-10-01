# Compatibility

This page describes the supported Voiceger Editor v1 compatibility scope.

Something outside this scope may still work, but it is not guaranteed.

## Voiceger

Voiceger Editor v1 is tested with:

~~~text
f77c1172baf1f490bb962f2d2acd01c852ef3464
~~~

Other Voiceger revisions may work. Run:

~~~bash
voiceger-editor --check
~~~

to compare the local installation with the tested revision.

## Python

Voiceger Editor v1 supports Python 3.9 and is intended to run inside Voiceger's Python environment.

## Supported speech scope

The documented v1 scope is:

- Japanese;
- Japanese with English sections.

Japanese supports editable reading, pitch accent, dictionary entries, previews, Takes, VOICEVOX-style AudioQuery generation, and optional LAB output.

English sections support Voiceger G2P, ARPAbet phoneme editing, stress editing, dictionary entries, previews, and mixed Japanese-English synthesis.

Example:

~~~text
このずんだ餅はvery sweetなのだ。
~~~

Other Voiceger language modes are not part of the v1 compatibility guarantee.

## Styles

Voiceger Editor uses Voiceger reference WAVs as styles and uses the corresponding VOICEVOX Zundamon IDs:

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

Neutral (3) is the default.

The same IDs are used by the TUI, saved settings, --style, /speakers, and API speaker parameters.

Only styles whose reference WAVs exist locally are available.

Matching the style ID does not mean the generated audio is VOICEVOX audio. Voiceger remains the synthesis engine.

## VOICEVOX-style API

Voiceger Editor implements a useful subset of the VOICEVOX Engine API, including /version, /speakers, /audio_query, /accent_phrases, /synthesis, and Japanese user-dictionary endpoints.

Supported AudioQuery controls include accent_phrases, speedScale, outputSamplingRate, and outputStereo.

Known VOICEVOX controls without a Voiceger equivalent are accepted and ignored with a warning. See [HTTP API](api.md).

Voiceger Editor may add voicegerSegments and pronunciationPunctuation to preserve information that standard VOICEVOX AudioQuery data does not fully represent.

## Dictionary compatibility

The Japanese dictionary API uses a VOICEVOX-compatible UUID-keyed UserDictWord representation.

The English pronunciation dictionary is a Voiceger Editor feature and is separate from the VOICEVOX dictionary API.

## Output files

Accepted TUI Takes use:

~~~text
YYYYMMDDHHMM_テキスト.wav
~~~

If the basename already exists, Voiceger Editor adds -2, -3, and so on. Optional .txt and .lab sidecars use the same basename.

The HTTP /synthesis endpoint returns WAV data directly and does not use this filename system.

## Public application identity

~~~text
Product:        Voiceger Editor
Repository:     sayosomi/voiceger-editor
PyPI:           voiceger-editor
CLI:            voiceger-editor
Python package: voiceger_editor
~~~


## What compatibility does not mean

Voiceger Editor does not guarantee every VOICEVOX endpoint, every VOICEVOX synthesis control, identical generated speech, identical metadata, or support for every Voiceger language mode.

Voiceger remains a separate upstream runtime and is not modified by Voiceger Editor.
