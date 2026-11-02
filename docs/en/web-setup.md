# Web UI Setup

Voiceger Editor provides a browser-based Web UI. Run the Web server on a computer with Voiceger installed, then open it in a browser.

You can use the Web UI on the same computer or access it from another PC, phone, or tablet through Tailscale Serve. Speech synthesis and file storage take place on the server.

## 1. Requirements

- A computer with Voiceger installed and Python 3.9
- Voiceger Editor
- A browser on the device used to operate the Web UI
- Tailscale on both devices when accessing the server remotely

**Verification scope:** The Web server has been tested on macOS, with remote browser operation tested on Android. Complete Web workflows have not been physically verified on Linux or Windows servers or on other browser platforms.

Other configurations may work, but their operation is not guaranteed. See [Compatibility](compatibility.md).

## 2. Install Voiceger Editor

First, follow the [common setup guide](setup.md) to install Voiceger and prepare its Python environment.

### macOS and Linux

Activate Voiceger's Python environment:

```bash
export VOICEGER_ROOT="$HOME/voiceger_v2"
source "$VOICEGER_ROOT/.venv/bin/activate"
```

### Windows PowerShell

```powershell
$env:VOICEGER_ROOT = "$HOME\voiceger_v2"
& "$env:VOICEGER_ROOT\.venv\Scripts\Activate.ps1"
```

Install the Web UI:

```bash
python -m pip install --upgrade "voiceger-editor[web]"
```

To install both the TUI and Web UI:

```bash
python -m pip install --upgrade "voiceger-editor[tui,web]"
```

Check the installation:

```bash
voiceger-editor --version
voiceger-editor --check
```

### Accept the voice usage terms

Before generating audio, read the official [Voiceger:Zundamon terms](https://zunko.jp/con_ongen_kiyaku.html):

```bash
voiceger-editor --open-voiceger-terms
```

If you agree, record your acceptance:

```bash
voiceger-editor --accept-voiceger-terms
```

## 3. Start the Web Server

The Web server requires an access token of at least 32 characters.

### macOS and Linux

In a terminal with Voiceger's Python environment active:

```bash
(
  export VOICEGER_WEB_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
  if [ "${#VOICEGER_WEB_TOKEN}" -lt 32 ]; then
    echo "ERROR: Could not generate an access token"
    exit 1
  fi
  printf 'Web access token: %s\n' "$VOICEGER_WEB_TOKEN"
  python -m uvicorn voiceger_editor.web:app --host 127.0.0.1 --port 8002
)
```

### Windows PowerShell

With Voiceger's Python environment active:

```powershell
$env:VOICEGER_WEB_TOKEN = python -c 'import secrets; print(secrets.token_urlsafe(32))'
Write-Host "Web access token: $env:VOICEGER_WEB_TOKEN"
python -m uvicorn voiceger_editor.web:app --host 127.0.0.1 --port 8002
```

Keep the displayed access token private.

On the computer running the server, open:

`http://127.0.0.1:8002`

Enter the token in **Webアクセストークン** (Web Access Token) and select **接続する** (Connect).

The server listens only on `127.0.0.1`. You do not need to bind it to `0.0.0.0` for remote access.

## 4. Connect from Another Device

Use Tailscale Serve to access the Web UI from another computer, phone, or tablet.

Connect both the server and client device to Tailscale.

On the server, open another terminal and check the existing Serve configuration:

```bash
tailscale serve status
```

Review any existing configuration before changing it.

Start Serve:

```bash
tailscale serve 8002
```

Open the displayed `https://...ts.net` URL in a browser on the client device.

Enter the access token displayed on the server and select **接続する** (Connect).

Tailscale Serve restricts access to permitted devices and users within your tailnet. Do not use Tailscale Funnel to expose Voiceger Editor to the public internet.

See the [official Tailscale Serve guide](https://tailscale.com/docs/features/tailscale-serve).

## 5. Sessions and Reconnection

The browser does not permanently store the access token. You must enter it again after reloading the page.

You can reconnect to the current session while the server is running and that session remains valid.

The current Batch and temporary Take candidates cannot be recovered after:

- restarting the Web server;
- session expiration;
- selecting **作業を終了** (End Session).

**Previously saved audio files are preserved.**

You can save and load Batch recipe files from the Batch List's **ファイル** (Files) menu, but these files do not contain generated Takes or their acceptance status.

## 6. Output Location

Generated audio is saved in the Output directory on the computer running the Web server.

You can change the location under **設定** (Settings) → **出力** (Output).

The Web UI does not save directly to a folder on the connecting phone or computer. Batch and dictionary file operations are also handled on the server.

## 7. Shut Down

In the Web UI, open **設定** (Settings) and select **作業を終了** (End Session). The current Batch and temporary Take candidates are discarded, but saved audio files remain.

If Tailscale Serve is running in the foreground, press `Ctrl+C` in its terminal to stop sharing.

Then press `Ctrl+C` in the terminal running the Web server.

## Troubleshooting

- **Cannot open the page on the server:** Check that the Web server is running and port 8002 is available.
- **Authentication fails:** Re-enter the access token displayed on the server.
- **Cannot connect from another device:** Check Tailscale connectivity, tailnet access controls, HTTPS configuration, and `tailscale serve status`.
- **Session data is missing:** The session may have expired or been discarded by a server restart.

The Web UI and VOICEVOX-compatible HTTP API are separate applications. Start the Web UI with `voiceger_editor.web:app`.
