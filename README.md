# voiceger-accent-adapter

An experimental adapter for controllable Japanese pronunciation and accent/prosody with [Voiceger](https://github.com/zunzun999/voiceger_v2).

## Goal

Provide a stable layer between user-editable Japanese pronunciation notation and Voiceger / GPT-SoVITS without vendoring or redistributing Voiceger itself.

The intended workflow is:

```text
Japanese text
    ↓
OpenJTalk-based automatic pronunciation/prosody
    ↓
editable pronunciation notation
    ↓
voiceger-accent-adapter
    ↓
Voiceger / GPT-SoVITS
    ↓
audio
```

## Core ideas

- Keep display text and spoken pronunciation separate.
- Generate a usable pronunciation automatically from Japanese text.
- Allow manual correction using a VOICEVOX-style / AquesTalk-style notation.
- Every accent phrase has exactly one `'`; `あ'め` means accent position 1 and `あめ'` means accent position 2.
- Use `/` for a no-pause accent-phrase boundary.
- Accept both hiragana and katakana in the editable notation.
- Prefer an explicitly supplied pronunciation over automatic analysis.
- Return the resolved pronunciation actually used for synthesis.
- Isolate Voiceger-specific integration behind an adapter so the pronunciation/prosody core can be tested independently.
- Do not copy or redistribute Voiceger source code, models, reference audio, or other Voiceger assets in this repository.

## Validated spike

A local runtime spike confirmed that Voiceger can be controlled without modifying upstream files:

```text
雨 -> a ] m e
飴 -> a [ m e
```

Injecting only that prosody difference into the same sentence produced natural audio with an audible accent difference.

At the Japanese G2P hook point, `/` is converted to OpenJTalk's `#` boundary token. Voiceger v2's existing `clean_text()` then converts `#` to `UNK`, reproducing the normal Voiceger frontend path. Dropping the boundary token entirely was tested and can destabilize synthesis.

## Planned API

Conceptually:

```http
POST /pronunciation
```

Converts Japanese `text` into an editable pronunciation representation.

```http
POST /tts
```

Synthesizes speech from `text` plus an optional manually edited `pronunciation`.

See [docs/japanese-pronunciation.md](docs/japanese-pronunciation.md) for the current design.

## Upstream dependency

Voiceger is developed separately at:

https://github.com/zunzun999/voiceger_v2

This repository is not a fork and does not contain Voiceger itself. The initial integration may import Voiceger / GPT-SoVITS internals at runtime and adapt its Japanese G2P path.

## Status

Early implementation / spike phase. No stable API yet.

## License

Not selected yet. Before public release, only code authored in this repository should be licensed here; Voiceger and its dependencies remain subject to their own terms.
