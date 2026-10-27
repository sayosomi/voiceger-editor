# HTTP API

Voiceger Editorには、VOICEVOX Engineと似た形式で音声を生成できるHTTP APIがあります。

このAPIを使用すると、ほかのプログラムからVoicegerに文章を渡し、生成した音声をWAV形式で取得できます。

基本的な処理の流れは次のとおりです。

```text
文章を送信
↓
AudioQueryを取得
↓
必要に応じて発音や設定を変更
↓
音声を生成
↓
WAVを取得
```

Voiceger EditorはVOICEVOX EngineのAPIの一部に対応していますが、完全な互換品ではありません。

**音声合成に使用するのはVOICEVOXではなくVoicegerです。**

## 必要な環境

HTTP APIを使用するには、VoicegerとVoiceger Editorがインストールされている必要があります。

VoicegerのPython環境を有効にした状態で、API用の追加パッケージをインストールします。

```bash
python -m pip install "voiceger-editor[api]"
```

Voiceger Editorの基本的なインストール方法については、[セットアップ](setup.md)を参照してください。

APIから音声を生成する場合も、事前にVoiceger:Zundamonの利用規約への同意が必要です。

まだ同意していない場合は、次のコマンドで利用規約を確認し、同意してください。

```bash
voiceger-editor --accept-voiceger-terms
```

