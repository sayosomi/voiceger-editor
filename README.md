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
- Allow manual correction using an AquesTalk/SofTalk-inspired notation.
- Use `'` for an accent nucleus and `/` for an accent-phrase boundary in the initial notation design.
- Prefer an explicitly supplied pronunciation over automatic analysis.
- Return the resolved pronunciation actually used for synthesis.
- Isolate Voiceger-specific integration behind an adapter so the pronunciation/prosody core can be tested independently.
- Do not copy or redistribute Voiceger source code, models, reference audio, or other Voiceger assets in this repository.

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

Design phase. No stable API yet.

## License

Not selected yet. Before public release, only code authored in this repository should be licensed here; Voiceger and its dependencies remain subject to their own terms.
