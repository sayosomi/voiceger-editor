# Settings

Voiceger Editor stores reusable synthesis and output settings.

Open Settings from Batch List or Batch Item with:

```text
s
```

Use Up / Down to choose a row.

Use Left / Right for adjustable values.

Use Enter for direct text or numeric editing where available.

Settings also exposes direct row shortcuts: `s` Style, `v` Speed, `n` Takes,
`f` Output, `o` File format & naming, `k` Top K, `p` Top P, and `t`
Temperature. These shortcuts focus or activate the same visible rows rather than
using a separate settings path.

Select `Apply and save` to persist changes.

Leaving Settings without applying does not save the draft.

`Reset` restores the values that were present when the Settings screen was opened. It does not restore factory defaults.

## Defaults

| Setting | Default |
| --- | --- |
| Style | Neutral (`3`) |
| Speed | `1.00` |
| Takes | `4` |
| Output | `~/.voiceger-editor/output` |
| Format | WAV |
| WAV encoding | Source |
| FLAC encoding | PCM 16-bit |
| MP3 bitrate | 192 kbps |
| TXT | Off |
| LAB | Off |
| Top K | `20` |
| Top P | `1.00` |
| Temperature | `1.00` |

## Style

Style selects the Voiceger reference WAV used for synthesis.

The IDs match the corresponding VOICEVOX Zundamon style IDs:

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

Only styles whose reference WAVs exist in the local Voiceger installation are selectable.

Applying a Style change clears existing candidate Takes.

## Speed

Speed changes speech speed.

Default:

```text
1.00
```

Left / Right changes it in small steps.

The value must be greater than zero.

Applying a Speed change clears existing candidate Takes.

## Takes

Takes is the number of candidates generated in a normal batch.

Default:

```text
4
```

Supported range:

```text
1–100
```

Changing the configured Take count does not change the synthesis parameters of Takes that already exist.

## Output

The default output directory is:

```text
~/.voiceger-editor/output
```

Select the Output row and press Enter to edit it, or press `f` to jump directly into Output editing.

Output is one shared saved directory across the TUI. Accepted Takes, Batch
recipe Write, and Dictionary Export all use `Settings.output_dir`. Their
`[F] Output` rows display the same saved value and can edit it in place.
Read Batch and Import Dictionary only use Output as the initial directory for
their temporary input File path; changing an input path does not change Output.

## Audio Output

Settings exposes **File format & naming**, which opens the **AUDIO OUTPUT** screen.
The screen owns the accepted-Take format, format-specific encoding, filename template,
TXT, and LAB settings. These values remain part of the parent Settings draft until
you return and select `Apply and save`.

Supported accepted-audio formats are:

- **WAV**: Source, PCM 16-bit, PCM 24-bit, or Float 32-bit.
- **FLAC**: PCM 16-bit or PCM 24-bit.
- **MP3**: 96, 128, 160, 192, 256, or 320 kbps when an external `ffmpeg`
  executable is installed and discoverable, normally through `PATH`.

MP3 support is optional. Voiceger Editor does not install or bundle ffmpeg, and
startup continues normally when ffmpeg is unavailable. In that case MP3 is not
shown as a Format choice. A saved MP3 selection safely falls back to WAV when
ffmpeg is unavailable, while the saved MP3 bitrate is retained.

WAV **Source** is the default and preserves the existing accepted-Take behavior:
Voiceger Editor copies the generated candidate WAV without an unnecessary
decode/re-encode step. Explicit WAV encodings, FLAC, and MP3 are converted only
when the Take is accepted. Candidate Takes, pronunciation Preview audio, and LAB
processing remain WAV-based.

Voiceger Editor remembers the WAV and FLAC encoding choices and the MP3 bitrate
separately when you switch Format back and forth.

## TXT sidecar

When TXT is enabled, accepting a Take saves the exact source text beside the accepted audio file.

Example:

```text
202610020307_今日は雨なのだ。.wav
202610020307_今日は雨なのだ。.txt
```

## LAB sidecar

When LAB is enabled, Voiceger Editor tries to create a phoneme-timing `.lab` file for the accepted Take.

LAB output has extra dependencies and language-specific requirements.

See [LAB Output](lab-output.md).