生成した音声には[Voicegerずんだもん音源利用規約](https://zunko.jp/con_ongen_kiyaku.html)が適用されます。

## APIサーバーを起動する

VoicegerのPython環境で、次のコマンドを実行します。

```bash
python -m uvicorn voiceger_editor.api:app --host 127.0.0.1 --port 8001
```

ここでは、APIを自分のコンピューターからのみ使用できるように、`127.0.0.1`で起動しています。

以降の例では、APIのアドレスを次のように指定します。

```text
http://127.0.0.1:8001
```

サーバーを起動したまま、別のターミナルからAPIにアクセスしてください。

### APIの動作確認

ブラウザで次のアドレスを開きます。

http://127.0.0.1:8001/docs

FastAPIが自動生成したAPIドキュメントが表示されます。

各エンドポイントのパラメータを確認し、ブラウザからリクエストを試すこともできます。

サーバーを終了する場合は、起動したターミナルで`Ctrl+C`を押します。

## 対応するエンドポイント

### 基本機能

| Method | Endpoint | 内容 |
|---|---|---|
| GET | `/` | APIの基本情報 |
| GET | `/version` | Voiceger Editorのバージョン |
| GET | `/speakers` | 使用できるStyleの一覧 |
| POST | `/audio_query` | 文章からAudioQueryを生成 |
| POST | `/accent_phrases` | アクセント句を生成 |
| POST | `/synthesis` | WAV音声を生成 |

### 日本語辞書

| Method | Endpoint | 内容 |
|---|---|---|
| GET | `/user_dict` | 登録済み単語の取得 |
| POST | `/user_dict_word` | 単語の追加 |
| PUT | `/user_dict_word/{word_uuid}` | 単語の更新 |
| DELETE | `/user_dict_word/{word_uuid}` | 単語の削除 |
| POST | `/import_user_dict` | 辞書のインポート |

### 英語辞書

| Method | Endpoint | 内容 |
|---|---|---|
| GET | `/english_user_dict` | 登録済み単語の取得 |
| POST | `/english_user_dict_word` | 単語の追加・置換 |
| PUT | `/english_user_dict_word/{surface}` | 単語の更新・名前変更 |
| DELETE | `/english_user_dict_word/{surface}` | 単語の削除 |
| POST | `/import_english_user_dict` | 辞書のインポート |

英語辞書のエンドポイントはVoiceger Editor独自の拡張機能です。VOICEVOX Engineとの互換性はありません。

## Styleを確認する

`/speakers` では、使用できるStyleを取得できます。

```bash
curl http://127.0.0.1:8001/speakers
```

Voiceger Editorでは、VOICEVOXのずんだもんに対応するStyle IDを使用します。

例えば、`3` はNeutral、`1` はSweetです。

ただし、実際に利用できるのは、インストールしたVoicegerに対応する参照音声が存在するStyleだけです。

Styleの一覧については、[設定](settings.md)を参照してください。

Voiceger Editorのspeaker UUIDは次の値です。

```text
voiceger-editor-zundamon
```

## 音声を生成する

ここでは、`curl`を使って「今日は雨なのだ。」という文章を音声に変換します。

コマンド例はmacOS・Linuxのシェルを想定しています。Windows PowerShellで使用する場合は、後述のコマンドを参照してください。

### 1. AudioQueryを生成する

`/audio_query`に文章とStyle IDを渡します。

```bash
curl -sS -G -X POST \
  'http://127.0.0.1:8001/audio_query' \
  --data-urlencode 'text=今日は雨なのだ。' \
  --data-urlencode 'speaker=3' \
  --output query.json
```

このコマンドでは、Neutral（`speaker=3`）を指定しています。

実行すると、`query.json`にAudioQueryが保存されます。

AudioQueryには、読み上げに使用する発音情報や話速などが含まれています。

### 2. 音声を生成する

保存したAudioQueryを`/synthesis`へ送信します。

```bash
curl -sS -X POST \
  'http://127.0.0.1:8001/synthesis?speaker=3' \
  -H 'Content-Type: application/json' \
  --data-binary @query.json \
  --output output.wav
```

成功すると、`output.wav`が保存されます。

これで音声生成は完了です。

### Windows PowerShell

PowerShellでは`curl.exe`を使用してください。

AudioQueryの生成：

```powershell
curl.exe -sS -G -X POST "http://127.0.0.1:8001/audio_query" --data-urlencode "text=今日は雨なのだ。" --data-urlencode "speaker=3" --output query.json
```

音声の生成：

```powershell
curl.exe -sS -X POST "http://127.0.0.1:8001/synthesis?speaker=3" -H "Content-Type: application/json" --data-binary "@query.json" --output output.wav
```

## AudioQueryを編集する

`/audio_query`で取得したJSONは、`/synthesis`へ送る前に変更できます。

主な設定項目は次のとおりです。

| フィールド | 内容 |
|---|---|
| `accent_phrases` | 日本語の読み・アクセント |
| `speedScale` | 話速 |
| `outputSamplingRate` | 出力音声のサンプリングレート |
| `outputStereo` | モノラル・ステレオの選択 |

例えば、`speedScale`の値を`1.2`に変更すると、音声を通常より速く生成できます。

### 日本語のアクセント

`accent_phrases`には、モーラやアクセント位置の情報が含まれています。

各アクセント句の`accent`を変更すると、アクセント位置を指定できます。

また、Voiceger Editorでは、複数の高低変化を保持するために`pronunciationPitchEvents`という独自の拡張フィールドを使用する場合があります。

このフィールドが存在するAudioQueryでは、単純に`accent`だけを書き換えても、意図した結果にならない場合があります。

発音の表記やアクセントの編集方法については、[日本語の発音編集](japanese-pronunciation.md)を参照してください。

### VOICEVOXと異なる設定項目

次のフィールドはAudioQueryとして受け付けますが、Voicegerでは同等の調声機能を提供していません。

```text
pitchScale
intonationScale
volumeScale
prePhonemeLength
postPhonemeLength
pauseLength
pauseLengthScale
```

これらを初期値以外に変更しても、指定した効果は音声に反映されません。

リクエスト全体をエラーにする代わりに、設定が無視されたことを警告します。

### サンプリング設定

HTTP APIでは、現在次のVoiceger初期値が使用されます。

| 設定 | 値 |
|---|---:|
| Top K | 20 |
| Top P | 1.00 |
| Temperature | 1.00 |

これらの値は、現在のAudioQueryから直接変更できません。

TUIの設定項目については、[設定](settings.md)を参照してください。

## 日本語と英語の文章

`/audio_query`では、日本語だけでなく英語や日本語・英語の混在した文章も使用できます。

英語の例：

```text
Hello, world!
```

日本語と英語の混在例：

```text
このずんだ餅はvery sweetなのだ。
```

英語だけの文章では、Voicegerの英語モードを使用して音声を生成します。

日本語と英語が混在する場合は、言語ごとの情報を保持して音声を生成します。

### Voiceger Editor独自のフィールド

AudioQueryには、次の拡張フィールドが含まれる場合があります。

| フィールド | 内容 |
|---|---|
| `voicegerSegments` | 日本語・英語のセクションと英語の音素情報 |
| `pronunciationPunctuation` | 日本語の句読点情報 |
| `pronunciationPitchEvents` | 日本語の複数の高低変化 |

これらはVOICEVOX Engine標準のフィールドではありません。

**`/audio_query`が返した拡張フィールドは、必要な部分を編集する場合を除き、削除せずに`/synthesis`へ渡してください。**

英語のARPAbetや強勢については、[英語の発音編集](arpabet.md)を参照してください。

## アクセント句を取得する

`/accent_phrases`では、文章から日本語のアクセント句を取得できます。

```bash
curl -sS -G -X POST \
  'http://127.0.0.1:8001/accent_phrases' \
  --data-urlencode 'text=今日は雨なのだ。' \
  --data-urlencode 'speaker=3'
```

`is_kana=true`を指定すると、アクセント記号を含むカナ表記からアクセント句を生成できます。

```bash
curl -sS -G -X POST \
  'http://127.0.0.1:8001/accent_phrases' \
  --data-urlencode "text=キョ'ーワ/ア'メナノダ。" \
  --data-urlencode 'speaker=3' \
  --data-urlencode 'is_kana=true'
```

カナ表記では、`/`をアクセント句の区切りに使用します。

なお、`/accent_phrases`はVoiceger Editor独自の複数の高低変化を表現するフィールドを返せません。その情報を扱う場合はAudioQueryの`pronunciationPitchEvents`を使用してください。

## ユーザー辞書

HTTP APIから、日本語辞書と英語辞書の登録・更新・削除・インポートができます。

辞書データの基本的な管理方法については、[ユーザー辞書](dictionary.md)を参照してください。

### 日本語辞書

登録済みの単語を取得するには、次のコマンドを使用します。

```bash
curl http://127.0.0.1:8001/user_dict
```

単語を追加する例：

```bash
curl -sS -X POST \
  'http://127.0.0.1:8001/user_dict_word' \
  --data-urlencode 'surface=ずんだもん' \
  --data-urlencode 'pronunciation=ズンダモン' \
  --data-urlencode 'accent_type=3'
```

`priority`の初期値は`5`で、`0`〜`10`の範囲を指定できます。

辞書の更新や削除は、対応する`word_uuid`を指定して行います。

`/import_user_dict`では、VOICEVOX形式のUUIDをキーとした辞書データをインポートできます。`override`パラメータの指定が必要です。

### 英語辞書

登録済みの英語辞書を取得するには、次のコマンドを使用します。

```bash
curl http://127.0.0.1:8001/english_user_dict
```

英語辞書は、単語をキー、ARPAbetの音素列を値とするJSON形式です。

例えば次のようなデータを扱います。

```json
{
  "sweet": ["S", "W", "IY1", "T"]
}
```

単語を追加・置換する例：

```bash
curl -sS -X POST \
  'http://127.0.0.1:8001/english_user_dict_word' \
  -H 'Content-Type: application/json' \
  -d '{"surface":"sweet","phonemes":["S","W","IY1","T"]}'
```

英語辞書の`surface`は大文字・小文字を区別せずに照合されます。

辞書のインポートには`/import_english_user_dict`を使用します。

`override=false`が初期値で、既存の単語を保持します。`override=true`を指定すると、同じ単語の登録内容を置き換えます。

APIとTUIは同じ辞書ファイルを使用します。API経由で変更した辞書内容は、そのAPIプロセスで新しく生成するAudioQueryに反映されます。

ただし、別のプロセスから辞書ファイルを変更した場合は、実行中のAPIサーバーに自動では読み込まれません。

## エラーが発生した場合

主なHTTPステータスコードは次のとおりです。

| Status | 内容 |
|---|---|
| `400` | 発音情報やAudioQueryが不正 |
| `403` | Voicegerの利用規約への同意が必要 |
| `422` | Style IDやリクエストの値が不正 |
| `500` | 音声生成や辞書操作に失敗 |
| `503` | Voicegerの実行環境が使用できない |

エラーの詳細は、レスポンスの`detail`フィールドで確認できます。

## TUIとの違い

HTTP APIの`/synthesis`は、リクエストに対してWAVデータを返します。

TUIのようなTakeの候補管理・再生・採用は行いません。

また、`/synthesis`では次のファイルを自動保存しません。

- MP3・FLACなどの採用済み音声ファイル
- TXTファイル
- LABファイル

APIで受け取ったWAVの保存や管理は、APIを呼び出した側で行います。

## 互換性について

VOICEVOX形式のAPIに対応していても、すべてのVOICEVOX対応ソフトウェアで動作するとは限りません。

対応していないエンドポイントや、VOICEVOX Engine固有の挙動を必要とするソフトウェアでは、正常に使用できない場合があります。

対応する環境や機能の範囲については、[互換性](compatibility.md)を参照してください。
