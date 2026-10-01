# LAB sidecar output

This document defines the production contract for optional `.lab` sidecar output.

Implementation tracking: #60 (pure-language production path), #66 (mixed-language production path).

Feasibility evidence:

- #56 selected **Julius** for Japanese after Human comparison against MFA.
- #58 selected **PocketSphinx 5.1.1** for English after real forced-alignment E2E and Human review.
- #61 validated Japanese-English mixed alignment with MRTE attention boundaries plus per-language forced alignment.
- #66 owns the production mixed-language implementation.

## User-facing behavior

LAB saving is optional and disabled by default.

The persisted setting is:

```text
save_lab: false
```

When an accepted take is saved with LAB enabled, the accepted WAV and sidecars share one basename:

```text
YYYYMMDD_HHMMSS_{text}.wav
YYYYMMDD_HHMMSS_{text}.txt
YYYYMMDD_HHMMSS_{text}.lab
```

The TXT file exists only when `save_text` is enabled.

The LAB file exists only when `save_lab` is enabled, the utterance language is supported, and forced alignment succeeds.

LAB generation happens only for the accepted take. Candidate takes are not aligned.

The TUI exposes a Settings toggle equivalent to:

```text
[L] LAB: ON/OFF
```

CLI one-shot overrides are:

```text
--save-lab
--no-save-lab
```

The VOICEVOX-style HTTP `/synthesis` endpoint continues to stream WAV and does not create sidecar files.

## Accepted-take source of truth

Forced alignment uses:

1. the exact accepted WAV;
2. the pronunciation/query snapshot that generated that accepted candidate.

The aligner must not rebuild pronunciation from subsequently edited text or pronunciation state.

The adapter remains the pronunciation authority. Aligners measure timing; they do not choose what was pronounced.

## LAB format

Each line is:

```text
<start_100ns> <end_100ns> <phoneme>
```

One second equals `10,000,000` timestamp units.

The final LAB must:

- cover the full accepted WAV duration;
- use `pau` for boundary silence;
- contain no invented internal gaps or overlaps;
- merge adjacent silence intervals when appropriate;
- be published only after the complete alignment has validated successfully.

Timing must come from forced alignment. Never derive timing by evenly dividing the WAV or by phoneme/mora count.

## Language dispatch

| Utterance | Aligner | Production status |
| --- | --- | --- |
| Pure Japanese | Julius | Supported |
| Pure English | PocketSphinx 5.1.1 | Supported |
| Japanese-English mixed | MRTE boundary probe + Julius/PocketSphinx | Supported when timing provenance and all region alignments validate |
| Other languages | None | Unsupported |

MFA is not part of the production LAB path.

## Japanese: Julius

Use the adapter-owned Japanese mora/phoneme sequence from the `AudioQuery`.

Do not run free ASR and do not ask Julius to infer pronunciation.

### Audio preparation

Align against a temporary mono 16 kHz PCM copy of the accepted WAV.

The successful #56 spike established that Julius preprocessing can strip zero-valued sample runs. Production alignment must preserve the spike's source-time mapping so these preprocessing differences do not shift the final LAB relative to the original accepted WAV.

### Acoustic model

Use the small pinned Julius segmentation model proven by #56:

- segmentation-kit commit: `e0e8bbaf98e27d19dfc6fe8312be607ad03592ad`
- model: `hmmdefs_monof_mix16_gid.binhmm`

The model is an external/cached runtime asset. Do not place it in the output directory and do not commit an unreviewed binary copy to the repository.

### Phone mapping

For Julius alignment:

- `cl -> q`
- `pau` / `sil -> sp` where required
- devoiced uppercase vowels use the Julius-compatible base vowel representation established by #56

For LAB export:

- Julius `q -> cl`
- Julius boundary silence -> `pau`
- preserve `N`
- exported vowels use the adapter/VOICEVOX-facing lowercase form established by the spike

The final aligned phone sequence must match the expected adapter-owned sequence after explicit mapping.

## English: PocketSphinx

Use PocketSphinx **5.1.1** through its Python API.

Use the exact adapter-owned `voicegerSegments[*].phonemes` as the pronunciation source.

PocketSphinx must not use free ASR, its own G2P, or its ordinary dictionary to replace the adapter pronunciation.

### Acoustic-phone conversion

PocketSphinx's bundled US-English acoustic model uses stressless CMU phones.

At the alignment boundary only:

- remove explicit non-acoustic punctuation/control tokens;
- strip lexical-stress digits from vowels, such as `AH0 -> AH`, `OW1 -> OW`;
- keep consonants unchanged;
- keep bare legacy `ER` and `IH`;
- reject `UNK` and unsupported phones instead of guessing.

The original stress-bearing ARPAbet remains adapter/query state.

