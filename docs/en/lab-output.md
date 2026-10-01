# LAB Output

Voiceger Editor can optionally save a .lab phoneme-timing file beside an accepted Take.

LAB output is disabled by default.

## What a LAB file contains

Each row contains a start time, end time, and phoneme:

~~~text
<start_100ns> <end_100ns> <phoneme>
~~~

One second is 10,000,000 timestamp units.

LAB output can be useful for lip sync, animation, and tools that need phoneme timing.

## Install

Install the LAB extra:

~~~bash
python -m pip install 'voiceger-editor[tui,lab]'
~~~

English alignment uses the pinned PocketSphinx 5.1.1 dependency.

Japanese alignment also requires a Julius executable. The adapter downloads its pinned small Julius acoustic model into an application cache when first needed, so the first Japanese LAB may require internet access.

## Enable LAB

Turn LAB on in Settings, or use the one-run CLI option:

~~~bash
voiceger-editor --save-lab
~~~

Disable it for one run with:

~~~bash
voiceger-editor --no-save-lab
~~~

LAB is created only for an accepted Take. Candidate Takes are not aligned in advance.

## Output files

Accepted output uses minute-resolution local time and source text:

~~~text
YYYYMMDDHHMM_テキスト.wav
YYYYMMDDHHMM_テキスト.lab
~~~

If TXT is enabled:

~~~text
YYYYMMDDHHMM_テキスト.txt
~~~

Style is not part of the filename.

Characters that are invalid in common filenames are removed.

If the basename already exists, Voiceger Editor adds -2, -3, and so on before the extension. WAV, TXT, and LAB use the same collision-safe stem.

Source text is not silently shortened. If the resulting filename is too long for the filesystem, saving reports an error.

## Supported languages

| Utterance | LAB |
| --- | --- |
| Japanese | Supported with Julius |
| English alignment used by the editor | Supported with PocketSphinx |
| Japanese-English mixed | Supported with both aligners and recorded mixed timing |
| Other languages | Unsupported |

Japanese alignment uses the pronunciation already chosen by Voiceger Editor. Julius measures timing; it does not choose a new reading.

English alignment uses the stored ARPAbet pronunciation. PocketSphinx measures timing; it does not replace the editor pronunciation.

## Mixed Japanese-English Takes

Mixed LAB needs language-boundary timing captured during the exact synthesis that created the candidate.

For that reason, enable LAB **before** generating a mixed Take that you want to save with LAB.

Recommended flow:

~~~text
LAB ON
→ Generate
→ listen
→ accept
~~~

If a mixed candidate was generated while LAB was off, turning LAB on afterward does not retroactively add the required timing data. Regenerate the Take after enabling LAB.

## Failure behavior

The WAV is the primary output.

If LAB generation fails:

1. the accepted WAV is kept;
2. TXT is kept if it was requested and saved;
3. no partial final .lab is left behind;
4. Voiceger Editor reports that WAV saving succeeded but LAB generation failed.

Common causes include a missing Julius executable, model download failure, missing PocketSphinx, an alignment mismatch, or missing mixed-language timing data.

## Cache and overrides

The Julius model is cached outside the output directory.

VOICEGER_LAB_CACHE_DIR can override the LAB cache location. Additional Julius runtime/model overrides are intended for advanced troubleshooting.

## HTTP API

The VOICEVOX-style /synthesis endpoint returns WAV data directly. It does not create accepted-Take TXT or LAB sidecars.
