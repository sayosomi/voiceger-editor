# Setup

Voiceger Editor uses a separate local installation of Voiceger. Voiceger itself, its models, and its reference audio are not included.

## 1. Install Voiceger

Install Voiceger from the official project:

https://github.com/zunzun999/voiceger_v2

Voiceger Editor v1 is tested with this Voiceger revision:

~~~text
f77c1172baf1f490bb962f2d2acd01c852ef3464
~~~

Other revisions may work, but they are not part of the v1 compatibility guarantee.

## 2. Set VOICEGER_ROOT

Point VOICEGER_ROOT to the Voiceger repository:

~~~bash
export VOICEGER_ROOT="$HOME/voiceger_v2"
~~~

If it is not set, Voiceger Editor tries ~/voiceger_v2 and reports a warning.

## 3. Activate Voiceger's Python environment

Voiceger Editor v1 supports Python 3.9 and is intended to run inside Voiceger's .venv.

On macOS or Linux:

~~~bash
source "$VOICEGER_ROOT/.venv/bin/activate"
python --version
~~~

## 4. Install Voiceger Editor from PyPI

For the TUI:

~~~bash
python -m pip install 'voiceger-editor[tui]'
~~~

For the exact v1 release:

~~~bash
python -m pip install 'voiceger-editor[tui]==1.0.0'
~~~

Check the installed version:

~~~bash
voiceger-editor --version
~~~

Expected output:

~~~text
voiceger-editor 1.0.0
~~~

Optional extras:

~~~bash
python -m pip install 'voiceger-editor[api]'
python -m pip install 'voiceger-editor[tui,lab]'
python -m pip install 'voiceger-editor[tui,api,lab]'
~~~

Japanese LAB output also requires Julius. See [LAB Output](lab-output.md).

## 5. Check the Voiceger environment

Run:

~~~bash
voiceger-editor --check
~~~

The report checks the editor version, Python version, VOICEGER_ROOT, Voiceger layout, Voiceger .venv, required model files, reference audio, available styles, and the Voiceger revision.

A ready setup ends with:

~~~text
READY: YES
~~~

Statuses are OK, WARN, and ERROR. A revision mismatch is normally a warning. An ERROR means the setup is not ready.

For a one-time alternative Voiceger path:

~~~bash
voiceger-editor --voiceger-root /path/to/voiceger_v2 --check
~~~

## 6. Read and accept the Voiceger:Zundamon terms

Official terms:

https://zunko.jp/con_ongen_kiyaku.html

Open them from the CLI:

~~~bash
voiceger-editor --open-voiceger-terms
~~~

After reading them, explicitly accept the current notice:

~~~bash
voiceger-editor --accept-voiceger-terms
~~~

Check the saved status:

~~~bash
voiceger-editor --voiceger-terms-status
~~~

The acceptance state is shared by the TUI and API. The official terms are authoritative; the local notice is only a summary.

On first interactive TUI use, the same notice is shown before synthesis. Pressing Enter alone does not accept it.

## 7. Start the TUI

~~~bash
voiceger-editor
~~~

Or start with a Caption:

~~~bash
voiceger-editor "このずんだ餅はvery sweetなのだ。"
~~~

See [TUI](tui.md).

## 8. Start the HTTP API

Install the API extra, then run:

~~~bash
python -m uvicorn   voiceger_editor.api:app   --host 127.0.0.1   --port 8001
~~~

Check it with:

~~~bash
curl http://127.0.0.1:8001/version
~~~

Interactive FastAPI documentation is available at http://127.0.0.1:8001/docs.

See [HTTP API](api.md).

## Updating

Upgrade Voiceger Editor from PyPI:

~~~bash
python -m pip install --upgrade 'voiceger-editor[tui]'
voiceger-editor --version
voiceger-editor --check
~~~

After updating Voiceger itself, run voiceger-editor --check again.
