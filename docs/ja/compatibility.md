# 互換性

このページでは、Voiceger Editor 0.1系の対応環境、対応機能、既知の制限事項について説明します。

ここに記載されていない環境や機能でも動作する可能性はありますが、動作を保証するものではありません。

## バージョンについて

Voiceger Editorの最初の公開バージョンは`0.1.0`です。

1.0に到達するまでは、機能の追加や改善に伴い、TUIの操作方法、設定ファイル、辞書形式、HTTP APIの独自拡張などが変更される可能性があります。

互換性に影響する変更は、リリースノートで案内します。

インストールされているバージョンは、次のコマンドで確認できます。

```bash
voiceger-editor --version
```

## Voicegerとの互換性

Voiceger Editor 0.1系は、次のVoiceger revisionを対象に動作確認されています。

```text
f77c1172baf1f490bb962f2d2acd01c852ef3464
```

Voicegerの別のrevisionでも動作する可能性はありますが、互換性は保証されません。

次のコマンドで、インストールした環境を確認できます。

```bash
voiceger-editor --check
```

Voicegerのrevisionが動作確認済みのものと異なる場合は、通常、エラーではなく警告が表示されます。

ただし、警告が表示されないことが、すべての機能の動作を保証するわけではありません。

インストールや環境の確認方法については、[セットアップ](setup.md)を参照してください。

## Python

Voiceger Editor 0.1系が対応するPythonのバージョンは、**Python 3.9**です。

Voiceger Editorは、VoicegerのPython仮想環境で実行することを想定しています。

ほかのPythonバージョンでの動作は保証されません。

## OSと動作確認範囲

### macOS・Linux

Voiceger Editorは、macOSおよびLinuxでの使用を想定しています。

必要なPython環境、Voiceger本体、音声再生や追加出力のための外部ツールを用意してください。

環境によっては、別途パッケージのインストールや設定が必要です。

### Windows

Voiceger Editor 0.1系では、Windows向けにPython 3.9を使用した自動テストを実施しています。

確認している内容は次のとおりです。

- パッケージのビルドとインストール
- `--help`と`--version`の実行
- TUI用追加パッケージと`windows-curses`のインストール
- `curses`とVoiceger EditorのTUIの読み込み
- 起動処理に関する自動テスト

ただし、**Windows上でVoicegerによる実際の音声生成や、対話的なTUI操作を完全に検証しているわけではありません。**

WindowsのTUIで音声を再生するには、PATHから実行できる`ffplay.exe`が必要です。

また、WindowsでのLAB出力は0.1系の動作確認済み範囲には含まれていません。

詳しくは[セットアップ](setup.md)と[LAB出力](lab.md)を参照してください。

## 対応する言語

Voiceger Editor 0.1系は、日本語、英語、日本語と英語が混在する文章に対応しています。

日本語では読みやアクセントの編集、英語ではARPAbetによる発音や強勢の編集ができます。

英語だけのCaptionでは、Voicegerの英語モードを使用します。

詳しくは[日本語の発音編集](japanese-pronunciation.md)と[英語の発音編集](arpabet.md)を参照してください。

### その他の言語

Voiceger本体が別の言語モードに対応していても、Voiceger Editor 0.1系で同じ機能を使用できるとは限りません。

日本語・英語以外の言語は、現在の動作保証の対象外です。

## Styleの互換性

Voiceger Editorでは、VOICEVOXのずんだもんに対応するStyle IDを使用します。

ただし、選択できるStyleは、ローカルにインストールされたVoicegerの参照音声によって決まります。

**Style IDがVOICEVOXと同じでも、VOICEVOXと同じ音声が生成されるわけではありません。**

音声合成にはVoicegerを使用します。

Styleの一覧や設定方法は[設定](settings.md)を参照してください。

## VOICEVOX形式のHTTP APIとの互換性

Voiceger Editorは、VOICEVOX EngineのHTTP APIの一部に対応しています。

ただし、**完全な互換性は保証していません。**

対応していないエンドポイントや、VOICEVOX Engine固有の音声合成機能を使用するソフトウェアでは、正常に動作しない場合があります。

また、一部のAudioQueryパラメータにはVoicegerで対応する機能がなく、値を指定しても音声に反映されません。

Voiceger Editor独自の拡張フィールドもあるため、VOICEVOX EngineのAudioQueryと完全に同一の構造ではありません。

対応エンドポイント、AudioQueryの設定項目、独自拡張については[HTTP API](http-api.md)を参照してください。

## 辞書の互換性

日本語辞書のHTTP APIは、VOICEVOX形式のUUIDをキーとした`UserDictWord`データに対応しています。

一方、英語辞書はVoiceger Editor独自の機能であり、VOICEVOXの辞書APIとは互換性がありません。

辞書の登録、インポート、エクスポートについては[ユーザー辞書](dictionary.md)を参照してください。

## 音声ファイルの対応範囲

TUIで採用したTakeは、WAV・FLAC形式で保存できます。FFmpegが使用できる環境ではMP3形式にも対応します。

TXT・LABファイルも必要に応じて出力できますが、LABには追加の依存パッケージや外部ツールが必要です。

詳しくは[設定](settings.md)、[MP3出力](mp3.md)、[LAB出力](lab.md)を参照してください。

HTTP APIの`/synthesis`はWAV音声を返し、TUIの保存形式やファイル名設定は使用しません。

## アプリケーション名

Voiceger Editor 0.1系で使用する正式な名称は次のとおりです。

| 項目 | 名称 |
|---|---|
| 製品名 | Voiceger Editor |
| GitHubリポジトリ | `sayosomi/voiceger-editor` |
| PyPIパッケージ | `voiceger-editor` |
| コマンド名 | `voiceger-editor` |
| Pythonパッケージ | `voiceger_editor` |

開発中に使用されていた別の名称は、互換性のための別名としてサポートしていません。

## Voicegerとの関係・生成音声の利用規約

Voiceger Editorは非公式のツールであり、Voiceger本体を同梱したり、Voicegerの実装を変更したりするものではありません。

Voiceger EditorのソースコードにはMITライセンスが適用されますが、**生成音声にはMITライセンスは適用されません。**

Voiceger:Zundamonで生成した音声には、[Voicegerずんだもん音源利用規約](https://zunko.jp/con_ongen_kiyaku.html)が適用され、所定のクレジット表記が必要です。

ライセンスや権利関係の詳細については、リポジトリの[README](../../README.md)を参照してください。