## Sampling controls

Top K, Top P, and Temperature control how Voiceger samples semantic tokens during synthesis.

They do **not** directly mean pitch, speed, volume, or emotional intensity.

The Voiceger defaults are:

```text
Top K:       20
Top P:       1.00
Temperature: 1.00
```

If you do not have a reason to change them, keep the defaults.

Changing any of these settings can change pronunciation details, rhythm, intonation, and variation between Takes.

Applying a sampling change clears existing candidate Takes.

### Top K

Top K limits the maximum number of most likely next-token candidates considered at each sampling step.

Example:

```text
Top K = 20
```

means up to 20 of the most likely candidates may be considered.

Lower values narrow the choice.

Higher values allow more candidates and can increase variation.

Supported range:

```text
1–100
```

The TUI changes Top K in steps of 1.

### Top P

Top P uses cumulative probability, also called nucleus sampling.

A lower Top P keeps only a smaller high-probability set.

A higher Top P allows a wider set.

```text
Top P = 1.00
```

means no additional cumulative-probability cutoff is applied.

Supported range:

```text
0.00–1.00
```

The TUI changes Top P in steps of `0.05`.

### Temperature

Temperature changes how strongly sampling prefers the highest-probability candidates.

Lower values make high-probability choices more dominant.

Higher values allow more uncertainty and variation.

Temperature does not directly control emotional intensity or speech speed.

Supported setting range:

```text
0.00–1.00
```

The default is `1.00`, and the TUI changes it in steps of `0.05`.

### Reset sampling

Settings includes:

```text
Reset sampling to Voiceger defaults
```

This resets only:

- Top K;
- Top P;
- Temperature.

Select `Apply and save` afterward to persist the reset values.

## Settings file

On Windows:

```text
%APPDATA%\voiceger-editor\config.json
```

If `APPDATA` is unavailable, Voiceger Editor falls back to:

```text
%USERPROFILE%\AppData\Roaming\voiceger-editor\config.json
```

On macOS:

```text
~/Library/Application Support/voiceger-editor/config.json
```

On Linux and other XDG-style systems, `XDG_CONFIG_HOME` is used when set. Otherwise:

```text
~/.config/voiceger-editor/config.json
```

The Japanese dictionary, English dictionary, and Voiceger terms acceptance record are stored beside this file:

```text
user_dict.json
english_user_dict.json
voiceger-terms-acceptance.json
```

Example:

```json
{
  "output_dir": "/path/to/output",
  "filename_template": "{YYYYMMDDHHmm}_{text}",
  "output_format": "wav",
  "wav_encoding": "source",
  "flac_encoding": "pcm16",
  "mp3_bitrate": "192k",
  "save_lab": false,
  "save_text": false,
  "speed": 1.0,
  "style_id": 3,
  "take_count": 4,
  "temperature": 1.0,
  "top_k": 20,
  "top_p": 1.0
}
```

### Accepted-output filename template

The default accepted-output basename template is:

```text
{YYYYMMDDHHmm}_{text}
```

Configure it from **Settings -> File format & naming -> Filename template**. The **AUDIO OUTPUT** screen shows a live preview before the Settings draft is applied.

Supported case-sensitive date/time tokens are `YYYY`, `MM`, `DD`, `HH`, `mm`, and `ss`. `MM` is the month and `mm` is the minute. Named variables are `{text}` and `{style}`.

The file extension comes from Format rather than the template. A rendered basename such as `202610071945_hello` is saved with the selected extension, such as `.wav`, `.flac`, or `.mp3` when MP3 is available. TXT and LAB sidecars, when enabled, use the same final basename and collision suffix.

Unknown variables and unsupported date/time tokens are rejected before the Settings draft can be saved.

## Command-line overrides

Some settings can be overridden for one invocation.

Example:

```text
voiceger-editor --take-count 8 --style 1 --speed 0.95
```

Available overrides include:

- `--config`;
- `--output-dir`;
- `--take-count`;
- `--style`;
- `--speed`;
- `--save-text` / `--no-save-text`;
- `--save-lab` / `--no-save-lab`.

Command-line overrides apply only to that invocation. They do not replace saved settings unless you later change and save those values in the TUI.
