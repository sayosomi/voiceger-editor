# LAB Output

Voiceger Editor can optionally save a `.lab` phoneme-timing file beside an accepted Take.

LAB output is useful for lip sync, animation, speech analysis, and tools that need phoneme timing.

LAB is optional and disabled by default.

## Install LAB support

Install the LAB extra:

```bash
python -m pip install 'voiceger-editor[tui,lab]'
```

English alignment uses the pinned PocketSphinx 5.1.1 dependency from this extra.

Japanese LAB output also requires a `julius` executable.

The Japanese acoustic model is a pinned external runtime asset. Voiceger Editor downloads and caches it when needed.

The first Japanese LAB operation may therefore require network access.

## Enable LAB output

Open Settings and set:

```text
LAB: ON
```

For one CLI invocation, use:

```text
--save-lab
```

To disable it for one invocation:

```text
--no-save-lab
```

## Saved files

LAB is generated only for the accepted Take.

Candidate Takes are not aligned in advance.

Example:

```text
202610020307_今日は雨なのだ。.wav
202610020307_今日は雨なのだ。.lab
```

If TXT is also enabled:

```text
202610020307_今日は雨なのだ。.txt
```

All sidecars use the same collision-safe basename.

If the basename already exists, Voiceger Editor adds:

```text
-2
-3
...
```

before the extension.

## Filename format

Accepted TUI Takes use:

```text
YYYYMMDDHHMM_テキスト.wav
```

The timestamp uses local time and minute resolution.

Style is not included in the filename.

Characters that are invalid in filenames are removed.

Voiceger Editor does not silently shorten source text if the resulting filename is too long. Saving fails with a clear filename-too-long error instead.

## LAB format

Each LAB line contains:

```text
<start> <end> <phoneme>
```

Times use 100-nanosecond units.

One second is:

```text
10000000
```

Boundary silence is written as:

```text
pau
```

The final LAB covers the complete accepted WAV.

## Japanese

Japanese alignment uses Julius.

Voiceger Editor aligns the pronunciation already stored in the accepted Take.

Julius does not choose a new pronunciation.

Japanese LAB requires:

- the `julius` executable;
- the pinned Voiceger Editor alignment model.

## English

English alignment uses PocketSphinx 5.1.1.

Voiceger Editor constrains the aligner to the stored ARPAbet pronunciation.

PocketSphinx does not replace the pronunciation with its own dictionary or G2P result.

If an unusual name or coined word sounds wrong, fix its pronunciation before generating a new Take.

## Japanese-English mixed Takes

Mixed LAB output uses timing information captured from the exact synthesis that generated the candidate.

Because this information is captured during generation, LAB must be enabled **before** generating a mixed Take.

Use this order:

```text
LAB ON
→ Generate
→ listen
→ accept
```

This does not work for an already-generated mixed candidate:

```text
LAB OFF
→ Generate
→ LAB ON
→ accept existing candidate
```

The WAV can still be accepted, but mixed LAB timing information is missing.

Regenerate the Take after enabling LAB.

## Failure behavior

The accepted WAV is the primary output.

If LAB generation fails:

- the WAV is kept;
- the TXT sidecar is kept if it was requested and saved successfully;
- no partial final `.lab` is left behind;
- Voiceger Editor reports that WAV saving succeeded but LAB generation failed.

Possible causes include:

- Julius is missing;
- the Japanese alignment model cannot be downloaded or loaded;
- PocketSphinx is unavailable;
- alignment fails;
- an unsupported phone is present;
- mixed timing information is unavailable.

LAB failure does not discard the accepted Take.

## Cache

On macOS, the default Japanese LAB cache is:

```text
~/Library/Caches/voiceger-editor/lab
```

On other platforms, the normal XDG cache location is used.

Advanced overrides include:

```text
VOICEGER_LAB_CACHE_DIR
VOICEGER_JULIUS
VOICEGER_JULIUS_HMM
```

## HTTP API

The HTTP `/synthesis` endpoint returns WAV data directly.

It does not save accepted-Take WAV, TXT, or LAB files.

LAB sidecars belong to the accepted-Take workflow in the TUI.
