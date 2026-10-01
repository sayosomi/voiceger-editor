# LAB Output

Voiceger Editor can optionally save a `.lab` phoneme-timing file beside an accepted Take.

LAB output is useful for lip sync, animation, speech analysis, and tools that need phoneme timing.

LAB saving is disabled by default.

## Install LAB support

Install the Python LAB dependencies from PyPI:

```bash
python -m pip install 'voiceger-editor[tui,lab]'
```

English alignment uses the pinned PocketSphinx 5.1.1 dependency.

Japanese alignment also requires a Julius executable.

## Enable LAB output

Open Settings and turn LAB on.

You can also enable it for one invocation:

```bash
voiceger-editor --save-lab
```

Disable it with:

```bash
voiceger-editor --no-save-lab
```

## Saved files

When an accepted Take is saved with LAB enabled:

```text
202610020307_今日は雨なのだ。.wav
202610020307_今日は雨なのだ。.lab
```

If TXT is also enabled:

```text
202610020307_今日は雨なのだ。.txt
```

All sidecars use the same collision-safe basename.

If that basename already exists, Voiceger Editor adds `-2`, `-3`, and so on.

## Output filename format

Accepted Takes use:

```text
YYYYMMDDHHMM_テキスト.wav
```

The timestamp uses local time with minute resolution.

The selected Style is not included in the filename.

Characters that are invalid in filenames are removed from the filename text. The TXT sidecar still stores the exact source text.

Voiceger Editor does not silently shorten an overlong filename. If the filesystem rejects the filename as too long, saving fails with a clear error.

## Supported languages

| Utterance | LAB support |
| --- | --- |
| Japanese | Supported |
| English alignment used by Voiceger Editor | Supported |
| Japanese-English mixed | Supported with mixed timing provenance |
| Other languages | Not supported |

Japanese uses Julius.

English uses PocketSphinx 5.1.1.

## Accepted Take only

LAB alignment runs only for the accepted Take.

Candidate Takes are not aligned in advance.

The aligner uses the exact accepted WAV and the pronunciation/query state that generated that candidate.

## Japanese alignment

Japanese LAB output uses Julius forced alignment.

Voiceger Editor supplies the known pronunciation. Julius measures timing; it does not choose a new pronunciation.

The required Julius acoustic model is treated as an external cached runtime asset rather than a file in the output directory.

## English alignment

English LAB output uses PocketSphinx forced alignment.

Voiceger Editor supplies the stored ARPAbet pronunciation.

PocketSphinx does not replace unusual names or coined words with its own pronunciation.

If an unusual word sounds wrong, correct the pronunciation first, then generate a new Take.

## Mixed Japanese-English LAB

Mixed LAB output uses timing information captured from the exact Voiceger synthesis that generated the candidate, then aligns the Japanese and English regions with their language-specific aligners.

For mixed text, enable LAB **before** generating the Take:

```text
LAB ON
→ Generate
→ listen
→ accept
```

If a mixed Take was generated while LAB was off, then LAB is turned on later, the existing candidate may not contain the timing provenance needed for mixed LAB output.

Regenerate after enabling LAB.

## LAB format

Each line is:

```text
<start_100ns> <end_100ns> <phoneme>
```

One second is:

```text
10000000
```

Boundary silence is written as `pau`.

The final LAB must cover the complete accepted WAV without invented gaps or overlaps.

## Failure behavior

The accepted WAV is the primary output.

If LAB generation fails:

- the WAV remains saved;
- the TXT file remains saved if it was requested successfully;
- no partial final `.lab` is left behind;
- Voiceger Editor shows a LAB warning.

Possible causes include:

- Julius is missing;
- an alignment model is unavailable;
- PocketSphinx is missing;
- the expected phoneme sequence does not align;
- mixed-language timing provenance is unavailable;
- LAB validation fails.

## HTTP API

The VOICEVOX-style `/synthesis` endpoint returns WAV data directly.

It does not create accepted-Take TXT or LAB sidecars.
