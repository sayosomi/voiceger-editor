# Compatibility

This page describes the supported Voiceger Editor 0.1 compatibility scope.

Something outside this scope may still work, but it is not guaranteed.

## Version stability

0.1.0 was the initial public release. The current documentation describes v0.1.1 behavior within the 0.1 series.

Before 1.0, user-facing interfaces may still change as the project gains real-world usage. This includes TUI behavior, settings and dictionary formats, and Voiceger Editor API extensions. Breaking changes will be documented in release notes.

## Voiceger

Voiceger Editor 0.1 is tested with:

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

Voiceger Editor 0.1 supports:

```text
Python 3.9
```

It is intended to run inside Voiceger's Python environment.

## Windows

The 0.1 package and TUI startup boundary are automatically verified on GitHub-hosted Windows with Python 3.9.

The Windows CI verifies:

- building and installing the package;
- `--help` and `--version` without the TUI extra;
- installing the TUI extra and its Windows curses backend;
- importing `curses` and the Voiceger Editor TUI;
- focused entrypoint tests.

TUI playback on Windows requires `ffplay.exe` in `PATH`.

This automated verification does not run a real Voiceger synthesis, an interactive keyboard TUI session, or LAB alignment on Windows.

LAB output is not part of the verified 0.1 Windows support boundary. See [LAB Output](lab-output.md).

## Supported speech scope

The documented 0.1 scope is:

- Japanese;
- English;
- Japanese with English sections.

### Japanese

Supported features include:

- text-to-pronunciation conversion;
- editable readings;
- editable pitch accent;
- Japanese user dictionary;
- previews and Takes;
- VOICEVOX-style AudioQuery generation;
- optional LAB output.

### English

English-only Captions and English sections inside mixed Japanese-English speech support:

- Voiceger English G2P;
- ARPAbet-style phonemes;
- stress editing;
- English user dictionary;
- previews;
- Takes and accepted output;
- synthesis in native Voiceger English mode for English-only Captions;
- synthesis inside mixed Japanese-English speech;
- optional LAB output.

Mixed example:

```text
このずんだ餅はvery sweetなのだ。
```

### Other languages

Other Voiceger language modes are not part of the Voiceger Editor 0.1 compatibility guarantee.

## Styles

Voiceger Editor uses Voiceger reference WAVs as styles.

The style IDs match the corresponding VOICEVOX Zundamon style IDs:

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

Matching the style ID does not mean that the generated audio is VOICEVOX audio. Voiceger remains the synthesis engine.

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

Known VOICEVOX controls without direct Voiceger equivalents are accepted and ignored with a warning:

```text
pitchScale
intonationScale
volumeScale
prePhonemeLength
postPhonemeLength
pauseLength
pauseLengthScale
```

## Voiceger Editor extensions

Voiceger Editor may add:

```text
voicegerSegments
pronunciationPunctuation
```

Applications should keep these fields when passing a query from `/audio_query` to `/synthesis`.

## Dictionary compatibility

The Japanese dictionary API uses a VOICEVOX-compatible UUID-keyed `UserDictWord` representation.

A compatible dictionary can be imported through:

```text
POST /import_user_dict
```

The English pronunciation dictionary is a Voiceger Editor feature and is separate from the VOICEVOX dictionary API.

## LAB output

On the platforms where the LAB dependencies are available and verified, optional LAB output supports the Voiceger Editor Japanese, English, and Japanese-English alignment workflows.

Japanese alignment uses Julius.

English alignment uses PocketSphinx 5.1.1.

Windows LAB is not verified for 0.1.

LAB sidecars belong to the accepted-Take workflow. They are not returned by the HTTP `/synthesis` endpoint.

See [LAB Output](lab-output.md).

## Output files

Accepted TUI Takes can be saved as WAV or FLAC, or as MP3 when ffmpeg is
available. The default basename template is:

```text
{YYYYMMDDHHmm}_{text}
```

The filename template is configurable and can use `{text}`, `{style}`, and
the supported date/time tokens. The file extension comes from the selected
Format.

If a final basename collides with an existing output, Voiceger Editor adds a
collision suffix such as `-2` or `-3`. Optional `.txt` and `.lab` files
use the same final basename.

Invalid filename characters are removed. Source text is not silently shortened
if the filename is too long.

The HTTP `/synthesis` endpoint returns WAV data directly and does not use this naming system.

## Application identity

The 0.1 public names are:

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