### Audio preparation and alignment

Create a temporary mono 16 kHz PCM copy of the accepted WAV while preserving duration.

Use the proven #58 two-pass flow:

1. construct a PocketSphinx decoder with the bundled US-English acoustic model;
2. inject one dummy lexical token with `Decoder.add_word()`, mapping it to the exact stressless adapter phone sequence;
3. use `Decoder.set_align_text()` and run the first decode pass;
4. use `Decoder.set_alignment()` and run the second decode pass;
5. obtain phone boundaries from `get_alignment().phones()`;
6. validate that returned non-silence phones exactly match the constrained sequence.

English LAB uses stressless CMU/ARPAbet labels plus `pau`.

### Unusual names and coined words

PocketSphinx does not repair a wrong source pronunciation.

The #58 stress cases with `Zundamon` and `zunda mochi` aligned poorly when the adapter-provided pronunciation did not match the generated audio closely enough. Common-word controls removed the major anomalies and were accepted for production use.

Therefore unusual names, coined words, and romanized Japanese must be corrected through the adapter's pronunciation editing or user dictionary.

Once corrected, LAB generation aligns the corrected adapter phone sequence. It must not silently substitute a PocketSphinx pronunciation.

## Mixed Japanese-English utterances

Mixed LAB alignment uses the strategy validated by #61.

### Generation-time timing provenance

For a mixed Take candidate, capture MRTE cross-attention from the exact Voiceger
decode that produced that candidate. Map adapter-owned segment phone ranges to
the exact target phone IDs passed to SoVITS and require an exact match.

On the attention-frame time axis:

- detect acoustic speech onset at -40, -35, -30, and -25 dB relative RMS;
- smooth per-head segment attention mass with the validated centered five-frame window;
- require exactly one attention head whose dominance follows the expected
  segment order after every onset threshold;
- obtain each language-segment boundary from that selected head.

Only the lightweight validated boundary provenance is retained with the Take.
Normal production use does not retain raw attention tensors or spike CSV/JSON
diagnostics.

Failure to obtain timing provenance does not invalidate the generated Take. It
only means that a mixed LAB cannot later be created from that candidate.

### Accepted-take region alignment

When a mixed Take is accepted with `save_lab=true`:

1. crop exact non-overlapping regions at the recorded segment boundaries;
2. use the accepted candidate's query/pronunciation snapshot;
3. align Japanese regions with Julius;
4. align English regions with PocketSphinx;
5. if direct PocketSphinx alignment fails for an English region, retry that
   exact region with 0.20 s of synthetic silence before and after it;
6. remove only the synthetic padding and reject the retry if any non-pause
   phone extends into that padding;
7. map all region LAB rows back to the original accepted-WAV time axis;
8. merge adjacent boundary pauses and require contiguous full-WAV coverage.

Do not run one language's aligner over the other language's phones. Do not
derive boundaries from text length or phone counts. Do not re-decode the
accepted WAV solely to recover missing attention.

If provenance, a region alignment, padding trim, sequence validation, or final
stitching fails, preserve WAV/TXT and publish no partial LAB.

## Dependency boundary

LAB support is optional.

With `save_lab=false`, normal TUI/API use must not require Julius or PocketSphinx.

Japanese LAB requires a Julius executable plus the pinned small HMM.

English LAB uses PocketSphinx 5.1.1 as an optional LAB dependency.

Mixed Japanese-English LAB uses both the Japanese and English production
aligners after its MRTE timing provenance has defined language regions.

MFA must not be installed or required for production LAB generation.

Missing optional alignment dependencies are LAB-sidecar errors, not synthesis errors.

## Failure behavior

The accepted WAV is the primary artifact.

If LAB generation fails:

1. keep the accepted WAV;
2. keep the TXT sidecar if requested and successfully saved;
3. leave no partial final `.lab`;
4. report clearly that WAV saving succeeded but LAB generation failed;
5. do not crash the TUI or discard the accepted take.

This applies to missing dependencies, unsupported languages/phones, phone-sequence mismatches, invalid timing, and aligner errors.

## Architecture

Forced alignment is shared application/core behavior, not TUI-specific behavior.

Shared owners must handle:

- language dispatch;
- Japanese and English phone extraction/mapping;
- temporary audio preparation;
- aligner invocation;
- timing validation;
- LAB rendering;
- sidecar result/error reporting.

The TUI owns only settings interaction and status display.

Do not modify Voiceger source.

## Normal-output hygiene

Normal accepted-take saving must not retain alignment WAVs, grammars, raw JSON, logs, or other diagnostic intermediates in the user's output directory.

Temporary/intermediate data belongs in temporary or application-cache locations and should be cleaned after the operation.

Generated test artifacts remain under `scratch/` and are never committed.
