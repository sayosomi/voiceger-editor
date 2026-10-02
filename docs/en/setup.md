# Setup

Voiceger Editor uses a separate local installation of Voiceger.

Voiceger itself, its models, and its reference audio are not included.

The normal setup is:

```text
Install Voiceger
→ set VOICEGER_ROOT
→ activate Voiceger's Python environment
→ install Voiceger Editor from PyPI
→ run the environment check
→ accept the Voiceger:Zundamon terms
→ start the TUI
```

## 1. Install Voiceger

Install Voiceger from the official project:

https://github.com/zunzun999/voiceger_v2

Voiceger Editor v1 is tested with this Voiceger revision:

```text
f77c1172baf1f490bb962f2d2acd01c852ef3464
```

Other revisions may work, but they are not part of the v1 compatibility guarantee.

## 2. Set `VOICEGER_ROOT`

Set `VOICEGER_ROOT` to the Voiceger repository directory.

On macOS or Linux:

```bash
export VOICEGER_ROOT="$HOME/voiceger_v2"
```

On Windows PowerShell:

```powershell
$env:VOICEGER_ROOT = "$HOME\voiceger_v2"
```

If it is not set, Voiceger Editor tries the `voiceger_v2` directory in your home directory and reports a warning.

## 3. Activate Voiceger's Python environment

Voiceger Editor v1 uses Python 3.9 and is intended to run inside Voiceger's `.venv`.

On macOS or Linux:

```bash
source "$VOICEGER_ROOT/.venv/bin/activate"
```

On Windows PowerShell:

```powershell
& "$env:VOICEGER_ROOT\.venv\Scripts\Activate.ps1"
```

Check the Python version:

```bash
python --version
```

It should report Python 3.9.

## 4. Install Voiceger Editor

Install the TUI from PyPI:

```text
python -m pip install "voiceger-editor[tui]"
```

For the exact v1.0.0 release:

```text
python -m pip install "voiceger-editor[tui]==1.0.0"
```

Check the installed version:

```bash
voiceger-editor --version
```

Expected output:

```text
voiceger-editor 1.0.0
```

### API support

Install the API extra with:

```bash
python -m pip install 'voiceger-editor[api]'
```

Or install both TUI and API support:

```bash
python -m pip install 'voiceger-editor[tui,api]'
```

### LAB support

Install LAB support with:

```bash
python -m pip install 'voiceger-editor[tui,lab]'
```

To install all optional Python features:

```bash
python -m pip install 'voiceger-editor[tui,api,lab]'
```

Japanese LAB output also requires Julius.

Windows LAB output is not part of the verified v1 Windows support boundary. See [LAB Output](lab-output.md) before installing the `lab` extra on Windows.

## 5. Check the Voiceger environment

Run:

```bash
voiceger-editor --check
```

The report checks:

- Voiceger Editor version;
- Python version;
- `VOICEGER_ROOT`;
- Voiceger repository layout;
- Voiceger Python environment;
- model files;
- reference audio and available styles;
- Voiceger revision.

A ready setup ends with:

```text
READY: YES
```

The report uses `OK`, `WARN`, and `ERROR`.

A warning does not always block use. For example, an untested Voiceger revision produces a warning.

An error means the setup is not ready.

## Common setup problems

### `VOICEGER_ROOT` is wrong

On macOS or Linux, check and set it with:

```bash
echo "$VOICEGER_ROOT"
export VOICEGER_ROOT=/path/to/voiceger_v2
```

On Windows PowerShell:

```powershell
$env:VOICEGER_ROOT
$env:VOICEGER_ROOT = "C:\path\to\voiceger_v2"
```

You can test another path without changing the environment variable:

```text
voiceger-editor --voiceger-root /path/to/voiceger_v2 --check
```

On Windows, replace the example path with a Windows path such as `C:\path\to\voiceger_v2`.

### Voiceger's `.venv` is missing

Complete the Voiceger installation first.

Voiceger Editor expects the Voiceger Python environment under:

```text
VOICEGER_ROOT/.venv
```

### The wrong Python environment is active

On macOS or Linux:

```bash
which python
which voiceger-editor
```

On Windows PowerShell:

```powershell
Get-Command python
Get-Command voiceger-editor
```

Both should point to Voiceger's `.venv`.

### Models or reference audio are missing

Complete the Voiceger model and reference-audio setup.

Voiceger Editor does not download or replace Voiceger models.

### Windows TUI playback does not work

Voiceger Editor uses `ffplay.exe` for TUI playback on Windows.

Install an FFmpeg build that includes `ffplay.exe`, then add its `bin` directory to `PATH`.

Synthesis and saving are separate from playback. A missing player does not mean that Voiceger synthesis itself failed.

## 6. Read and accept the Voiceger:Zundamon terms

Before Voiceger can be used for synthesis, you must explicitly accept the current terms notice.

Official terms:

https://zunko.jp/con_ongen_kiyaku.html

Open the terms with:

```bash
voiceger-editor --open-voiceger-terms
```

After reading them, accept the current notice:

```bash
voiceger-editor --accept-voiceger-terms
```

Check the saved status:

```bash
voiceger-editor --voiceger-terms-status
```

A successful status includes:

```text
Voiceger:Zundamon terms acceptance: current and accepted
```

The acceptance state is shared by the TUI and API.

The official terms are authoritative. The local notice does not replace them.

### Interactive first use

If no acceptance record exists, starting the TUI shows the notice first.

You can open the official terms, accept and continue, switch between Japanese and English, or quit.

Pressing Enter alone does not accept the terms.

## 7. Start the TUI

Run:

```bash
voiceger-editor
```

Or start with a Caption:

```bash
voiceger-editor "このずんだ餅はvery sweetなのだ。"
```

The normal workflow is:

```text
Caption
→ pronunciation
→ Generate
→ listen to Takes
→ accept one Take
```

See [TUI](tui.md).

## 8. Start the HTTP API

If the API extra is installed:

```text
python -m uvicorn voiceger_editor.api:app --host 127.0.0.1 --port 8001
```

On macOS or Linux, check it with:

```bash
curl http://127.0.0.1:8001/version
```

On Windows PowerShell:

```powershell
curl.exe http://127.0.0.1:8001/version
```

Interactive FastAPI documentation is available at:

```text
http://127.0.0.1:8001/docs
```

See [HTTP API](api.md).

## Updating Voiceger Editor

Upgrade the published package with:

```bash
python -m pip install --upgrade 'voiceger-editor[tui]'
```

Include any extras you use.

Then check:

```bash
voiceger-editor --version
voiceger-editor --check
```

## Updating Voiceger

After updating Voiceger, run:

```bash
voiceger-editor --check
```

If the revision differs from the tested revision, Voiceger Editor reports a warning.

A revision warning means compatibility is unverified. It does not automatically mean the revision is incompatible.
