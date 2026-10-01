# Settings

Voiceger Editor stores reusable settings in a JSON config file.

Open Settings from the TUI with the Settings row or s.

## Defaults

| Setting | Default |
| --- | --- |
| Style | Neutral (ID 3) |
| Speed | 1.00 |
| Takes | 4 |
| Output | ~/.voiceger-editor/output |
| TXT | Off |
| LAB | Off |
| Top K | 20 |
| Top P | 1.00 |
| Temperature | 1.00 |

Use Up / Down to select a row and Left / Right to adjust supported values. Some fields use Enter for direct editing.

Apply and save writes the settings. Back leaves without applying. Reset restores the values that were present when the Settings editor was opened.

## Styles

Voiceger Editor uses Voiceger reference WAVs as styles and uses the corresponding VOICEVOX Zundamon IDs:

| Style | ID |
| --- | ---: |
| Sweet | 1 |
| Neutral | 3 |
| Sexy | 5 |
| Snippy | 7 |
| Whispering | 22 |
| Murmuring | 38 |
| Exhausted | 75 |
| Sobbing | 76 |

Only styles whose reference WAV exists in the local Voiceger installation can be selected.

Changing Style clears existing Takes.

## Speed

Speed defaults to 1.00 and must be greater than zero.

Changing Speed clears existing Takes.

## Takes

Take count defaults to 4 and supports 1 through 100.

Changing the requested count does not rewrite synthesis settings stored with Takes that have already been generated.

## Output, TXT, and LAB

The default output directory is:

~~~text
~/.voiceger-editor/output
~~~

TXT saves the exact source Caption beside an accepted WAV.

LAB saves optional phoneme timing beside an accepted WAV. See [LAB Output](lab-output.md).

## Sampling controls

Voiceger uses sampling while generating speech. This is one reason repeated Takes can differ.

Top K, Top P, and Temperature change how the model selects among possible next tokens. They do **not** directly mean pitch, speed, volume, or emotional intensity.

The Voiceger defaults are:

~~~text
Top K:       20
Top P:       1.00
Temperature: 1.00
~~~

Keep these defaults unless you have a reason to experiment.

### Top K

Top K limits the maximum number of highest-probability candidates considered at each step.

- Lower values narrow the choice.
- Higher values allow more possible candidates.

Voiceger Editor allows 1 through 100 in steps of 1.

### Top P

Top P uses cumulative probability filtering.

- Lower values keep a smaller high-probability set.
- Higher values allow a wider set.
- 1.00 means no reduction by this cumulative cutoff.

Voiceger Editor allows 0.00 through 1.00 in steps of 0.05.

### Temperature

Temperature changes how strongly high-probability choices are preferred.

- Lower values make the distribution sharper.
- Higher values allow more variation.

It does not directly control emotion or speaking speed.

Voiceger Editor allows 0.00 through 1.00 in steps of 0.05.

Changing Top K, Top P, or Temperature clears existing Takes.

The Settings editor also has an action to reset only these sampling controls to the Voiceger defaults.

## Config location

On macOS:

~~~text
~/Library/Application Support/voiceger-editor/config.json
~~~

If XDG_CONFIG_HOME is set on other platforms:

~~~text
$XDG_CONFIG_HOME/voiceger-editor/config.json
~~~

Otherwise:

~~~text
~/.config/voiceger-editor/config.json
~~~

The terms-acceptance file and user dictionaries are stored beside the default config file.

## CLI overrides

Available one-run overrides include:

~~~text
--config
--output-dir
--take-count
--style
--speed
--save-text / --no-save-text
--save-lab / --no-save-lab
~~~

Example:

~~~bash
voiceger-editor   --take-count 8   --style 1   --speed 0.95
~~~

CLI overrides apply to that invocation. They do not replace the saved config unless you later save settings from the TUI.
