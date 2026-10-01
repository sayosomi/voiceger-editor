# voiceger-accent-adapter

An experimental adapter for Voiceger that adds more control over pronunciation and speech generation.

It provides:

- editable Japanese pronunciation and accent;
- editable English stress;
- multiple generation candidates;
- selectable Voiceger reference-audio styles;
- a VOICEVOX-style TTS API;
- a keyboard-first terminal interface.

Voiceger itself is not modified.

## Requirements

You need a local installation of Voiceger:

https://github.com/zunzun999/voiceger_v2

This adapter is currently tested with Voiceger revision:

`f77c1172baf1f490bb962f2d2acd01c852ef3464`

Other revisions may also work, but they are not currently guaranteed.

Set `VOICEGER_ROOT` to your local Voiceger directory:

```bash
export VOICEGER_ROOT=/path/to/voiceger_v2
```

## Terminal Interface

Install the TUI in the Voiceger Python environment:

```bash
"$VOICEGER_ROOT/.venv/bin/python" -m pip install -e '.[tui]'
```

Start it with:

```bash
voiceger-accent-adapter
```

You can also give it text directly:

```bash
voiceger-accent-adapter "このずんだ餅はvery sweetなのだ。"
```

The TUI is still under active development.

Its layout, controls, and shortcuts may change. Detailed TUI documentation will be added after the interface becomes more stable.

Optional LAB sidecars for accepted Japanese, English, and Japanese-English
mixed takes require the LAB extra:

```bash
"$VOICEGER_ROOT/.venv/bin/python" -m pip install -e '.[tui,lab]'
```

Japanese LAB output also requires a `julius` executable. The adapter uses the
pinned segmentation-kit model documented in
[`docs/lab-output.md`](docs/lab-output.md) and caches it outside the output
directory. English LAB output uses the pinned PocketSphinx 5.1.1 dependency.
Mixed Japanese-English LAB output uses MRTE attention from the exact generated
Take to define language regions, then applies the same Julius/PocketSphinx
aligners inside those regions.

## API

This project also provides a VOICEVOX-style HTTP API.

```http
GET  /version
GET  /speakers
POST /audio_query
POST /accent_phrases
POST /synthesis
```

Install the API dependencies:

```bash
"$VOICEGER_ROOT/.venv/bin/python" -m pip install -e '.[api]'
```

Start the API:

```bash
"$VOICEGER_ROOT/.venv/bin/python" -m uvicorn \
  voiceger_accent_adapter.api:app \
  --host 127.0.0.1 \
  --port 8001
```

Basic workflow:

```text
text
  ↓
POST /audio_query
  ↓
edit pronunciation or accent if needed
  ↓
POST /synthesis
  ↓
audio/wav
```

The API does not permanently save generated WAV files.

## Language Support

The current supported scope is:

- Japanese
- Japanese + English mixed text

Japanese pronunciation and pitch accent can be edited.

English stress can also be edited using Voiceger-compatible ARPAbet phonemes.

Other language combinations may work through Voiceger, but they are not currently part of the compatibility guarantee.

For technical details about Japanese pronunciation and accent handling, see:

[`docs/japanese-pronunciation.md`](docs/japanese-pronunciation.md)

Production LAB sidecar behavior is specified in:

[`docs/lab-output.md`](docs/lab-output.md)

## Voiceger Styles

Voiceger's local reference audio files are available as selectable styles.

Current presets include:

- Neutral
- Sweet
- Snippy
- Sexy
- Whispering
- Murmuring
- Exhausted
- Sobbing

Only reference audio that exists in the user's local Voiceger installation is used.

## Project Boundaries

voiceger-accent-adapter is an unofficial project.

It is not made, approved, or supported by the Voiceger project or the Tohoku Zunko / Zundamon Project.

This adapter uses Voiceger as it is. It does not try to remove or bypass safety rules, usage limits, or other restrictions added by Voiceger.

This project only adds more control over Voiceger inference, such as pronunciation, accent, English stress, generation candidates, and inference settings.

If Voiceger has a safety feature or restriction, this project will not add a feature to disable or avoid it.

This project does not modify or redistribute the official Voiceger models or reference audio.

Voiceger is a separate project:

https://github.com/zunzun999/voiceger_v2

## Generated Audio License

> [!IMPORTANT]
> Audio generated with Voiceger:Zundamon is **not covered by the MIT License of this adapter**.
>
> You must follow the official Voiceger Zundamon terms of use when using, publishing, or distributing generated audio.
>
> The official terms require the credit:
>
> `Voiceger:Zundamon`
>
> Please read the latest official terms before using generated audio:
>
> https://zunko.jp/con_ongen_kiyaku.html

The Voiceger Zundamon terms also include rules about how the voice may and may not be used.

These rules still apply when the audio is generated through voiceger-accent-adapter.

## This Adapter License

The code in this repository is licensed under the MIT License.

The MIT License applies **only to the code in this repository**.

It does not grant any rights to Voiceger, GPT-SoVITS, the Voiceger:Zundamon models, reference audio, or other third-party assets.

**The MIT License does not grant rights to the Zundamon character, name, voice, or related trademarks.**

Voiceger and other third-party software and assets remain subject to their own licenses and terms.

Installing or using this adapter does not grant any additional rights to those third-party materials or to generated audio.

For direct optional dependencies and external runtime components, see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Status

voiceger-accent-adapter is under active development.

The API, TUI, settings, and other interfaces may change before the first stable release.
