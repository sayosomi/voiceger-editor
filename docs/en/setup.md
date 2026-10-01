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

## 2. Set VOICEGER_ROOT

Set `VOICEGER_ROOT` to the Voiceger repository directory.

```bash
export VOICEGER_ROOT="$HOME/voiceger_v2"
```

If it is not set, Voiceger Editor tries `~/voiceger_v2` and reports a warning.

## 3. Activate Voiceger's Python environment

Voiceger Editor v1 uses Python 3.9 and is intended to run inside Voiceger's `.venv`.

On macOS or Linux:

```bash
source "$VOICEGER_ROOT/.venv/bin/activate"
```

Check the version:

```bash
python --version
```

## 4. Install Voiceger Editor

Install the TUI:

```bash
python -m pip install 'voiceger-editor[tui]'
```

For the exact v1.0.0 release:

```bash
python -m pip install 'voiceger-editor[tui]==1.0.0'
```

Check the installed version:

```bash
voiceger-editor --version
```

Expected output:

```text
voiceger-editor 1.0.0
```

For API support:

```bash
python -m pip install 'voiceger-editor[api]'
```

For TUI and API support:

```bash
python -m pip install 'voiceger-editor[tui,api]'
```

For optional LAB output:

```bash
python -m pip install 'voiceger-editor[tui,lab]'
```

To install all optional Python features:

```bash
python -m pip install 'voiceger-editor[tui,api,lab]'
```

Japanese LAB output also requires Julius. See [LAB Output](lab-output.md).

## 5. Check the Voiceger environment

Run:

```bash
voiceger-editor --check
```

The report checks:

- Voiceger Editor version;
- Python version;
- resolved `VOICEGER_ROOT`;
- Voiceger repository layout;
- Voiceger Python environment;
- required models;
- reference audio and available styles;
- Voiceger revision.

A ready setup ends with:

```text
READY: YES
```

The report uses `[OK]`, `[WARN]`, and `[ERROR]`.

A warning does not always block use. For example, an untested Voiceger revision is a warning.

An error means the setup is not ready.

## Common setup problems

### VOICEGER_ROOT is wrong

```bash
echo "$VOICEGER_ROOT"
export VOICEGER_ROOT=/path/to/voiceger_v2
voiceger-editor --check
```

You can also check another path for one invocation:

```bash
voiceger-editor --voiceger-root /path/to/voiceger_v2 --check
```

### Voiceger's .venv is missing

Complete the Voiceger installation first. Voiceger Editor expects the environment under `VOICEGER_ROOT/.venv`.

### The wrong Python environment is active

```bash
which python
which voiceger-editor
```

Both should point to Voiceger's `.venv`.

### Models or reference audio are missing

Complete the Voiceger model and reference-audio setup. Voiceger Editor does not download or replace Voiceger models.

## 6. Read and accept the Voiceger:Zundamon terms

Official terms:

https://zunko.jp/con_ongen_kiyaku.html

Open them from the CLI:

```bash
voiceger-editor --open-voiceger-terms
```

After reading them, explicitly accept the current notice:

```bash
voiceger-editor --accept-voiceger-terms
```

Check the saved status:

```bash
voiceger-editor --voiceger-terms-status
```

The acceptance state is shared by the TUI and API.

The official terms are authoritative. The local notice does not replace them.

If no acceptance record exists, starting the TUI shows the notice first. Pressing Enter alone does not accept the terms.

## 7. Start the TUI

```bash
voiceger-editor
```

Or start with a Caption:

```bash
voiceger-editor "このずんだ餅はvery sweetなのだ。"
```

See [TUI](tui.md).

## 8. Start the HTTP API

If the API extra is installed:

```bash
python -m uvicorn \
  voiceger_editor.api:app \
  --host 127.0.0.1 \
  --port 8001
```

Check it with:

```bash
curl http://127.0.0.1:8001/version
```

Interactive FastAPI documentation is available at `http://127.0.0.1:8001/docs`.

See [HTTP API](api.md).

## Updating

Upgrade Voiceger Editor with:

```bash
python -m pip install --upgrade 'voiceger-editor[tui]'
```

Include any extras you use.

After updating Voiceger Editor or Voiceger, run:

```bash
voiceger-editor --version
voiceger-editor --check
```
