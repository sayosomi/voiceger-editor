# セットアップ

Voiceger Editor は、ローカルにインストールした Voiceger の Python 環境で動作します。

## 1. Voiceger のインストール

Voiceger をインストールします。

インストール手順は [Voiceger 公式リポジトリ](https://github.com/zunzun999/voiceger_v2)を参照してください。

Voiceger Editor 0.1 は Python 3.9 に対応しています。動作確認済みの Voiceger revision や対応OSについては [互換性](compatibility.md) を参照してください。

## 2. Python 環境の設定

Voiceger のインストール先を環境変数 `VOICEGER_ROOT` に指定し、Voiceger の `.venv` を有効にします。

以下は、ホームディレクトリの `voiceger_v2` にインストールした場合の例です。

### macOS / Linux

```bash
export VOICEGER_ROOT="$HOME/voiceger_v2"
source "$VOICEGER_ROOT/.venv/bin/activate"
```

### Windows PowerShell

```powershell
$env:VOICEGER_ROOT = "$HOME\voiceger_v2"
& "$env:VOICEGER_ROOT\.venv\Scripts\Activate.ps1"
```

Python のバージョンを確認します。

```bash
python --version
```

Python 3.9 が使用されていることを確認してください。

**補足：** `VOICEGER_ROOT` が未設定の場合、ホームディレクトリの `voiceger_v2` が使用されます。この場合、動作確認時に Warning が表示されます。

## 3. Voiceger Editor のインストール

Voiceger の Python 環境を有効にした状態で実行します。

```bash
python -m pip install "voiceger-editor[tui]"
```

インストールしたバージョンを確認します。

```bash
voiceger-editor --version
```

## 4. 動作確認

次のコマンドで、Voiceger のインストール状態を確認します。

```bash
voiceger-editor --check
```

主に以下の項目が確認されます。

- Python のバージョンと実行環境
- Voiceger のインストール先とディレクトリ構成
- モデルファイルと参照音声
- Voiceger の revision

正常な実行結果の一部を示します。

```text
[OK] Voiceger installation layout was detected.
[OK] Python 3.9.6 matches the 0.1 supported runtime.
[OK] Required Voiceger model files are available.
[OK] Voiceger reference assets are available (8 style(s) detected).

READY: YES
```

各項目の結果は `OK`、`WARN`、`ERROR` で表示されます。

`WARN` は動作を妨げるとは限りません。動作確認済みと異なる Voiceger revision などが該当します。

`ERROR` がある場合は `READY: NO` となります。エラーの確認方法は後述の「トラブルシューティング」を参照してください。

## 5. 起動

次のコマンドを実行します。

```bash
voiceger-editor
```

### 初回起動時の利用規約確認

初回起動時には、Voicegerずんだもん音源の利用規約に関する案内が表示されます。

```text
[O] 公式利用規約を開く
[A] 同意して続ける
[E] English
[Q] 終了
```

`O` で公式利用規約を開き、内容を確認します。

同意する場合は `A` を押します。

利用規約への同意状態は保存されます。案内が更新された場合は、再度確認が必要になることがあります。

公式利用規約：[Voicegerずんだもん音源利用規約](https://zunko.jp/con_ongen_kiyaku.html)

### 起動完了

`BATCH LIST` 画面が表示されれば、セットアップは完了です。

基本操作は [はじめての音声生成](tui.md) を参照してください。

## 追加機能のインストール

以下の機能を使用する場合は、追加の準備が必要です。

- [HTTP API](http-api.md) — HTTP API のインストールと起動
- [LAB 出力](lab.md) — LAB 出力に必要な依存パッケージと外部ツール
- [MP3 出力](mp3.md) — MP3 出力に必要な FFmpeg の導入

## トラブルシューティング

### Voiceger が見つからない

`VOICEGER_ROOT` が実際のインストール先を指しているか確認します。

macOS / Linux:

```bash
echo "$VOICEGER_ROOT"
```

Windows PowerShell:

```powershell
$env:VOICEGER_ROOT
```

`VOICEGER_ROOT` を設定せず、一時的に別のパスを指定して確認することもできます。

```bash
voiceger-editor --voiceger-root /path/to/voiceger_v2 --check
```

### Python 環境が正しくない

Voiceger の `.venv` が存在し、有効になっていることを確認します。

macOS / Linux:

```bash
which python
which voiceger-editor
```

Windows PowerShell:

```powershell
Get-Command python
Get-Command voiceger-editor
```

Voiceger の `.venv` 内の実行ファイルを参照していることを確認してください。

`.venv` が存在しない場合は、Voiceger のインストール手順を確認してください。

### モデルや参照音声が見つからない

Voiceger 側のセットアップを確認してください。

Voiceger Editor は、モデルファイルや参照音声のダウンロードを行いません。

### Windows で Take を再生できない

Windows の TUI 再生には `ffplay.exe` が必要です。

FFmpeg の導入と Windows での動作確認範囲については [互換性](compatibility.md) を参照してください。

## Voiceger Editor の更新

Voiceger の Python 環境を有効にして、次のコマンドを実行します。

```bash
python -m pip install --upgrade "voiceger-editor[tui]"
```

HTTP API や LAB などを使用している場合は、必要な追加機能も指定してください。

更新後は、バージョンと動作環境を確認します。

```bash
voiceger-editor --version
voiceger-editor --check
```

Voiceger 本体を更新した場合も、`--check` で互換性を確認してください。
