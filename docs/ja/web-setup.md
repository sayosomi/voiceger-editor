# Web UIのセットアップ

Voiceger EditorのWeb UIは、VoicegerをインストールしたコンピューターでWebサーバーを起動し、ブラウザから操作する機能です。

同じコンピューターから利用できるほか、Tailscale Serveを使うことで、別のPCやスマートフォンからもアクセスできます。音声生成とファイル保存はサーバー側で行われます。

## 1. 必要な環境

- VoicegerとPython 3.9をインストールしたコンピューター
- Voiceger Editor
- Web UIを操作する端末のブラウザ
- 別の端末から接続する場合は、両方の端末で利用できるTailscale

**動作確認範囲：** Webサーバーの実機動作はmacOS、ブラウザからのリモート操作はAndroidで確認しています。Linux・WindowsでのWebサーバー実行、およびその他のブラウザ環境では、一連の動作を実機検証していません。

ほかの環境で動作する可能性はありますが、未検証の環境での動作を保証するものではありません。詳しくは[互換性](compatibility.md)を参照してください。

## 2. Voiceger Editorをインストールする

最初に[共通セットアップ](setup.md)に従い、VoicegerとPython環境を用意してください。

### macOS・Linux

VoicegerのPython仮想環境を有効にします。

```bash
export VOICEGER_ROOT="$HOME/voiceger_v2"
source "$VOICEGER_ROOT/.venv/bin/activate"
```

### Windows PowerShell

```powershell
$env:VOICEGER_ROOT = "$HOME\voiceger_v2"
& "$env:VOICEGER_ROOT\.venv\Scripts\Activate.ps1"
```

続いて、Web UIをインストールします。

```bash
python -m pip install --upgrade "voiceger-editor[web]"
```

TUIも使用する場合は、代わりに次を指定できます。

```bash
python -m pip install --upgrade "voiceger-editor[tui,web]"
```

インストール後、動作環境を確認します。

```bash
voiceger-editor --version
voiceger-editor --check
```

### 音源利用規約への同意

音声を生成する前に、[Voicegerずんだもん音源利用規約](https://zunko.jp/con_ongen_kiyaku.html)を確認してください。

```bash
voiceger-editor --open-voiceger-terms
```

規約を確認し、同意する場合は次を実行します。

```bash
voiceger-editor --accept-voiceger-terms
```

## 3. Webサーバーを起動する

Webサーバーへの接続には、32文字以上のアクセストークンが必要です。

### macOS・Linux

VoicegerのPython環境を有効にしたターミナルで実行します。

```bash
(
  export VOICEGER_WEB_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
  if [ "${#VOICEGER_WEB_TOKEN}" -lt 32 ]; then
    echo "ERROR: アクセストークンを生成できませんでした"
    exit 1
  fi
  printf 'Web access token: %s\n' "$VOICEGER_WEB_TOKEN"
  python -m uvicorn voiceger_editor.web:app --host 127.0.0.1 --port 8002
)
```

### Windows PowerShell

VoicegerのPython環境を有効にしたPowerShellで実行します。

```powershell
$env:VOICEGER_WEB_TOKEN = python -c 'import secrets; print(secrets.token_urlsafe(32))'
Write-Host "Web access token: $env:VOICEGER_WEB_TOKEN"
python -m uvicorn voiceger_editor.web:app --host 127.0.0.1 --port 8002
```

表示されたアクセストークンは第三者に共有しないでください。

Webサーバーを起動したコンピューターのブラウザで、次のアドレスを開きます。

`http://127.0.0.1:8002`

「Webアクセストークン」にトークンを入力し、「接続する」を押します。

Webサーバーはローカルアドレス`127.0.0.1`で待ち受けます。ほかの端末から接続するために、待ち受けアドレスを`0.0.0.0`へ変更する必要はありません。

## 4. 別の端末から接続する

別のPCやスマートフォンから操作する場合は、Tailscale Serveを使用します。

Webサーバーを動かしているコンピューターと、接続する端末の両方でTailscaleに接続してください。

サーバー側で別のターミナルを開き、既存のServe設定を確認します。

```bash
tailscale serve status
```

既存の設定がある場合は、変更して問題ないか確認してください。

続いて次を実行します。

```bash
tailscale serve 8002
```

表示された`https://...ts.net`のURLを、接続先のPCやスマートフォンのブラウザで開きます。

サーバー側で表示されたアクセストークンを入力し、「接続する」を押します。

Tailscale Serveは、アクセスが許可されたtailnet内の端末から利用する仕組みです。インターネットへ一般公開するTailscale Funnelは使用しません。

詳細は[Tailscale Serve公式ガイド](https://tailscale.com/docs/features/tailscale-serve)を参照してください。

## 5. セッションと再接続

アクセストークンはブラウザに永続保存されません。ページを再読み込みすると再入力が必要です。

Webサーバーが動作しており、セッションが残っている場合は、再接続して作業を継続できます。

次の場合は、作業中のBatchや一時的なTake候補を復元できません。

- Webサーバーを再起動した場合
- セッションの有効期限が切れた場合
- 「作業を終了」を実行した場合

**保存済みの音声ファイルは残ります。**

Batch Listの「ファイル」からBatchファイルを保存・読み込みできますが、生成済みTakeや採用状態はBatchファイルに含まれません。

## 6. 保存先

生成した音声は、Webサーバーを実行しているコンピューターのOutputフォルダに保存されます。

保存先はWeb UIの「設定」→「出力」で変更できます。

接続元のスマートフォンやPCのフォルダに直接保存する機能ではありません。Batchファイルや辞書ファイルの読み書きもサーバー側で行います。

## 7. 終了する

Web UIの「設定」から「作業を終了」を選びます。作業中のBatchと一時的なTake候補は破棄されますが、保存済みの音声ファイルは残ります。

Tailscale Serveをフォアグラウンドで起動している場合は、そのターミナルで`Ctrl+C`を押して共有を停止します。

Webサーバーのターミナルでも`Ctrl+C`を押して終了します。

## 接続できない場合

- **サーバー上で画面を開けない：** Webサーバーが起動しているか、ポート8002が使用可能か確認してください。
- **認証に失敗する：** サーバー側に表示されたアクセストークンを入力し直してください。
- **別の端末から接続できない：** Tailscale接続、tailnetのアクセス制御、HTTPS設定、`tailscale serve status`を確認してください。
- **作業データが見つからない：** セッション期限切れやサーバー再起動によって破棄された可能性があります。

Web UIとVOICEVOX互換HTTP APIは別のアプリケーションです。Web UIには`voiceger_editor.web:app`を使用してください。
