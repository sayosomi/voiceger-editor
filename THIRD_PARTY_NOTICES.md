# Third-Party Notices

voiceger-accent-adapter is licensed under the MIT License in [LICENSE](LICENSE).

This file documents third-party software, services, models, and other assets that
the adapter integrates with or declares as optional dependencies. Those
third-party materials are not relicensed under the adapter's MIT License.

## Voiceger and Voiceger:Zundamon

Voiceger is a separate project:

https://github.com/zunzun999/voiceger_v2

voiceger-accent-adapter requires a separately installed Voiceger runtime. This
repository does not redistribute Voiceger source, Voiceger models, or Voiceger
reference audio.

Voiceger includes and integrates software and assets that remain subject to
their own licenses and terms. Refer to the Voiceger repository for its current
third-party license information.

The Voiceger:Zundamon voice model and audio generated with it are subject to
the applicable official terms of use, which are separate from this adapter's
MIT License:

https://zunko.jp/con_ongen_kiyaku.html

Installing or using voiceger-accent-adapter does not grant additional rights to
Voiceger, GPT-SoVITS, Voiceger:Zundamon models or reference audio, the Zundamon
character/name/voice, generated audio, or other third-party assets.

## Python optional dependencies

The following packages are installed separately by the user's Python package
manager when the corresponding extras are selected. They are not vendored in
this repository and remain subject to their upstream licenses.

| Package | Version used by this project | Upstream license |
| --- | --- | --- |
| FastAPI | 0.112.1 | MIT |
| Uvicorn | 0.34.2 | BSD-3-Clause |
| SoundFile | 0.13.1 | BSD-3-Clause |
| PocketSphinx | 5.1.1 | BSD-style license; see its upstream LICENSE for bundled-component notices |

Upstream projects:

- FastAPI: https://github.com/fastapi/fastapi
- Uvicorn: https://github.com/Kludex/uvicorn
- SoundFile: https://github.com/bastibe/python-soundfile
- PocketSphinx: https://github.com/cmusphinx/pocketsphinx

Dependencies of those packages, including native libraries that may be bundled
in their wheels, are governed by their own licenses and notices.

## Julius

Japanese LAB alignment can use the external Julius speech-recognition
executable:

https://github.com/julius-speech/julius

Julius is licensed under the BSD 3-Clause License. The Julius executable is not
bundled in this repository.

## Julius segmentation-kit acoustic model

When Japanese LAB output is used without a user-supplied HMM, the adapter can
download and cache this file at runtime:

`hmmdefs_monof_mix16_gid.binhmm`

It is fetched from the Julius segmentation-kit repository at pinned commit:

`e0e8bbaf98e27d19dfc6fe8312be607ad03592ad`

Source:

https://github.com/julius-speech/segmentation-kit

The segmentation-kit repository is licensed under the MIT License and carries
the following copyright notices in its license file:

- Copyright (c) 2005-2015 Julius project team, Lee Lab., Nagoya Institute of Technology
- Copyright (c) 2008 Ryuichi Nisimura

The model is an external runtime asset. It is not committed to or distributed
as part of the voiceger-accent-adapter source repository.

## No endorsement

References to third-party projects identify interoperability and dependency
boundaries only. They do not imply sponsorship, approval, or endorsement of
voiceger-accent-adapter by those projects or their rights holders.
