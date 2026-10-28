# Voiceger Editor

**日本語** | [English](README.en.md)

Voiceger Editorは、[Voiceger](https://github.com/zunzun999/voiceger_v2)に追加して使うTUIの発音・音声合成エディターです。

日本語の読みやアクセント、英語の発音や強勢を調整しながら、複数の音声を生成して聴き比べて気に入ったTakeを保存できます。

日本語・英語・日英混在の文章に対応しています。

Voiceger本体、モデル、参照音声はVoiceger Editorに含まれていません。Voicegerを別途インストールする必要があります。

> **重要：生成音声の利用規約**
>
> Voicegerで生成した音声には、[Voicegerずんだもん音源利用規約](https://zunko.jp/con_ongen_kiyaku.html)が適用されます。
>
> 生成音声には所定のクレジット表記が必要です。Voiceger EditorのMITライセンスは生成音声には適用されません。

## 主な機能

### 発音・アクセント編集

- [日本語の読みとピッチアクセントを編集](docs/ja/japanese-pronunciation.md)
- [1つのアクセント句に複数のピッチの上昇・下降を指定](docs/ja/japanese-pronunciation.md#複数のアクセントを指定する)
- [英語のARPAbet発音記号と強勢を編集](docs/ja/arpabet.md)
- [日本語と英語が混在する文章の発音を編集](docs/ja/batch-item.md#セクションを追加する)
- [編集した発音をプレビューで確認](docs/ja/japanese-pronunciation.md#previewとapply)
- [**英語ずんだもんに日本語を喋らせる**](docs/ja/arpabet.md#日本語をarpabetで近似する)

### 音声生成・Take管理

- [同じ文章から複数のTakeを生成](docs/ja/tui.md#5-take-を生成)
- [Takeを再生して聴き比べ、気に入ったTakeを採用](docs/ja/tui.md#6-take-を再生)
- [BATCH LISTで複数のCaptionをまとめて管理・生成](docs/ja/batch-list.md)
- [CaptionごとにStyleやSpeedを調整](docs/ja/batch-item.md#styleとspeedを変更する)
- [バッチファイルに発音情報や生成設定を保存・読み込み](docs/ja/batch-list.md#バッチファイルを保存する)

### ユーザー辞書

- [日本語・英語のユーザー辞書](docs/ja/dictionary.md)
- [VOICEVOX形式のユーザー辞書のインポート・エクスポート](docs/ja/dictionary.md)

### 音声ファイル・その他の機能

- [WAV・FLAC](docs/ja/settings.md#音声形式)・[MP3](docs/ja/mp3.md)形式で音声を保存（MP3は要FFmpeg）
- [TXT](docs/ja/settings.md#txt)・[LAB](docs/ja/lab.md)ファイルのオプション出力
- [保存先とファイル名のカスタマイズ](docs/ja/settings.md)
- [VOICEVOX Engine APIの一部に対応したHTTP API](docs/ja/http-api.md)

## インストール

### 1. Voicegerをインストールする

まず、Voiceger本体をインストールしてください。

[Voiceger公式リポジトリ](https://github.com/zunzun999/voiceger_v2)

Voiceger Editor 0.1系は、Python 3.9と次のVoiceger revisionを対象に動作確認しています。

```text
f77c1172baf1f490bb962f2d2acd01c852ef3464
```

### 2. Python環境を有効にする

VoicegerのPython仮想環境を使用します。

macOS / Linux：

```bash
export VOICEGER_ROOT="$HOME/voiceger_v2"
source "$VOICEGER_ROOT/.venv/bin/activate"
```

Windows PowerShell：

```powershell
$env:VOICEGER_ROOT = "$HOME\voiceger_v2"
& "$env:VOICEGER_ROOT\.venv\Scripts\Activate.ps1"
```

### 3. Voiceger Editorをインストールする

```bash
python -m pip install "voiceger-editor[tui]"
```

インストール後、次のコマンドでバージョンと動作環境を確認します。

```bash
voiceger-editor --version
voiceger-editor --check
```

WindowsのTUIで音声を再生する場合は、別途`ffplay.exe`が必要です。

詳しいインストール方法や追加機能の設定については[セットアップガイド](docs/ja/setup.md)を参照してください。

## 使い方

ターミナルから次のコマンドで起動します。

```bash
voiceger-editor
```

最初のCaptionを指定して起動することもできます。

```bash
voiceger-editor "このずんだ餅はvery sweetなのだ。"
```

初回起動時には[Voicegerずんだもん音源利用規約](https://zunko.jp/con_ongen_kiyaku.html)の確認・同意が必要です。

### 基本的な操作の流れ

```text
BATCH LIST
  ↓
Captionを追加
  ↓
BATCH ITEM
  ↓
発音・アクセントを確認、編集
  ↓
Takeを生成
  ↓
Takeを再生して聴き比べ
  ↓
気に入ったTakeを採用・保存
```

複数のCaptionを登録しまとめて音声を生成することもできます。

初めて使う場合は、スクリーンショット付きの[はじめての音声生成](docs/ja/tui.md)を参照してください。

## HTTP API

VOICEVOX Engine APIの一部に対応したHTTP APIを使用できます。

APIに必要なパッケージをインストールします。

```bash
python -m pip install "voiceger-editor[api]"
```

APIを起動します。

```bash
python -m uvicorn voiceger_editor.api:app --host 127.0.0.1 --port 8001
```

基本的な処理の流れは次のとおりです。

```text
テキスト
  ↓
/audio_query
  ↓
発音・合成パラメータを編集
  ↓
/synthesis
  ↓
WAV音声
```

音声合成にはVOICEVOXではなくVoicegerを使用します。VOICEVOX Engine APIとの完全な互換性を保証するものではありません。

詳しくは[HTTP API](docs/ja/http-api.md)を参照してください。

## ドキュメント

操作方法を詳しく説明したユーザードキュメントを用意しています。

- [日本語ドキュメント](docs/ja/README.md) — スクリーンショット付きの操作ガイド
- [English Documentation](docs/en/README.md) — 英語版ユーザーガイド

## 対応環境・制限事項

Voiceger Editor 0.1系はPython 3.9での動作を対象としています。

日本語、英語、日本語と英語が混在する文章に対応しています。

Windowsでは、パッケージのインストールとTUIの起動処理を自動テストしています。ただし、物理Windows環境での実際の音声生成、対話的なTUI操作、LAB生成は十分に検証されていません。

動作確認済みVoiceger revision以外でも動作する可能性はありますが、互換性は保証されません。

v1.0に到達するまでは、操作方法やデータ形式などが変更される可能性があります。

詳細は[互換性・対応環境](docs/ja/compatibility.md)を参照してください。

## 開発について

このリポジトリの製品コードは、AIコーディングエージェントによって実装されています。

人間が製品仕様の決定、開発の監督、UI・UXの最終的な評価を担当しています。

## ライセンスと生成音声について

Voiceger Editorは非公式のツールです。Voicegerプロジェクトおよび東北ずん子・ずんだもんプロジェクトが開発・承認・サポートするものではありません。

Voiceger EditorのソースコードにはMITライセンスが適用されます。

**MITライセンスが適用されるのはVoiceger Editorのコードのみです。**

Voiceger本体、GPT-SoVITS、モデル、参照音声、生成音声、キャラクター、名称、商標など、第三者の権利に対する利用許諾を与えるものではありません。

Voicegerで生成した音声には公式の[Voicegerずんだもん音源利用規約](https://zunko.jp/con_ongen_kiyaku.html)が適用されます。

利用規約に従い適切なクレジットを表記してください。

クレジット表記の例：

```text
Voicegerずんだもん
Voiceger:Zundamon
```

Voiceger Editorに表示される規約案内は、公式の利用規約に代わるものではありません。

依存ライブラリやVoicegerとの関係については、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)を参照してください。
