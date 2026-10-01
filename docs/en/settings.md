# Settings

Voiceger Editor stores reusable TUI and synthesis settings.

Open Settings from the main screen with:

```text
s
```

Use Up and Down to move between settings.

Use Left and Right to adjust supported values.

Choose Apply and save to persist changes.

## Defaults

| Setting | Default |
| --- | --- |
| Style | Neutral (`3`) |
| Speed | `1.00` |
| Takes | `4` |
| Output | `~/.voiceger-editor/output` |
| TXT | Off |
| LAB | Off |
| Top K | `20` |
| Top P | `1.00` |
| Temperature | `1.00` |

## Style

Voiceger Editor uses the corresponding VOICEVOX Zundamon style IDs:

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

Only styles whose reference WAV exists in the local Voiceger installation are selectable.

Changing Style clears current Takes.

## Speed

Default:

```text
1.00
```

Left and Right change Speed in small steps.

Speed must be greater than zero.

Changing Speed clears current Takes.

## Takes

Default:

```text
4
```

Supported range:

```text
1–100
```

Changing the Take count changes how many candidates are generated next. It does not rewrite the synthesis parameters of Takes that were already generated.

## Output directory

Default:

```text
~/.voiceger-editor/output
```

Press Enter on Output to edit the path.

Accepted Takes are saved there.

## TXT

When TXT is enabled, accepting a Take also saves the exact source text in a `.txt` file with the same basename as the WAV.

## LAB

When LAB is enabled, Voiceger Editor tries to create a `.lab` phoneme-timing sidecar for the accepted Take.

Additional dependencies are required.

See [LAB Output](lab-output.md).

## Top K, Top P, and Temperature

Voiceger uses sampling while generating speech. The same input can therefore produce different results across Takes.

Top K, Top P, and Temperature control the token-selection process. They do not directly mean pitch, speed, volume, or emotional intensity.

The supported Voiceger defaults are:

```text
Top K:       20
Top P:       1.00
Temperature: 1.00
```

If you do not have a reason to change them, keep the defaults.

Changing any of these settings clears existing Takes.

### Top K

Top K limits the maximum number of most likely next-token candidates considered.

Example:

```text
Top K = 20
```

means that up to the 20 most likely candidates can remain before later sampling steps.

Lower values narrow the candidate set.

Higher values allow more possible candidates.

Supported range:

```text
1–100
```

### Top P

Top P uses cumulative probability filtering.

A lower value keeps a smaller group of likely candidates.

A higher value allows a wider group.

```text
Top P = 1.00
```

means no candidates are removed by the cumulative-probability cutoff.

Supported range:

```text
0.00–1.00
```

The TUI changes it in `0.05` steps.

### Temperature

Temperature changes how strongly the sampling process prefers higher-probability candidates.

Lower values make the distribution sharper.

Higher values allow more uncertainty and variation.

Temperature does **not** directly control emotional intensity or speech speed.

Supported range:

```text
0.00–1.00
```

The default is `1.00`.

### Reset sampling

Settings provides:

```text
Reset sampling to Voiceger defaults
```

This restores only Top K, Top P, and Temperature to:

```text
20 / 1.00 / 1.00
```

Choose Apply and save to persist the reset.

## Reset

The Settings Reset action restores the values that were present when the Settings screen was opened.

It is not a factory-reset command.

## Settings file

On macOS:

```text
~/Library/Application Support/voiceger-editor/config.json
```

If `XDG_CONFIG_HOME` is set, Voiceger Editor uses:

```text
$XDG_CONFIG_HOME/voiceger-editor/config.json
```

Otherwise:

```text
~/.config/voiceger-editor/config.json
```

## CLI overrides

The CLI can override selected settings for one invocation:

```bash
voiceger-editor \
  --take-count 8 \
  --style 1 \
  --speed 0.95
```

Available overrides include:

- `--config`
- `--output-dir`
- `--take-count`
- `--style`
- `--speed`
- `--save-text`
- `--no-save-text`
- `--save-lab`
- `--no-save-lab`

CLI overrides do not replace the saved settings file unless you later change and save settings from the TUI.
